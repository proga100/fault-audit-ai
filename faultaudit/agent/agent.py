"""FaultAuditAI agent team — built on Vertex AI Agent Builder (Google ADK).

THIS is the file that "uses Vertex AI Agent Builder":
  * google.adk  == the Agent Builder SDK (code-first path of Vertex AI Agent Builder)
  * LlmAgent    == Agent Builder agents, reasoning with Gemini 3 on Vertex AI
  * McpToolset  == the partner MCP integration (official MongoDB MCP server, read-only)
  * LongRunningFunctionTool == the human-in-the-loop approval gate primitive

Deploys to Vertex AI Agent Engine (Agent Builder's managed runtime).
Set GOOGLE_GENAI_USE_VERTEXAI=TRUE so the model runs on Vertex AI, not the public API.
"""

from __future__ import annotations

import asyncio
import os
from collections import defaultdict
from typing import Any

from google.adk.agents import LlmAgent
from google.adk.tools import FunctionTool, LongRunningFunctionTool
from google.adk.tools.mcp_tool.mcp_toolset import (
    McpToolset,
    StdioConnectionParams,
    StdioServerParameters,
)

from faultaudit.config import get_settings

settings = get_settings()

COORDINATOR_INSTRUCTION = """\
You are FaultAuditCoordinatorAgent, the root Google ADK / Agent Builder coordinator
for FaultAuditAI. Orchestrate a corporate-finance fraud audit through specialist
ADK agents. Use Gemini 3 via the configured model setting. Never write or flag
anything without explicit human approval.

Workflow you must follow:
1. Turn 1: delegate to MissionPlanningAgent and return a short numbered plan only.
2. After Gate 1 approval: gather evidence with TransactionScreeningAgent,
   SpendAnalysisAgent and RiskTriageAgent. Prefer MongoDB MCP evidence tools where
   available. Use internal tools only for OFAC, evidence merge/ranking and fallback.
3. Propose flagged invoice IDs for Gate 2. Do not write.
4. After Gate 2 approval: AuditTrailAgent performs the gated write, then
   ReportGenerationAgent drafts a concise closing narrative.
Be concise and concrete. Cite invoice IDs, amounts and evidence sources.
"""

PLANNING_INSTRUCTION = """You are MissionPlanningAgent. Produce a short numbered audit
plan for the user's finance mission. Mention Gemini 3, MongoDB MCP vector search,
MongoDB aggregation, detector evidence and human approval gates. Return only the plan."""

TRANSACTION_SCREENING_INSTRUCTION = """You are TransactionScreeningAgent. Use MongoDB
MCP vector-search evidence to find transactions semantically related to the mission.
Return concrete invoice IDs, vendors, scores and the evidence source."""

SPEND_ANALYSIS_INSTRUCTION = """You are SpendAnalysisAgent. Use MongoDB MCP aggregate,
count and schema evidence to summarize spend by department, vendor or category. Return
concise numeric evidence."""

RISK_TRIAGE_INSTRUCTION = """You are RiskTriageAgent. Combine MongoDB MCP-powered
detector evidence with internal OFAC screening and fallback detector results. Return
flagged invoice candidates with reasons and evidence. Do not write."""

HUMAN_APPROVAL_INSTRUCTION = """You are HumanApprovalAgent. Explain which approval gate
is needed and why. You never approve on behalf of the human auditor."""

AUDIT_TRAIL_INSTRUCTION = """You are AuditTrailAgent. Coordinate the gated write only
after the server confirms human approval. Do not invent writes."""

REPORT_INSTRUCTION = """You are ReportGenerationAgent. Write a concise finance-review
narrative from approved findings. Cite totals, risk categories and human approval."""

ASSISTANT_INSTRUCTION = """You are AuditAssistantAgent. Answer auditor questions using
only provided audit context. Be concrete, cite invoice IDs and amounts, and state when
the context cannot answer."""


# --------------------------------------------------------------------------- #
# Partner MCP integration: the official MongoDB MCP server, read-only.
# This is the "partner superpower" — vector search + aggregation over Atlas.
# --------------------------------------------------------------------------- #
def build_mongodb_mcp() -> McpToolset:
    return McpToolset(
        connection_params=StdioConnectionParams(
            server_params=StdioServerParameters(
                command=settings.mcp_command,  # npx
                args=settings.mcp_args.split(","),  # -y mongodb-mcp-server --readOnly
                env={"MDB_MCP_CONNECTION_STRING": settings.atlas_uri},
            ),
        ),
        # restrict the surface the model sees to the reads we want
        tool_filter=["find", "aggregate", "count", "collection-schema"],
    )


# --------------------------------------------------------------------------- #
# Custom tools (delegate to the tools/ slice — Agent-Core owns the bodies).
# ADK builds the function-calling schema from the signature + docstring.
# --------------------------------------------------------------------------- #
def _db():
    from pymongo import MongoClient

    s = get_settings()
    return MongoClient(s.atlas_uri)[s.db_name]


def _json_items(items: list[Any]) -> list[dict]:
    return [item.model_dump(mode="json") if hasattr(item, "model_dump") else dict(item) for item in items]


async def _mcp_or_empty(collection: str, pipeline: list[dict]) -> list[dict]:
    from faultaudit.agent.mcp_reads import mcp_aggregate

    s = get_settings()
    if not s.atlas_uri or not s.use_mcp_reads:
        return []
    return await mcp_aggregate(s.db_name, collection, pipeline)


async def run_vector_search_evidence(query: str, limit: int = 8) -> dict:
    """Run MongoDB MCP-backed Atlas Vector Search for suspicious transaction evidence.

    Args:
        query: Plain-English audit query.
        limit: Maximum hits to return.
    Returns:
        {"source": str, "hits": [{"invoice_id", "vendor_name", "score"}, ...]}
    """
    from faultaudit.agent.embedding import embed_query
    from faultaudit.tools.mongo_reads import vector_search_transactions

    s = get_settings()
    qvec = await asyncio.to_thread(embed_query, query)
    pipeline = [
        {"$vectorSearch": {"index": s.vector_index_name, "path": "embedding",
                           "queryVector": qvec, "numCandidates": max(100, limit * 15), "limit": limit}},
        {"$addFields": {"score": {"$meta": "vectorSearchScore"}}},
        {"$project": {"_id": 0, "embedding": 0}},
    ]
    hits = await _mcp_or_empty(s.txn_collection, pipeline)
    source = "MongoDB MCP · $vectorSearch"
    if not hits:
        hits = await asyncio.to_thread(vector_search_transactions, _db(), qvec, limit)
        source = "direct driver fallback"
    return {
        "source": source,
        "hits": [
            {
                "invoice_id": h.get("invoice_id"),
                "vendor_name": h.get("vendor_name"),
                "amount": h.get("amount"),
                "score": round(float(h.get("score", 0.0)), 4),
            }
            for h in hits[:limit]
        ],
    }


async def run_spend_aggregation(group_by: str = "department") -> dict:
    """Aggregate spend through MongoDB MCP, falling back to the direct driver.

    Args:
        group_by: One of department, vendor_name, category.
    Returns:
        {"source": str, "groups": [{"_id", "total", "count"}, ...]}
    """
    from faultaudit.tools.mongo_reads import aggregate_spend

    safe_group = group_by if group_by in {"department", "vendor_name", "category"} else "department"
    s = get_settings()
    pipeline = [
        {"$group": {"_id": f"${safe_group}", "total": {"$sum": "$amount"}, "count": {"$sum": 1}}},
        {"$sort": {"total": -1}},
        {"$limit": 20},
    ]
    groups = await _mcp_or_empty(s.txn_collection, pipeline)
    source = "MongoDB MCP · aggregate"
    if not groups:
        groups = await asyncio.to_thread(aggregate_spend, _db(), safe_group)
        source = "direct driver fallback"
    return {"source": source, "group_by": safe_group, "groups": groups}


async def detect_duplicate_invoices() -> dict:
    """Detect exact duplicate invoices with a MongoDB MCP aggregation.

    Returns:
        {"source": str, "duplicates": [{"original_id", "duplicate_id"}, ...]}
    """
    from faultaudit.models import Invoice
    from faultaudit.tools.dedup import find_exact_duplicates

    s = get_settings()
    pipeline = [
        {"$sort": {"invoice_date": 1, "invoice_id": 1}},
        {"$group": {
            "_id": {"vendor_id": "$vendor_id", "amount": "$amount", "category": "$category"},
            "invoice_ids": {"$push": "$invoice_id"},
            "count": {"$sum": 1},
        }},
        {"$match": {"count": {"$gt": 1}}},
        {"$project": {"_id": 0, "invoice_ids": 1}},
    ]
    docs = await _mcp_or_empty(s.txn_collection, pipeline)
    source = "MongoDB MCP · aggregate"
    pairs: list[dict] = []
    if docs:
        for doc in docs:
            ids = doc.get("invoice_ids", [])
            for dup_id in ids[1:]:
                pairs.append({"original_id": ids[0], "duplicate_id": dup_id})
    else:
        invoices = [Invoice.model_validate(d) for d in _db().transactions.find({}, {"embedding": 0})]
        pairs = [{"original_id": a, "duplicate_id": b} for a, b in find_exact_duplicates(invoices)]
        source = "direct detector fallback"
    return {"source": source, "duplicates": pairs}


async def detect_policy_violations() -> dict:
    """Detect policy threshold violations with MongoDB MCP aggregation where available."""
    from faultaudit.models import Invoice, Policy
    from faultaudit.tools.policy import check_policy as _check

    s = get_settings()
    pipeline = [
        {"$lookup": {"from": s.policy_collection, "localField": "category", "foreignField": "category", "as": "category_policies"}},
        {"$lookup": {"from": s.policy_collection, "pipeline": [{"$match": {"category": "*"}}], "as": "wildcard_policies"}},
        {"$project": {
            "_id": 0, "invoice_id": 1, "vendor_name": 1, "department": 1, "amount": 1,
            "policies": {"$concatArrays": ["$category_policies", "$wildcard_policies"]},
        }},
        {"$unwind": "$policies"},
        {"$match": {"$expr": {"$gt": ["$amount", "$policies.max_amount"]}}},
        {"$project": {
            "invoice_id": 1, "vendor_name": 1, "department": 1, "amount": 1,
            "rule_id": "$policies.rule_id", "max_amount": "$policies.max_amount", "text": "$policies.text",
        }},
        {"$limit": 100},
    ]
    docs = await _mcp_or_empty(s.txn_collection, pipeline)
    source = "MongoDB MCP · aggregate"
    if not docs:
        db = _db()
        policies = [Policy.model_validate(p) for p in db.policies.find({}, {"_id": 0})]
        docs = []
        for inv_doc in db.transactions.find({}, {"embedding": 0}):
            inv = Invoice.model_validate(inv_doc)
            for violation in _check(inv, policies):
                docs.append({"invoice_id": inv.invoice_id, "vendor_name": inv.vendor_name,
                             "department": inv.department, "amount": inv.amount, **violation.model_dump()})
        source = "direct detector fallback"
    return {"source": source, "violations": docs}


async def detect_off_hours_payments() -> dict:
    """Detect off-hours payments with MongoDB MCP filtering."""
    s = get_settings()
    pipeline = [
        {"$match": {"$or": [{"payment_hour": {"$lt": 8}}, {"payment_hour": {"$gt": 18}}]}},
        {"$project": {"_id": 0, "invoice_id": 1, "vendor_name": 1, "department": 1, "amount": 1, "payment_hour": 1}},
        {"$limit": 100},
    ]
    docs = await _mcp_or_empty(s.txn_collection, pipeline)
    source = "MongoDB MCP · aggregate"
    if not docs:
        docs = list(_db().transactions.find(
            {"$or": [{"payment_hour": {"$lt": 8}}, {"payment_hour": {"$gt": 18}}]},
            {"_id": 0, "embedding": 0},
        ).limit(100))
        source = "direct detector fallback"
    return {"source": source, "items": docs}


async def detect_ghost_vendor_payments() -> dict:
    """Detect payments to ghost vendors with MongoDB MCP lookup evidence."""
    s = get_settings()
    pipeline = [
        {"$lookup": {"from": s.vendor_collection, "localField": "vendor_id", "foreignField": "vendor_id", "as": "vendor"}},
        {"$unwind": "$vendor"},
        {"$match": {"vendor.is_ghost": True}},
        {"$project": {"_id": 0, "invoice_id": 1, "vendor_name": 1, "department": 1, "amount": 1, "vendor_id": 1}},
        {"$limit": 100},
    ]
    docs = await _mcp_or_empty(s.txn_collection, pipeline)
    source = "MongoDB MCP · aggregate"
    if not docs:
        db = _db()
        ghost_ids = [v["vendor_id"] for v in db.vendors.find({"is_ghost": True}, {"_id": 0, "vendor_id": 1})]
        docs = list(db.transactions.find({"vendor_id": {"$in": ghost_ids}}, {"_id": 0, "embedding": 0}).limit(100))
        source = "direct detector fallback"
    return {"source": source, "items": docs}


def _merge_detector_docs() -> dict[str, list[str]]:
    """Cheap direct summary used by run_detectors to make the agent context compact."""
    db = _db()
    reasons: dict[str, list[str]] = defaultdict(list)
    for doc in db.transactions.find({"$or": [{"payment_hour": {"$lt": 8}}, {"payment_hour": {"$gt": 18}}]},
                                    {"_id": 0, "invoice_id": 1, "payment_hour": 1}):
        reasons[doc["invoice_id"]].append(f"off-hours payment at {doc['payment_hour']:02d}:00")
    return reasons


def screen_vendor_sanctions(vendor_name: str) -> dict:
    """Screen a vendor against the live OFAC SDN sanctions list.

    Args:
        vendor_name: The payee/vendor legal name to screen.
    Returns:
        {"hit": bool, "matched_name": str | None, "score": float}
    """
    from faultaudit.tools.ofac import load_sdn, screen_vendor_sanctions as _screen

    hit = _screen(vendor_name, load_sdn(), settings.ofac_match_threshold)
    return hit.model_dump() | {"hit": True} if hit else {"hit": False, "matched_name": None, "score": 0.0}


def check_policy(invoice_id: str) -> dict:
    """Check a single invoice against corporate spend policies (P1-P4).

    Args:
        invoice_id: The invoice to evaluate.
    Returns:
        {"violations": [{"rule_id", "text", "amount", "max_amount"}, ...]}
    """
    from faultaudit.models import Invoice, Policy
    from faultaudit.tools.policy import check_policy as _check

    db = _db()
    raw = db.transactions.find_one({"invoice_id": invoice_id}, {"embedding": 0})
    if raw is None:
        return {"invoice_id": invoice_id, "violations": [], "found": False}
    invoice = Invoice.model_validate(raw)
    policies = [Policy.model_validate(p) for p in db.policies.find({}, {"_id": 0})]
    return {
        "invoice_id": invoice_id,
        "found": True,
        "violations": [v.model_dump(mode="json") for v in _check(invoice, policies)],
    }


def run_detectors(limit: int = 40) -> dict:
    """Run the internal fallback detector sweep and return triaged candidates.

    Args:
        limit: Maximum candidates to return.
    Returns:
        {"source": "internal detector fallback", "items": [...]}
    """
    from faultaudit.tools.triage import assemble_flagged

    items = assemble_flagged(_db(), [])[:limit]
    return {
        "source": "internal detector fallback",
        "items": [
            {
                "invoice_id": i.invoice_id,
                "vendor_name": i.vendor_name,
                "department": i.department,
                "amount": i.amount,
                "reasons": [r.value for r in i.reasons],
                "similarity": i.similarity,
                "detail": i.detail,
            }
            for i in items
        ],
    }


def mark_flagged(invoice_ids: list[str]) -> dict:
    """Flag the given invoices as audited-suspicious and write an audit log entry.

    This is a WRITE. It must only run after the human approves the specific items
    (Gate 2). Wrapped as a LongRunningFunctionTool so the runtime pauses for approval.

    Args:
        invoice_ids: Invoice IDs the human approved for flagging.
    Returns:
        {"status": "pending_approval"} initially; the server resumes it on approval.
    """
    # The long-running contract: return a pending status; the FastAPI layer supplies
    # the human decision and resumes the tool, which then performs the real write
    # via faultaudit.tools.flagging.mark_flagged.
    return {"status": "pending_approval", "invoice_ids": invoice_ids}


# --------------------------------------------------------------------------- #
# Assemble the Agent Builder agent.
# --------------------------------------------------------------------------- #
def _agent(name: str, description: str, instruction: str, tools: list[Any] | None = None) -> LlmAgent:
    return LlmAgent(
        name=name,
        description=description,
        model=settings.gemini_model,
        instruction=instruction,
        tools=tools or [],
        mode="task",
        disallow_transfer_to_parent=False,
        disallow_transfer_to_peers=True,
    )


def build_agent_team() -> LlmAgent:
    os.environ.setdefault("GOOGLE_GENAI_USE_VERTEXAI", "TRUE")
    os.environ.setdefault("GOOGLE_CLOUD_PROJECT", settings.gcp_project)
    os.environ.setdefault("GOOGLE_CLOUD_LOCATION", settings.gemini_location)

    transaction_tools: list[Any] = [FunctionTool(run_vector_search_evidence)]
    spend_tools: list[Any] = [FunctionTool(run_spend_aggregation)]
    if settings.atlas_uri:
        # Expose the official MongoDB MCP server to the read-only specialist agents.
        transaction_tools.insert(0, build_mongodb_mcp())
        spend_tools.insert(0, build_mongodb_mcp())

    mission_planning = _agent(
        "MissionPlanningAgent",
        "Creates the Gemini 3 audit plan before Gate 1.",
        PLANNING_INSTRUCTION,
    )
    transaction_screening = _agent(
        "TransactionScreeningAgent",
        "Uses MongoDB MCP vector search evidence over transaction embeddings.",
        TRANSACTION_SCREENING_INSTRUCTION,
        transaction_tools,
    )
    spend_analysis = _agent(
        "SpendAnalysisAgent",
        "Uses MongoDB MCP aggregation/count/schema evidence for spend analysis.",
        SPEND_ANALYSIS_INSTRUCTION,
        spend_tools,
    )
    risk_triage = _agent(
        "RiskTriageAgent",
        "Runs MCP-powered detector evidence and internal OFAC/fallback triage.",
        RISK_TRIAGE_INSTRUCTION,
        [
            FunctionTool(detect_duplicate_invoices),
            FunctionTool(detect_policy_violations),
            FunctionTool(detect_off_hours_payments),
            FunctionTool(detect_ghost_vendor_payments),
            FunctionTool(screen_vendor_sanctions),
            FunctionTool(check_policy),
            FunctionTool(run_detectors),
        ],
    )
    human_approval = _agent(
        "HumanApprovalAgent",
        "Explains human approval gates and never approves for the user.",
        HUMAN_APPROVAL_INSTRUCTION,
        [LongRunningFunctionTool(func=mark_flagged)],
    )
    audit_trail = _agent(
        "AuditTrailAgent",
        "Coordinates the approved gated write to the audit log.",
        AUDIT_TRAIL_INSTRUCTION,
        [LongRunningFunctionTool(func=mark_flagged)],
    )
    report_generation = _agent(
        "ReportGenerationAgent",
        "Generates the final Gemini 3 report narrative.",
        REPORT_INSTRUCTION,
    )
    audit_assistant = _agent(
        "AuditAssistantAgent",
        "Answers scoped auditor questions from current report context.",
        ASSISTANT_INSTRUCTION,
    )

    return LlmAgent(
        name="FaultAuditCoordinatorAgent",
        description="Root coordinator for the FaultAuditAI Google ADK multi-agent team.",
        model=settings.gemini_model,
        instruction=COORDINATOR_INSTRUCTION,
        sub_agents=[
            mission_planning,
            transaction_screening,
            spend_analysis,
            risk_triage,
            human_approval,
            audit_trail,
            report_generation,
            audit_assistant,
        ],
        tools=[
            FunctionTool(run_vector_search_evidence),
            FunctionTool(run_spend_aggregation),
            FunctionTool(detect_duplicate_invoices),
            FunctionTool(detect_policy_violations),
            FunctionTool(detect_off_hours_payments),
            FunctionTool(detect_ghost_vendor_payments),
            FunctionTool(run_detectors),
            LongRunningFunctionTool(func=mark_flagged),
        ],
    )


def build_agent() -> LlmAgent:
    """Backward-compatible alias for ADK tooling that imports build_agent."""
    return build_agent_team()


def iter_agent_team(agent: LlmAgent | None = None) -> list[LlmAgent]:
    """Return the coordinator and all LlmAgent descendants for tests/introspection."""
    root = agent or root_agent
    agents: list[LlmAgent] = []

    def walk(node: Any) -> None:
        if isinstance(node, LlmAgent):
            agents.append(node)
        for child in getattr(node, "sub_agents", []) or []:
            walk(child)

    walk(root)
    return agents


# ADK convention: a module-level `root_agent` is what `adk run` / Agent Engine deploy picks up.
root_agent = build_agent_team()
