"""Phase-0 smoke tests: prove the contracts + harness work. These pass today.

Slice feature tests live in tests/unit/<slice>/ and start RED (NotImplementedError).
"""

from __future__ import annotations

from faultaudit.models import (
    AgentEvent,
    ApprovalDecision,
    ApprovalGate,
    EventType,
    FlaggedItem,
    FlaggedReason,
)
from faultaudit.server.events import parse_sse_data, to_sse


def test_sample_fixtures_load(invoices, vendors, policies):
    assert len(invoices) == 6
    assert any(i.is_near_duplicate for i in invoices)
    assert any(i.is_ghost_vendor for i in invoices)
    assert all(i.embedding for i in invoices)


def test_mock_db_populated(mock_db):
    assert mock_db.transactions.count_documents({}) == 6
    assert mock_db.vendors.count_documents({}) == 2


def test_event_sse_roundtrip():
    ev = AgentEvent(
        run_id="r1",
        type=EventType.TOOL_RESULT,
        data={"tool": "vector_search", "hits": 3, "top_score": 0.91},
    )
    frame = to_sse(ev)
    assert "event: tool_result" in frame
    # extract the data line and parse it back
    data_line = [ln for ln in frame.splitlines() if ln.startswith("data: ")][0][6:]
    back = parse_sse_data(data_line)
    assert back.run_id == "r1"
    assert back.type is EventType.TOOL_RESULT


def test_approval_decision_shapes():
    plan = ApprovalDecision(gate=ApprovalGate.PLAN, approved=True)
    action = ApprovalDecision(gate=ApprovalGate.ACTION, approved_ids=["i4", "i6"])
    assert plan.gate is ApprovalGate.PLAN
    assert action.approved_ids == ["i4", "i6"]


def test_flagged_item_contract():
    item = FlaggedItem(
        invoice_id="i3", vendor_name="Acme Corp", department="Finance", amount=20300,
        reasons=[FlaggedReason.NEAR_DUPLICATE, FlaggedReason.VECTOR_SIMILAR], similarity=0.94,
    )
    assert FlaggedReason.NEAR_DUPLICATE in item.reasons
    assert item.similarity == 0.94
