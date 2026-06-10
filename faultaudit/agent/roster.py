"""Agent roster — attribution for each stage of the audit pipeline.

Every AgentEvent carries this attribution so the UI can show *which agent* did
*what* with *which tool*. Both runners (FakeRunner and RealRunner) import from
here so the scripted demo and the live run tell the same story.

Labels are honest about the implementation: vector search and aggregation run
through the official MongoDB MCP server; the policy / duplicate / ghost-vendor /
off-hours detectors are internal tools operating on data read from Atlas; OFAC is
a live US Treasury feed; plan + narrative come from Gemini 3 on Vertex AI.
"""

from __future__ import annotations

MISSION_PLANNING = {"agent": "Mission Planning Agent", "tool_label": "Gemini 3 · Vertex AI"}
VECTOR_SEARCH = {"agent": "Transaction Screening Agent", "tool_label": "MongoDB MCP · $vectorSearch"}
SPEND_ANALYSIS = {"agent": "Spend Analysis Agent", "tool_label": "MongoDB MCP · aggregate"}
RISK_TRIAGE = {"agent": "Risk Triage Agent", "tool_label": "Policy · Duplicate · Ghost · OFAC detectors"}
HUMAN_GATE = {"agent": "Human Approval Gate", "tool_label": "Auditor decision required"}
AUDIT_TRAIL = {"agent": "Audit Trail Agent", "tool_label": "MongoDB Atlas · gated write"}
REPORT_GENERATION = {"agent": "Report Generation Agent", "tool_label": "Gemini 3 · Vertex AI"}
AUDIT_ASSISTANT = {"agent": "AI Audit Assistant", "tool_label": "Gemini 3 · Vertex AI"}
