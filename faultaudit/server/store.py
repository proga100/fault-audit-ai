"""In-memory run store for FaultAuditAI.

Each run has:
  - metadata (run_id, mission text, status)
  - an asyncio.Queue[AgentEvent | None] — None is the sentinel for "stream done"
  - an optional final AuditReport (set when REPORT_READY fires)
  - a reference to the runner so approvals can be forwarded
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Optional

from faultaudit.models import (
    AgentEvent,
    ApprovalDecision,
    AuditReport,
    MissionRequest,
)
from faultaudit.server.runner import AgentRunner


class RunRecord:
    def __init__(self, run_id: str, mission: MissionRequest, runner: AgentRunner) -> None:
        self.run_id = run_id
        self.mission = mission
        self.runner = runner
        self.queue: asyncio.Queue[Optional[AgentEvent]] = asyncio.Queue()
        self.report: Optional[AuditReport] = None


class RunStore:
    """Thread-safe (asyncio-safe) in-memory store of active/completed runs."""

    def __init__(self) -> None:
        self._runs: dict[str, RunRecord] = {}

    def create_run(self, mission: MissionRequest, runner: AgentRunner) -> RunRecord:
        """Create a new run record and return it."""
        run_id = str(uuid.uuid4())
        record = RunRecord(run_id=run_id, mission=mission, runner=runner)
        self._runs[run_id] = record
        return record

    def get_run(self, run_id: str) -> Optional[RunRecord]:
        """Return the run record or None if unknown."""
        return self._runs.get(run_id)

    def require_run(self, run_id: str) -> RunRecord:
        """Return the run record or raise KeyError if unknown."""
        record = self._runs.get(run_id)
        if record is None:
            raise KeyError(run_id)
        return record

    async def push_approval(
        self, run_id: str, decision: ApprovalDecision
    ) -> None:
        """Forward an approval decision to the runner for this run."""
        record = self.require_run(run_id)
        await record.runner.deliver_decision(run_id, decision)

    def set_report(self, run_id: str, report: AuditReport) -> None:
        """Persist the final audit report for a completed run."""
        record = self._runs.get(run_id)
        if record is not None:
            record.report = report

    def get_report(self, run_id: str) -> Optional[AuditReport]:
        record = self._runs.get(run_id)
        if record is None:
            return None
        return record.report

    def newest_report(self) -> Optional[AuditReport]:
        for record in reversed(list(self._runs.values())):
            if record.report is not None:
                return record.report
        return None


# Module-level singleton used by the FastAPI app.
run_store = RunStore()
