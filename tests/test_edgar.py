import pytest
from unittest.mock import MagicMock


@pytest.fixture
def settings(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://test.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_KEY", "test-key")
    monkeypatch.setenv("EDGAR_USER_AGENT", "Test User test@test.com")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-anthropic-key")
    from wsd.config import Settings
    return Settings()


EDGAR_RESPONSE = {
    "filings": {
        "recent": {
            "form": ["8-K", "10-Q", "DEF 14A", "4", "10-K"],
            "accessionNumber": [
                "0000320193-24-000001", "0000320193-24-000002",
                "0000320193-24-000003", "0000320193-24-000004", "0000320193-24-000005",
            ],
            "filingDate": ["2024-01-15", "2024-01-20", "2024-02-01", "2024-02-10", "2024-02-15"],
            "reportDate": ["2024-01-14", "2023-12-31", "2023-12-31", "2024-02-09", "2023-09-30"],
        },
        "files": [],
    }
}


def test_parse_filing_block_filters_to_target_forms():
    from wsd.ingestion.edgar import _parse_filing_block
    rows = _parse_filing_block(EDGAR_RESPONSE["filings"]["recent"], "uuid-123", "0000320193")
    assert {r["form_type"] for r in rows} == {"8-K", "10-Q", "4", "10-K"}


def test_parse_filing_block_uses_filed_date_not_period_date():
    from wsd.ingestion.edgar import _parse_filing_block
    rows = _parse_filing_block(EDGAR_RESPONSE["filings"]["recent"], "uuid-123", "0000320193")
    eight_k = next(r for r in rows if r["form_type"] == "8-K")
    assert eight_k["filed_date"] == "2024-01-15"
    assert eight_k["period_date"] == "2024-01-14"


def test_parse_filing_block_sets_company_id_and_cik():
    from wsd.ingestion.edgar import _parse_filing_block
    rows = _parse_filing_block(EDGAR_RESPONSE["filings"]["recent"], "uuid-123", "0000320193")
    assert all(r["company_id"] == "uuid-123" for r in rows)
    assert all(r["cik"] == "0000320193" for r in rows)


def test_parse_filing_block_sets_is_parsed_false():
    from wsd.ingestion.edgar import _parse_filing_block
    rows = _parse_filing_block(EDGAR_RESPONSE["filings"]["recent"], "uuid-123", "0000320193")
    assert all(r["is_parsed"] is False for r in rows)


def test_parse_filing_block_returns_empty_for_empty_block():
    from wsd.ingestion.edgar import _parse_filing_block
    assert _parse_filing_block({}, "uuid-123", "0000320193") == []


def test_ingest_edgar_exits_if_no_companies(settings, mocker):
    mock_client = MagicMock()
    mock_client.table.return_value.select.return_value.not_.is_.return_value.execute.return_value.data = []
    mocker.patch("wsd.ingestion.edgar.db.get_client", return_value=mock_client)
    from wsd.ingestion.edgar import ingest_edgar
    with pytest.raises(SystemExit):
        ingest_edgar(settings)
