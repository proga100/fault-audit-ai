"""Tests for faultaudit/agent/report.py — render_report"""

from __future__ import annotations

import pytest

from faultaudit.models import AuditReport, FlaggedItem, FlaggedReason
from faultaudit.agent.report import render_report


def make_item(invoice_id: str, amount: float, reasons=None) -> FlaggedItem:
    return FlaggedItem(
        invoice_id=invoice_id,
        vendor_name="Test Corp",
        department="Finance",
        amount=amount,
        reasons=reasons or [FlaggedReason.DUPLICATE],
        detail=f"Item {invoice_id}",
    )


class TestRenderReport:
    def test_returns_audit_report_instance(self):
        report = render_report("r1", "Audit test", [])
        assert isinstance(report, AuditReport)

    def test_run_id_set(self):
        report = render_report("run-abc", "mission", [])
        assert report.run_id == "run-abc"

    def test_mission_set(self):
        report = render_report("r1", "Audit May invoices", [])
        assert report.mission == "Audit May invoices"

    def test_flagged_count_zero_for_empty(self):
        report = render_report("r1", "mission", [])
        assert report.flagged_count == 0

    def test_flagged_count_matches_items_length(self):
        items = [make_item("i1", 1000), make_item("i2", 2000), make_item("i3", 3000)]
        report = render_report("r1", "mission", items)
        assert report.flagged_count == 3

    def test_total_at_risk_zero_for_empty(self):
        report = render_report("r1", "mission", [])
        assert report.total_at_risk == 0.0

    def test_total_at_risk_sum_of_amounts(self):
        items = [make_item("i1", 1000.0), make_item("i2", 2500.0), make_item("i3", 750.0)]
        report = render_report("r1", "mission", items)
        assert report.total_at_risk == pytest.approx(4250.0)

    def test_items_list_stored(self):
        items = [make_item("i1", 1000)]
        report = render_report("r1", "mission", items)
        assert len(report.items) == 1
        assert report.items[0].invoice_id == "i1"

    def test_markdown_contains_title(self):
        report = render_report("r1", "mission", [])
        assert "FaultAuditAI" in report.markdown

    def test_markdown_contains_mission(self):
        report = render_report("r1", "Audit May invoices", [])
        assert "Audit May invoices" in report.markdown

    def test_markdown_contains_run_id(self):
        report = render_report("run-xyz", "mission", [])
        assert "run-xyz" in report.markdown

    def test_markdown_contains_flagged_count(self):
        items = [make_item("i1", 1000), make_item("i2", 2000)]
        report = render_report("r1", "mission", items)
        assert "2" in report.markdown

    def test_markdown_contains_total_at_risk(self):
        items = [make_item("i1", 10000.0)]
        report = render_report("r1", "mission", items)
        assert "10,000" in report.markdown or "10000" in report.markdown

    def test_markdown_contains_invoice_ids(self):
        items = [make_item("inv-001", 500), make_item("inv-002", 1500)]
        report = render_report("r1", "mission", items)
        assert "inv-001" in report.markdown
        assert "inv-002" in report.markdown

    def test_markdown_is_string(self):
        report = render_report("r1", "mission", [])
        assert isinstance(report.markdown, str)
        assert len(report.markdown) > 0

    def test_markdown_has_table_for_items(self):
        items = [make_item("i1", 1000)]
        report = render_report("r1", "mission", items)
        # Markdown table should have | delimiters
        assert "|" in report.markdown

    def test_multiple_reasons_in_table(self):
        reasons = [FlaggedReason.DUPLICATE, FlaggedReason.OFAC_HIT]
        items = [make_item("i1", 5000, reasons=reasons)]
        report = render_report("r1", "mission", items)
        assert "duplicate" in report.markdown
        assert "ofac_hit" in report.markdown

    def test_generated_at_set(self):
        report = render_report("r1", "mission", [])
        assert report.generated_at is not None
