"""Tests for tools/mongo_reads.py — vector_search, aggregate_spend, get_vendor_history"""

from __future__ import annotations

import hashlib

import pytest

from faultaudit.tools.mongo_reads import (
    aggregate_spend,
    get_vendor_history,
    vector_search_transactions,
)


def fake_embed(text: str, dims: int = 8) -> list[float]:
    h = hashlib.sha256(text.encode()).digest()
    return [b / 255.0 for b in h[:dims]]


class TestVectorSearchTransactions:
    def test_returns_top_k(self, mock_db):
        """Should return at most k results."""
        query_vec = fake_embed("Acme Corp Consulting 20000 Q2 consulting engagement")
        results = vector_search_transactions(mock_db, query_vec, k=2)
        assert len(results) <= 2

    def test_results_include_score(self, mock_db):
        query_vec = fake_embed("Acme Corp Consulting 20000 Q2 consulting engagement")
        results = vector_search_transactions(mock_db, query_vec, k=5)
        for r in results:
            assert "score" in r
            assert 0.0 <= r["score"] <= 1.0

    def test_results_ordered_by_score_desc(self, mock_db):
        query_vec = fake_embed("Acme Corp Consulting 20000 Q2 consulting engagement")
        results = vector_search_transactions(mock_db, query_vec, k=10)
        scores = [r["score"] for r in results]
        assert scores == sorted(scores, reverse=True)

    def test_top_result_is_most_similar(self, mock_db):
        """Querying with the embedding of i1 should return i1 as top result."""
        query_vec = fake_embed("Acme Corp Consulting 20000 Q2 consulting engagement")
        results = vector_search_transactions(mock_db, query_vec, k=10)
        assert results[0]["invoice_id"] == "i1"

    def test_filter_by_vendor_id(self, mock_db):
        """Only return docs matching the filter."""
        query_vec = fake_embed("Ghostly LLC Services 45000 Urgent off-cycle wire")
        results = vector_search_transactions(mock_db, query_vec, k=10, filters={"vendor_id": "v2"})
        assert all(r["vendor_id"] == "v2" for r in results)

    def test_filter_excludes_non_matching(self, mock_db):
        """Filter by vendor_id=v2 should exclude v1 invoices."""
        query_vec = fake_embed("Acme Corp Consulting 20000 Q2 consulting engagement")
        results = vector_search_transactions(mock_db, query_vec, k=10, filters={"vendor_id": "v2"})
        assert not any(r["vendor_id"] == "v1" for r in results)

    def test_empty_filters(self, mock_db):
        """Empty/None filters should return all docs (up to k)."""
        query_vec = fake_embed("Acme Corp Consulting 20000 Q2 consulting engagement")
        results = vector_search_transactions(mock_db, query_vec, k=100, filters=None)
        assert len(results) == 6  # all 6 invoices from fixture


class TestAggregateSpend:
    def test_groups_by_department(self, mock_db):
        """All fixture invoices have department=Finance."""
        results = aggregate_spend(mock_db, group_by="department")
        ids = [r["_id"] for r in results]
        assert "Finance" in ids

    def test_totals_correct(self, mock_db):
        """Sum of all amounts: 20000+20000+20300+120000+8000+45000 = 233300."""
        results = aggregate_spend(mock_db, group_by="department")
        total_sum = sum(r["total"] for r in results)
        assert total_sum == pytest.approx(233300.0)

    def test_count_correct(self, mock_db):
        results = aggregate_spend(mock_db, group_by="department")
        total_count = sum(r["count"] for r in results)
        assert total_count == 6  # all invoices in fixture

    def test_group_by_category(self, mock_db):
        results = aggregate_spend(mock_db, group_by="category")
        ids = {r["_id"] for r in results}
        assert "Consulting" in ids
        assert "Services" in ids

    def test_group_by_vendor_name(self, mock_db):
        results = aggregate_spend(mock_db, group_by="vendor_name")
        ids = {r["_id"] for r in results}
        assert "Acme Corp" in ids
        assert "Ghostly LLC" in ids


class TestGetVendorHistory:
    def test_returns_vendor_data(self, mock_db):
        result = get_vendor_history(mock_db, "v1")
        assert result["vendor_id"] == "v1"
        assert result["vendor_name"] == "Acme Corp"

    def test_invoice_count(self, mock_db):
        result = get_vendor_history(mock_db, "v1")
        # v1 has 5 invoices (i1,i2,i3,i4,i5)
        assert result["invoice_count"] == 5

    def test_total_amount(self, mock_db):
        result = get_vendor_history(mock_db, "v1")
        # 20000+20000+20300+120000+8000 = 188300
        assert result["total_amount"] == pytest.approx(188300.0)

    def test_first_and_last_invoice_date(self, mock_db):
        result = get_vendor_history(mock_db, "v1")
        # All fixture invoices have same date, so first == last
        assert result["first_invoice_date"] is not None
        assert result["last_invoice_date"] is not None

    def test_is_ghost_false_for_v1(self, mock_db):
        result = get_vendor_history(mock_db, "v1")
        assert result["is_ghost"] is False

    def test_is_ghost_true_for_v2(self, mock_db):
        result = get_vendor_history(mock_db, "v2")
        assert result["is_ghost"] is True

    def test_ghost_vendor_history(self, mock_db):
        result = get_vendor_history(mock_db, "v2")
        assert result["vendor_id"] == "v2"
        assert result["invoice_count"] == 1  # only i6

    def test_unknown_vendor_returns_empty(self, mock_db):
        result = get_vendor_history(mock_db, "vXXX")
        assert result == {}
