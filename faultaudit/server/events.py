"""Event-protocol serialization (agent -> SSE -> UI). Backend/API slice owns extensions.

Provided in Phase 0 so the Frontend and Backend slices agree on the wire format.
"""

from __future__ import annotations

import json

from faultaudit.models import AgentEvent


def to_sse(event: AgentEvent) -> str:
    """Render an AgentEvent as a Server-Sent-Events frame: `event:` + `data:` lines."""
    payload = event.model_dump(mode="json")
    return f"event: {event.type.value}\ndata: {json.dumps(payload)}\n\n"


def parse_sse_data(raw: str) -> AgentEvent:
    """Inverse of to_sse for the data payload (used by tests / a JS-equivalent client)."""
    return AgentEvent.model_validate_json(raw)
