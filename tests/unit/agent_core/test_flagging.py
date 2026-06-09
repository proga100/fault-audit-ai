"""Tests for tools/flagging.py — mark_flagged + idempotency"""

from __future__ import annotations

import pytest

from faultaudit.models import FlaggedItem, FlaggedReason
from faultaudit.tools.flagging import WriteResult, mark_flagged


def make_item(invoice_id: str, amount: float = 1000.0) -> FlaggedItem:
    return FlaggedItem(
        invoice_id=invoice_id,
        vendor_name="Test Corp",
        department="Finance",
        amount=amount,
        reasons=[FlaggedReason.DUPLICATE],
        detail="test",
    )


class TestMarkFlagged:
    def test_write_result_correct(self, mock_db):
        items = [make_item("i1"), make_item("i2")]
        result = mark_flagged(mock_db, "run-001", ["i1", "i2"], items)
        assert isinstance(result, WriteResult)
        assert result.flagged_count == 2
        assert result.audit_log_id == "run-001"

    def test_transactions_marked_flagged(self, mock_db):
        mark_flagged(mock_db, "run-002", ["i1"], [make_item("i1")])
        doc = mock_db.transactions.find_one({"invoice_id": "i1"})
        assert doc["flagged"] is True

    def test_only_approved_ids_flagged(self, mock_db):
        mark_flagged(mock_db, "run-003", ["i1"], [make_item("i1"), make_item("i2")])
        i2 = mock_db.transactions.find_one({"invoice_id": "i2"})
        assert i2.get("flagged") is not True

    def test_audit_log_entry_written(self, mock_db):
        mark_flagged(mock_db, "run-004", ["i1", "i3"], [make_item("i1"), make_item("i3")])
        log = mock_db.audit_log.find_one({"run_id": "run-004"})
        assert log is not None
        assert log["count"] == 2
        assert set(log["invoice_ids"]) == {"i1", "i3"}

    def test_idempotent_does_not_double_write(self, mock_db):
        items = [make_item("i1")]
        mark_flagged(mock_db, "run-005", ["i1"], items)
        mark_flagged(mock_db, "run-005", ["i1"], items)  # second call same run_id
        # Exactly one audit_log doc for run-005
        count = mock_db.audit_log.count_documents({"run_id": "run-005"})
        assert count == 1

    def test_idempotent_returns_same_result(self, mock_db):
        items = [make_item("i1"), make_item("i2")]
        r1 = mark_flagged(mock_db, "run-006", ["i1", "i2"], items)
        r2 = mark_flagged(mock_db, "run-006", ["i1", "i2"], items)
        assert r1.flagged_count == r2.flagged_count
        assert r1.audit_log_id == r2.audit_log_id

    def test_different_run_ids_are_independent(self, mock_db):
        items = [make_item("i1")]
        mark_flagged(mock_db, "run-A", ["i1"], items)
        mark_flagged(mock_db, "run-B", ["i1"], items)
        count = mock_db.audit_log.count_documents({})
        assert count == 2

    def test_empty_approved_ids(self, mock_db):
        result = mark_flagged(mock_db, "run-007", [], [])
        assert result.flagged_count == 0
        log = mock_db.audit_log.find_one({"run_id": "run-007"})
        assert log is not None
        assert log["count"] == 0

    def test_run_id_stored_on_transaction(self, mock_db):
        mark_flagged(mock_db, "run-008", ["i4"], [make_item("i4")])
        doc = mock_db.transactions.find_one({"invoice_id": "i4"})
        assert doc["run_id"] == "run-008"

    def test_flagged_at_stored(self, mock_db):
        mark_flagged(mock_db, "run-009", ["i5"], [make_item("i5")])
        doc = mock_db.transactions.find_one({"invoice_id": "i5"})
        assert "flagged_at" in doc
