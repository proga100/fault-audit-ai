"""ADK-backed live runner.

This runner uses the Google ADK / Agent Builder multi-agent team from
faultaudit.agent.agent, while preserving the existing FastAPI SSE event contract.
The UI sees the same high-level sequence as RealRunner, plus richer attribution
for the actual ADK specialist and evidence source.
"""

from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from typing import Any, AsyncIterator

from google.adk.agents import LlmAgent
from google.adk.runners import InMemoryRunner
from google.genai import types
from pymongo import MongoClient

from faultaudit.agent import llm, roster
from faultaudit.agent.agent import (
    PLANNING_INSTRUCTION,
    REPORT_INSTRUCTION,
    detect_duplicate_invoices,
    detect_ghost_vendor_payments,
    detect_off_hours_payments,
    detect_policy_violations,
    run_spend_aggregation,
    run_vector_search_evidence,
)
from faultaudit.agent.report import render_report
from faultaudit.config import get_settings
from faultaudit.models import (
    AgentEvent,
    ApprovalDecision,
    ApprovalGate,
    EventType,
    FlaggedItem,
    MissionRequest,
)
from faultaudit.tools.triage import assemble_flagged

MAX_FLAGGED = 40
log = logging.getLogger(__name__)


class AdkAgentRunner:
    """Live runner backed by Google ADK multi-agent orchestration."""

    def __init__(self) -> None:
        self._settings = get_settings()
        self._client = MongoClient(self._settings.atlas_uri)
        self._db = self._client[self._settings.db_name]
        self._adk_model_ready = self._can_use_adk_model()
        self._approval_events: dict[str, asyncio.Event] = {}
        self._decisions: dict[str, ApprovalDecision] = {}

    async def run(self, run_id: str, mission: MissionRequest) -> AsyncIterator[AgentEvent]:
        def evt(t: EventType, **data: object) -> AgentEvent:
            return AgentEvent(run_id=run_id, type=t, data=dict(data))

        plan = await self._adk_text_agent_turn(
            "MissionPlanningAgent",
            PLANNING_INSTRUCTION,
            f"Mission: {mission.text}\nReturn the Gate 1 audit plan only.",
            timeout=45,
            fallback=lambda: llm.plan_for(mission.text),
        )
        yield evt(EventType.PLAN, plan=plan, adk_agent_name="MissionPlanningAgent", **roster.MISSION_PLANNING)
        yield evt(
            EventType.AWAITING_APPROVAL,
            gate=ApprovalGate.PLAN.value,
            adk_agent_name="HumanApprovalAgent",
            **roster.HUMAN_GATE,
        )
        await self._wait(run_id)
        if not self._decisions.pop(run_id).approved:
            yield evt(EventType.ERROR, reason="Plan rejected by reviewer", adk_agent_name="HumanApprovalAgent")
            yield evt(EventType.DONE)
            return

        vector_hits: list[dict] = []
        yield evt(
            EventType.TOOL_CALL,
            tool="mongodb.vectorSearch",
            query=mission.text,
            via="MongoDB MCP server",
            adk_agent_name="TransactionScreeningAgent",
            **roster.VECTOR_SEARCH,
        )
        try:
            vector_result = await run_vector_search_evidence(mission.text)
            vector_hits = [
                {"invoice_id": h.get("invoice_id"), "score": h.get("score", 0.0)}
                for h in vector_result.get("hits", [])
            ]
        except Exception as exc:  # noqa: BLE001
            vector_result = {"source": f"unavailable ({type(exc).__name__})", "hits": []}
        yield evt(
            EventType.TOOL_RESULT,
            tool="mongodb.vectorSearch",
            via=vector_result.get("source", "MongoDB MCP"),
            hits=len(vector_result.get("hits", [])),
            sample=vector_result.get("hits", [])[:5],
            adk_agent_name="TransactionScreeningAgent",
            **self._tool_roster(vector_result.get("source"), roster.VECTOR_SEARCH),
        )

        yield evt(
            EventType.TOOL_CALL,
            tool="mongodb.aggregate",
            group_by="department",
            adk_agent_name="SpendAnalysisAgent",
            **roster.SPEND_ANALYSIS,
        )
        try:
            spend_result = await run_spend_aggregation("department")
        except Exception as exc:  # noqa: BLE001
            spend_result = {"source": f"unavailable ({type(exc).__name__})", "groups": []}
        yield evt(
            EventType.TOOL_RESULT,
            tool="mongodb.aggregate",
            by_department=spend_result.get("groups", []),
            via=spend_result.get("source", "MongoDB MCP"),
            adk_agent_name="SpendAnalysisAgent",
            **self._tool_roster(spend_result.get("source"), roster.SPEND_ANALYSIS),
        )

        detector_results: list[tuple[str, dict]] = []
        for tool_name, call in [
            ("detectors.duplicates", detect_duplicate_invoices),
            ("detectors.policy", detect_policy_violations),
            ("detectors.off_hours", detect_off_hours_payments),
            ("detectors.ghost_vendors", detect_ghost_vendor_payments),
        ]:
            yield evt(
                EventType.TOOL_CALL,
                tool=tool_name,
                adk_agent_name="RiskTriageAgent",
                **roster.RISK_TRIAGE,
            )
            try:
                result = await call()
            except Exception as exc:  # noqa: BLE001
                result = {"source": f"unavailable ({type(exc).__name__})"}
            detector_results.append((tool_name, result))
            yield evt(
                EventType.TOOL_RESULT,
                tool=tool_name,
                via=result.get("source", "internal detector fallback"),
                count=self._result_count(result),
                adk_agent_name="RiskTriageAgent",
                **self._tool_roster(result.get("source"), roster.RISK_TRIAGE),
            )

        all_items = await asyncio.to_thread(assemble_flagged, self._db, vector_hits)
        items = all_items[:MAX_FLAGGED]
        dept_counts: dict[str, int] = defaultdict(int)
        vendor_counts: dict[str, int] = defaultdict(int)
        for item in all_items:
            dept_counts[item.department] += 1
            vendor_counts[item.vendor_name] += 1

        yield evt(
            EventType.PROPOSAL,
            items=[i.model_dump(mode="json") for i in items],
            total_flagged=len(all_items),
            shown=len(items),
            total_at_risk=sum(i.amount for i in all_items),
            dept_counts=dict(dept_counts),
            vendor_counts=dict(vendor_counts),
            detector_sources=[{"tool": name, "source": result.get("source")} for name, result in detector_results],
            adk_agent_name="RiskTriageAgent",
            **roster.RISK_TRIAGE,
        )
        yield evt(
            EventType.AWAITING_APPROVAL,
            gate=ApprovalGate.ACTION.value,
            adk_agent_name="HumanApprovalAgent",
            **roster.HUMAN_GATE,
        )
        await self._wait(run_id)
        decision = self._decisions.pop(run_id)

        proposed = {i.invoice_id for i in items}
        if decision.approved_ids:
            keep = set(decision.approved_ids) & proposed
        elif decision.rejected_ids:
            keep = proposed - set(decision.rejected_ids)
        elif decision.approved:
            keep = proposed
        else:
            keep = set()
        approved = [i for i in items if i.invoice_id in keep]

        from faultaudit.tools.flagging import mark_flagged

        await asyncio.to_thread(mark_flagged, self._db, run_id, [i.invoice_id for i in approved], approved)
        yield evt(EventType.WRITTEN, flagged=len(approved), adk_agent_name="AuditTrailAgent", **roster.AUDIT_TRAIL)

        report = render_report(run_id, mission.text, approved)
        reasons = [r.value for item in approved for r in item.reasons]
        narrative = await self._adk_text_agent_turn(
            "ReportGenerationAgent",
            REPORT_INSTRUCTION,
            "Gate 2 approved and write completed. ReportGenerationAgent: write a short "
            f"closing narrative for mission '{mission.text}' with {report.flagged_count} "
            f"approved findings and ${report.total_at_risk:,.0f} at risk.",
            timeout=45,
            fallback=lambda: llm.summarize(mission.text, report.flagged_count, report.total_at_risk, reasons),
        )
        report.markdown = f"# Audit Report\n\n{narrative}\n\n" + report.markdown
        yield evt(
            EventType.REPORT_READY,
            run_id=run_id,
            flagged_count=report.flagged_count,
            total_at_risk=report.total_at_risk,
            report=report.model_dump(mode="json"),
            adk_agent_name="ReportGenerationAgent",
            **roster.REPORT_GENERATION,
        )
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

    async def _adk_text_agent_turn(
        self,
        agent_name: str,
        instruction: str,
        prompt: str,
        *,
        timeout: float,
        fallback,
    ) -> str:
        if not self._adk_model_ready:
            return await asyncio.to_thread(fallback)

        async def collect() -> str:
            app_name = f"faultauditai_{agent_name.lower()}"
            session_id = f"{agent_name.lower()}_{id(prompt)}"
            user_id = "auditor"
            agent = LlmAgent(
                name=agent_name,
                model=self._settings.gemini_model,
                instruction=instruction,
            )
            runner = InMemoryRunner(agent, app_name=app_name)
            await runner.session_service.create_session(
                app_name=app_name,
                user_id=user_id,
                session_id=session_id,
            )
            chunks: list[str] = []
            message = types.Content(role="user", parts=[types.Part(text=prompt)])
            async for event in runner.run_async(
                user_id=user_id,
                session_id=session_id,
                new_message=message,
            ):
                content = getattr(event, "content", None)
                for part in getattr(content, "parts", []) or []:
                    text = getattr(part, "text", None)
                    if text:
                        chunks.append(text)
            return "\n".join(chunks).strip()

        try:
            text = await asyncio.wait_for(collect(), timeout=timeout)
        except Exception as exc:  # noqa: BLE001
            log.warning("ADK turn failed (%s); using deterministic fallback", type(exc).__name__)
            text = ""
        return text or await asyncio.to_thread(fallback)

    def _can_use_adk_model(self) -> bool:
        if not self._settings.gcp_project:
            return False
        try:
            import google.auth

            google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
            return True
        except Exception as exc:  # noqa: BLE001
            log.warning("Google credentials unavailable for ADK model turns (%s); using fallbacks", type(exc).__name__)
            return False

    @staticmethod
    def _result_count(result: dict) -> int:
        for key in ("hits", "groups", "duplicates", "violations", "items"):
            value = result.get(key)
            if isinstance(value, list):
                return len(value)
        return 0

    @staticmethod
    def _tool_roster(source: object, default: dict) -> dict:
        source_text = str(source or "")
        if "MongoDB MCP" in source_text:
            return default
        if "direct driver" in source_text:
            return {**default, "tool_label": "MongoDB direct driver fallback"}
        return {**default, "tool_label": "Internal detector fallback"}
