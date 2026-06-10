"""Risk triage — assemble the flagged-candidate list from the detector suite.

Shared by the deterministic RealRunner, the ADK agent's `run_detectors` tool, and
the ADK runner's proposal enrichment, so every execution path proposes the same
evidence-backed candidates.
"""

from __future__ import annotations

from collections import defaultdict

from faultaudit.models import FlaggedItem, FlaggedReason, Invoice, Policy, Vendor
from faultaudit.tools.dedup import find_exact_duplicates
from faultaudit.tools.policy import check_policy

BUSINESS_START, BUSINESS_END = 8, 18
VECTOR_SIMILAR_MIN = 0.80  # surface vector hits at/above this score as VECTOR_SIMILAR
HIGH_SIGNAL = {
    FlaggedReason.OFAC_HIT,
    FlaggedReason.GHOST_VENDOR,
    FlaggedReason.DUPLICATE,
    FlaggedReason.NEAR_DUPLICATE,
    FlaggedReason.VECTOR_SIMILAR,
}


def assemble_flagged(db, vector_hits: list[dict]) -> list[FlaggedItem]:
    """Run the detector suite over the ledger and return prioritised candidates.

    Detectors: policy limits, ghost vendors, off-hours payments, exact duplicates,
    plus vector-similarity hits supplied by the caller (real `$vectorSearch` output).
    """
    invoices = [Invoice.model_validate(d) for d in db.transactions.find({}, {"embedding": 0})]
    vendors = {v["vendor_id"]: Vendor.model_validate(v) for v in db.vendors.find({}, {"_id": 0})}
    policies = [Policy.model_validate(p) for p in db.policies.find({}, {"_id": 0})]
    by_id = {i.invoice_id: i for i in invoices}

    reasons: dict[str, set[FlaggedReason]] = defaultdict(set)
    details: dict[str, list[str]] = defaultdict(list)
    sims: dict[str, float] = {}

    for inv in invoices:
        for v in check_policy(inv, policies):
            reasons[inv.invoice_id].add(FlaggedReason.POLICY_VIOLATION)
            details[inv.invoice_id].append(f"{v.rule_id}: {v.amount:.0f} > {v.max_amount:.0f}")
        vend = vendors.get(inv.vendor_id)
        if vend and vend.is_ghost:
            reasons[inv.invoice_id].add(FlaggedReason.GHOST_VENDOR)
            details[inv.invoice_id].append("payment to ghost vendor")
        if inv.payment_hour < BUSINESS_START or inv.payment_hour > BUSINESS_END:
            reasons[inv.invoice_id].add(FlaggedReason.OFF_HOURS)
            details[inv.invoice_id].append(f"paid at {inv.payment_hour:02d}:00")

    for original_id, dup_id in find_exact_duplicates(invoices):
        reasons[dup_id].add(FlaggedReason.DUPLICATE)
        details[dup_id].append(f"exact duplicate of {original_id}")

    # vector-similar to the mission (real $vectorSearch results)
    for h in vector_hits:
        score = h.get("score", 0.0)
        iid = h.get("invoice_id")
        if iid and score >= VECTOR_SIMILAR_MIN:
            reasons[iid].add(FlaggedReason.VECTOR_SIMILAR)
            sims[iid] = score
            details[iid].append(f"semantically matches the audit query ({score:.2f})")

    items: list[FlaggedItem] = []
    for iid, rset in reasons.items():
        inv = by_id.get(iid)
        if inv is None:
            continue
        items.append(FlaggedItem(
            invoice_id=iid, vendor_name=inv.vendor_name, department=inv.department,
            amount=inv.amount, reasons=sorted(rset, key=lambda r: r.value),
            similarity=sims.get(iid), detail="; ".join(details[iid]),
        ))

    # Prioritise: high-signal fraud first, then by # of distinct reasons, then $.
    def _priority(it: FlaggedItem):
        high = len(set(it.reasons) & HIGH_SIGNAL)
        return (high > 0, high, len(it.reasons), it.amount)

    items.sort(key=_priority, reverse=True)
    return items
