"""Policy checking. Owned by Agent-Core slice. Pure logic -> heavy TDD here.

CONTRACT:
    check_policy(invoice, policies) -> list[PolicyViolation]
"""

from __future__ import annotations

from pydantic import BaseModel

from faultaudit.models import Invoice, Policy


class PolicyViolation(BaseModel):
    rule_id: str
    text: str
    amount: float
    max_amount: float


def check_policy(invoice: Invoice, policies: list[Policy]) -> list[PolicyViolation]:
    """Return every policy `invoice` violates.

    A policy applies if policy.category == invoice.category OR policy.category == "*".
    It is violated if invoice.amount > policy.max_amount.
    """
    violations: list[PolicyViolation] = []
    for policy in policies:
        applies = policy.category == "*" or policy.category == invoice.category
        if applies and invoice.amount > policy.max_amount:
            violations.append(
                PolicyViolation(
                    rule_id=policy.rule_id,
                    text=policy.text,
                    amount=invoice.amount,
                    max_amount=policy.max_amount,
                )
            )
    return violations
