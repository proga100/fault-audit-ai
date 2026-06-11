"""FaultAuditAI - synthetic corporate finance data generator.

Generates a license-safe (GPL-3.0) corporate ledger with injected fraud so the
audit agent has something real to find. Deliberately seeds *near*-duplicates and a
handful of labeled "known fraud exemplars" so semantic vector search beats a plain
GROUP BY.

Outputs: vendors.json, invoices.json, policies.json, budgets.json

Run:  python generate_data.py
"""

import json
import random
import uuid

from faker import Faker

fake = Faker()
Faker.seed(42)
random.seed(42)

# --- knobs -------------------------------------------------------------------
N_VENDORS = 60
N_GHOST_VENDORS = 3
N_INVOICES = 1500          # ~1.5k keeps embedding fast/cheap; demo looks identical
N_EXACT_DUPLICATES = 25
N_NEAR_DUPLICATES = 30
PROB_POLICY_VIOLATION = 0.08
PROB_OFF_HOURS = 0.05

DEPARTMENTS = ["IT", "HR", "Sales", "Operations", "Marketing", "Finance"]
CATEGORIES = ["Software", "Travel", "Consulting", "Equipment",
              "Office Supplies", "Services", "Marketing"]
PAY_METHODS = ["ACH", "Wire", "Corporate Card", "Cheque"]
DEPT_BUDGETS = {d: random.randint(80_000, 400_000) for d in DEPARTMENTS}

POLICIES = [
    {"rule_id": "P1", "category": "Travel", "max_amount": 5000,
     "text": "Travel expenses above 5000 require VP approval."},
    {"rule_id": "P2", "category": "Consulting", "max_amount": 50000,
     "text": "Consulting invoices above 50000 require dual sign-off."},
    {"rule_id": "P3", "category": "Office Supplies", "max_amount": 2000,
     "text": "Office supply purchases capped at 2000 per invoice."},
    {"rule_id": "P4", "category": "*", "max_amount": 100000,
     "text": "Any single payment above 100000 requires CFO approval."},
]

# Templates used to reword near-duplicate invoice notes so they are semantically
# similar but not byte-identical -- this is what the vector search is meant to catch.
DUP_NOTE_TEMPLATES = [
    "Resubmitted invoice for the same engagement.",
    "Second submission, slightly revised amount.",
    "Re-invoiced after initial payment delay.",
    "Duplicate billing for prior month services.",
    "Repeat charge, reference number changed.",
]

# A couple of canonical fraud "stories" the agent can vector-search against.
FRAUD_EXEMPLAR_NOTES = [
    "Urgent off-cycle wire to new vendor, invoice rushed before month-end close.",
    "Round-number consulting fee with no statement of work attached.",
    "Payment split into several smaller invoices to stay under approval limit.",
]


def make_vendors(n=N_VENDORS):
    vendors = []
    for _ in range(n):
        vendors.append({
            "vendor_id": str(uuid.uuid4()),
            "vendor_name": fake.company(),
            "country": fake.country(),
            "category": random.choice(CATEGORIES),
            "onboarded": fake.date_between("-4y", "-6M").isoformat(),
            "is_ghost": False,
            "risk_score": round(random.uniform(0, 0.4), 2),
        })
    # promote a few to "ghost vendors": brand new, high risk
    for v in random.sample(vendors, N_GHOST_VENDORS):
        v["is_ghost"] = True
        v["onboarded"] = fake.date_between("-30d", "today").isoformat()
        v["risk_score"] = round(random.uniform(0.7, 0.95), 2)
    return vendors


def base_invoice(vendor, notes=None):
    cat = vendor["category"]
    date = fake.date_between("-6M", "today")
    return {
        "invoice_id": str(uuid.uuid4()),
        "vendor_id": vendor["vendor_id"],
        "vendor_name": vendor["vendor_name"],
        "department": random.choice(DEPARTMENTS),
        "category": cat,
        "amount": round(random.uniform(500, 60000), 2),
        "currency": "USD",
        "payment_method": random.choice(PAY_METHODS),
        "invoice_date": date.isoformat(),
        "payment_hour": random.randint(8, 18),
        "approved_by": fake.name(),
        "notes": notes if notes else fake.sentence(),
        "is_duplicate": False,
        "is_near_duplicate": False,
        "is_policy_violation": False,
        "is_off_hours": False,
        "is_ghost_vendor": vendor["is_ghost"],
        "is_fraud_exemplar": False,
        "fraud_label": 1 if vendor["is_ghost"] else 0,
    }


def embedding_text(inv):
    return (f"Vendor {inv['vendor_name']} | dept {inv['department']} | "
            f"{inv['category']} | amount {inv['amount']} {inv['currency']} | "
            f"paid via {inv['payment_method']} at hour {inv['payment_hour']} | "
            f"{inv['notes']}")


def generate():
    vendors = make_vendors()
    invoices = []

    # --- normal + structurally fraudulent invoices --------------------------
    for _ in range(N_INVOICES):
        v = random.choice(vendors)
        inv = base_invoice(v)
        if random.random() < PROB_POLICY_VIOLATION:
            inv["amount"] = round(random.uniform(60000, 250000), 2)
            inv["is_policy_violation"] = True
            inv["fraud_label"] = 1
        if random.random() < PROB_OFF_HOURS:
            inv["payment_hour"] = random.choice([0, 1, 2, 3, 23])
            inv["is_off_hours"] = True
            inv["fraud_label"] = 1
        invoices.append(inv)

    # --- exact duplicates (caught by aggregation) ---------------------------
    for orig in random.sample(invoices, N_EXACT_DUPLICATES):
        dup = dict(orig)
        dup["invoice_id"] = str(uuid.uuid4())
        dup["is_duplicate"] = True
        dup["fraud_label"] = 1
        dup["notes"] = "Resubmitted invoice"
        invoices.append(dup)

    # --- near-duplicates (only caught by semantic vector search) ------------
    for orig in random.sample(invoices, N_NEAR_DUPLICATES):
        nd = dict(orig)
        nd["invoice_id"] = str(uuid.uuid4())
        nd["is_near_duplicate"] = True
        nd["fraud_label"] = 1
        # nudge the amount and reword the note so it is similar, not identical
        nd["amount"] = round(orig["amount"] * random.uniform(0.97, 1.03), 2)
        nd["payment_hour"] = min(18, max(8, orig["payment_hour"] + random.choice([-1, 1])))
        nd["notes"] = random.choice(DUP_NOTE_TEMPLATES)
        invoices.append(nd)

    # --- labeled fraud exemplars (vector search anchors) --------------------
    for note in FRAUD_EXEMPLAR_NOTES:
        v = random.choice([x for x in vendors if x["is_ghost"]] or vendors)
        ex = base_invoice(v, notes=note)
        ex["amount"] = round(random.choice([25000.0, 50000.0, 99000.0]), 2)
        ex["is_fraud_exemplar"] = True
        ex["fraud_label"] = 1
        invoices.append(ex)

    # --- text used to build embeddings later --------------------------------
    for inv in invoices:
        inv["embedding_text"] = embedding_text(inv)

    return vendors, invoices


def main():
    vendors, invoices = generate()

    json.dump(vendors, open("vendors.json", "w"), indent=2)
    json.dump(invoices, open("invoices.json", "w"), indent=2)
    json.dump(POLICIES, open("policies.json", "w"), indent=2)
    json.dump({"budgets": DEPT_BUDGETS}, open("budgets.json", "w"), indent=2)

    flagged = sum(i["fraud_label"] for i in invoices)
    print(f"Generated {len(invoices)} invoices  ({flagged} flagged, "
          f"{flagged / len(invoices):.0%}) across {len(vendors)} vendors.")
    print("  breakdown:")
    for key, label in [
        ("is_duplicate", "exact duplicates"),
        ("is_near_duplicate", "near-duplicates"),
        ("is_policy_violation", "policy violations"),
        ("is_off_hours", "off-hours payments"),
        ("is_ghost_vendor", "ghost-vendor invoices"),
        ("is_fraud_exemplar", "fraud exemplars"),
    ]:
        print(f"    {sum(i[key] for i in invoices):>4}  {label}")
    print("  wrote: vendors.json, invoices.json, policies.json, budgets.json")


if __name__ == "__main__":
    main()
