"""Duplicate / near-duplicate detection. Owned by Agent-Core slice. Pure logic -> TDD.

CONTRACT:
    find_exact_duplicates(invoices)  -> list[tuple[str, str]]  (original_id, duplicate_id)
    find_near_duplicates(invoices, threshold) -> list[NearDuplicate]
"""

from __future__ import annotations

from pydantic import BaseModel

from faultaudit.models import Invoice


class NearDuplicate(BaseModel):
    invoice_id: str
    similar_to_id: str
    similarity: float
    reason: str


def _cosine(a: list[float], b: list[float]) -> float:
    """Cosine similarity between two vectors using pure Python."""
    dot = sum(x * y for x, y in zip(a, b))
    mag_a = sum(x * x for x in a) ** 0.5
    mag_b = sum(y * y for y in b) ** 0.5
    if mag_a == 0.0 or mag_b == 0.0:
        return 0.0
    return dot / (mag_a * mag_b)


def find_exact_duplicates(invoices: list[Invoice]) -> list[tuple[str, str]]:
    """Exact dupes = same vendor_id + amount + category (different invoice_id).

    Returns (original_invoice_id, duplicate_invoice_id) pairs. This is the cheap
    aggregation-style check; near-duplicates need vectors (see find_near_duplicates).
    """
    # Map (vendor_id, amount, category) -> first invoice seen (by invoice_date, then position)
    from collections import defaultdict

    groups: dict[tuple, list[Invoice]] = defaultdict(list)
    for inv in invoices:
        key = (inv.vendor_id, inv.amount, inv.category)
        groups[key].append(inv)

    result: list[tuple[str, str]] = []
    for key, group in groups.items():
        if len(group) < 2:
            continue
        # Sort: earliest invoice_date first; ties broken by original list order
        sorted_group = sorted(group, key=lambda i: (i.invoice_date, invoices.index(i)))
        original = sorted_group[0]
        for dup in sorted_group[1:]:
            result.append((original.invoice_id, dup.invoice_id))
    return result


def find_near_duplicates(
    invoices: list[Invoice], threshold: float = 0.92
) -> list[NearDuplicate]:
    """Near dupes = high cosine similarity on `embedding` but NOT exact matches.

    Requires invoices to carry `embedding`. This is what justifies vector search:
    catching reworded/nudged resubmissions exact matching misses.
    """
    # Build set of exact-dup pairs to exclude
    exact_pairs: set[frozenset[str]] = {
        frozenset([a, b]) for a, b in find_exact_duplicates(invoices)
    }

    # Only consider invoices that have embeddings
    embedded = [inv for inv in invoices if inv.embedding is not None]

    result: list[NearDuplicate] = []
    for i in range(len(embedded)):
        for j in range(i + 1, len(embedded)):
            inv_a = embedded[i]
            inv_b = embedded[j]
            pair = frozenset([inv_a.invoice_id, inv_b.invoice_id])
            if pair in exact_pairs:
                continue
            sim = _cosine(inv_a.embedding, inv_b.embedding)  # type: ignore[arg-type]
            if sim >= threshold:
                result.append(
                    NearDuplicate(
                        invoice_id=inv_b.invoice_id,
                        similar_to_id=inv_a.invoice_id,
                        similarity=round(sim, 6),
                        reason=f"Cosine similarity {sim:.4f} >= threshold {threshold}",
                    )
                )
    return result
