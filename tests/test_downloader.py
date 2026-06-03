import pytest
from pathlib import Path
from unittest.mock import MagicMock


@pytest.fixture
def settings(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://test.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_KEY", "test-key")
    monkeypatch.setenv("EDGAR_USER_AGENT", "Test User test@test.com")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-anthropic-key")
    from wsd.config import Settings
    return Settings()


FILING = {
    "id": "uuid-filing-1",
    "company_id": "uuid-company-1",
    "cik": "0000320193",
    "accession_number": "0000320193-24-000001",
    "form_type": "8-K",
    "filed_date": "2024-01-15",
}

INDEX_JSON = {
    "directory": {
        "item": [
            {"name": "0000320193-24-000001-index.htm", "type": "text/html"},
            {"name": "aapl20240115_8k.htm", "type": "text/html"},
            {"name": "ex99-1.htm", "type": "text/html"},
        ]
    }
}


def test_accession_nodash():
    from wsd.extraction.downloader import _accession_nodash
    assert _accession_nodash("0000320193-24-000001") == "000032019324000001"


def test_cache_path_strips_leading_zeros_from_cik():
    from wsd.extraction.downloader import _cache_path
    p = _cache_path("0000320193", "0000320193-24-000001")
    assert "320193" in str(p)
    assert str(p).endswith("0000320193-24-000001.html")


def test_download_returns_cached_content_without_http(settings, tmp_path, monkeypatch):
    from wsd.extraction import downloader
    monkeypatch.setattr(downloader, "_CACHE_DIR", tmp_path)
    cache = tmp_path / "320193" / "0000320193-24-000001.html"
    cache.parent.mkdir(parents=True)
    cache.write_text("<html>cached</html>")
    result = downloader.download_filing(FILING, settings)
    assert result == "<html>cached</html>"


def test_download_returns_none_on_404(settings, tmp_path, monkeypatch):
    import requests
    from wsd.extraction import downloader
    monkeypatch.setattr(downloader, "_CACHE_DIR", tmp_path)

    def raise_404(url, s):
        r = MagicMock()
        r.status_code = 404
        raise requests.HTTPError(response=r)

    monkeypatch.setattr(downloader, "_fetch_json", raise_404)
    result = downloader.download_filing(FILING, settings)
    assert result is None


def test_find_primary_doc_skips_index_files():
    from wsd.extraction.downloader import _find_primary_doc
    result = _find_primary_doc(INDEX_JSON)
    assert result == "aapl20240115_8k.htm"


def test_find_primary_doc_returns_none_for_empty():
    from wsd.extraction.downloader import _find_primary_doc
    assert _find_primary_doc({"directory": {"item": []}}) is None
