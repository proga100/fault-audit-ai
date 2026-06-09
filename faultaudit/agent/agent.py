"""FaultAuditAI agent — built on Vertex AI Agent Builder (Google ADK).

THIS is the file that "uses Vertex AI Agent Builder":
  * google.adk  == the Agent Builder SDK (code-first path of Vertex AI Agent Builder)
  * LlmAgent    == an Agent Builder agent, reasoning with Gemini 3 on Vertex AI
  * McpToolset  == the partner MCP integration (official MongoDB MCP server, read-only)
  * LongRunningFunctionTool == the human-in-the-loop approval gate primitive

Deploys to Vertex AI Agent Engine (Agent Builder's managed runtime).
Set GOOGLE_GENAI_USE_VERTEXAI=TRUE so the model runs on Vertex AI, not the public API.
"""

from __future__ import annotations

import os

from google.adk.agents import LlmAgent
from google.adk.tools import FunctionTool, LongRunningFunctionTool
from google.adk.tools.mcp_tool.mcp_toolset import (
    McpToolset,
    StdioConnectionParams,
    StdioServerParameters,
)

from faultaudit.config import get_settings

settings = get_settings()

SYSTEM_INSTRUCTION = """\
You are FaultAuditAI, a corporate-finance audit agent. Given a plain-English mission,
you PLAN the audit, then use your tools to find suspicious vendor payments
(duplicates, near-duplicates, ghost vendors, policy breaches, off-hours payments,
sanctioned payees). You NEVER write or flag anything without explicit human approval.

Workflow you must follow:
1. Propose a short numbered PLAN and wait for approval (Gate 1).
2. Use MongoDB (vector search + aggregation via the mongodb tools) and the policy /
   sanctions tools to gather evidence. Cite real numbers.
3. Assemble a flagged list and PROPOSE it. Call mark_flagged only after the human
   approves specific items (Gate 2).
Be concise. Show your reasoning as you call tools.
"""


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
    raise NotImplementedError("Agent-Core slice: wire to tools.policy + Mongo lookup")


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
def build_agent() -> LlmAgent:
    os.environ.setdefault("GOOGLE_GENAI_USE_VERTEXAI", "TRUE")
    os.environ.setdefault("GOOGLE_CLOUD_PROJECT", settings.gcp_project)
    os.environ.setdefault("GOOGLE_CLOUD_LOCATION", settings.gcp_region)

    tools = [
        FunctionTool(screen_vendor_sanctions),
        FunctionTool(check_policy),
        LongRunningFunctionTool(func=mark_flagged),  # the approval gate
    ]
    if settings.atlas_uri:  # only wire MCP when a connection string exists
        tools.insert(0, build_mongodb_mcp())

    return LlmAgent(
        name="faultaudit",
        model=settings.gemini_model,  # gemini-3-pro on Vertex AI
        instruction=SYSTEM_INSTRUCTION,
        tools=tools,
    )


# ADK convention: a module-level `root_agent` is what `adk run` / Agent Engine deploy picks up.
root_agent = build_agent()
