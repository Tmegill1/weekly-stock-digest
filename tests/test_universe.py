import pytest
import csv
from pathlib import Path


@pytest.fixture
def settings(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://test.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_KEY", "test-key")
    monkeypatch.setenv("EDGAR_USER_AGENT", "Test User test@test.com")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-anthropic-key")
    from wsd.config import Settings
    return Settings()


VALID_CSV = """ticker,cik,name,sector,industry,exchange,entry_date,exit_date,exit_reason
AAPL,0000320193,Apple Inc,Technology,Hardware,NASDAQ,1982-11-30,,
MSFT,0000789019,Microsoft Corp,Technology,Software,NASDAQ,1994-06-01,,
ENRN,,Enron Corp,Energy,Oil & Gas,NYSE,1986-01-01,2001-11-30,bankrupt
"""


def _make_csv(tmp_path: Path, content: str) -> Path:
    p = tmp_path / "test.csv"
    p.write_text(content)
    return p


def test_load_universe_upserts_valid_rows(settings, tmp_path, mocker):
    mocker.patch("wsd.ingestion.universe.db.upsert_companies", return_value=3)
    from wsd.ingestion.universe import load_universe
    result = load_universe(settings, csv_path=_make_csv(tmp_path, VALID_CSV))
    assert result["upserted"] == 3
    assert result["skipped"] == 0


def test_load_universe_skips_row_missing_ticker(settings, tmp_path, mocker):
    mocker.patch("wsd.ingestion.universe.db.upsert_companies", return_value=1)
    bad_csv = "ticker,cik,name,sector,industry,exchange,entry_date,exit_date,exit_reason\n,0000320193,Apple Inc,Tech,HW,NASDAQ,1982-11-30,,\nMSFT,0000789019,Microsoft,Tech,SW,NASDAQ,1994-06-01,,\n"
    from wsd.ingestion.universe import load_universe
    result = load_universe(settings, csv_path=_make_csv(tmp_path, bad_csv))
    assert result["skipped"] == 1


def test_load_universe_skips_row_missing_entry_date(settings, tmp_path, mocker):
    mocker.patch("wsd.ingestion.universe.db.upsert_companies", return_value=1)
    bad_csv = "ticker,cik,name,sector,industry,exchange,entry_date,exit_date,exit_reason\nAAPL,0000320193,Apple Inc,Tech,HW,NASDAQ,,,\nMSFT,0000789019,Microsoft,Tech,SW,NASDAQ,1994-06-01,,\n"
    from wsd.ingestion.universe import load_universe
    result = load_universe(settings, csv_path=_make_csv(tmp_path, bad_csv))
    assert result["skipped"] == 1


def test_load_universe_skips_invalid_exit_reason(settings, tmp_path, mocker):
    mocker.patch("wsd.ingestion.universe.db.upsert_companies", return_value=1)
    bad_csv = "ticker,cik,name,sector,industry,exchange,entry_date,exit_date,exit_reason\nAAPL,0000320193,Apple Inc,Tech,HW,NASDAQ,1982-11-30,2020-01-01,INVALID\nMSFT,0000789019,Microsoft,Tech,SW,NASDAQ,1994-06-01,,\n"
    from wsd.ingestion.universe import load_universe
    result = load_universe(settings, csv_path=_make_csv(tmp_path, bad_csv))
    assert result["skipped"] == 1


def test_validate_row_maps_fields_correctly():
    from wsd.ingestion.universe import _validate_row
    raw = {"ticker": "AAPL", "cik": "0000320193", "name": "Apple Inc",
           "sector": "Technology", "industry": "Hardware", "exchange": "NASDAQ",
           "entry_date": "1982-11-30", "exit_date": "", "exit_reason": ""}
    row, error = _validate_row(raw)
    assert error is None
    assert row["ticker"] == "AAPL"
    assert row["cik"] == "0000320193"
    assert row["exit_date"] is None
    assert row["exit_reason"] is None
