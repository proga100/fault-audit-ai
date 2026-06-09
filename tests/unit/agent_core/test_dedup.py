"""Tests for tools/dedup.py — find_exact_duplicates + find_near_duplicates"""

from __future__ import annotations

import hashlib

import pytest

from faultaudit.models import Invoice
from faultaudit.tools.dedup import NearDuplicate, find_exact_duplicates, find_near_duplicates


def fake_embed(text: str, dims: int = 8) -> list[float]:
    h = hashlib.sha256(text.encode()).digest()
    return [b / 255.0 for b in h[:dims]]


def make_inv(iid, vid, cat, amount, notes, inv_date="2026-05-01", embed_text=None):
    text = embed_text or f"{vid} {cat} {amount} {notes}"
    return Invoice(
        invoice_id=iid,
        vendor_id=vid,
        vendor_name="Test Corp",
        department="Finance",
        category=cat,
        amount=amount,
        payment_method="ACH",
        invoice_date=inv_date,
        payment_hour=10,
        approved_by="Tester",
        notes=notes,
        embedding_text=text,
        embedding=fake_embed(text),
    )


class TestFindExactDuplicates:
    def test_no_duplicates_empty_list(self):
        assert find_exact_duplicates([]) == []

    def test_no_duplicates_all_unique(self, invoices):
        # filter to just distinct invoices
        unique = [invoices[0], invoices[3], invoices[5]]
        result = find_exact_duplicates(unique)
        assert result == []

    def test_detects_exact_duplicate_pair(self, invoices):
        # i1 and i2 are exact dups (same vendor_id, amount=20000, category=Consulting)
        pairs = find_exact_duplicates(invoices)
        ids = {frozenset(p) for p in pairs}
        assert frozenset(["i1", "i2"]) in ids

    def test_original_is_earliest_by_date(self):
        earlier = make_inv("a", "v1", "Consulting", 1000, "note", "2026-01-01")
        later = make_inv("b", "v1", "Consulting", 1000, "note", "2026-06-01")
        pairs = find_exact_duplicates([later, earlier])  # later first in list
        assert ("a", "b") in pairs  # earlier is original

    def test_original_first_seen_when_same_date(self):
        inv_a = make_inv("a", "v1", "Consulting", 1000, "note", "2026-05-01")
        inv_b = make_inv("b", "v1", "Consulting", 1000, "note", "2026-05-01")
        pairs = find_exact_duplicates([inv_a, inv_b])
        # a appears first in list -> is original
        assert ("a", "b") in pairs

    def test_triple_creates_two_pairs(self):
        a = make_inv("a", "v1", "Consulting", 1000, "n")
        b = make_inv("b", "v1", "Consulting", 1000, "n")
        c = make_inv("c", "v1", "Consulting", 1000, "n")
        pairs = find_exact_duplicates([a, b, c])
        assert len(pairs) == 2
        originals = {p[0] for p in pairs}
        assert originals == {"a"}

    def test_different_category_not_a_dup(self):
        a = make_inv("a", "v1", "Consulting", 1000, "n")
        b = make_inv("b", "v1", "Travel", 1000, "n")
        assert find_exact_duplicates([a, b]) == []

    def test_different_amount_not_a_dup(self):
        a = make_inv("a", "v1", "Consulting", 1000, "n")
        b = make_inv("b", "v1", "Consulting", 1001, "n")
        assert find_exact_duplicates([a, b]) == []


class TestFindNearDuplicates:
    def test_identical_embeddings_detected(self):
        """Two invoices with identical embedding text -> cosine == 1.0."""
        text = "v1 Consulting 20000 Q2 engagement"
        a = make_inv("a", "v1", "Consulting", 20000, "Q2 engagement", embed_text=text)
        b = make_inv("b", "v1", "Consulting", 20300, "Q2 eng revised", embed_text=text)
        # Same embedding means cosine=1.0 but not exact dup -> should appear in results
        results = find_near_duplicates([a, b], threshold=0.9)
        ids = {r.invoice_id for r in results} | {r.similar_to_id for r in results}
        assert "a" in ids or "b" in ids

    def test_near_dup_not_exact_dup(self, invoices):
        """i3 is a near-dup of i1 but NOT exact (different amount 20300 vs 20000)."""
        result = find_near_duplicates(invoices, threshold=0.0)  # low threshold = catch all
        near_pairs = {frozenset([r.invoice_id, r.similar_to_id]) for r in result}
        # i1 and i2 are exact dups — should NOT appear in near-dup results
        # (find_exact_duplicates excludes them)
        exact_pairs = {frozenset(p) for p in find_exact_duplicates(invoices)}
        for ep in exact_pairs:
            assert ep not in near_pairs

    def test_below_threshold_not_returned(self):
        """Two completely different texts should have very low cosine -> not returned."""
        a = make_inv("a", "v1", "Consulting", 100, "aaa bbb ccc", embed_text="aaabbbccc")
        b = make_inv("b", "v2", "Travel", 999, "xyz xyz xyz", embed_text="xyzxyzxyz")
        results = find_near_duplicates([a, b], threshold=0.99)
        assert results == []

    def test_missing_embedding_skipped(self):
        a = make_inv("a", "v1", "Consulting", 100, "note")
        b = Invoice(
            invoice_id="b",
            vendor_id="v1",
            vendor_name="X",
            department="D",
            category="Consulting",
            amount=100,
            payment_method="ACH",
            invoice_date="2026-05-01",
            payment_hour=10,
            approved_by="T",
            notes="note",
            embedding=None,
        )
        # Should not raise; just silently skip b
        results = find_near_duplicates([a, b], threshold=0.0)
        assert results == []

    def test_near_dup_result_has_valid_similarity(self, invoices):
        results = find_near_duplicates(invoices, threshold=0.0)
        for r in results:
            assert 0.0 <= r.similarity <= 1.0

    def test_empty_list_returns_empty(self):
        assert find_near_duplicates([]) == []
