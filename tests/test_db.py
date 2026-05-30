import pytest
from unittest.mock import MagicMock


@pytest.fixture
def settings(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://test.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_KEY", "test-key")
    monkeypatch.setenv("EDGAR_USER_AGENT", "Test User test@test.com")
    from wsd.config import Settings
    return Settings()


def test_upsert_companies_returns_row_count(settings, mocker):
    mock_result = MagicMock()
    mock_result.data = [{"id": "1"}, {"id": "2"}]
    mock_execute = MagicMock(return_value=mock_result)
    mock_upsert = MagicMock(return_value=MagicMock(execute=mock_execute))
    mock_table = MagicMock(return_value=MagicMock(upsert=mock_upsert))
    mocker.patch("wsd.db.get_client", return_value=MagicMock(table=mock_table))
    from wsd.db import upsert_companies
    count = upsert_companies([{"ticker": "AAPL"}, {"ticker": "MSFT"}], settings)
    assert count == 2


def test_upsert_companies_returns_zero_for_empty_list(settings, mocker):
    mocker.patch("wsd.db.get_client")
    from wsd.db import upsert_companies
    assert upsert_companies([], settings) == 0


def test_upsert_prices_returns_zero_for_empty_list(settings, mocker):
    mocker.patch("wsd.db.get_client")
    from wsd.db import upsert_prices
    assert upsert_prices([], settings) == 0


def test_upsert_filings_returns_zero_for_empty_list(settings, mocker):
    mocker.patch("wsd.db.get_client")
    from wsd.db import upsert_filings
    assert upsert_filings([], settings) == 0


def test_insert_quality_log_does_nothing_for_empty_list(settings, mocker):
    mock_client = mocker.patch("wsd.db.get_client")
    from wsd.db import insert_quality_log
    insert_quality_log([], settings)
    mock_client.return_value.table.assert_not_called()
