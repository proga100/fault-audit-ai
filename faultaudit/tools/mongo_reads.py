"""MongoDB read helpers. Owned by Agent-Core slice.

At RUNTIME the agent reads via the MongoDB MCP server (--readOnly). These helpers are
the direct-driver equivalents used for: (a) unit tests with mongomock, (b) any read the
agent needs outside the MCP path. Same query shapes as the MCP tools, so behaviour matches.

CONTRACT:
    vector_search_transactions(db, query_vector, k, filters) -> list[dict]   (carry 'score')
    aggregate_spend(db, group_by) -> list[dict]
    get_vendor_history(db, vendor_id) -> dict
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date
from typing import Any, Optional


def _cosine(a: list[float], b: list[float]) -> float:
    """Cosine similarity between two vectors."""
    dot = sum(x * y for x, y in zip(a, b))
    mag_a = sum(x * x for x in a) ** 0.5
    mag_b = sum(y * y for y in b) ** 0.5
    if mag_a == 0.0 or mag_b == 0.0:
        return 0.0
    return dot / (mag_a * mag_b)


def vector_search_transactions(
    db: Any,
    query_vector: list[float],
    k: int = 10,
    filters: Optional[dict] = None,
) -> list[dict]:
    """$vectorSearch over transactions.embedding. Each result dict includes 'score'.

    Under mongomock there is no $vectorSearch, so the test/mock path falls back to
    brute-force cosine over stored embeddings (config.use_mocks drives this).
    """
    query = filters or {}
    docs = list(db.transactions.find(query, {"_id": 0}))

    scored: list[dict] = []
    for doc in docs:
        embedding = doc.get("embedding")
        if embedding is None:
            continue
        score = _cosine(query_vector, embedding)
        result = dict(doc)
        result["score"] = score
        scored.append(result)

    scored.sort(key=lambda d: d["score"], reverse=True)
    return scored[:k]


def aggregate_spend(db: Any, group_by: str = "department") -> list[dict]:
    """Sum amount grouped by a field (department/category/vendor_name)."""
    docs = list(db.transactions.find({}, {"_id": 0, group_by: 1, "amount": 1}))
    groups: dict[str, dict] = defaultdict(lambda: {"total": 0.0, "count": 0})

    for doc in docs:
        key = doc.get(group_by, "unknown")
        groups[key]["total"] += doc.get("amount", 0.0)
        groups[key]["count"] += 1

    return [{"_id": k, "total": v["total"], "count": v["count"]} for k, v in groups.items()]


def get_vendor_history(db: Any, vendor_id: str) -> dict:
    """Vendor record + summary stats (invoice count, total, first/last seen, is_ghost)."""
    vendor = db.vendors.find_one({"vendor_id": vendor_id}, {"_id": 0})
    if vendor is None:
        return {}

    invoices = list(db.transactions.find({"vendor_id": vendor_id}, {"_id": 0}))
    invoice_count = len(invoices)
    total_amount = sum(doc.get("amount", 0.0) for doc in invoices)

    dates: list[date] = []
    for doc in invoices:
        raw_date = doc.get("invoice_date")
        if raw_date is not None:
            if isinstance(raw_date, str):
                from datetime import date as dt_date
                try:
                    parsed = dt_date.fromisoformat(raw_date)
                    dates.append(parsed)
                except ValueError:
                    pass
            elif isinstance(raw_date, date):
                dates.append(raw_date)

    first_invoice_date = str(min(dates)) if dates else None
    last_invoice_date = str(max(dates)) if dates else None

    return {
        **vendor,
        "invoice_count": invoice_count,
        "total_amount": total_amount,
        "first_invoice_date": first_invoice_date,
        "last_invoice_date": last_invoice_date,
        "is_ghost": vendor.get("is_ghost", False),
    }
