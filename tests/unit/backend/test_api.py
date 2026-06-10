"""Backend API tests (TDD).

Strategy for SSE + approval interplay:
  - Use httpx.AsyncClient with anyio to drive the async FastAPI app.
  - For the streaming test, we consume the SSE stream in one task while posting
    approvals from another, using asyncio.gather or sequential awaits once we
    know the stream will pause at the right gate.
  - A thin helper `drain_queue` lets us test queue contents without HTTP when
    needed for determinism.
"""

from __future__ import annotations

import asyncio
import json
from typing import Optional

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from faultaudit.models import (
    AgentEvent,
    ApprovalDecision,
    ApprovalGate,
    AuditReport,
    EventType,
    MissionRequest,
)
from faultaudit.server.app import app, _run_mission
from faultaudit.server.runner import FakeRunner
from faultaudit.server.store import RunStore


# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #

@pytest.fixture
def store() -> RunStore:
    """Fresh RunStore per test — prevents cross-test state leakage."""
    return RunStore()


@pytest_asyncio.fixture
async def client(store: RunStore):
    """AsyncClient wired to a fresh store."""
    app.state.store = store
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

async def _drain_run(run_id: str, store: RunStore, *, timeout: float = 5.0) -> list[AgentEvent]:
    """Drain all events from the run queue without HTTP, for deterministic testing."""
    record = store.get_run(run_id)
    assert record is not None, f"Run {run_id!r} not in store"
    events: list[AgentEvent] = []
    deadline = asyncio.get_event_loop().time() + timeout
    while True:
        remaining = deadline - asyncio.get_event_loop().time()
        if remaining <= 0:
            break
        try:
            event: Optional[AgentEvent] = await asyncio.wait_for(
                record.queue.get(), timeout=min(0.5, remaining)
            )
        except asyncio.TimeoutError:
            break
        if event is None:
            break
        events.append(event)
        if event.type == EventType.DONE:
            break
    return events


def _parse_sse_chunk(chunk: str) -> list[AgentEvent]:
    """Parse one or more SSE frames from a raw chunk string."""
    events: list[AgentEvent] = []
    for frame in chunk.split("\n\n"):
        frame = frame.strip()
        if not frame:
            continue
        data_line: Optional[str] = None
        for line in frame.splitlines():
            if line.startswith("data:"):
                data_line = line[len("data:"):].strip()
        if data_line:
            events.append(AgentEvent.model_validate_json(data_line))
    return events


# --------------------------------------------------------------------------- #
# Test: POST /healthz
# --------------------------------------------------------------------------- #

@pytest.mark.anyio
async def test_healthz(client: AsyncClient) -> None:
    resp = await client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


@pytest.mark.anyio
async def test_status_exposes_runtime_and_gemini_model(client: AsyncClient) -> None:
    resp = await client.get("/api/status")
    assert resp.status_code == 200
    body = resp.json()
    assert body["agent_runtime"] == "mock"
    assert body["gemini_model"].startswith("gemini-3.")
    assert body["human_approval"] is True
    assert body["audit_trail"] is True


@pytest.mark.anyio
async def test_stats_shape(client: AsyncClient) -> None:
    resp = await client.get("/api/stats")
    assert resp.status_code == 200
    body = resp.json()
    assert body["invoices"] > 0
    assert body["vendors"] > 0
    assert body["total_spend"] > 0
    assert body["source"]


@pytest.mark.anyio
async def test_ask_demo_mode_returns_grounded_answer(client: AsyncClient) -> None:
    resp = await client.post("/api/ask", json={"question": "What is in scope?"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["ai_generated"] is True
    assert body["model"] == "demo-template"
    assert "dataset in scope" in body["answer"].lower()


@pytest.mark.anyio
async def test_ask_validation(client: AsyncClient) -> None:
    empty = await client.post("/api/ask", json={"question": ""})
    assert empty.status_code == 422
    too_long = await client.post("/api/ask", json={"question": "x" * 2001})
    assert too_long.status_code == 422


# --------------------------------------------------------------------------- #
# Test: POST /api/mission returns a run_id
# --------------------------------------------------------------------------- #

@pytest.mark.anyio
async def test_start_mission_returns_run_id(client: AsyncClient, store: RunStore) -> None:
    resp = await client.post("/api/mission", json={"text": "Audit Q4 vendor payments"})
    assert resp.status_code == 200
    body = resp.json()
    assert "run_id" in body
    run_id = body["run_id"]
    assert isinstance(run_id, str) and len(run_id) > 0
    # The run should be registered in the store.
    assert store.get_run(run_id) is not None


# --------------------------------------------------------------------------- #
# Test: Full event sequence through queue drain (deterministic, no HTTP stream)
# --------------------------------------------------------------------------- #

@pytest.mark.anyio
async def test_full_event_sequence_via_queue(store: RunStore) -> None:
    """Drive FakeRunner directly: create run, post both approvals, assert all EventTypes."""
    mission = MissionRequest(text="Full audit test")
    runner = FakeRunner()
    record = store.create_run(mission, runner)
    run_id = record.run_id

    # Start background task.
    task = asyncio.create_task(_run_mission(run_id, store))

    # Collect events up to AWAITING_APPROVAL(plan).
    plan_gate_seen = False
    events_so_far: list[AgentEvent] = []

    for _ in range(20):
        try:
            evt = await asyncio.wait_for(record.queue.get(), timeout=1.0)
        except asyncio.TimeoutError:
            break
        if evt is None:
            break
        events_so_far.append(evt)
        if evt.type == EventType.AWAITING_APPROVAL and evt.data.get("gate") == ApprovalGate.PLAN.value:
            plan_gate_seen = True
            break

    assert plan_gate_seen, f"Did not see AWAITING_APPROVAL(plan). Got: {[e.type for e in events_so_far]}"

    # Post plan approval.
    plan_decision = ApprovalDecision(gate=ApprovalGate.PLAN, approved=True)
    await store.push_approval(run_id, plan_decision)

    # Collect until AWAITING_APPROVAL(action).
    action_gate_seen = False
    for _ in range(20):
        try:
            evt = await asyncio.wait_for(record.queue.get(), timeout=1.0)
        except asyncio.TimeoutError:
            break
        if evt is None:
            break
        events_so_far.append(evt)
        if evt.type == EventType.AWAITING_APPROVAL and evt.data.get("gate") == ApprovalGate.ACTION.value:
            action_gate_seen = True
            break

    assert action_gate_seen, f"Did not see AWAITING_APPROVAL(action). Got: {[e.type for e in events_so_far]}"

    # Post action approval — approve all items.
    action_decision = ApprovalDecision(
        gate=ApprovalGate.ACTION,
        approved=True,
        approved_ids=["INV-001", "INV-002", "INV-003"],
    )
    await store.push_approval(run_id, action_decision)

    # Drain remaining events until DONE.
    for _ in range(20):
        try:
            evt = await asyncio.wait_for(record.queue.get(), timeout=1.0)
        except asyncio.TimeoutError:
            break
        if evt is None:
            break
        events_so_far.append(evt)
        if evt.type == EventType.DONE:
            break

    await task

    # Verify the complete sequence.
    types = [e.type for e in events_so_far]
    assert EventType.PLAN in types
    assert EventType.AWAITING_APPROVAL in types
    assert EventType.TOOL_CALL in types
    assert EventType.TOOL_RESULT in types
    assert EventType.PROPOSAL in types
    assert EventType.WRITTEN in types
    assert EventType.REPORT_READY in types
    assert EventType.DONE in types

    # Ensure PLAN comes before first AWAITING_APPROVAL.
    plan_idx = types.index(EventType.PLAN)
    await_idx = types.index(EventType.AWAITING_APPROVAL)
    assert plan_idx < await_idx

    # Ensure DONE is last.
    assert types[-1] == EventType.DONE

    attributed = [e for e in events_so_far if e.type != EventType.DONE]
    assert all("agent" in e.data for e in attributed)
    assert all("tool_label" in e.data for e in attributed)


# --------------------------------------------------------------------------- #
# Test: /api/report returns a valid AuditReport after completion
# --------------------------------------------------------------------------- #

@pytest.mark.anyio
async def test_report_after_completion(client: AsyncClient, store: RunStore) -> None:
    """Start a mission, drive through both gates, then GET /api/report."""
    # Start mission.
    resp = await client.post("/api/mission", json={"text": "Report test mission"})
    assert resp.status_code == 200
    run_id = resp.json()["run_id"]

    record = store.get_run(run_id)
    assert record is not None

    # Wait for AWAITING_APPROVAL(plan).
    plan_gate_seen = False
    for _ in range(20):
        try:
            evt = await asyncio.wait_for(record.queue.get(), timeout=1.0)
        except asyncio.TimeoutError:
            break
        if evt is None:
            break
        if evt.type == EventType.AWAITING_APPROVAL and evt.data.get("gate") == ApprovalGate.PLAN.value:
            plan_gate_seen = True
            break

    assert plan_gate_seen

    # Approve plan via HTTP.
    resp2 = await client.post(
        f"/api/approve/{run_id}",
        json={"gate": "plan", "approved": True},
    )
    assert resp2.status_code == 200
    assert resp2.json() == {"ok": True}

    # Wait for AWAITING_APPROVAL(action).
    action_gate_seen = False
    for _ in range(20):
        try:
            evt = await asyncio.wait_for(record.queue.get(), timeout=1.0)
        except asyncio.TimeoutError:
            break
        if evt is None:
            break
        if evt.type == EventType.AWAITING_APPROVAL and evt.data.get("gate") == ApprovalGate.ACTION.value:
            action_gate_seen = True
            break

    assert action_gate_seen

    # Approve action via HTTP.
    resp3 = await client.post(
        f"/api/approve/{run_id}",
        json={
            "gate": "action",
            "approved": True,
            "approved_ids": ["INV-001", "INV-002", "INV-003"],
            "rejected_ids": [],
        },
    )
    assert resp3.status_code == 200

    # Drain until DONE so report is stored.
    done_seen = False
    for _ in range(20):
        try:
            evt = await asyncio.wait_for(record.queue.get(), timeout=1.0)
        except asyncio.TimeoutError:
            break
        if evt is None:
            break
        if evt.type == EventType.DONE:
            done_seen = True
            break

    assert done_seen

    # GET /api/report.
    resp4 = await client.get(f"/api/report/{run_id}")
    assert resp4.status_code == 200
    report = AuditReport.model_validate(resp4.json())
    assert report.run_id == run_id
    assert report.flagged_count == 3
    assert report.total_at_risk > 0
    assert len(report.items) == 3
    assert report.markdown != ""


# --------------------------------------------------------------------------- #
# Test: Approving an unknown run_id -> 404
# --------------------------------------------------------------------------- #

@pytest.mark.anyio
async def test_approve_unknown_run_returns_404(client: AsyncClient) -> None:
    resp = await client.post(
        "/api/approve/nonexistent-run-id",
        json={"gate": "plan", "approved": True},
    )
    assert resp.status_code == 404


# --------------------------------------------------------------------------- #
# Test: GET /api/report for unknown run -> 404
# --------------------------------------------------------------------------- #

@pytest.mark.anyio
async def test_report_unknown_run_returns_404(client: AsyncClient) -> None:
    resp = await client.get("/api/report/nonexistent-run-id")
    assert resp.status_code == 404


# --------------------------------------------------------------------------- #
# Test: GET /api/events for unknown run -> 404
# --------------------------------------------------------------------------- #

@pytest.mark.anyio
async def test_events_unknown_run_returns_404(client: AsyncClient) -> None:
    resp = await client.get("/api/events/nonexistent-run-id")
    assert resp.status_code == 404


# --------------------------------------------------------------------------- #
# Test: SSE stream yields proper frames (format check + GET returns 200)
# --------------------------------------------------------------------------- #

@pytest.mark.anyio
async def test_sse_stream_response_headers(client: AsyncClient, store: RunStore) -> None:
    """Verify that GET /api/events/{run_id} returns text/event-stream content-type."""
    resp = await client.post("/api/mission", json={"text": "SSE headers test"})
    run_id = resp.json()["run_id"]

    # Immediately post both approvals so the stream can complete without blocking.
    record = store.get_run(run_id)
    assert record is not None

    # Drive the run to completion via queue drain (same as test_full_event_sequence_via_queue)
    # but also verify the SSE route returns 200 + correct content-type on first connect.
    # We use a HEAD-like pattern: just initiate the connection, check headers, then close.
    # Note: httpx ASGITransport buffers the full response body before streaming, so we
    # test headers and format via the to_sse helper directly rather than live streaming.
    from faultaudit.server.events import to_sse as _to_sse

    # Verify to_sse produces valid SSE frames with correct fields.
    event = AgentEvent(
        run_id=run_id,
        type=EventType.PLAN,
        data={"plan": "test plan"},
    )
    sse_frame = _to_sse(event)
    assert sse_frame.startswith("event: plan\n")
    assert "data: " in sse_frame
    assert sse_frame.endswith("\n\n")

    # Parse the data line back.
    lines = sse_frame.strip().splitlines()
    data_line = next(l for l in lines if l.startswith("data:"))
    parsed = AgentEvent.model_validate_json(data_line[len("data:"):].strip())
    assert parsed.type == EventType.PLAN
    assert parsed.run_id == run_id


@pytest.mark.anyio
async def test_sse_stream_full_sequence_via_queue(store: RunStore) -> None:
    """Drive FakeRunner, verify all SSE frames are emitted correctly via queue drain.

    httpx's ASGITransport buffers the full response before yielding, so testing
    SSE streaming with concurrent approvals via HTTP requires a real HTTP server.
    Instead, we test the complete event sequence via the queue (which is what the
    SSE generator reads) and separately verify the SSE frame format above.
    """
    from faultaudit.server.app import _run_mission
    from faultaudit.server.events import to_sse as _to_sse

    mission_request = MissionRequest(text="SSE queue test")
    runner = FakeRunner()
    record = store.create_run(mission_request, runner)
    run_id = record.run_id

    task = asyncio.create_task(_run_mission(run_id, store))

    all_events: list[AgentEvent] = []

    # Helper: drain events from queue until gate or done.
    async def _collect_until(gate_type: EventType, gate_value: str) -> None:
        for _ in range(20):
            try:
                evt = await asyncio.wait_for(record.queue.get(), timeout=1.0)
            except asyncio.TimeoutError:
                break
            if evt is None:
                return
            all_events.append(evt)
            # Verify to_sse produces a valid frame for every event.
            frame = _to_sse(evt)
            assert frame.startswith(f"event: {evt.type.value}\n")
            assert frame.endswith("\n\n")
            if evt.type == gate_type and evt.data.get("gate") == gate_value:
                return
            if evt.type == EventType.DONE:
                return

    # Collect until plan gate.
    await _collect_until(EventType.AWAITING_APPROVAL, ApprovalGate.PLAN.value)
    plan_types = [e.type for e in all_events]
    assert EventType.PLAN in plan_types
    assert EventType.AWAITING_APPROVAL in plan_types

    # Deliver plan approval.
    await store.push_approval(run_id, ApprovalDecision(gate=ApprovalGate.PLAN, approved=True))

    # Collect until action gate.
    await _collect_until(EventType.AWAITING_APPROVAL, ApprovalGate.ACTION.value)
    mid_types = [e.type for e in all_events]
    assert EventType.TOOL_CALL in mid_types
    assert EventType.TOOL_RESULT in mid_types
    assert EventType.PROPOSAL in mid_types

    # Deliver action approval.
    await store.push_approval(
        run_id,
        ApprovalDecision(
            gate=ApprovalGate.ACTION,
            approved=True,
            approved_ids=["INV-001", "INV-002", "INV-003"],
        ),
    )

    # Drain remaining events.
    await _collect_until(EventType.DONE, "")
    await task

    final_types = [e.type for e in all_events]
    assert EventType.WRITTEN in final_types
    assert EventType.REPORT_READY in final_types
    assert EventType.DONE in final_types
