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


def find_exact_duplicates(invoices: list[Invoice]) -> list[tuple[str, str]]:
    """Exact dupes = same vendor_id + amount + category (different invoice_id).

    Returns (original_invoice_id, duplicate_invoice_id) pairs. This is the cheap
    aggregation-style check; near-duplicates need vectors (see find_near_duplicates).
    """
    raise NotImplementedError("Agent-Core slice: implement via TDD")


def find_near_duplicates(
    invoices: list[Invoice], threshold: float = 0.92
) -> list[NearDuplicate]:
    """Near dupes = high cosine similarity on `embedding` but NOT exact matches.

    Requires invoices to carry `embedding`. This is what justifies vector search:
    catching reworded/nudged resubmissions exact matching misses.
    """
    raise NotImplementedError("Agent-Core slice: implement via TDD")
