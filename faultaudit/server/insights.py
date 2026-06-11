"""Read-only insight endpoints' logic: integration status, dataset stats, assistant.

Everything here is best-effort and never raises to the route layer — the UI must
always get a sane payload (the dashboard may not be empty, the status strip may
not break the page). No secrets ever leave this module: connection strings, key
paths and project IDs stay server-side.
"""

from __future__ import annotations

import json
import logging
from functools import lru_cache
from typing import Any, Optional

from faultaudit.config import DATA_DIR, get_settings
from faultaudit.models import AskResponse, AuditReport

log = logging.getLogger(__name__)

# Last-resort baseline matching the shape of the generated demo ledger, used only
# when neither Atlas nor the local demo_dataset files are reachable.
_FALLBACK_STATS = {"invoices": 1000, "vendors": 80, "total_spend": 4_800_000.0, "source": "baseline"}


def get_status() -> dict:
    """Integration status for the UI strip. Safe to expose: no URIs, no keys."""
    s = get_settings()
    live = not s.use_mocks
    agent_runtime = "mock"
    if live:
        agent_runtime = "adk_multi_agent" if s.use_adk else "pipeline"
    return {
        "mode": "live" if live else "demo",
        "gemini_model": s.gemini_model,
        "gemini_active": True,  # planner/report/assistant route through Gemini (with fallback)
        "mcp_enabled": bool(live and s.atlas_uri and s.use_mcp_reads),
        "mcp_server": "mongodb-mcp-server (read-only)",
        "agent_runtime": agent_runtime,
        "agent_runtime_label": {
            "mock": "Scripted demo runner",
            "adk_multi_agent": "Google ADK multi-agent",
            "pipeline": "Direct pipeline fallback",
        }[agent_runtime],
        "human_approval": True,   # structural gates — always on
        "audit_trail": True,      # gated writes land in the audit_log collection
    }


@lru_cache(maxsize=1)
def get_stats() -> dict:
    """Dataset scope for the dashboard's first paint: invoices, vendors, total spend.

    Live mode reads Atlas; demo mode reads the local demo_dataset files; both fall
    back to a static baseline so the endpoint never fails. Cached per process —
    the in-scope dataset doesn't change during a demo.
    """
    s = get_settings()
    if not s.use_mocks and s.atlas_uri:
        try:
            from pymongo import MongoClient

            client: MongoClient = MongoClient(s.atlas_uri, serverSelectionTimeoutMS=4000)
            db = client[s.db_name]
            total = next(
                db[s.txn_collection].aggregate([{"$group": {"_id": None, "t": {"$sum": "$amount"}}}]),
                {},
            ).get("t", 0.0)
            stats = {
                "invoices": db[s.txn_collection].count_documents({}),
                "vendors": db[s.vendor_collection].count_documents({}),
                "total_spend": float(total),
                "source": "mongodb-atlas",
            }
            client.close()
            if stats["invoices"]:
                return stats
        except Exception as exc:  # noqa: BLE001 — stats must never break the page
            log.warning("Atlas stats failed (%s); falling back", type(exc).__name__)
    try:
        invoices = json.loads((DATA_DIR / "invoices.json").read_text())
        vendors = json.loads((DATA_DIR / "vendors.json").read_text())
        return {
            "invoices": len(invoices),
            "vendors": len(vendors),
            "total_spend": float(sum(i.get("amount", 0.0) for i in invoices)),
            "source": "demo-dataset",
        }
    except Exception:  # noqa: BLE001
        return dict(_FALLBACK_STATS)


# --------------------------------------------------------------------------- #
# AI Audit Assistant ("Ask Audit Agent" drawer)
# --------------------------------------------------------------------------- #

def _run_context(report: Optional[AuditReport]) -> str:
    """Compact, grounded context block for the assistant prompt."""
    stats = get_stats()
    lines = [
        f"Dataset in scope: {stats['invoices']} invoices from {stats['vendors']} vendors, "
        f"total spend ${stats['total_spend']:,.0f}.",
    ]
    if report is not None:
        lines.append(
            f"Current audit run: mission '{report.mission}' flagged {report.flagged_count} "
            f"invoices, ${report.total_at_risk:,.0f} at risk."
        )
        for it in report.items[:15]:
            reasons = ", ".join(r.value for r in it.reasons)
            lines.append(
                f"- {it.invoice_id} | {it.vendor_name} | {it.department} | "
                f"${it.amount:,.0f} | {reasons} | {it.detail}"
            )
    else:
        lines.append("No completed audit run in this session yet.")
    return "\n".join(lines)


def _invoice_context_lines(invoice_context: Optional[dict[str, Any]]) -> list[str]:
    """Compact invoice evidence block supplied by the UI during Gate 2 review."""
    if not invoice_context:
        return []
    reasons = invoice_context.get("reasons") or []
    if isinstance(reasons, str):
        reasons_text = reasons
    else:
        reasons_text = ", ".join(str(r).replace("_", " ") for r in reasons)
    amount = invoice_context.get("amount") or 0
    try:
        amount_text = f"${float(amount):,.0f}"
    except (TypeError, ValueError):
        amount_text = str(amount)
    return [
        "Clicked invoice evidence:",
        f"- invoice_id: {invoice_context.get('invoice_id', 'unknown')}",
        f"- vendor: {invoice_context.get('vendor_name', 'unknown')}",
        f"- department: {invoice_context.get('department', 'unknown')}",
        f"- amount: {amount_text}",
        f"- reasons: {reasons_text or 'not supplied'}",
        f"- evidence: {invoice_context.get('detail') or 'not supplied'}",
    ]


def _template_invoice_answer(invoice_context: dict[str, Any]) -> str:
    reasons = invoice_context.get("reasons") or []
    reasons_text = ", ".join(str(r).replace("_", " ") for r in reasons) if not isinstance(reasons, str) else reasons
    amount = invoice_context.get("amount") or 0
    try:
        amount_text = f"${float(amount):,.0f}"
    except (TypeError, ValueError):
        amount_text = str(amount)
    detail = invoice_context.get("detail") or "No detailed evidence was supplied."
    invoice_id = invoice_context.get("invoice_id", "this invoice")
    vendor = invoice_context.get("vendor_name", "the vendor")
    dept = invoice_context.get("department", "the department")
    return (
        f"Invoice {invoice_id} from {vendor} ({dept}) is flagged for "
        f"{reasons_text or 'audit risk'} on a {amount_text} payment. Evidence: {detail}. "
        "The auditor should verify the vendor master record, PO or contract approval, "
        "duplicate invoice history, payment authorization, and whether the policy threshold "
        "or exception approval is documented before approving the item."
    )


def _template_answer(
    question: str,
    report: Optional[AuditReport],
    invoice_context: Optional[dict[str, Any]] = None,
) -> str:
    """Deterministic grounded answer used in demo mode / as the LLM fallback."""
    if invoice_context:
        return _template_invoice_answer(invoice_context)
    stats = get_stats()
    if report is None:
        return (
            f"No audit run has completed in this session yet. The dataset in scope holds "
            f"{stats['invoices']} invoices from {stats['vendors']} vendors "
            f"(${stats['total_spend']:,.0f} total spend). Launch a mission from Mission "
            f"Control and I can answer questions about the findings."
        )
    top = sorted(report.items, key=lambda i: i.amount, reverse=True)[:3]
    top_lines = "".join(
        f"\n• {it.invoice_id} — {it.vendor_name} — ${it.amount:,.0f} "
        f"({', '.join(r.value.replace('_', ' ') for r in it.reasons)})"
        for it in top
    )
    return (
        f"Regarding “{question.strip()}”: the mission “{report.mission}” flagged "
        f"{report.flagged_count} invoices worth ${report.total_at_risk:,.0f} at risk. "
        f"Highest-value flagged items:{top_lines}\n"
        f"Each flag carries its evidence in the Findings tab; every write was approved "
        f"by a human auditor before it reached the audit log."
    )


def answer_question(
    question: str,
    report: Optional[AuditReport],
    invoice_context: Optional[dict[str, Any]] = None,
) -> AskResponse:
    """Answer via Gemini when live, else via the grounded template."""
    s = get_settings()
    fallback = _template_answer(question, report, invoice_context)
    if s.use_mocks or not s.gcp_project:
        return AskResponse(answer=fallback, model="demo-template")

    from faultaudit.agent import llm

    context = "\n".join([
        _run_context(report),
        *_invoice_context_lines(invoice_context),
    ])
    prompt = (
        "You are the AI Audit Assistant inside FaultAuditAI, a corporate-finance fraud "
        "audit console. Answer the auditor's question using ONLY the context below. Be "
        "concrete, cite invoice IDs and amounts, and keep it under 150 words. For invoice "
        "review questions, structure the answer as: why flagged, evidence, what to verify "
        "next, and recommended action. If the context can't answer it, say so plainly.\n\n"
        f"CONTEXT:\n{context}\n\nQUESTION: {question.strip()}"
    )
    answer = llm.generate(prompt, fallback=fallback)
    return AskResponse(answer=answer, model=s.gemini_model)
