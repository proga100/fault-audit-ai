"""RealRunner — the live agent: real Gemini reasoning + real Atlas vector search.

Drives the same two-gate event sequence as FakeRunner, but:
  * PLAN + report narrative come from Gemini 3 (Vertex AI)
  * semantic similarity uses real Atlas $vectorSearch (the MongoDB superpower)
  * fast O(n) detectors find duplicates / policy / ghost / off-hours
  * the gated write hits real Atlas

Used when USE_MOCKS=false. Requires ATLAS_URI + GCP creds in the environment.
"""

from __future__ import annotations

import asyncio
from collections import defaultdict
from typing import AsyncIterator

from pymongo import MongoClient

from faultaudit.agent import llm
from faultaudit.agent.embedding import embed_query
from faultaudit.agent.mcp_reads import mcp_aggregate
from faultaudit.agent.report import render_report
from faultaudit.config import get_settings
from faultaudit.models import (
    AgentEvent,
    ApprovalDecision,
    ApprovalGate,
    EventType,
    FlaggedItem,
    FlaggedReason,
    Invoice,
    MissionRequest,
    Policy,
    Vendor,
)
from faultaudit.tools.dedup import find_exact_duplicates
from faultaudit.tools.mongo_reads import aggregate_spend, vector_search_transactions
from faultaudit.tools.policy import check_policy

BUSINESS_START, BUSINESS_END = 8, 18
VECTOR_SIMILAR_MIN = 0.80  # surface vector hits at/above this score as VECTOR_SIMILAR
MAX_FLAGGED = 40  # cap: a human reviews exceptions, not hundreds of rows
HIGH_SIGNAL = {
    FlaggedReason.OFAC_HIT,
    FlaggedReason.GHOST_VENDOR,
    FlaggedReason.DUPLICATE,
    FlaggedReason.NEAR_DUPLICATE,
    FlaggedReason.VECTOR_SIMILAR,
}


class RealRunner:
    """Live runner backed by Atlas + Vertex AI."""

    def __init__(self) -> None:
        self._settings = get_settings()
        self._client = MongoClient(self._settings.atlas_uri)
        self._db = self._client[self._settings.db_name]
        self._approval_events: dict[str, asyncio.Event] = {}
        self._decisions: dict[str, ApprovalDecision] = {}

    # ------------------------------------------------------------------ run
    async def run(self, run_id: str, mission: MissionRequest) -> AsyncIterator[AgentEvent]:
        def evt(t: EventType, **data) -> AgentEvent:
            return AgentEvent(run_id=run_id, type=t, data=dict(data))

        db = self._db

        # --- Gate 1: Gemini-authored plan (timeout-guarded so it can't hang) ---
        _PLAN_FALLBACK = (
            "1. Vector-search transactions similar to known fraud patterns.\n"
            "2. Aggregate spend by department.\n"
            "3. Check policy limits, duplicates, ghost vendors, off-hours.\n"
            "4. Screen payees against sanctions.\n"
            "5. Propose a flagged list for your approval."
        )
        try:
            plan = await asyncio.wait_for(asyncio.to_thread(llm.plan_for, mission.text), timeout=30)
        except (asyncio.TimeoutError, Exception):
            plan = _PLAN_FALLBACK
        yield evt(EventType.PLAN, plan=plan)
        yield evt(EventType.AWAITING_APPROVAL, gate=ApprovalGate.PLAN.value)
        await self._wait(run_id)
        if not self._decisions.pop(run_id).approved:
            yield evt(EventType.ERROR, reason="Plan rejected by reviewer")
            yield evt(EventType.DONE)
            return

        # --- Tool 1: $vectorSearch via the MongoDB MCP server (partner integration) ---
        yield evt(EventType.TOOL_CALL, tool="mongodb.vectorSearch", query=mission.text,
                  via="MongoDB MCP server")
        qvec = await asyncio.to_thread(embed_query, mission.text)
        source = "MongoDB MCP server"
        hits: list[dict] = []
        if self._settings.use_mcp_reads:
            pipeline = [
                {"$vectorSearch": {"index": self._settings.vector_index_name, "path": "embedding",
                                   "queryVector": qvec, "numCandidates": 150, "limit": 8}},
                {"$addFields": {"score": {"$meta": "vectorSearchScore"}}},
                {"$project": {"_id": 0, "embedding": 0}},
            ]
            try:
                hits = await mcp_aggregate(self._settings.db_name, self._settings.txn_collection, pipeline)
            except Exception:  # noqa: BLE001
                hits = []
        if not hits:  # fallback keeps the demo reliable if the MCP subprocess hiccups
            hits = await asyncio.to_thread(vector_search_transactions, db, qvec, 8)
            source = "direct driver (MCP fallback)"
        top = round(hits[0]["score"], 4) if hits else 0.0
        yield evt(
            EventType.TOOL_RESULT, tool="mongodb.vectorSearch", via=source, hits=len(hits), top_score=top,
            sample=[{"invoice_id": h.get("invoice_id"), "vendor_name": h.get("vendor_name"),
                     "score": round(h["score"], 3)} for h in hits[:5]],
        )

        # --- Tool 2: real aggregation ---
        yield evt(EventType.TOOL_CALL, tool="mongodb.aggregate", group_by="department")
        spend = await asyncio.to_thread(aggregate_spend, db, "department")
        yield evt(EventType.TOOL_RESULT, tool="mongodb.aggregate",
                  by_department=sorted(spend, key=lambda s: s["total"], reverse=True))

        # --- Assemble flagged list (fast detectors + vector hits), cap for review ---
        all_items = await asyncio.to_thread(self._assemble, db, hits)
        items = all_items[:MAX_FLAGGED]
        dept_counts: dict[str, int] = defaultdict(int)
        vendor_counts: dict[str, int] = defaultdict(int)
        for it in all_items:
            dept_counts[it.department] += 1
            vendor_counts[it.vendor_name] += 1
        yield evt(
            EventType.PROPOSAL,
            items=[i.model_dump(mode="json") for i in items],
            total_flagged=len(all_items),
            shown=len(items),
            total_at_risk=sum(i.amount for i in all_items),
            dept_counts=dict(dept_counts),
            vendor_counts=dict(vendor_counts),
        )
        yield evt(EventType.AWAITING_APPROVAL, gate=ApprovalGate.ACTION.value)
        await self._wait(run_id)
        decision = self._decisions.pop(run_id)

        # approve set: explicit approves win; else all-minus-rejected; else all shown
        proposed = {i.invoice_id for i in items}
        if decision.approved_ids:
            keep = set(decision.approved_ids) & proposed
        elif decision.rejected_ids:
            keep = proposed - set(decision.rejected_ids)
        else:
            keep = proposed
        approved = [i for i in items if i.invoice_id in keep]

        # --- Gated write to Atlas ---
        from faultaudit.tools.flagging import mark_flagged

        await asyncio.to_thread(mark_flagged, db, run_id, [i.invoice_id for i in approved], approved)
        yield evt(EventType.WRITTEN, flagged=len(approved))

        # --- Report (Gemini narrative + structured) ---
        report = render_report(run_id, mission.text, approved)
        reasons = [r.value for it in approved for r in it.reasons]
        try:
            narrative = await asyncio.wait_for(
                asyncio.to_thread(llm.summarize, mission.text, report.flagged_count, report.total_at_risk, reasons),
                timeout=30,
            )
        except (asyncio.TimeoutError, Exception):
            narrative = (f"Flagged {report.flagged_count} transactions totalling "
                         f"${report.total_at_risk:,.0f} at risk across {len(set(reasons))} risk types.")
        report.markdown = f"# Audit Report\n\n{narrative}\n\n" + report.markdown
        yield evt(EventType.REPORT_READY, run_id=run_id, flagged_count=report.flagged_count,
                  total_at_risk=report.total_at_risk, report=report.model_dump(mode="json"))
        yield evt(EventType.DONE)

    async def deliver_decision(self, run_id: str, decision: ApprovalDecision) -> None:
        self._decisions[run_id] = decision
        ev = self._approval_events.get(run_id)
        if ev is not None:
            ev.set()

    async def _wait(self, run_id: str) -> None:
        ev = asyncio.Event()
        self._approval_events[run_id] = ev
        await ev.wait()
        self._approval_events.pop(run_id, None)

    # --------------------------------------------------------------- audit
    def _assemble(self, db, vector_hits: list[dict]) -> list[FlaggedItem]:
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
        return items  # full sorted list; caller caps and reports the total
