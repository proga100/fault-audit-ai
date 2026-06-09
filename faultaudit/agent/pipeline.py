"""Deterministic audit pipeline — composes the Agent-Core tools into a flagged list.

This is the audit logic the ADK agent orchestrates via tool calls. Pulling it into one
pure function means: (a) the app can run a full audit on mock data with NO Gemini/creds,
and (b) the real agent's tools and this pipeline share identical behaviour.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Optional

from faultaudit.config import get_settings
from faultaudit.models import FlaggedItem, FlaggedReason, Invoice, Policy, Vendor
from faultaudit.tools.dedup import find_exact_duplicates, find_near_duplicates
from faultaudit.tools.policy import check_policy

BUSINESS_START, BUSINESS_END = 8, 18  # off-hours = outside [08:00, 18:00]


def _load(db: Any) -> tuple[list[Invoice], dict[str, Vendor], list[Policy]]:
    invoices = [Invoice.model_validate(d) for d in db.transactions.find({}, {"_id": 0})]
    vendors = {v["vendor_id"]: Vendor.model_validate(v) for v in db.vendors.find({}, {"_id": 0})}
    policies = [Policy.model_validate(p) for p in db.policies.find({}, {"_id": 0})]
    return invoices, vendors, policies


def run_audit(db: Any, near_threshold: Optional[float] = None) -> list[FlaggedItem]:
    """Run the full audit over a populated MongoDB and return proposed FlaggedItems."""
    settings = get_settings()
    threshold = near_threshold if near_threshold is not None else settings.neardup_similarity_threshold
    invoices, vendors, policies = _load(db)
    by_id = {inv.invoice_id: inv for inv in invoices}

    reasons: dict[str, set[FlaggedReason]] = defaultdict(set)
    details: dict[str, list[str]] = defaultdict(list)
    sims: dict[str, float] = {}

    # policy violations
    for inv in invoices:
        for v in check_policy(inv, policies):
            reasons[inv.invoice_id].add(FlaggedReason.POLICY_VIOLATION)
            details[inv.invoice_id].append(f"{v.rule_id}: {v.amount:.0f} > {v.max_amount:.0f}")

    # exact duplicates (aggregation-style)
    for original_id, dup_id in find_exact_duplicates(invoices):
        reasons[dup_id].add(FlaggedReason.DUPLICATE)
        details[dup_id].append(f"exact duplicate of {original_id}")

    # near-duplicates (vector search — the MongoDB superpower)
    for nd in find_near_duplicates(invoices, threshold):
        reasons[nd.invoice_id].add(FlaggedReason.NEAR_DUPLICATE)
        reasons[nd.invoice_id].add(FlaggedReason.VECTOR_SIMILAR)
        sims[nd.invoice_id] = nd.similarity
        details[nd.invoice_id].append(f"semantically similar to {nd.similar_to_id} ({nd.similarity:.2f})")

    # ghost vendor + off-hours
    for inv in invoices:
        vendor = vendors.get(inv.vendor_id)
        if vendor and vendor.is_ghost:
            reasons[inv.invoice_id].add(FlaggedReason.GHOST_VENDOR)
            details[inv.invoice_id].append("payment to ghost vendor")
        if inv.payment_hour < BUSINESS_START or inv.payment_hour > BUSINESS_END:
            reasons[inv.invoice_id].add(FlaggedReason.OFF_HOURS)
            details[inv.invoice_id].append(f"paid at {inv.payment_hour:02d}:00")

    items: list[FlaggedItem] = []
    for invoice_id, reason_set in reasons.items():
        inv = by_id[invoice_id]
        items.append(
            FlaggedItem(
                invoice_id=invoice_id,
                vendor_name=inv.vendor_name,
                department=inv.department,
                amount=inv.amount,
                reasons=sorted(reason_set, key=lambda r: r.value),
                similarity=sims.get(invoice_id),
                detail="; ".join(details[invoice_id]),
            )
        )
    items.sort(key=lambda it: it.amount, reverse=True)
    return items
