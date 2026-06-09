"""OFAC SDN sanctions screening (the live web-service tool). Owned by Agent-Core slice.

CONTRACT:
    load_sdn(path|url) -> list[str]                  (cached SDN names)
    screen_vendor_sanctions(name, sdn, threshold) -> Optional[SanctionsHit]

The fuzzy matcher is pure logic -> TDD it. The network fetch is mocked with respx.
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel


class SanctionsHit(BaseModel):
    query: str
    matched_name: str
    score: float


def load_sdn(source: Optional[str] = None) -> list[str]:
    """Load OFAC SDN entity names from local cache (or download + cache if missing).

    Network call must be mockable (respx). Returns a list of canonical names.
    """
    raise NotImplementedError("Agent-Core slice: implement via TDD")


def screen_vendor_sanctions(
    name: str, sdn: list[str], threshold: float = 0.85
) -> Optional[SanctionsHit]:
    """Fuzzy-match `name` against the SDN list. Return best hit >= threshold, else None."""
    raise NotImplementedError("Agent-Core slice: implement via TDD")
