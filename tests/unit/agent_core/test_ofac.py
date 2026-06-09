"""Tests for tools/ofac.py — load_sdn + screen_vendor_sanctions"""

from __future__ import annotations

import io
from pathlib import Path

import pytest
import respx
import httpx

from faultaudit.tools.ofac import SanctionsHit, load_sdn, screen_vendor_sanctions


SDN_CSV_CONTENT = (
    "ACME WEAPONS LLC,entity,IRN,,\n"
    "GHOSTLY ARMS CORP,entity,SYR,,\n"
    "EVIL TRADING CO,entity,RUS,,\n"
)


class TestScreenVendorSanctions:
    def test_exact_match_hits(self):
        sdn = ["ACME WEAPONS LLC", "GHOSTLY ARMS CORP"]
        hit = screen_vendor_sanctions("ACME WEAPONS LLC", sdn, threshold=0.85)
        assert hit is not None
        assert hit.matched_name == "ACME WEAPONS LLC"
        assert hit.score == pytest.approx(1.0)

    def test_fuzzy_hit_above_threshold(self):
        sdn = ["ACME WEAPONS LLC"]
        # "ACME WEAPNS LLC" is close enough
        hit = screen_vendor_sanctions("ACME WEAPNS LLC", sdn, threshold=0.80)
        assert hit is not None
        assert hit.query == "ACME WEAPNS LLC"

    def test_miss_below_threshold(self):
        sdn = ["ACME WEAPONS LLC", "GHOSTLY ARMS CORP"]
        hit = screen_vendor_sanctions("Totally Benign Inc", sdn, threshold=0.85)
        assert hit is None

    def test_case_insensitive(self):
        sdn = ["ACME WEAPONS LLC"]
        hit = screen_vendor_sanctions("acme weapons llc", sdn, threshold=0.85)
        assert hit is not None

    def test_empty_sdn_returns_none(self):
        assert screen_vendor_sanctions("Any Corp", [], threshold=0.85) is None

    def test_returns_best_match(self):
        sdn = ["CLOSE MATCH CORP", "EXACT MATCH INC"]
        hit = screen_vendor_sanctions("EXACT MATCH INC", sdn, threshold=0.85)
        assert hit is not None
        assert hit.matched_name == "EXACT MATCH INC"
        assert hit.score == pytest.approx(1.0)


class TestLoadSdn:
    def test_load_from_cache_file(self, tmp_path, monkeypatch):
        """When cache file exists, should read from it without HTTP."""
        cache_file = tmp_path / "sdn.csv"
        cache_file.write_text(SDN_CSV_CONTENT, encoding="utf-8")

        # Monkeypatch the settings to point to our tmp cache
        from faultaudit import config as cfg_module
        cfg_module.get_settings.cache_clear()
        monkeypatch.setenv("OFAC_CACHE_PATH", str(cache_file))
        cfg_module.get_settings.cache_clear()

        names = load_sdn()
        assert "ACME WEAPONS LLC" in names
        assert "GHOSTLY ARMS CORP" in names
        assert "EVIL TRADING CO" in names
        cfg_module.get_settings.cache_clear()

    @respx.mock
    def test_download_when_no_cache(self, tmp_path, monkeypatch):
        """When cache file doesn't exist, should HTTP GET and parse."""
        cache_file = tmp_path / "sdn_not_existing.csv"
        assert not cache_file.exists()

        from faultaudit import config as cfg_module
        cfg_module.get_settings.cache_clear()
        monkeypatch.setenv("OFAC_CACHE_PATH", str(cache_file))
        monkeypatch.setenv("OFAC_SDN_URL", "https://mock-ofac.test/sdn.csv")
        cfg_module.get_settings.cache_clear()

        respx.get("https://mock-ofac.test/sdn.csv").mock(
            return_value=httpx.Response(200, text=SDN_CSV_CONTENT)
        )

        names = load_sdn()
        assert "ACME WEAPONS LLC" in names
        cfg_module.get_settings.cache_clear()

    @respx.mock
    def test_caches_downloaded_file(self, tmp_path, monkeypatch):
        """After downloading, a cache file should be written."""
        cache_file = tmp_path / "sdn_new.csv"

        from faultaudit import config as cfg_module
        cfg_module.get_settings.cache_clear()
        monkeypatch.setenv("OFAC_CACHE_PATH", str(cache_file))
        monkeypatch.setenv("OFAC_SDN_URL", "https://mock-ofac.test/sdn.csv")
        cfg_module.get_settings.cache_clear()

        respx.get("https://mock-ofac.test/sdn.csv").mock(
            return_value=httpx.Response(200, text=SDN_CSV_CONTENT)
        )

        load_sdn()
        assert cache_file.exists()
        cfg_module.get_settings.cache_clear()
