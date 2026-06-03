import os
import pytest

FILING = {
    "id": "uuid-filing-1",
    "company_id": "uuid-company-1",
    "cik": "0000320193",
    "accession_number": "0000320193-24-000001",
    "form_type": "8-K",
    "filed_date": "2024-01-15",
}

HTML_WITH_502 = """
<html><body>
<p>Item 5.02 Departure of Directors or Certain Officers</p>
<p>The Company announces that John Smith has been appointed as CEO effective January 15, 2024.</p>
<p>Item 9.01 Financial Statements and Exhibits</p>
<p>Exhibit 99.1</p>
</body></html>
"""

HTML_WITH_201 = """
<html><body>
<p>Item 2.01 Completion of Acquisition or Disposition of Assets</p>
<p>The Company completed its acquisition of Target Corp for $500 million.</p>
</body></html>
"""

HTML_ONLY_901 = """
<html><body>
<p>Item 9.01 Financial Statements and Exhibits</p>
<p>Exhibit 99.1 Press Release</p>
</body></html>
"""


@pytest.fixture(autouse=True)
def set_env(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://test.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_KEY", "test-key")
    monkeypatch.setenv("EDGAR_USER_AGENT", "Test test@test.com")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")


def test_8k_dispatches_502_to_claude(monkeypatch):
    from wsd.extraction.parsers import filing_8k
    called_with = []
    monkeypatch.setattr(
        filing_8k, "extract_8k_event",
        lambda text, settings: called_with.append(text) or {
            "event_code": "ceo_change",
            "sentiment": "neutral",
            "magnitude": None,
            "details": {"incoming_name": "John Smith"},
        }
    )
    from wsd.config import Settings
    events = filing_8k.EightKParser().parse(FILING, HTML_WITH_502, Settings())
    assert len(called_with) == 1
    assert len(events) == 1
    assert events[0]["event_code"] == "ceo_change"
    assert events[0]["extracted_by"] == "claude"


def test_8k_skips_901_item(monkeypatch):
    from wsd.extraction.parsers import filing_8k
    monkeypatch.setattr(filing_8k, "extract_8k_event",
                        lambda *a: {"event_code": "ceo_change", "sentiment": "neutral",
                                    "magnitude": None, "details": {}})
    from wsd.config import Settings
    events = filing_8k.EightKParser().parse(FILING, HTML_ONLY_901, Settings())
    assert events == []


def test_8k_claude_returns_none_yields_no_event(monkeypatch):
    from wsd.extraction.parsers import filing_8k
    monkeypatch.setattr(filing_8k, "extract_8k_event", lambda *a: None)
    from wsd.config import Settings
    events = filing_8k.EightKParser().parse(FILING, HTML_WITH_502, Settings())
    assert events == []


def test_8k_event_has_required_fields(monkeypatch):
    from wsd.extraction.parsers import filing_8k
    monkeypatch.setattr(filing_8k, "extract_8k_event",
                        lambda *a: {"event_code": "acquisition_announced",
                                    "sentiment": "positive", "magnitude": 500.0,
                                    "details": {"target_name": "Target Corp"}})
    from wsd.config import Settings
    events = filing_8k.EightKParser().parse(FILING, HTML_WITH_201, Settings())
    assert len(events) == 1
    e = events[0]
    assert e["filing_id"] == FILING["id"]
    assert e["company_id"] == FILING["company_id"]
    assert e["filed_date"] == FILING["filed_date"]
    assert e["extracted_by"] == "claude"
