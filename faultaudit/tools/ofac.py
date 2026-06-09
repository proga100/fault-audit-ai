"""OFAC SDN sanctions screening (the live web-service tool). Owned by Agent-Core slice.

CONTRACT:
    load_sdn(path|url) -> list[str]                  (cached SDN names)
    screen_vendor_sanctions(name, sdn, threshold) -> Optional[SanctionsHit]

The fuzzy matcher is pure logic -> TDD it. The network fetch is mocked with respx.
"""

from __future__ import annotations

import csv
import io
from pathlib import Path
from typing import Optional
import difflib

import httpx
from pydantic import BaseModel

from faultaudit.config import get_settings


class SanctionsHit(BaseModel):
    query: str
    matched_name: str
    score: float


def _parse_sdn_csv(text: str) -> list[str]:
    """Parse OFAC SDN CSV and return list of names (first column)."""
    names: list[str] = []
    reader = csv.reader(io.StringIO(text))
    for row in reader:
        if row and row[0].strip():
            names.append(row[0].strip())
    return names


def load_sdn(source: Optional[str] = None) -> list[str]:
    """Load OFAC SDN entity names from local cache (or download + cache if missing).

    Network call must be mockable (respx). Returns a list of canonical names.
    """
    settings = get_settings()
    cache_path = Path(settings.ofac_cache_path)

    # If local cache exists, read from it
    if cache_path.exists():
        text = cache_path.read_text(encoding="utf-8", errors="replace")
        return _parse_sdn_csv(text)

    # Otherwise download and cache
    url = source or settings.ofac_sdn_url
    response = httpx.get(url, follow_redirects=True)
    response.raise_for_status()
    text = response.text

    # Cache to disk for future calls
    try:
        cache_path.write_text(text, encoding="utf-8")
    except OSError:
        pass  # can't write cache; that's OK

    return _parse_sdn_csv(text)


def screen_vendor_sanctions(
    name: str, sdn: list[str], threshold: float = 0.85
) -> Optional[SanctionsHit]:
    """Fuzzy-match `name` against the SDN list. Return best hit >= threshold, else None."""
    name_lower = name.lower()
    best_score = 0.0
    best_name = ""

    for candidate in sdn:
        score = difflib.SequenceMatcher(
            None, name_lower, candidate.lower()
        ).ratio()
        if score > best_score:
            best_score = score
            best_name = candidate

    if best_score >= threshold:
        return SanctionsHit(query=name, matched_name=best_name, score=best_score)
    return None
