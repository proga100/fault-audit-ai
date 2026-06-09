"""Phase 2 E2E: a full audit mission through the REAL slices, on mock data, no creds.

mission -> audit pipeline (Agent-Core tools) -> two-gate approval (GateMachine)
        -> gated write (mark_flagged) -> report (render_report)

Proves the independently-built slices compose into a correct end-to-end audit.
"""

from __future__ import annotations

from faultaudit.agent.gates import GateMachine
from faultaudit.agent.pipeline import run_audit
from faultaudit.agent.report import render_report
from faultaudit.models import ApprovalDecision, ApprovalGate, FlaggedReason
from faultaudit.tools.flagging import mark_flagged

RUN_ID = "run-e2e-1"
MISSION = "Audit this month's vendor payments"


def _reasons_for(items, invoice_id):
    return next((set(it.reasons) for it in items if it.invoice_id == invoice_id), set())


def test_full_mission_finds_planted_fraud_and_writes_report(mock_db):
    # 1. Agent runs the audit (the tool-driven step)
    items = run_audit(mock_db)
    flagged_ids = {it.invoice_id for it in items}

    # the planted fraud must be caught by the right detectors
    assert "i2" in flagged_ids and FlaggedReason.DUPLICATE in _reasons_for(items, "i2")
    assert "i4" in flagged_ids and FlaggedReason.POLICY_VIOLATION in _reasons_for(items, "i4")
    assert "i5" in flagged_ids and FlaggedReason.OFF_HOURS in _reasons_for(items, "i5")
    assert "i6" in flagged_ids and FlaggedReason.GHOST_VENDOR in _reasons_for(items, "i6")

    # 2. Two-gate human-in-the-loop
    gm = GateMachine(RUN_ID)
    gm.submit_plan("1. vector search 2. aggregate 3. policy check 4. propose")
    assert gm.status == "awaiting_plan"
    gm.approve_plan(ApprovalDecision(gate=ApprovalGate.PLAN, approved=True))
    assert gm.status == "executing"

    gm.propose(items)
    assert gm.status == "awaiting_action"
    approved_ids = gm.approve_action(
        ApprovalDecision(gate=ApprovalGate.ACTION, approved_ids=list(flagged_ids))
    )
    assert set(approved_ids) == flagged_ids

    # 3. Gated write
    result = mark_flagged(mock_db, RUN_ID, approved_ids, items)
    assert result.flagged_count == len(flagged_ids)
    assert mock_db.audit_log.count_documents({"run_id": RUN_ID}) == 1
    for iid in flagged_ids:
        assert mock_db.transactions.find_one({"invoice_id": iid})["flagged"] is True

    # 4. Report
    report = render_report(RUN_ID, MISSION, items)
    assert report.flagged_count == len(items)
    assert report.total_at_risk == sum(it.amount for it in items)
    assert "## " in report.markdown or "#" in report.markdown  # has a markdown heading


def test_write_is_idempotent(mock_db):
    items = run_audit(mock_db)
    ids = [it.invoice_id for it in items]
    mark_flagged(mock_db, "run-idem", ids, items)
    mark_flagged(mock_db, "run-idem", ids, items)  # second call must not double-write
    assert mock_db.audit_log.count_documents({"run_id": "run-idem"}) == 1


def test_rejecting_plan_blocks_execution(mock_db):
    gm = GateMachine("run-reject")
    gm.submit_plan("plan")
    gm.approve_plan(ApprovalDecision(gate=ApprovalGate.PLAN, approved=False))
    assert gm.status in ("done", "error")  # rejected plan must not reach executing
