"""Runner protocol and FakeRunner for FaultAuditAI.

AgentRunner is a pluggable protocol. FakeRunner drives the scripted event
sequence (no Atlas / GCP credentials required) and is used by tests and
local development. A real ADK-backed runner is wired later in integration.

FakeRunner event sequence:
    PLAN
    AWAITING_APPROVAL(gate=plan)        <- pauses until ApprovalDecision posted
    TOOL_CALL(tool="vector_search")
    TOOL_RESULT(hits=5, top_score=0.97)
    TOOL_CALL(tool="aggregate")
    TOOL_RESULT(count=3, total=12500.0)
    PROPOSAL(items=[...])
    AWAITING_APPROVAL(gate=action)      <- pauses until ApprovalDecision posted
    WRITTEN(flagged=3)
    REPORT_READY(run_id=...)
    DONE
"""

from __future__ import annotations

import asyncio
from typing import AsyncIterator, Protocol, runtime_checkable

from faultaudit.agent import roster
from faultaudit.models import (
    AgentEvent,
    ApprovalDecision,
    ApprovalGate,
    AuditReport,
    EventType,
    FlaggedItem,
    FlaggedReason,
    MissionRequest,
)


@runtime_checkable
class AgentRunner(Protocol):
    """Protocol for a runner that executes a mission and yields AgentEvents.

    The runner is started once per run via `run()` which returns an async
    iterator. The runner may pause (by not yielding further) while waiting
    for a human approval. `deliver_decision` is called by the server to
    resume the paused run.
    """

    async def run(
        self, run_id: str, mission: MissionRequest
    ) -> AsyncIterator[AgentEvent]:
        ...  # pragma: no cover

    async def deliver_decision(
        self, run_id: str, decision: ApprovalDecision
    ) -> None:
        ...  # pragma: no cover


# --------------------------------------------------------------------------- #
# FakeRunner
# --------------------------------------------------------------------------- #

_FAKE_ITEMS = [
    FlaggedItem(
        invoice_id="INV-001",
        vendor_name="Acme Corp",
        department="Finance",
        amount=7500.0,
        reasons=[FlaggedReason.DUPLICATE],
        similarity=0.97,
        detail="Duplicate invoice from same vendor same month",
    ),
    FlaggedItem(
        invoice_id="INV-002",
        vendor_name="Ghost LLC",
        department="IT",
        amount=3000.0,
        reasons=[FlaggedReason.GHOST_VENDOR],
        detail="Vendor has no verifiable registration",
    ),
    FlaggedItem(
        invoice_id="INV-003",
        vendor_name="NightPay Inc",
        department="Operations",
        amount=2000.0,
        reasons=[FlaggedReason.OFF_HOURS],
        detail="Payment processed at 03:00 local time",
    ),
]


class FakeRunner:
    """Scripted in-memory runner for tests and local dev (no external dependencies)."""

    def __init__(self) -> None:
        # Per run_id: asyncio.Event that is set when a decision arrives.
        self._approval_events: dict[str, asyncio.Event] = {}
        # Per run_id: the decision delivered.
        self._decisions: dict[str, ApprovalDecision] = {}

    async def run(
        self, run_id: str, mission: MissionRequest
    ) -> AsyncIterator[AgentEvent]:
        """Emit the scripted event sequence, pausing at two approval gates."""

        def _evt(etype: EventType, **data: object) -> AgentEvent:
            return AgentEvent(run_id=run_id, type=etype, data=dict(data))

        # --- Gate 1: PLAN ---
        yield _evt(EventType.PLAN, plan=f"Audit plan for: {mission.text}", **roster.MISSION_PLANNING)
        yield _evt(EventType.AWAITING_APPROVAL, gate=ApprovalGate.PLAN.value, **roster.HUMAN_GATE)

        # Wait for plan approval
        await self._wait_for_decision(run_id)
        plan_decision = self._decisions.pop(run_id)
        if not plan_decision.approved:
            yield _evt(EventType.ERROR, reason="Plan rejected by reviewer")
            yield _evt(EventType.DONE)
            return

        # --- Tool execution ---
        yield _evt(EventType.TOOL_CALL, tool="vector_search", query=mission.text, **roster.VECTOR_SEARCH)
        yield _evt(EventType.TOOL_RESULT, tool="vector_search", hits=5, top_score=0.97, **roster.VECTOR_SEARCH)
        yield _evt(EventType.TOOL_CALL, tool="aggregate", bucket="vendor_month", **roster.SPEND_ANALYSIS)
        yield _evt(
            EventType.TOOL_RESULT,
            tool="aggregate",
            count=3,
            total=12500.0,
            **roster.SPEND_ANALYSIS,
        )

        # --- Gate 2: PROPOSAL ---
        yield _evt(
            EventType.PROPOSAL,
            items=[item.model_dump(mode="json") for item in _FAKE_ITEMS],
            **roster.RISK_TRIAGE,
        )
        yield _evt(EventType.AWAITING_APPROVAL, gate=ApprovalGate.ACTION.value, **roster.HUMAN_GATE)

        # Wait for action approval
        await self._wait_for_decision(run_id)
        action_decision = self._decisions.pop(run_id)

        # Determine which items were approved
        approved_ids = set(action_decision.approved_ids) or {
            item.invoice_id for item in _FAKE_ITEMS
        }
        approved_items = [i for i in _FAKE_ITEMS if i.invoice_id in approved_ids]

        # --- Write & finish ---
        yield _evt(EventType.WRITTEN, flagged=len(approved_items), **roster.AUDIT_TRAIL)

        report = AuditReport(
            run_id=run_id,
            mission=mission.text,
            flagged_count=len(approved_items),
            total_at_risk=sum(i.amount for i in approved_items),
            items=approved_items,
            markdown=_build_markdown(mission.text, approved_items),
        )
        yield _evt(
            EventType.REPORT_READY,
            run_id=run_id,
            flagged_count=report.flagged_count,
            total_at_risk=report.total_at_risk,
            report=report.model_dump(mode="json"),
            **roster.REPORT_GENERATION,
        )
        yield _evt(EventType.DONE)

    async def deliver_decision(
        self, run_id: str, decision: ApprovalDecision
    ) -> None:
        """Deliver an approval decision to unblock the paused runner coroutine."""
        self._decisions[run_id] = decision
        event = self._approval_events.get(run_id)
        if event is not None:
            event.set()

    # ------------------------------------------------------------------ helpers

    async def _wait_for_decision(self, run_id: str) -> None:
        """Block until deliver_decision is called for this run_id."""
        event = asyncio.Event()
        self._approval_events[run_id] = event
        await event.wait()
        # Clean up
        self._approval_events.pop(run_id, None)


def _build_markdown(mission: str, items: list[FlaggedItem]) -> str:
    lines = [
        f"# Audit Report",
        f"",
        f"**Mission:** {mission}",
        f"",
        f"## Flagged Items ({len(items)})",
        f"",
    ]
    for item in items:
        reasons = ", ".join(r.value for r in item.reasons)
        lines.append(
            f"- **{item.invoice_id}** — {item.vendor_name} — ${item.amount:,.2f} — {reasons} — {item.detail}"
        )
    return "\n".join(lines)
