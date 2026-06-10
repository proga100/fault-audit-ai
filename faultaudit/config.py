"""Runtime configuration + the MOCK/REAL switch.

Everything is built and tested with USE_MOCKS=true (no Atlas, no GCP). When your
credentials exist, set USE_MOCKS=false and supply ATLAS_URI / GCP_PROJECT — no code
changes required.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = REPO_ROOT / "demo_dataset"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # --- mock switch ---
    use_mocks: bool = True  # tests + local dev default; flip to false with real creds

    # --- MongoDB ---
    atlas_uri: str = ""
    db_name: str = "faultaudit"
    txn_collection: str = "transactions"
    vendor_collection: str = "vendors"
    policy_collection: str = "policies"
    config_collection: str = "config"
    audit_collection: str = "audit_log"
    vector_index_name: str = "txn_vector_index"

    # --- Google Cloud / Vertex AI ---
    gcp_project: str = ""
    gcp_region: str = "us-central1"             # embeddings region
    gemini_model: str = "gemini-3.1-pro-preview"  # Gemini 3 family
    gemini_location: str = "global"             # Gemini 3 preview models serve from `global`
    embedding_model: str = "gemini-embedding-001"
    embedding_dims: int = 768

    # --- MongoDB MCP server (read path) ---
    mcp_command: str = "npx"
    mcp_args: str = "-y,mongodb-mcp-server,--readOnly"
    use_mcp_reads: bool = True  # run the live vector search through the MCP server

    # --- OFAC ---
    ofac_sdn_url: str = "https://www.treasury.gov/ofac/downloads/sdn.csv"
    ofac_cache_path: str = str(REPO_ROOT / "sdn.csv")
    ofac_match_threshold: float = 0.85

    # --- near-duplicate detection ---
    neardup_similarity_threshold: float = 0.92


@lru_cache
def get_settings() -> Settings:
    return Settings()
