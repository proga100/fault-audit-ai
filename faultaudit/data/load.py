"""Pure, testable data pipeline functions for FaultAuditAI.

All I/O side effects (real embedder, real MongoDB) are injected so unit tests
can pass a fake embedder and mongomock without any network calls.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

from pymongo.database import Database

from faultaudit.models import Invoice, Policy, Vendor


# --------------------------------------------------------------------------- #
# 1.  JSON loading
# --------------------------------------------------------------------------- #

def load_json_dir(path: str | Path) -> dict[str, list[dict]]:
    """Read the four JSON files from *path* and return a dict of raw lists.

    Keys: "invoices", "vendors", "policies", "budgets".

    Raises FileNotFoundError if any of the required files is missing.
    The returned dicts are validated against the Pydantic models so callers
    get a clean failure rather than silent bad data.
    """
    base = Path(path)
    result: dict[str, list[dict]] = {}

    # --- invoices ---
    raw_invoices: list[dict] = json.loads((base / "invoices.json").read_text())
    result["invoices"] = [Invoice.model_validate(r).model_dump(mode="json") for r in raw_invoices]

    # --- vendors ---
    raw_vendors: list[dict] = json.loads((base / "vendors.json").read_text())
    result["vendors"] = [Vendor.model_validate(r).model_dump(mode="json") for r in raw_vendors]

    # --- policies ---
    raw_policies: list[dict] = json.loads((base / "policies.json").read_text())
    result["policies"] = [Policy.model_validate(r).model_dump(mode="json") for r in raw_policies]

    # --- budgets (free-form dict, no model) ---
    raw_budgets: dict = json.loads((base / "budgets.json").read_text())
    # budgets.json is {"budgets": {...}}, store as a list-of-one so callers
    # get a consistent dict[str, list] shape.
    result["budgets"] = [raw_budgets] if isinstance(raw_budgets, dict) else raw_budgets

    return result


# --------------------------------------------------------------------------- #
# 2.  Build embeddable documents
# --------------------------------------------------------------------------- #

def build_documents(
    invoices: list[dict],
    embedder: Callable[[str], list[float]],
) -> list[dict]:
    """Attach an `embedding` vector to each invoice dict.

    Args:
        invoices: Raw invoice dicts (as returned by load_json_dir or any
                  list[dict] with an ``embedding_text`` key).
        embedder: Callable ``(text: str) -> list[float]``.  In production
                  this wraps the real Gemini API; in tests it is a deterministic
                  hash-based fake so no network is required.

    Returns:
        A new list of dicts; original dicts are not mutated.
    """
    docs: list[dict] = []
    for inv in invoices:
        doc = dict(inv)
        text: str = doc.get("embedding_text") or ""
        doc["embedding"] = embedder(text)
        docs.append(doc)
    return docs


# --------------------------------------------------------------------------- #
# 3.  Idempotent upsert into MongoDB collections
# --------------------------------------------------------------------------- #

def upsert_collections(
    db: Database,
    invoices: list[dict],
    vendors: list[dict],
    policies: list[dict],
    budgets: list[dict],
) -> dict[str, int]:
    """Upsert all four collections idempotently.

    Uses ``replace_one(filter, doc, upsert=True)`` so running this function
    twice produces the same state (no duplicates).

    Works with both real PyMongo and mongomock.

    Returns:
        A summary dict with upserted/matched counts per collection.
    """
    summary: dict[str, int] = {}

    # invoices -> transactions collection
    txn_count = 0
    for doc in invoices:
        db.transactions.replace_one(
            {"invoice_id": doc["invoice_id"]},
            doc,
            upsert=True,
        )
        txn_count += 1
    summary["transactions"] = txn_count

    # vendors
    vendor_count = 0
    for doc in vendors:
        db.vendors.replace_one(
            {"vendor_id": doc["vendor_id"]},
            doc,
            upsert=True,
        )
        vendor_count += 1
    summary["vendors"] = vendor_count

    # policies
    policy_count = 0
    for doc in policies:
        db.policies.replace_one(
            {"rule_id": doc["rule_id"]},
            doc,
            upsert=True,
        )
        policy_count += 1
    summary["policies"] = policy_count

    # budgets (store as a single config doc keyed by a sentinel)
    budget_count = 0
    for doc in budgets:
        db.config.replace_one(
            {"_config_key": "dept_budgets"},
            {**doc, "_config_key": "dept_budgets"},
            upsert=True,
        )
        budget_count += 1
    summary["budgets"] = budget_count

    return summary
