"""The gated WRITE. Owned by Agent-Core slice.

This is the only mutation in the system and runs ONLY after Gate-2 approval. Exposed to
the agent as a LongRunningFunctionTool so the runtime pauses until the human approves.

CONTRACT:
    mark_flagged(db, run_id, approved_ids, items) -> WriteResult
        - sets transactions.flagged=true + audit metadata on approved_ids
        - appends one audit_log document
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from faultaudit.models import FlaggedItem


class WriteResult(BaseModel):
    flagged_count: int
    audit_log_id: str


def mark_flagged(
    db: Any, run_id: str, approved_ids: list[str], items: list[FlaggedItem]
) -> WriteResult:
    """Write flags for approved invoices + append an audit_log doc. Idempotent per run_id."""
    raise NotImplementedError("Agent-Core slice: implement via TDD")
