import pytest
import requests
from unittest.mock import MagicMock


@pytest.fixture
def settings(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://test.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_KEY", "test-key")
    monkeypatch.setenv("EDGAR_USER_AGENT", "Test User test@test.com")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-anthropic-key")
    from wsd.config import Settings
    return Settings()


def test_rate_limiter_allows_single_acquire():
    from wsd.utils import RateLimiter
    limiter = RateLimiter(rate=10)
    limiter.acquire()  # should not raise or block meaningfully


def test_retry_succeeds_on_first_attempt():
    from wsd.utils import retry
    call_count = 0

    @retry(attempts=3, backoff=0.01)
    def succeeds():
        nonlocal call_count
        call_count += 1
        return "ok"

    assert succeeds() == "ok"
    assert call_count == 1


def test_retry_retries_on_request_exception():
    from wsd.utils import retry
    call_count = 0

    @retry(attempts=3, backoff=0.01)
    def fails_twice():
        nonlocal call_count
        call_count += 1
        if call_count < 3:
            raise requests.RequestException("connection error")
        return "ok"

    assert fails_twice() == "ok"
    assert call_count == 3


def test_retry_raises_after_max_attempts():
    from wsd.utils import retry
    call_count = 0

    @retry(attempts=3, backoff=0.01)
    def always_fails():
        nonlocal call_count
        call_count += 1
        raise requests.RequestException("always fails")

    with pytest.raises(requests.RequestException):
        always_fails()
    assert call_count == 3


def test_edgar_get_returns_json(settings, mocker):
    mock_response = MagicMock()
    mock_response.json.return_value = {"cik": "0000320193"}
    mock_response.raise_for_status = MagicMock()
    mocker.patch("requests.get", return_value=mock_response)
    mocker.patch("wsd.utils._get_limiter", return_value=MagicMock())
    from wsd.utils import edgar_get
    result = edgar_get("https://data.sec.gov/submissions/CIK0000320193.json", settings)
    assert result == {"cik": "0000320193"}


def test_edgar_get_includes_user_agent_header(settings, mocker):
    mock_response = MagicMock()
    mock_response.json.return_value = {}
    mock_response.raise_for_status = MagicMock()
    mock_get = mocker.patch("requests.get", return_value=mock_response)
    mocker.patch("wsd.utils._get_limiter", return_value=MagicMock())
    from wsd.utils import edgar_get
    edgar_get("https://data.sec.gov/submissions/CIK0000320193.json", settings)
    _, kwargs = mock_get.call_args
    assert kwargs["headers"]["User-Agent"] == "Test User test@test.com"
