import pytest
from unittest.mock import MagicMock


@pytest.fixture
def settings(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://test.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_KEY", "test-key")
    monkeypatch.setenv("EDGAR_USER_AGENT", "Test User test@test.com")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    from wsd.config import Settings
    return Settings()


FILING_FORM4 = {
    "id": "f1", "company_id": "c1", "cik": "0000320193",
    "accession_number": "0000320193-24-000001",
    "form_type": "4", "filed_date": "2024-01-15",
}
FILING_8K = {
    "id": "f2", "company_id": "c1", "cik": "0000320193",
    "accession_number": "0000320193-24-000002",
    "form_type": "8-K", "filed_date": "2024-01-20",
}


def _mock_client(filings, total=10):
    mock = MagicMock()
    # chain for fetching unparsed filings
    mock.table.return_value.select.return_value.eq.return_value \
        .order.return_value.limit.return_value.execute.return_value.data = filings
    # chain for count query
    mock.table.return_value.select.return_value.eq.return_value \
        .execute.return_value.count = total
    return mock


def test_orchestrator_dispatches_form4_to_correct_parser(settings, mocker):
    mocker.patch("wsd.extraction.run.db.get_client", return_value=_mock_client([FILING_FORM4]))
    mocker.patch("wsd.extraction.run.download_filing", return_value="<xml/>")
    mock_form4 = mocker.patch("wsd.extraction.run.Form4Parser")
    mock_form4.return_value.parse.return_value = []
    mocker.patch("wsd.extraction.run.db.upsert_events", return_value=0)
    mocker.patch("wsd.extraction.run.db.mark_filing_parsed")

    from wsd.extraction.run import run_extraction
    run_extraction(settings, batch_size=1)
    mock_form4.return_value.parse.assert_called_once()


def test_orchestrator_marks_filing_parsed_after_success(settings, mocker):
    mocker.patch("wsd.extraction.run.db.get_client", return_value=_mock_client([FILING_FORM4]))
    mocker.patch("wsd.extraction.run.download_filing", return_value="<xml/>")
    mocker.patch("wsd.extraction.run.Form4Parser").return_value.parse.return_value = []
    mocker.patch("wsd.extraction.run.db.upsert_events", return_value=0)
    mock_mark = mocker.patch("wsd.extraction.run.db.mark_filing_parsed")

    from wsd.extraction.run import run_extraction
    run_extraction(settings, batch_size=1)
    mock_mark.assert_called_once_with("f1", settings)


def test_orchestrator_skips_filing_when_download_fails(settings, mocker):
    mocker.patch("wsd.extraction.run.db.get_client", return_value=_mock_client([FILING_FORM4]))
    mocker.patch("wsd.extraction.run.download_filing", return_value=None)
    mock_mark = mocker.patch("wsd.extraction.run.db.mark_filing_parsed")

    from wsd.extraction.run import run_extraction
    run_extraction(settings, batch_size=1)
    mock_mark.assert_not_called()


def test_orchestrator_returns_correct_counts(settings, mocker):
    mocker.patch("wsd.extraction.run.db.get_client",
                 return_value=_mock_client([FILING_FORM4, FILING_8K], total=100))
    mocker.patch("wsd.extraction.run.download_filing", return_value="<xml/>")
    mocker.patch("wsd.extraction.run.Form4Parser").return_value.parse.return_value = [{"event": 1}]
    mocker.patch("wsd.extraction.run.EightKParser").return_value.parse.return_value = []
    mocker.patch("wsd.extraction.run.db.upsert_events", return_value=0)
    mocker.patch("wsd.extraction.run.db.mark_filing_parsed")

    from wsd.extraction.run import run_extraction
    result = run_extraction(settings, batch_size=2)
    assert result["processed"] == 2
    assert result["errors"] == 0
