"""Tests for tools/policy.py — check_policy"""

from __future__ import annotations

import pytest

from faultaudit.models import Invoice, Policy
from faultaudit.tools.policy import PolicyViolation, check_policy


def make_invoice(amount: float, category: str = "Consulting") -> Invoice:
    return Invoice(
        invoice_id="i_test",
        vendor_id="v1",
        vendor_name="Test Corp",
        department="Finance",
        category=category,
        amount=amount,
        payment_method="ACH",
        invoice_date="2026-05-01",
        payment_hour=10,
        approved_by="Tester",
        notes="test",
    )


class TestCheckPolicy:
    def test_no_violation_within_limit(self, policies):
        inv = make_invoice(4999.99, "Travel")
        result = check_policy(inv, policies)
        assert result == []

    def test_exact_limit_is_not_violation(self, policies):
        # > not >= so 5000 is NOT a violation
        inv = make_invoice(5000.0, "Travel")
        result = check_policy(inv, policies)
        assert result == []

    def test_single_category_violation(self, policies):
        inv = make_invoice(6000.0, "Travel")
        violations = check_policy(inv, policies)
        rule_ids = [v.rule_id for v in violations]
        assert "P1" in rule_ids  # Travel > 5000

    def test_consulting_violation(self, policies):
        inv = make_invoice(60000.0, "Consulting")
        violations = check_policy(inv, policies)
        rule_ids = [v.rule_id for v in violations]
        assert "P2" in rule_ids  # Consulting > 50000

    def test_wildcard_policy_applies_to_all_categories(self, policies):
        inv = make_invoice(150000.0, "Catering")  # no specific policy for Catering
        violations = check_policy(inv, policies)
        rule_ids = [v.rule_id for v in violations]
        assert "P4" in rule_ids  # wildcard > 100000

    def test_multiple_violations_returned(self, policies):
        # Consulting 120000 -> violates P2 (>50000) + P4 (>100000)
        inv = make_invoice(120000.0, "Consulting")
        violations = check_policy(inv, policies)
        rule_ids = {v.rule_id for v in violations}
        assert "P2" in rule_ids
        assert "P4" in rule_ids

    def test_wrong_category_no_violation(self, policies):
        # P1 is Travel-only; Catering 6000 should NOT trigger P1
        inv = make_invoice(6000.0, "Catering")
        violations = check_policy(inv, policies)
        rule_ids = [v.rule_id for v in violations]
        assert "P1" not in rule_ids

    def test_violation_carries_correct_amounts(self, policies):
        inv = make_invoice(6000.0, "Travel")
        violations = check_policy(inv, policies)
        v = next(x for x in violations if x.rule_id == "P1")
        assert v.amount == 6000.0
        assert v.max_amount == 5000.0

    def test_empty_policies_returns_empty(self):
        inv = make_invoice(999999.0, "Travel")
        assert check_policy(inv, []) == []

    def test_violation_text_matches_policy(self, policies):
        inv = make_invoice(6000.0, "Travel")
        violations = check_policy(inv, policies)
        v = next(x for x in violations if x.rule_id == "P1")
        assert "VP" in v.text  # from the fixture's policy text
