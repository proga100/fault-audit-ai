# FaultAuditAI

**An AI corporate-finance audit agent that hunts payment fraud — and keeps a human in control of every decision.**

Built for the **Google Cloud Rapid Agent Hackathon** (MongoDB track). Powered by **Google Vertex AI Agent Builder (ADK) + Gemini**, with **MongoDB Atlas Vector Search** as its superpower via the **MongoDB MCP server**.

---

## The problem it solves

Every month, finance and audit teams manually comb through hundreds of vendor payments looking for duplicate invoices, ghost vendors, policy breaches, off-hours payments, and sanctioned payees. It's slow, error-prone, and exactly the kind of repetitive, high-stakes work an agent should do — *with the human approving the consequential calls.*

FaultAuditAI takes a plain-English mission ("Audit this month's vendor payments"), **plans** the audit, **uses tools** to gather evidence, **proposes** a flagged list, and only **writes anything after you approve it.**

## How it works — a multi-step mission with two human gates

```
Mission (plain English)
   │
   ▼
1. Gemini drafts a PLAN ───────────────▶  GATE 1: you Approve / Edit / Reject
   │
   ▼
2. MongoDB Atlas $vectorSearch  (transactions semantically similar to fraud)
3. MongoDB aggregation          (spend by department)
4. Policy / duplicate / ghost-vendor / off-hours detectors
5. OFAC sanctions screening     (live US Treasury SDN list)
   │
   ▼
6. Proposed flagged list ──────────────▶  GATE 2: you Approve / Reject each item
   │
   ▼
7. Write flags + audit log to Atlas, generate an audit report
```

The approval gates are **structural**, not prompt-based: the write tool is an ADK
`LongRunningFunctionTool` that pauses the run until a human decision arrives.

## How it maps to the challenge

| Challenge goal | How FaultAuditAI meets it |
|---|---|
| **Move beyond chat** | Manages a live MongoDB database, calls a live web service (OFAC), and produces an artifact (audit report + audit log). |
| **Multi-step mission** | One mission → plan → vector search → aggregate → policy/sanctions checks → propose → write → report. |
| **Keep you in control** | Two human gates: approve the *plan*, then approve each *flagged item*, before any write. |
| **Partner power (MCP)** | Reads run through the official **MongoDB MCP server**; Atlas Vector Search + aggregation are the agent's core capability. |
| **Built on Agent Builder** | The agent is a Vertex AI Agent Builder **ADK `LlmAgent`** on Gemini, deployable to **Agent Engine**. |

## Architecture

- **Agent** — Google ADK (`google.adk`) `LlmAgent` reasoning with Gemini on Vertex AI.
- **Tools** — MongoDB MCP server (reads, read-only) · OFAC sanctions screen · policy / dedup / vector-similarity detectors · a gated `mark_flagged` write.
- **Data** — MongoDB Atlas stores transactions, vendors, policies **and** their 768-dim `gemini-embedding-001` vectors (no separate vector DB).
- **Backend** — FastAPI bridge streaming agent events to the UI over SSE, relaying the two approval gates.
- **Frontend** — a two-pane web console: live mission timeline + approval cards on the left, a flagged-spend dashboard on the right.

## Tech stack

Google Vertex AI Agent Builder (ADK) · Gemini · `gemini-embedding-001` · MongoDB Atlas Vector Search · MongoDB MCP server · FastAPI · Python 3.12 · vanilla JS frontend.

## Quickstart

### Run with Docker (mock mode — no credentials needed)

```bash
docker build -t faultaudit .
docker run -p 8080:8080 faultaudit
# open http://localhost:8080
```

Mock mode runs the full UX — plan gate, streaming tool calls, per-item approval, report — on a scripted runner, so you can see the whole experience instantly.

### Run locally (mock mode)

```bash
python -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/uvicorn faultaudit.server.app:app --reload --port 8080
```

### Run live (real Gemini + real Atlas vector search)

1. Create a MongoDB Atlas free cluster and a Google Cloud project with the Vertex AI API enabled.
2. Copy `.env.example` to `.env` and fill in `ATLAS_URI`, `GCP_PROJECT`, set `USE_MOCKS=false`.
3. Provide Google credentials (a service-account key with the *Vertex AI User* role, or `gcloud auth application-default login`).
4. Load data and build the vector index:
   ```bash
   python demo_dataset/generate_data.py      # synthetic, Apache-2.0 corporate ledger
   python embed_and_load.py                  # embed + load to Atlas
   python create_vector_index.py             # create the Atlas Vector Search index
   ```
5. Start the app and open it — missions now run on real Gemini + real `$vectorSearch`.

#### Live mode in Docker

```bash
docker run -p 8080:8080 \
  -e USE_MOCKS=false \
  -e ATLAS_URI="mongodb+srv://..." \
  -e GCP_PROJECT="your-project" \
  -e GOOGLE_APPLICATION_CREDENTIALS=/run/key.json \
  -v /path/to/gcp-key.json:/run/key.json:ro \
  faultaudit
```

## Data & licensing

No public dataset is simultaneously corporate-grade, fraud-labeled, and commercially licensed, so FaultAuditAI ships a **synthetic** corporate ledger generated with [Faker](https://faker.readthedocs.io/) ([`demo_dataset/generate_data.py`](demo_dataset/generate_data.py)) — vendors, invoices, policies, and injected fraud (duplicates, near-duplicates, ghost vendors, policy violations, off-hours payments). Fully Apache-2.0, fully reproducible.

## Tests

```bash
.venv/bin/pip install -r requirements.txt
.venv/bin/python -m pytest          # 146 tests, all on mocks (no creds needed)
```

The suite covers the policy engine, exact + vector duplicate detection, OFAC matching, the gate state machine, the gated write, the FastAPI routes, the data loader, and an end-to-end audit on an in-memory MongoDB.

## Project structure

```
faultaudit/
  agent/      ADK agent, gate state machine, audit pipeline, report, Gemini calls
  tools/      policy · dedup · ofac · mongo reads · gated write
  server/     FastAPI app, SSE events, real + fake runners
  web/        two-pane UI + standalone mock server
demo_dataset/ synthetic data generator
embed_and_load.py · create_vector_index.py · vector_index.json
```

## License

[Apache-2.0](LICENSE) © 2026 Rustamjon Akhmedov.
