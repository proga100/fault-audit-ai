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

from typing import Any, Optional


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
    raise NotImplementedError("Agent-Core slice: implement via TDD")


def aggregate_spend(db: Any, group_by: str = "department") -> list[dict]:
    """Sum amount grouped by a field (department/category/vendor_name)."""
    raise NotImplementedError("Agent-Core slice: implement via TDD")


def get_vendor_history(db: Any, vendor_id: str) -> dict:
    """Vendor record + summary stats (invoice count, total, first/last seen, is_ghost)."""
    raise NotImplementedError("Agent-Core slice: implement via TDD")
