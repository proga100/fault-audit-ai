"""Gemini text generation via Vertex AI (the agent's reasoning).

Used for the audit PLAN and the report narrative. Every call is wrapped so a model/quota
hiccup degrades to a sensible template instead of breaking the mission — the audit itself
never depends on the LLM being up.
"""

from __future__ import annotations

import logging
from functools import lru_cache

from faultaudit.config import get_settings

log = logging.getLogger(__name__)


@lru_cache
def _client():
    from google import genai

    s = get_settings()
    # Gemini 3 preview models serve from the `global` location, not us-central1.
    return genai.Client(vertexai=True, project=s.gcp_project, location=s.gemini_location)


def generate(prompt: str, fallback: str = "") -> str:
    """Generate text with Gemini on Vertex AI. Returns `fallback` on any failure."""
    s = get_settings()
    try:
        resp = _client().models.generate_content(model=s.gemini_model, contents=prompt)
        return (resp.text or fallback).strip()
    except Exception as exc:  # noqa: BLE001 — never let the LLM break the mission
        log.warning("Gemini generate failed (%s); using fallback", type(exc).__name__)
        return fallback


def plan_for(mission: str) -> str:
    fallback = (
        "1. Vector-search transactions semantically similar to known fraud patterns.\n"
        "2. Aggregate spend by department to spot anomalies.\n"
        "3. Check invoices against policy limits, duplicates, ghost vendors and off-hours.\n"
        "4. Screen payees against the OFAC sanctions list.\n"
        "5. Assemble a flagged list for your approval before writing anything."
    )
    return generate(
        f"You are a corporate finance audit agent. The user mission is: '{mission}'.\n"
        "Write a short numbered plan (max 5 steps) of how you'll audit the vendor payments "
        "using MongoDB vector search, aggregation, policy checks and sanctions screening. "
        "Plain text, no preamble.",
        fallback=fallback,
    )


def summarize(mission: str, flagged_count: int, total_at_risk: float, reasons: list[str]) -> str:
    fallback = (
        f"Audited vendor payments for the mission '{mission}'. Flagged {flagged_count} "
        f"transactions totalling ${total_at_risk:,.0f} at risk, spanning: "
        f"{', '.join(sorted(set(reasons))) or 'n/a'}. Review the table below and the audit log."
    )
    return generate(
        f"Summarize this corporate finance audit in 2-3 sentences for a finance reviewer. "
        f"Mission: '{mission}'. Flagged {flagged_count} transactions, ${total_at_risk:,.0f} at risk. "
        f"Reason types: {', '.join(sorted(set(reasons)))}. Be concrete and concise.",
        fallback=fallback,
    )
