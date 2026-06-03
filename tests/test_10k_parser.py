import pytest

FILING = {
    "id": "uuid-filing-1",
    "company_id": "uuid-company-1",
    "cik": "0000320193",
    "accession_number": "0000320193-24-000003",
    "form_type": "10-K",
    "filed_date": "2024-02-15",
}

HTML_10K_EPS = """<html><body>
<ix:nonFraction name="us-gaap:EarningsPerShareBasic" contextRef="current">6.40</ix:nonFraction>
<ix:nonFraction name="us-gaap:EarningsPerShareBasic" contextRef="prior">5.80</ix:nonFraction>
<div id="mda">We expect continued growth in fiscal 2025.</div>
</body></html>"""


@pytest.fixture(autouse=True)
def set_env(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://test.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_KEY", "test-key")
    monkeypatch.setenv("EDGAR_USER_AGENT", "Test test@test.com")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")


def test_10k_earnings_beat(monkeypatch):
    from wsd.extraction.parsers import filing_10k
    monkeypatch.setattr(filing_10k, "extract_guidance_event", lambda *a: None)
    from wsd.config import Settings
    events = filing_10k.TenKParser().parse(FILING, HTML_10K_EPS, Settings())
    earnings = [e for e in events if "earnings" in e["event_code"]]
    assert earnings[0]["event_code"] == "earnings_beat"
    assert earnings[0]["extracted_by"] == "rules"


def test_10k_mda_guidance_via_claude(monkeypatch):
    from wsd.extraction.parsers import filing_10k, filing_10q
    monkeypatch.setattr(filing_10q, "extract_guidance_event",
                        lambda *a: {"event_code": "guidance_raised",
                                    "sentiment": "positive", "magnitude": None,
                                    "details": {"metric": "revenue"}})
    from wsd.config import Settings
    events = filing_10k.TenKParser().parse(FILING, HTML_10K_EPS, Settings())
    guidance = [e for e in events if e["event_code"] == "guidance_raised"]
    assert len(guidance) == 1
    assert guidance[0]["extracted_by"] == "claude"


def test_10k_no_xbrl_returns_empty(monkeypatch):
    from wsd.extraction.parsers import filing_10k, filing_10q
    monkeypatch.setattr(filing_10q, "extract_guidance_event", lambda *a: None)
    from wsd.config import Settings
    events = filing_10k.TenKParser().parse(FILING, "<html><p>no data</p></html>", Settings())
    assert events == []
