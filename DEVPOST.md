# FaultAuditAI — Devpost submission text

> Paste into the Devpost "About the project" field. Track: **MongoDB**.

---

## Inspiration

Every month, finance and audit teams manually comb through hundreds of vendor payments hunting for duplicate invoices, ghost vendors, policy breaches, off-hours payments, and sanctioned payees. It's slow, error-prone, and high-stakes — exactly the kind of work an agent should do, *as long as a human approves every consequential call*. FaultAuditAI was built to prove that an agent can run a real multi-step audit mission while keeping the human structurally — not just politely — in control.

## What it does (features and functionality)

FaultAuditAI is a corporate-finance audit agent. You give it a plain-English mission ("Audit this month's vendor payments") and it:

1. **Plans** — Gemini drafts an audit plan → **Gate 1: you approve, edit, or reject the plan.**
2. **Investigates** — runs MongoDB Atlas `$vectorSearch` to find transactions semantically similar to known fraud exemplars, runs aggregation pipelines for departmental spend, applies policy/duplicate/ghost-vendor/off-hours detectors, and screens every payee against the live US Treasury OFAC sanctions list.
3. **Proposes** — presents a flagged list with evidence → **Gate 2: you approve or reject each item individually.**
4. **Acts** — only after approval does it write flags and an audit log to Atlas and generate the audit report.

The approval gates are **structural, not prompt-based**: the write tool is an ADK `LongRunningFunctionTool` that pauses the run until a human decision arrives. The agent cannot write anything without you. A live web console streams every tool call, plan, and decision in real time, alongside a flagged-spend dashboard and an "Ask the Audit Agent" chat.

## How we built it (technologies used)

- **Agent**: Google Vertex AI Agent Builder (ADK) `LlmAgent` reasoning with **Gemini**, deployable to Agent Engine.
- **Partner integration (MongoDB track)**: all agent reads run through the official **MongoDB MCP server** (read-only); **MongoDB Atlas Vector Search** + aggregation pipelines are the agent's core investigative capability. Atlas stores transactions, vendors, policies *and* their 768-dimension `gemini-embedding-001` vectors — no separate vector database.
- **Tools**: MCP reads · OFAC sanctions screening (live SDN list) · policy / dedup / vector-similarity detectors · one gated write (`mark_flagged`).
- **Backend**: FastAPI bridge streaming agent events to the UI over Server-Sent Events, relaying the two approval gates.
- **Frontend**: vanilla-JS two-pane console — live mission timeline + approval cards on the left, flagged-spend dashboard on the right.
- **Quality**: 146 tests covering the policy engine, exact + vector duplicate detection, OFAC matching, the gate state machine, the gated write, the API routes, and an end-to-end audit. Docker one-liner runs the full UX in mock mode with zero credentials.

## Data sources

- **Synthetic corporate ledger** — no public dataset is simultaneously corporate-grade, fraud-labeled, and commercially licensed, so we generate our own with [Faker](https://faker.readthedocs.io/) (`demo_dataset/generate_data.py`): 1,500+ invoices across 60 vendors with policies and budgets, plus *injected* fraud — exact duplicates, reworded near-duplicates, ghost vendors, policy violations, and off-hours payments. Fully open-source (GPL-3.0) and reproducible from a fixed seed; loaded into MongoDB Atlas with `gemini-embedding-001` embeddings.
- **US Treasury OFAC Specially Designated Nationals (SDN) list** — fetched live from the official Treasury source for sanctions screening of every payee.

## Findings and learnings

- **Vector search catches what GROUP BY can't.** Exact-match dedup misses invoices that were reworded or slightly re-amounted. Seeding labeled fraud exemplars and using Atlas `$vectorSearch` over `gemini-embedding-001` embeddings surfaced near-duplicates that plain aggregation never flags — semantic similarity turned out to be the single most valuable detector.
- **Human control must be structural.** Early prompt-based "always ask before writing" guardrails were unreliable. Moving the gate into an ADK `LongRunningFunctionTool` — where the run *physically pauses* until a decision arrives — made approval enforcement deterministic instead of probabilistic.
- **Separating reads from writes via MCP is a clean safety boundary.** Routing all reads through the read-only MongoDB MCP server and funneling the single write through the gated tool gives an auditable, least-privilege architecture by construction.
- **Streaming transparency builds trust.** Showing every tool call live over SSE — rather than a spinner followed by a verdict — is what makes a human comfortable approving an agent's findings.

## What's next

Connect to real ERP/AP exports, add scheduled recurring missions, and ship reviewer roles so audit teams can split approval duty.

---

**Live demo:** https://faultauditai.flance.info/ · **Code:** https://github.com/proga100/fault-audit-ai (GPL-3.0)
