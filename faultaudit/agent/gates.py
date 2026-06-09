"""Approval gate state machine. Owned by Agent-Core slice.

Implements the two-gate approval flow used by FaultAuditAI.

State transitions:
    planning -> awaiting_plan  (submit_plan)
    awaiting_plan -> executing (approve_plan with approved=True)
    awaiting_plan -> done      (approve_plan with approved=False / rejected)
    executing -> awaiting_action (propose)
    awaiting_action -> writing (approve_action with some approved_ids)
    awaiting_action -> done    (approve_action with empty approved_ids / rejected)
    writing -> done            (complete)
"""

from __future__ import annotations

from typing import Optional

from faultaudit.models import ApprovalDecision, FlaggedItem, RunStatus


class GateMachineError(Exception):
    """Raised when an invalid state transition is attempted."""


class GateMachine:
    """Two-gate approval state machine for a single audit run.

    Gates:
        Gate 1 (PLAN): human approves / edits / rejects the proposed plan
        Gate 2 (ACTION): human approves the list of invoices to flag

    Pure logic — no I/O.
    """

    def __init__(self, run_id: str) -> None:
        self.run_id = run_id
        self._status: RunStatus = "planning"
        self._plan: Optional[str] = None
        self._proposed_items: list[FlaggedItem] = []
        self._approved_ids: list[str] = []

    # ---------------------------------------------------------------------- #
    # Public state accessor
    # ---------------------------------------------------------------------- #
    @property
    def status(self) -> RunStatus:
        return self._status

    @property
    def plan(self) -> Optional[str]:
        return self._plan

    @property
    def proposed_items(self) -> list[FlaggedItem]:
        return list(self._proposed_items)

    @property
    def approved_ids(self) -> list[str]:
        return list(self._approved_ids)

    # ---------------------------------------------------------------------- #
    # State transition methods
    # ---------------------------------------------------------------------- #
    def submit_plan(self, plan_text: str) -> None:
        """Agent submits the proposed plan. Transitions planning -> awaiting_plan."""
        self._require_status("planning", "submit_plan")
        if not plan_text or not plan_text.strip():
            raise GateMachineError("plan_text must be non-empty")
        self._plan = plan_text
        self._status = "awaiting_plan"

    def approve_plan(self, decision: ApprovalDecision) -> None:
        """Human approves or rejects Gate 1.

        approved=True  -> transitions awaiting_plan -> executing
        approved=False -> transitions awaiting_plan -> done
        If edited_plan is provided and approved=True, the plan text is updated.
        """
        self._require_status("awaiting_plan", "approve_plan")
        if decision.approved:
            if decision.edited_plan is not None:
                self._plan = decision.edited_plan
            self._status = "executing"
        else:
            self._status = "done"

    def propose(self, items: list[FlaggedItem]) -> None:
        """Agent proposes the list of flagged items for Gate 2 review.

        Transitions executing -> awaiting_action.
        """
        self._require_status("executing", "propose")
        self._proposed_items = list(items)
        self._status = "awaiting_action"

    def approve_action(self, decision: ApprovalDecision) -> list[str]:
        """Human approves a subset of flagged invoices for writing.

        Transitions awaiting_action -> writing (if approved_ids non-empty and approved=True)
        or awaiting_action -> done (if rejected or empty list).

        Returns the list of approved invoice_ids that should be passed to mark_flagged.
        """
        self._require_status("awaiting_action", "approve_action")
        if decision.approved and decision.approved_ids:
            self._approved_ids = list(decision.approved_ids)
            self._status = "writing"
        else:
            self._approved_ids = []
            self._status = "done"
        return list(self._approved_ids)

    def complete(self) -> None:
        """Mark the write phase done. Transitions writing -> done."""
        self._require_status("writing", "complete")
        self._status = "done"

    # ---------------------------------------------------------------------- #
    # Internal helpers
    # ---------------------------------------------------------------------- #
    def _require_status(self, expected: RunStatus, op: str) -> None:
        if self._status != expected:
            raise GateMachineError(
                f"Cannot call '{op}' in state '{self._status}'; expected '{expected}'"
            )
