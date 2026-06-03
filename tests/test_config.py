import pytest
from datetime import date, timedelta


def test_settings_loads_required_vars(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://test.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_KEY", "test-service-key")
    monkeypatch.setenv("EDGAR_USER_AGENT", "Test User test@test.com")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-anthropic-key")
    from wsd.config import Settings
    s = Settings()
    assert s.supabase_url == "https://test.supabase.co"
    assert s.supabase_service_key == "test-service-key"
    assert s.edgar_user_agent == "Test User test@test.com"
    assert s.anthropic_api_key == "test-anthropic-key"
    assert s.edgar_rate_limit == 8
    assert s.price_history_years == 5


def test_settings_raises_on_missing_supabase_url(monkeypatch):
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.setenv("SUPABASE_SERVICE_KEY", "test-key")
    monkeypatch.setenv("EDGAR_USER_AGENT", "Test User test@test.com")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    from wsd.config import Settings
    with pytest.raises(ValueError, match="SUPABASE_URL"):
        Settings()


def test_settings_raises_on_missing_service_key(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://test.supabase.co")
    monkeypatch.delenv("SUPABASE_SERVICE_KEY", raising=False)
    monkeypatch.setenv("EDGAR_USER_AGENT", "Test User test@test.com")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    from wsd.config import Settings
    with pytest.raises(ValueError, match="SUPABASE_SERVICE_KEY"):
        Settings()


def test_settings_raises_on_missing_edgar_user_agent(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://test.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_KEY", "test-key")
    monkeypatch.delenv("EDGAR_USER_AGENT", raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    from wsd.config import Settings
    with pytest.raises(ValueError, match="EDGAR_USER_AGENT"):
        Settings()


def test_settings_raises_on_missing_anthropic_key(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://test.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_KEY", "test-key")
    monkeypatch.setenv("EDGAR_USER_AGENT", "Test User test@test.com")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    from wsd.config import Settings
    with pytest.raises(ValueError, match="ANTHROPIC_API_KEY"):
        Settings()


def test_price_start_date_is_five_years_ago(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://test.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_KEY", "test-key")
    monkeypatch.setenv("EDGAR_USER_AGENT", "Test User test@test.com")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    from wsd.config import Settings
    s = Settings()
    expected = date.today() - timedelta(days=365 * 5)
    assert s.price_start_date == expected
