"""Runtime reads through the **MongoDB MCP server** (the partner integration).

The live agent runs its MongoDB reads via the official `mongodb-mcp-server` over MCP
(stdio) — this is the "Partner Power via MCP" path. Results come back wrapped in the
server's `<untrusted-user-data>` security envelope; we extract the JSON array.

Every call is best-effort: on any failure the caller falls back to the direct driver,
so the agent never breaks if the MCP subprocess hiccups.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re

from faultaudit.config import get_settings

log = logging.getLogger(__name__)

# The server's own warning prose mentions the tag strings inline, so match only the
# block whose payload actually starts with a JSON array/object right after the tag.
_ENVELOPE = re.compile(
    r"<untrusted-user-data-[0-9a-f-]+>\s*(\[.*\]|\{.*\})\s*</untrusted-user-data-[0-9a-f-]+>",
    re.S,
)


async def mcp_aggregate(database: str, collection: str, pipeline: list[dict], timeout: float = 30.0) -> list[dict]:
    """Run an aggregation (incl. `$vectorSearch`) via the MongoDB MCP server.

    Returns the parsed documents, or [] on any failure (caller should fall back).
    """
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    s = get_settings()
    params = StdioServerParameters(
        command=s.mcp_command,
        args=s.mcp_args.split(","),
        env={**os.environ, "MDB_MCP_CONNECTION_STRING": s.atlas_uri},
    )
    result: list[dict] = []
    captured = False
    try:
        # NOTE: do NOT wrap mcp calls in asyncio.wait_for — it cancels the library's
        # anyio task groups and raises an ExceptionGroup before the result is captured.
        async with stdio_client(params) as (r, w):
            async with ClientSession(r, w) as sess:
                await sess.initialize()
                res = await sess.call_tool(
                    "aggregate",
                    {"database": database, "collection": collection, "pipeline": pipeline},
                )
                text = "\n".join((getattr(c, "text", "") or "") for c in res.content)
                m = _ENVELOPE.search(text)
                result = json.loads(m.group(1)) if m else []
                captured = True
    except Exception as exc:  # noqa: BLE001 — incl. the stdio teardown ExceptionGroup
        if not captured:
            log.warning("MCP aggregate failed (%s); caller falls back", type(exc).__name__)
    return result
