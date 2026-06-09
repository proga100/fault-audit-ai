"""Unit tests for faultaudit.data.load.

No real network calls — mongomock + a deterministic fake embedder only.
"""

from __future__ import annotations

import hashlib
import json
import tempfile
from pathlib import Path

import mongomock
import pytest

from faultaudit.config import get_settings
from faultaudit.data.load import build_documents, load_json_dir, upsert_collections
from faultaudit.models import Invoice, Policy, Vendor


# --------------------------------------------------------------------------- #
# Helpers / fixtures
# --------------------------------------------------------------------------- #

EMBEDDING_DIMS = 768


def fake_embed_768(text: str) -> list[float]:
    """Deterministic 768-dim pseudo-embedding (no network)."""
    # repeat the 32-byte SHA-256 digest until we have >= 768 bytes, then slice
    raw = hashlib.sha256(text.encode()).digest()
    repeated = (raw * ((EMBEDDING_DIMS // len(raw)) + 2))[:EMBEDDING_DIMS]
    return [b / 255.0 for b in repeated]


@pytest.fixture
def small_invoice_dict() -> dict:
    """One minimal invoice dict matching the Invoice schema."""
    return {
        "invoice_id": "test-inv-001",
        "vendor_id": "test-vendor-001",
        "vendor_name": "TestCo Ltd",
        "department": "IT",
        "category": "Software",
        "amount": 12345.67,
        "currency": "USD",
        "payment_method": "ACH",
        "invoice_date": "2026-01-15",
        "payment_hour": 10,
        "approved_by": "J. Tester",
        "notes": "Annual licence renewal",
        "is_duplicate": False,
        "is_near_duplicate": False,
        "is_policy_violation": False,
        "is_off_hours": False,
        "is_ghost_vendor": False,
        "is_fraud_exemplar": False,
        "fraud_label": 0,
        "embedding_text": "TestCo Ltd IT Software 12345.67 Annual licence renewal",
        "embedding": None,
    }


@pytest.fixture
def small_vendor_dict() -> dict:
    return {
        "vendor_id": "test-vendor-001",
        "vendor_name": "TestCo Ltd",
        "country": "USA",
        "category": "Software",
        "onboarded": "2022-06-01",
        "is_ghost": False,
        "risk_score": 0.1,
    }


@pytest.fixture
def small_policy_dict() -> dict:
    return {
        "rule_id": "P1",
        "category": "Travel",
        "max_amount": 5000.0,
        "text": "Travel > 5000 requires VP approval.",
    }


@pytest.fixture
def tmp_json_dir(small_invoice_dict, small_vendor_dict, small_policy_dict, tmp_path) -> Path:
    """Write the four JSON files to a temp directory and return the path."""
    (tmp_path / "invoices.json").write_text(json.dumps([small_invoice_dict]))
    (tmp_path / "vendors.json").write_text(json.dumps([small_vendor_dict]))
    (tmp_path / "policies.json").write_text(json.dumps([small_policy_dict]))
    (tmp_path / "budgets.json").write_text(
        json.dumps({"budgets": {"IT": 200000, "HR": 150000}})
    )
    return tmp_path


@pytest.fixture
def mock_db():
    client = mongomock.MongoClient()
    return client["faultaudit_test"]


# --------------------------------------------------------------------------- #
# Tests: load_json_dir
# --------------------------------------------------------------------------- #

class TestLoadJsonDir:
    def test_returns_all_four_keys(self, tmp_json_dir):
        data = load_json_dir(tmp_json_dir)
        assert set(data.keys()) == {"invoices", "vendors", "policies", "budgets"}

    def test_invoice_parses_pydantic_fields(self, tmp_json_dir):
        data = load_json_dir(tmp_json_dir)
        assert len(data["invoices"]) == 1
        inv_dict = data["invoices"][0]
        # Validates against Invoice schema — these fields must be present
        Invoice.model_validate(inv_dict)

    def test_vendor_parses_pydantic_fields(self, tmp_json_dir):
        data = load_json_dir(tmp_json_dir)
        assert len(data["vendors"]) == 1
        Vendor.model_validate(data["vendors"][0])

    def test_policy_parses_pydantic_fields(self, tmp_json_dir):
        data = load_json_dir(tmp_json_dir)
        assert len(data["policies"]) == 1
        Policy.model_validate(data["policies"][0])

    def test_budgets_is_list(self, tmp_json_dir):
        data = load_json_dir(tmp_json_dir)
        assert isinstance(data["budgets"], list)
        assert len(data["budgets"]) >= 1

    def test_missing_file_raises(self, tmp_path):
        # Only write 3 of the 4 files → should raise FileNotFoundError
        (tmp_path / "invoices.json").write_text("[]")
        (tmp_path / "vendors.json").write_text("[]")
        (tmp_path / "policies.json").write_text("[]")
        # budgets.json intentionally missing
        with pytest.raises(FileNotFoundError):
            load_json_dir(tmp_path)


# --------------------------------------------------------------------------- #
# Tests: build_documents (embedder injection — no network)
# --------------------------------------------------------------------------- #

class TestBuildDocuments:
    def test_embedding_attached(self, small_invoice_dict):
        docs = build_documents([small_invoice_dict], fake_embed_768)
        assert "embedding" in docs[0]

    def test_embedding_correct_length(self, small_invoice_dict):
        docs = build_documents([small_invoice_dict], fake_embed_768)
        assert len(docs[0]["embedding"]) == EMBEDDING_DIMS

    def test_embedding_is_float_list(self, small_invoice_dict):
        docs = build_documents([small_invoice_dict], fake_embed_768)
        emb = docs[0]["embedding"]
        assert all(isinstance(v, float) for v in emb)

    def test_deterministic_same_text(self, small_invoice_dict):
        docs1 = build_documents([small_invoice_dict], fake_embed_768)
        docs2 = build_documents([small_invoice_dict], fake_embed_768)
        assert docs1[0]["embedding"] == docs2[0]["embedding"]

    def test_deterministic_different_text(self):
        inv_a = {"embedding_text": "text alpha", "invoice_id": "a"}
        inv_b = {"embedding_text": "text beta", "invoice_id": "b"}
        docs = build_documents([inv_a, inv_b], fake_embed_768)
        assert docs[0]["embedding"] != docs[1]["embedding"]

    def test_original_dict_not_mutated(self, small_invoice_dict):
        original_embedding = small_invoice_dict.get("embedding")
        build_documents([small_invoice_dict], fake_embed_768)
        # original should be unchanged
        assert small_invoice_dict.get("embedding") == original_embedding

    def test_multiple_invoices(self):
        invs = [
            {"embedding_text": f"invoice text {i}", "invoice_id": str(i)}
            for i in range(10)
        ]
        docs = build_documents(invs, fake_embed_768)
        assert len(docs) == 10
        assert all(len(d["embedding"]) == EMBEDDING_DIMS for d in docs)

    def test_empty_embedding_text_handled(self):
        inv = {"embedding_text": "", "invoice_id": "empty"}
        docs = build_documents([inv], fake_embed_768)
        assert len(docs[0]["embedding"]) == EMBEDDING_DIMS


# --------------------------------------------------------------------------- #
# Tests: upsert_collections (idempotency, mongomock)
# --------------------------------------------------------------------------- #

class TestUpsertCollections:
    def _three_invoices(self, embedder=fake_embed_768) -> list[dict]:
        base = [
            {"invoice_id": f"inv-{i}", "vendor_id": "v1", "vendor_name": "TestCo",
             "department": "IT", "category": "Software", "amount": 1000.0 * i,
             "currency": "USD", "payment_method": "ACH",
             "invoice_date": "2026-01-01", "payment_hour": 9,
             "approved_by": "Tester", "notes": f"Invoice {i}",
             "is_duplicate": False, "is_near_duplicate": False,
             "is_policy_violation": False, "is_off_hours": False,
             "is_ghost_vendor": False, "is_fraud_exemplar": False,
             "fraud_label": 0, "embedding_text": f"Invoice {i}", "embedding": None}
            for i in range(1, 4)
        ]
        return build_documents(base, embedder)

    def _vendors(self) -> list[dict]:
        return [
            {"vendor_id": "v1", "vendor_name": "TestCo", "country": "USA",
             "category": "Software", "onboarded": "2022-01-01",
             "is_ghost": False, "risk_score": 0.1},
        ]

    def _policies(self) -> list[dict]:
        return [
            {"rule_id": "P1", "category": "Travel",
             "max_amount": 5000.0, "text": "VP approval required."},
        ]

    def _budgets(self) -> list[dict]:
        return [{"budgets": {"IT": 200000}}]

    def test_first_upsert_inserts_documents(self, mock_db):
        invoices = self._three_invoices()
        upsert_collections(mock_db, invoices, self._vendors(), self._policies(), self._budgets())
        assert mock_db.transactions.count_documents({}) == 3
        assert mock_db.vendors.count_documents({}) == 1
        assert mock_db.policies.count_documents({}) == 1

    def test_upsert_is_idempotent(self, mock_db):
        """Running upsert_collections twice must not duplicate documents."""
        invoices = self._three_invoices()
        vendors = self._vendors()
        policies = self._policies()
        budgets = self._budgets()

        upsert_collections(mock_db, invoices, vendors, policies, budgets)
        upsert_collections(mock_db, invoices, vendors, policies, budgets)

        assert mock_db.transactions.count_documents({}) == 3
        assert mock_db.vendors.count_documents({}) == 1
        assert mock_db.policies.count_documents({}) == 1

    def test_upsert_updates_existing_document(self, mock_db):
        """Second upsert with different data should update, not create a new doc."""
        inv = self._three_invoices()[0]
        upsert_collections(mock_db, [inv], [], [], [])
        # Mutate amount and upsert again
        updated = dict(inv)
        updated["amount"] = 99999.0
        upsert_collections(mock_db, [updated], [], [], [])
        docs = list(mock_db.transactions.find({"invoice_id": inv["invoice_id"]}))
        assert len(docs) == 1
        assert docs[0]["amount"] == 99999.0

    def test_returns_summary_counts(self, mock_db):
        invoices = self._three_invoices()
        summary = upsert_collections(
            mock_db, invoices, self._vendors(), self._policies(), self._budgets()
        )
        assert summary["transactions"] == 3
        assert summary["vendors"] == 1
        assert summary["policies"] == 1
        assert summary["budgets"] == 1


# --------------------------------------------------------------------------- #
# Tests: vector_index.json
# --------------------------------------------------------------------------- #

class TestVectorIndexJson:
    def _load(self) -> dict:
        repo_root = Path(__file__).resolve().parent.parent.parent.parent
        index_path = repo_root / "vector_index.json"
        return json.loads(index_path.read_text())

    def test_file_exists(self):
        repo_root = Path(__file__).resolve().parent.parent.parent.parent
        assert (repo_root / "vector_index.json").exists()

    def test_num_dimensions_is_768(self):
        index = self._load()
        fields = index["definition"]["fields"]
        vector_fields = [f for f in fields if f.get("type") == "vector"]
        assert len(vector_fields) == 1
        assert vector_fields[0]["numDimensions"] == 768

    def test_similarity_is_cosine(self):
        index = self._load()
        fields = index["definition"]["fields"]
        vector_fields = [f for f in fields if f.get("type") == "vector"]
        assert vector_fields[0]["similarity"] == "cosine"

    def test_embedding_path(self):
        index = self._load()
        fields = index["definition"]["fields"]
        vector_fields = [f for f in fields if f.get("type") == "vector"]
        assert vector_fields[0]["path"] == "embedding"

    def test_filter_fields_present(self):
        index = self._load()
        fields = index["definition"]["fields"]
        filter_paths = {f["path"] for f in fields if f.get("type") == "filter"}
        assert {"department", "category", "fraud_label"}.issubset(filter_paths)

    def test_index_name_matches_settings(self):
        settings = get_settings()
        index = self._load()
        assert index["name"] == settings.vector_index_name


# --------------------------------------------------------------------------- #
# Integration: load from real demo_dataset JSONs if present
# --------------------------------------------------------------------------- #

class TestLoadFromDemoDataset:
    def test_load_real_demo_data_if_exists(self):
        """If demo_dataset JSON files exist, parse them into Pydantic models without error."""
        from faultaudit.config import DATA_DIR

        invoices_file = DATA_DIR / "invoices.json"
        if not invoices_file.exists():
            pytest.skip("demo_dataset/*.json not present — run generate_data.py first")

        data = load_json_dir(DATA_DIR)
        # Should have at least 1000 invoices
        assert len(data["invoices"]) >= 1000
        # All should validate cleanly
        for inv in data["invoices"][:10]:  # sample check for speed
            Invoice.model_validate(inv)

    def test_build_documents_with_real_data_sample(self):
        """build_documents runs without error on a sample of real invoices."""
        from faultaudit.config import DATA_DIR

        invoices_file = DATA_DIR / "invoices.json"
        if not invoices_file.exists():
            pytest.skip("demo_dataset/*.json not present — run generate_data.py first")

        data = load_json_dir(DATA_DIR)
        sample = data["invoices"][:5]
        docs = build_documents(sample, fake_embed_768)
        assert len(docs) == 5
        assert all(len(d["embedding"]) == EMBEDDING_DIMS for d in docs)
