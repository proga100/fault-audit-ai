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

from fastapi import FastAPI

app = FastAPI(title="FaultAuditAI")


@app.get("/healthz")
def healthz() -> dict:
    return {"status": "ok"}


# Backend/API slice: implement /api/mission, /api/events, /api/approve, /api/report.
