"""FastAPI bridge between the web UI and the ADK agent. Owned by the Backend/API slice.

CONTRACT (the Frontend slice codes against exactly these routes):
    POST /api/mission        {text}                  -> {run_id}
    GET  /api/events/{run_id}                         -> text/event-stream of AgentEvent
    POST /api/approve/{run_id}  ApprovalDecision      -> {ok: true}
    GET  /api/report/{run_id}                         -> AuditReport
    GET  /healthz                                     -> {status:"ok"}

The Backend/API slice implements the bodies (running the ADK agent, relaying the
approval/resume signal, fanning AgentEvents to the SSE stream). Keep the routes/shapes
stable — the Frontend depends on them.
"""

from __future__ import annotations

import asyncio
from typing import AsyncIterator

from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse

from faultaudit.models import (
    AgentEvent,
    ApprovalDecision,
    AuditReport,
    AskRequest,
    AskResponse,
    EventType,
    MissionRequest,
    MissionStarted,
)
from faultaudit.server import insights
from faultaudit.server.events import to_sse
from faultaudit.server.runner import FakeRunner
from faultaudit.config import get_settings
from faultaudit.server.store import RunStore, run_store as _default_store

app = FastAPI(title="FaultAuditAI")

# Allow tests to inject a custom store by replacing app.state.store.
# The default is the module-level singleton.
app.state.store = _default_store


def _get_store() -> RunStore:
    return app.state.store  # type: ignore[attr-defined]


# --------------------------------------------------------------------------- #
# Background task: drive the runner and feed the event queue
# --------------------------------------------------------------------------- #

async def _run_mission(run_id: str, store: RunStore) -> None:
    """Background task: iterate AgentEvents from the runner into the queue."""
    record = store.get_run(run_id)
    if record is None:
        return

    try:
        async for event in record.runner.run(run_id, record.mission):
            await record.queue.put(event)
            # Cache the AuditReport when REPORT_READY fires so /api/report works.
            if event.type == EventType.REPORT_READY:
                report_data = event.data.get("report")
                if report_data:
                    report = AuditReport.model_validate(report_data)
                    store.set_report(run_id, report)
    except Exception as exc:  # noqa: BLE001
        err_event = AgentEvent(
            run_id=run_id,
            type=EventType.ERROR,
            data={"error": str(exc)},
        )
        await record.queue.put(err_event)
        done_event = AgentEvent(run_id=run_id, type=EventType.DONE, data={})
        await record.queue.put(done_event)
    finally:
        # Sentinel: None signals the SSE generator to close the stream.
        await record.queue.put(None)


# --------------------------------------------------------------------------- #
# SSE generator
# --------------------------------------------------------------------------- #

async def _sse_generator(run_id: str, store: RunStore) -> AsyncIterator[str]:
    record = store.get_run(run_id)
    if record is None:
        return

    while True:
        event: AgentEvent | None = await record.queue.get()
        if event is None:
            break
        yield to_sse(event)
        if event.type == EventType.DONE:
            break


# --------------------------------------------------------------------------- #
# Routes
# --------------------------------------------------------------------------- #

@app.get("/healthz")
def healthz() -> dict:
    return {"status": "ok"}


@app.get("/api/status")
def status() -> dict:
    return insights.get_status()


@app.get("/api/stats")
def stats() -> dict:
    return insights.get_stats()


@app.post("/api/ask", response_model=AskResponse)
def ask(body: AskRequest) -> AskResponse:
    store = _get_store()
    report = store.get_report(body.run_id) if body.run_id else store.newest_report()
    return insights.answer_question(body.question, report)


@app.post("/api/mission", response_model=MissionStarted)
async def start_mission(body: MissionRequest) -> MissionStarted:
    """Start a new audit mission. Returns a run_id immediately.

    The runner is launched as a background task and feeds AgentEvents into the
    run's queue, which the /api/events/{run_id} SSE stream consumes.
    """
    store = _get_store()
    settings = get_settings()
    if settings.use_mocks:
        runner = FakeRunner()
    elif settings.use_adk:
        from faultaudit.server.adk_runner import AdkAgentRunner

        runner = AdkAgentRunner()
    else:
        from faultaudit.server.real_runner import RealRunner

        runner = RealRunner()  # live: Gemini + Atlas vector search
    record = store.create_run(body, runner)
    asyncio.create_task(_run_mission(record.run_id, store))
    return MissionStarted(run_id=record.run_id)


@app.get("/api/events/{run_id}")
async def stream_events(run_id: str) -> StreamingResponse:
    """Stream AgentEvents as Server-Sent-Events until DONE."""
    store = _get_store()
    if store.get_run(run_id) is None:
        raise HTTPException(status_code=404, detail=f"Run {run_id!r} not found")
    return StreamingResponse(
        _sse_generator(run_id, store),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@app.post("/api/approve/{run_id}")
async def approve(run_id: str, body: ApprovalDecision) -> dict:
    """Deliver an approval decision to resume a paused run."""
    store = _get_store()
    try:
        await store.push_approval(run_id, body)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Run {run_id!r} not found")
    return {"ok": True}


@app.get("/api/report/{run_id}", response_model=AuditReport)
def get_report(run_id: str) -> AuditReport:
    """Return the final AuditReport for a completed run."""
    store = _get_store()
    report = store.get_report(run_id)
    if report is None:
        if store.get_run(run_id) is None:
            raise HTTPException(status_code=404, detail=f"Run {run_id!r} not found")
        raise HTTPException(status_code=404, detail="Report not yet available")
    return report


# --------------------------------------------------------------------------- #
# Serve the web UI (mounted last so it doesn't shadow /api routes)
# --------------------------------------------------------------------------- #
from pathlib import Path  # noqa: E402

from fastapi.staticfiles import StaticFiles  # noqa: E402

_WEB_DIR = Path(__file__).resolve().parent.parent / "web"
if _WEB_DIR.is_dir():
    app.mount("/", StaticFiles(directory=str(_WEB_DIR), html=True), name="web")
