import pytest
import pandas as pd
from datetime import date, timedelta


@pytest.fixture
def settings(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://test.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_KEY", "test-key")
    monkeypatch.setenv("EDGAR_USER_AGENT", "Test User test@test.com")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-anthropic-key")
    from wsd.config import Settings
    return Settings()


def _make_price_df(dates: list[str]) -> pd.DataFrame:
    idx = pd.to_datetime(dates)
    return pd.DataFrame(
        {"Open": [100.0]*len(dates), "High": [105.0]*len(dates),
         "Low": [98.0]*len(dates), "Close": [102.0]*len(dates), "Volume": [1_000_000]*len(dates)},
        index=idx,
    )


def test_build_price_rows_maps_fields_correctly():
    from wsd.ingestion.prices import _build_price_rows
    rows = _build_price_rows(_make_price_df(["2024-01-02", "2024-01-03"]), "uuid-123", "AAPL")
    assert len(rows) == 2
    assert rows[0]["company_id"] == "uuid-123"
    assert rows[0]["trading_date"] == "2024-01-02"
    assert rows[0]["adj_close"] == 102.0
    assert rows[0]["high"] == 105.0


def test_build_price_rows_drops_zero_adj_close():
    from wsd.ingestion.prices import _build_price_rows
    df = _make_price_df(["2024-01-02"])
    df.loc[df.index[0], "Close"] = 0.0
    assert _build_price_rows(df, "uuid-123", "AAPL") == []


def test_build_price_rows_drops_high_less_than_low():
    from wsd.ingestion.prices import _build_price_rows
    df = _make_price_df(["2024-01-02"])
    df.loc[df.index[0], "High"] = 50.0
    df.loc[df.index[0], "Low"] = 100.0
    assert _build_price_rows(df, "uuid-123", "AAPL") == []


def test_get_start_date_uses_max_date_plus_one_if_exists():
    from wsd.ingestion.prices import _get_start_date
    result = _get_start_date("uuid-123", {"uuid-123": "2024-06-01"}, date(2020, 1, 1), date(2015, 1, 1))
    assert result == date(2024, 6, 2)


def test_get_start_date_uses_price_start_for_new_company():
    from wsd.ingestion.prices import _get_start_date
    result = _get_start_date("uuid-123", {}, date(2020, 1, 1), date(2015, 1, 1))
    assert result == date(2020, 1, 1)


def test_get_start_date_uses_entry_date_if_later_than_price_start():
    from wsd.ingestion.prices import _get_start_date
    result = _get_start_date("uuid-123", {}, date(2020, 1, 1), date(2022, 6, 1))
    assert result == date(2022, 6, 1)
