"""Tests for the Google ADK multi-agent team assembly."""

from __future__ import annotations

from pathlib import Path

from faultaudit.agent.agent import build_agent_team, iter_agent_team
from faultaudit.config import get_settings


def test_build_agent_team_has_expected_specialists() -> None:
    root = build_agent_team()
    names = {agent.name for agent in iter_agent_team(root)}
    assert names == {
        "FaultAuditCoordinatorAgent",
        "MissionPlanningAgent",
        "TransactionScreeningAgent",
        "SpendAnalysisAgent",
        "RiskTriageAgent",
        "HumanApprovalAgent",
        "AuditTrailAgent",
        "ReportGenerationAgent",
        "AuditAssistantAgent",
    }


def test_every_adk_agent_uses_configured_gemini_3_model() -> None:
    settings = get_settings()
    assert settings.gemini_model.startswith("gemini-3.")
    root = build_agent_team()
    for agent in iter_agent_team(root):
        assert agent.model == settings.gemini_model


def test_no_gemini_2_model_is_hardcoded() -> None:
    repo = Path(__file__).resolve().parents[3]
    offenders: list[str] = []
    for path in (repo / "faultaudit").rglob("*.py"):
        text = path.read_text()
        if "gemini-2" in text or "gemini_2" in text:
            offenders.append(str(path.relative_to(repo)))
    assert offenders == []
