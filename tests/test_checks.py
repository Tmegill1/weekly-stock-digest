import pytest
from datetime import date, timedelta


def test_check_stale_prices_flags_old_data():
    from wsd.quality.checks import _check_stale_prices
    old_date = (date.today() - timedelta(days=10)).isoformat()
    logs = _check_stale_prices([{"company_id": "uuid-1", "max": old_date}])
    assert len(logs) == 1
    assert logs[0]["check_type"] == "stale_price"
    assert logs[0]["severity"] == "error"
    assert logs[0]["company_id"] == "uuid-1"


def test_check_stale_prices_ignores_recent_data():
    from wsd.quality.checks import _check_stale_prices
    recent = (date.today() - timedelta(days=2)).isoformat()
    assert _check_stale_prices([{"company_id": "uuid-1", "max": recent}]) == []


def test_check_price_anomalies_flags_large_moves():
    from wsd.quality.checks import _check_price_anomalies
    rows = [
        {"company_id": "uuid-1", "trading_date": "2024-01-01", "adj_close": 100.0},
        {"company_id": "uuid-1", "trading_date": "2024-01-02", "adj_close": 160.0},
    ]
    logs = _check_price_anomalies(rows)
    assert len(logs) == 1
    assert logs[0]["check_type"] == "price_anomaly"


def test_check_price_anomalies_ignores_normal_moves():
    from wsd.quality.checks import _check_price_anomalies
    rows = [
        {"company_id": "uuid-1", "trading_date": "2024-01-01", "adj_close": 100.0},
        {"company_id": "uuid-1", "trading_date": "2024-01-02", "adj_close": 102.0},
    ]
    assert _check_price_anomalies(rows) == []


def test_check_missing_filings_flags_companies_without_recent_10q():
    from wsd.quality.checks import _check_missing_filings
    logs = _check_missing_filings([{"id": "uuid-1", "ticker": "AAPL"}], {})
    assert len(logs) == 1
    assert logs[0]["check_type"] == "missing_filing"


def test_check_missing_filings_ignores_companies_with_recent_10q():
    from wsd.quality.checks import _check_missing_filings
    recent = (date.today() - timedelta(days=30)).isoformat()
    filings = {"uuid-1": [{"filed_date": recent}]}
    assert _check_missing_filings([{"id": "uuid-1", "ticker": "AAPL"}], filings) == []
