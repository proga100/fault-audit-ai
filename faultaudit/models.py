"""Shared data contracts for FaultAuditAI.

This module is the single source of truth. Every build slice (tools, agent, server,
frontend, data loader) codes against these types. Do not fork or redefine them in a
slice — import from here. Changes here are coordinated by the orchestrator.

Field names on Invoice/Vendor/Policy intentionally match the JSON emitted by
demo_dataset/generate_data.py so loading is a straight parse.
"""

from __future__ import annotations

from datetime import datetime, date, timezone
from enum import Enum
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# --------------------------------------------------------------------------- #
# Domain records (mirror generate_data.py output)
# --------------------------------------------------------------------------- #
class Vendor(BaseModel):
    vendor_id: str
    vendor_name: str
    country: str
    category: str
    onboarded: date
    is_ghost: bool = False
    risk_score: float = 0.0


class Policy(BaseModel):
    rule_id: str
    category: str  # "*" means applies to all categories
    max_amount: float
    text: str


class Invoice(BaseModel):
    invoice_id: str
    vendor_id: str
    vendor_name: str
    department: str
    category: str
    amount: float
    currency: str = "USD"
    payment_method: str
    invoice_date: date
    payment_hour: int
    approved_by: str
    notes: str
    # injected-fraud ground-truth flags (used for eval + demo narration)
    is_duplicate: bool = False
    is_near_duplicate: bool = False
    is_policy_violation: bool = False
    is_off_hours: bool = False
    is_ghost_vendor: bool = False
    is_fraud_exemplar: bool = False
    fraud_label: int = 0
    # retrieval
    embedding_text: str = ""
    embedding: Optional[list[float]] = None  # 768-dim gemini-embedding-001, set at load


# --------------------------------------------------------------------------- #
# Audit findings
# --------------------------------------------------------------------------- #
class FlaggedReason(str, Enum):
    DUPLICATE = "duplicate"
    NEAR_DUPLICATE = "near_duplicate"
    GHOST_VENDOR = "ghost_vendor"
    POLICY_VIOLATION = "policy_violation"
    OFF_HOURS = "off_hours"
    OFAC_HIT = "ofac_hit"
    VECTOR_SIMILAR = "vector_similar"  # semantically close to a known fraud exemplar


class FlaggedItem(BaseModel):
    """One suspicious invoice the agent proposes flagging. Shown in Gate 2."""

    invoice_id: str
    vendor_name: str
    department: str
    amount: float
    reasons: list[FlaggedReason] = Field(default_factory=list)
    similarity: Optional[float] = None  # vector score if VECTOR_SIMILAR
    detail: str = ""  # human-readable one-liner for the UI row


# --------------------------------------------------------------------------- #
# Human-in-the-loop approval
# --------------------------------------------------------------------------- #
class ApprovalGate(str, Enum):
    PLAN = "plan"      # Gate 1: approve/edit the plan before any tool runs
    ACTION = "action"  # Gate 2: per-item approve before the write


class ApprovalDecision(BaseModel):
    """Posted by the UI to resume a paused run."""

    gate: ApprovalGate
    approved: bool = True               # PLAN gate: approve/reject the whole plan
    edited_plan: Optional[str] = None   # PLAN gate: user-edited plan text
    approved_ids: list[str] = Field(default_factory=list)   # ACTION gate
    rejected_ids: list[str] = Field(default_factory=list)   # ACTION gate


# --------------------------------------------------------------------------- #
# Streaming event protocol (agent -> server -> UI over SSE)
# --------------------------------------------------------------------------- #
class EventType(str, Enum):
    PLAN = "plan"                      # agent proposed a plan (triggers Gate 1)
    TOOL_CALL = "tool_call"            # agent invoked a tool
    TOOL_RESULT = "tool_result"       # tool returned (carry similarity scores, counts)
    PROPOSAL = "proposal"             # flagged list assembled (triggers Gate 2)
    AWAITING_APPROVAL = "awaiting_approval"  # run paused, which gate
    WRITTEN = "written"               # mark_flagged committed
    REPORT_READY = "report_ready"     # audit report available
    ERROR = "error"
    DONE = "done"


class AgentEvent(BaseModel):
    """One item in the SSE stream. `data` shape depends on `type`."""

    run_id: str
    type: EventType
    data: dict[str, Any] = Field(default_factory=dict)
    ts: datetime = Field(default_factory=_utcnow)


# --------------------------------------------------------------------------- #
# Final artifact
# --------------------------------------------------------------------------- #
class AuditReport(BaseModel):
    run_id: str
    mission: str
    generated_at: datetime = Field(default_factory=_utcnow)
    flagged_count: int = 0
    total_at_risk: float = 0.0
    items: list[FlaggedItem] = Field(default_factory=list)
    markdown: str = ""


# --------------------------------------------------------------------------- #
# Mission lifecycle
# --------------------------------------------------------------------------- #
class MissionRequest(BaseModel):
    text: str  # plain-English mission, e.g. "Audit this month's vendor payments"


class MissionStarted(BaseModel):
    run_id: str


# --------------------------------------------------------------------------- #
# AI Audit Assistant (the "Ask Audit Agent" drawer)
# --------------------------------------------------------------------------- #
class AskRequest(BaseModel):
    """A question for the AI Audit Assistant, optionally scoped to a run."""

    question: str = Field(min_length=1, max_length=2000)
    run_id: Optional[str] = None


class AskResponse(BaseModel):
    answer: str
    model: str
    ai_generated: bool = True  # the UI must surface this — answers need human review


RunStatus = Literal["planning", "awaiting_plan", "executing", "awaiting_action", "writing", "done", "error"]
