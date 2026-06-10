"""Shared test fixtures for all slices. No network, no creds — mongomock + fakes only.

Slices may add their own fixtures, but these shared ones define the canonical sample
data every slice tests against.
"""

from __future__ import annotations

import hashlib
import os

# Tests always run against mongomock, which has no $vectorSearch. Force mock mode
# regardless of .env (which may set USE_MOCKS=false for live runs). Env vars take
# precedence over the .env file in pydantic-settings.
os.environ["USE_MOCKS"] = "true"

import mongomock
import pytest

from faultaudit.config import get_settings

get_settings.cache_clear()

from faultaudit.models import Invoice, Policy, Vendor


# --------------------------------------------------------------------------- #
# Deterministic fake embedder (stands in for gemini-embedding-001 in tests)
# --------------------------------------------------------------------------- #
def fake_embed(text: str, dims: int = 8) -> list[float]:
    """Deterministic pseudo-embedding so cosine tests are reproducible.

    Identical text -> identical vector; similar text -> closer vectors (shared prefix
    of the hash). Good enough to exercise dedup/vector logic without a real model.
    """
    h = hashlib.sha256(text.encode()).digest()
    return [b / 255.0 for b in h[:dims]]


@pytest.fixture
def embedder():
    return fake_embed


# --------------------------------------------------------------------------- #
# Canonical sample domain data
# --------------------------------------------------------------------------- #
@pytest.fixture
def policies() -> list[Policy]:
    return [
        Policy(rule_id="P1", category="Travel", max_amount=5000, text="Travel > 5000 needs VP."),
        Policy(rule_id="P2", category="Consulting", max_amount=50000, text="Consulting > 50000 dual sign-off."),
        Policy(rule_id="P4", category="*", max_amount=100000, text="Any payment > 100000 needs CFO."),
    ]


@pytest.fixture
def vendors() -> list[Vendor]:
    return [
        Vendor(vendor_id="v1", vendor_name="Acme Corp", country="USA", category="Consulting",
               onboarded="2022-01-01", is_ghost=False, risk_score=0.1),
        Vendor(vendor_id="v2", vendor_name="Ghostly LLC", country="USA", category="Services",
               onboarded="2026-05-20", is_ghost=True, risk_score=0.9),
    ]


@pytest.fixture
def invoices(embedder) -> list[Invoice]:
    """A small ledger with one of each fraud type for slice tests to assert against."""
    def mk(iid, vid, vname, cat, amount, hour, notes, **flags):
        text = f"{vname} {cat} {amount} {notes}"
        return Invoice(
            invoice_id=iid, vendor_id=vid, vendor_name=vname, department="Finance",
            category=cat, amount=amount, payment_method="ACH", invoice_date="2026-05-01",
            payment_hour=hour, approved_by="A. Tester", notes=notes,
            embedding_text=text, embedding=embedder(text), **flags,
        )

    orig = mk("i1", "v1", "Acme Corp", "Consulting", 20000, 10, "Q2 consulting engagement")
    exact_dup = mk("i2", "v1", "Acme Corp", "Consulting", 20000, 10, "Resubmitted invoice",
                   is_duplicate=True, fraud_label=1)
    near_dup = mk("i3", "v1", "Acme Corp", "Consulting", 20300, 9,
                  "Q2 consulting engagement, revised", is_near_duplicate=True, fraud_label=1)
    policy_viol = mk("i4", "v1", "Acme Corp", "Consulting", 120000, 11, "Big consulting",
                     is_policy_violation=True, fraud_label=1)
    off_hours = mk("i5", "v1", "Acme Corp", "Consulting", 8000, 2, "Late night payment",
                   is_off_hours=True, fraud_label=1)
    ghost = mk("i6", "v2", "Ghostly LLC", "Services", 45000, 3,
               "Urgent off-cycle wire to new vendor", is_ghost_vendor=True, fraud_label=1)
    return [orig, exact_dup, near_dup, policy_viol, off_hours, ghost]


# --------------------------------------------------------------------------- #
# In-memory MongoDB (mongomock) populated with the sample data
# --------------------------------------------------------------------------- #
@pytest.fixture
def mock_db(invoices, vendors, policies):
    client = mongomock.MongoClient()
    db = client["faultaudit"]
    db.transactions.insert_many([i.model_dump(mode="json") for i in invoices])
    db.vendors.insert_many([v.model_dump(mode="json") for v in vendors])
    db.policies.insert_many([p.model_dump(mode="json") for p in policies])
    return db
