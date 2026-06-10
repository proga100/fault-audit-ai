"""Headless live-mission driver — proves the real agent path end-to-end.

Runs RealRunner against live Atlas + Gemini, auto-approving both gates, and prints
the event stream. Requires .env (USE_MOCKS=false, ATLAS_URI, GCP_PROJECT) and
GOOGLE_APPLICATION_CREDENTIALS. Usage:  python live_mission.py "your mission"
"""

from __future__ import annotations

import asyncio
import os
import sys

os.environ.setdefault("GOOGLE_APPLICATION_CREDENTIALS", "./gcp-key.json")

from faultaudit.models import ApprovalDecision, ApprovalGate, EventType, MissionRequest
from faultaudit.server.real_runner import RealRunner


async def main(mission_text: str) -> None:
    runner = RealRunner()
    run_id = "live-1"
    mission = MissionRequest(text=mission_text)
    q: asyncio.Queue = asyncio.Queue()

    async def consume():
        async for ev in runner.run(run_id, mission):
            await q.put(ev)
        await q.put(None)

    async def react():
        while True:
            ev = await q.get()
            if ev is None:
                break
            d = ev.data
            t = ev.type
            if t == EventType.PLAN:
                print("\n[PLAN]\n" + d.get("plan", "")[:600] + "\n")
            elif t == EventType.TOOL_CALL:
                print(f"[TOOL_CALL] {d.get('tool')}  {d.get('query') or d.get('group_by') or ''}")
            elif t == EventType.TOOL_RESULT:
                print(f"[TOOL_RESULT] {d.get('tool')}  hits={d.get('hits')} top_score={d.get('top_score')}")
                for s in (d.get("sample") or [])[:4]:
                    print(f"      ~ {s.get('vendor_name')} (score {s.get('score')})  {s.get('invoice_id')}")
                for row in (d.get("by_department") or [])[:3]:
                    print(f"      $ {row.get('_id')}: {row.get('total'):,.0f} ({row.get('count')} invoices)")
            elif t == EventType.PROPOSAL:
                items = d.get("items", [])
                print(f"\n[PROPOSAL] {len(items)} flagged items:")
                for it in items[:8]:
                    print(f"      {it['invoice_id'][:8]}  {it['vendor_name'][:22]:22}  ${it['amount']:>10,.0f}  {it['reasons']}")
            elif t == EventType.AWAITING_APPROVAL:
                gate = d.get("gate")
                print(f"[AWAITING_APPROVAL gate={gate}] -> auto-approving")
                await asyncio.sleep(0.3)
                if gate == "plan":
                    await runner.deliver_decision(run_id, ApprovalDecision(gate=ApprovalGate.PLAN, approved=True))
                else:
                    await runner.deliver_decision(run_id, ApprovalDecision(gate=ApprovalGate.ACTION, approved_ids=[]))
            elif t == EventType.WRITTEN:
                print(f"[WRITTEN] flagged={d.get('flagged')} (written to Atlas)")
            elif t == EventType.REPORT_READY:
                print(f"\n[REPORT_READY] {d.get('flagged_count')} flagged, ${d.get('total_at_risk'):,.0f} at risk")
                print("--- report ---\n" + d["report"]["markdown"][:700])
            elif t == EventType.ERROR:
                print("[ERROR]", d)
            elif t == EventType.DONE:
                print("\n[DONE]")

    await asyncio.gather(consume(), react())


if __name__ == "__main__":
    text = sys.argv[1] if len(sys.argv) > 1 else "Audit this month's vendor payments for fraud and policy violations"
    asyncio.run(main(text))
