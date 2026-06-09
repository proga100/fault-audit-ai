"""FaultAuditAI — embed & load entrypoint.

Reads demo_dataset/*.json, embeds each invoice with gemini-embedding-001 via
Vertex AI, then upserts everything into Atlas MongoDB.

Real network/client code is guarded behind ``if __name__ == "__main__":`` so
that importing this module in tests never hits the network.

Usage:
    python embed_and_load.py

Environment / .env:
    GCP_PROJECT   - GCP project ID (required)
    GCP_REGION    - defaults to us-central1
    ATLAS_URI     - MongoDB Atlas connection string (required)
    DB_NAME       - defaults to faultaudit
"""

from __future__ import annotations

# --------------------------------------------------------------------------- #
# Pure helpers (safe to import anywhere — no network, no side effects)
# --------------------------------------------------------------------------- #
from faultaudit.config import DATA_DIR, get_settings
from faultaudit.data.load import build_documents, load_json_dir, upsert_collections


def make_vertex_embedder(client, model: str, dims: int):
    """Return a callable that embeds one text string using Vertex AI Gemini.

    One request per call — gemini-embedding-001 is safest used one-at-a-time.
    """
    from google.genai.types import EmbedContentConfig  # type: ignore[import-untyped]

    def _embed(text: str) -> list[float]:
        response = client.models.embed_content(
            model=model,
            contents=text,
            config=EmbedContentConfig(
                task_type="RETRIEVAL_DOCUMENT",
                output_dimensionality=dims,
            ),
        )
        # response.embeddings is a list[ContentEmbedding]; we sent one text so [0]
        return response.embeddings[0].values  # type: ignore[index]

    return _embed


# --------------------------------------------------------------------------- #
# Main entrypoint (real network, real Atlas — only runs when invoked directly)
# --------------------------------------------------------------------------- #

if __name__ == "__main__":
    import time

    from google import genai  # type: ignore[import-untyped]
    from pymongo import MongoClient

    settings = get_settings()

    print("FaultAuditAI — embed & load pipeline")
    print(f"  data dir    : {DATA_DIR}")
    print(f"  embedding   : {settings.embedding_model} ({settings.embedding_dims} dims)")
    print(f"  db          : {settings.db_name}")

    # --- 1. Load JSON --------------------------------------------------------
    print("\n[1/4] Loading JSON files …", flush=True)
    data = load_json_dir(DATA_DIR)
    invoices_raw = data["invoices"]
    vendors = data["vendors"]
    policies = data["policies"]
    budgets = data["budgets"]
    print(f"      invoices={len(invoices_raw)}  vendors={len(vendors)}  "
          f"policies={len(policies)}  budgets={len(budgets)}")

    # --- 2. Build real Vertex AI embedder ------------------------------------
    print("\n[2/4] Initialising Vertex AI Gemini embedder …", flush=True)
    vertex_client = genai.Client(
        vertexai=True,
        project=settings.gcp_project,
        location=settings.gcp_region,
    )
    embedder = make_vertex_embedder(
        client=vertex_client,
        model=settings.embedding_model,
        dims=settings.embedding_dims,
    )
    print(f"      model={settings.embedding_model}, dims={settings.embedding_dims}")

    # --- 3. Embed invoices ---------------------------------------------------
    print(f"\n[3/4] Embedding {len(invoices_raw)} invoices (one request each) …",
          flush=True)
    t0 = time.time()
    invoices_embedded = build_documents(invoices_raw, embedder)
    elapsed = time.time() - t0
    print(f"      done in {elapsed:.1f}s  ({elapsed / len(invoices_raw):.2f}s/invoice)")

    # --- 4. Upsert into Atlas ------------------------------------------------
    print("\n[4/4] Upserting into Atlas …", flush=True)
    mongo_client: MongoClient = MongoClient(settings.atlas_uri)
    db = mongo_client[settings.db_name]
    summary = upsert_collections(db, invoices_embedded, vendors, policies, budgets)

    print("\n  Summary:")
    for coll, count in summary.items():
        print(f"    {coll:<20} {count:>6} documents upserted/matched")

    mongo_client.close()
    print("\nDone.")
