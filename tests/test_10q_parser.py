import pytest

FILING = {
    "id": "uuid-filing-1",
    "company_id": "uuid-company-1",
    "cik": "0000320193",
    "accession_number": "0000320193-24-000002",
    "form_type": "10-Q",
    "filed_date": "2024-01-20",
}

HTML_EPS_BEAT = """<html><body>
<ix:nonFraction name="us-gaap:EarningsPerShareBasic" contextRef="current">2.50</ix:nonFraction>
<ix:nonFraction name="us-gaap:EarningsPerShareBasic" contextRef="prior">1.90</ix:nonFraction>
<div id="mda">Management Discussion: We expect revenue to increase in the coming quarter.</div>
</body></html>"""

HTML_EPS_MISS = """<html><body>
<ix:nonFraction name="us-gaap:EarningsPerShareBasic" contextRef="current">1.20</ix:nonFraction>
<ix:nonFraction name="us-gaap:EarningsPerShareBasic" contextRef="prior">1.80</ix:nonFraction>
</body></html>"""

HTML_NO_XBRL = """<html><body><p>No financial data found.</p></body></html>"""


@pytest.fixture(autouse=True)
def set_env(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://test.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_KEY", "test-key")
    monkeypatch.setenv("EDGAR_USER_AGENT", "Test test@test.com")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")


def test_10q_earnings_beat_classification(monkeypatch):
    from wsd.extraction.parsers import filing_10q
    monkeypatch.setattr(filing_10q, "extract_guidance_event", lambda *a: None)
    from wsd.config import Settings
    events = filing_10q.TenQParser().parse(FILING, HTML_EPS_BEAT, Settings())
    earnings = [e for e in events if e["event_code"] in ("earnings_beat", "earnings_miss", "earnings_inline")]
    assert len(earnings) == 1
    assert earnings[0]["event_code"] == "earnings_beat"
    assert earnings[0]["extracted_by"] == "rules"


def test_10q_earnings_miss_classification(monkeypatch):
    from wsd.extraction.parsers import filing_10q
    monkeypatch.setattr(filing_10q, "extract_guidance_event", lambda *a: None)
    from wsd.config import Settings
    events = filing_10q.TenQParser().parse(FILING, HTML_EPS_MISS, Settings())
    earnings = [e for e in events if "earnings" in e["event_code"]]
    assert earnings[0]["event_code"] == "earnings_miss"
    assert earnings[0]["sentiment"] == "negative"


def test_10q_no_xbrl_returns_empty(monkeypatch):
    from wsd.extraction.parsers import filing_10q
    monkeypatch.setattr(filing_10q, "extract_guidance_event", lambda *a: None)
    from wsd.config import Settings
    events = filing_10q.TenQParser().parse(FILING, HTML_NO_XBRL, Settings())
    assert events == []


def test_10q_mda_section_sent_to_claude(monkeypatch):
    from wsd.extraction.parsers import filing_10q
    called = []
    monkeypatch.setattr(filing_10q, "extract_guidance_event",
                        lambda text, s: called.append(text) or {
                            "event_code": "guidance_raised",
                            "sentiment": "positive",
                            "magnitude": None,
                            "details": {"metric": "revenue"},
                        })
    from wsd.config import Settings
    events = filing_10q.TenQParser().parse(FILING, HTML_EPS_BEAT, Settings())
    assert len(called) == 1
    guidance = [e for e in events if e["event_code"] == "guidance_raised"]
    assert len(guidance) == 1
    assert guidance[0]["extracted_by"] == "claude"


def test_10q_earnings_details_shape(monkeypatch):
    from wsd.extraction.parsers import filing_10q
    monkeypatch.setattr(filing_10q, "extract_guidance_event", lambda *a: None)
    from wsd.config import Settings
    events = filing_10q.TenQParser().parse(FILING, HTML_EPS_BEAT, Settings())
    e = next(e for e in events if "earnings" in e["event_code"])
    assert "eps_current" in e["details"]
    assert "eps_prior" in e["details"]
    assert "beat_pct" in e["details"]
