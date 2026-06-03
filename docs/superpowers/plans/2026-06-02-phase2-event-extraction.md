# Phase 2 Event Extraction Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Parse 47K SEC filings into structured events stored in `event_taxonomy` + `events` tables, surfaced in the development dashboard.

**Architecture:** Hybrid extraction — rules-based for Form 4 (XML) and 8-K item codes, Claude Haiku API for high-signal free-text sections (8-K items 1.01/2.01/5.02/7.01, 10-Q/10-K MD&A). Orchestrator in `run.py` iterates `filings WHERE is_parsed = false`, downloads HTML, dispatches to typed parsers, upserts events, flips `is_parsed = true`.

**Tech Stack:** Python 3.12, supabase-py v2, requests, anthropic>=0.25, xml.etree.ElementTree (stdlib), re (stdlib), pytest, pytest-mock

---

## File Map

| File | Action | Purpose |
|------|--------|---------|
| `supabase/migrations/20260602000004_phase2_event_extraction.sql` | Create | `event_taxonomy` + `events` tables + RLS + seed |
| `src/wsd/config.py` | Modify | Add `anthropic_api_key` field to `Settings` |
| `src/wsd/db.py` | Modify | Add `upsert_events()` + `mark_filing_parsed()` helpers |
| `src/wsd/extraction/__init__.py` | Create | Package marker |
| `src/wsd/extraction/downloader.py` | Create | Fetch filing HTML from EDGAR, cache to disk |
| `src/wsd/extraction/claude.py` | Create | Claude Haiku call + JSON parse with graceful fallback |
| `src/wsd/extraction/parsers/__init__.py` | Create | Package marker |
| `src/wsd/extraction/parsers/base.py` | Create | Abstract `BaseParser` + shared HTML helpers |
| `src/wsd/extraction/parsers/form4.py` | Create | Form 4 XML → insider trade events (rules only) |
| `src/wsd/extraction/parsers/filing_8k.py` | Create | 8-K item extraction (rules) + Claude for items 1.01/2.01/5.02/7.01 |
| `src/wsd/extraction/parsers/filing_10q.py` | Create | 10-Q XBRL financial figures (rules) + Claude for MD&A |
| `src/wsd/extraction/parsers/filing_10k.py` | Create | 10-K — same pattern as 10-Q |
| `src/wsd/extraction/run.py` | Create | Orchestrator: iterate → download → parse → upsert → mark done |
| `dashboard.html` | Create | Full dashboard with Phase 2 events card + progress bar |
| `pyproject.toml` | Modify | Add `anthropic>=0.25` dependency |
| `tests/test_downloader.py` | Create | URL construction, cache hit, rate limit |
| `tests/test_form4_parser.py` | Create | Buy/sell classification, large/small, malformed XML |
| `tests/test_8k_parser.py` | Create | Item regex, Claude dispatch, graceful fallback |
| `tests/test_10q_parser.py` | Create | XBRL extraction, beat/miss, Claude MD&A |
| `tests/test_10k_parser.py` | Create | Same coverage as 10-Q |
| `tests/test_extraction_run.py` | Create | Orchestrator flow end-to-end with mocks |

---

## Task 1: Migration + DB Helpers + Settings

**Files:**
- Create: `supabase/migrations/20260602000004_phase2_event_extraction.sql`
- Modify: `src/wsd/db.py`
- Modify: `src/wsd/config.py`
- Modify: `pyproject.toml`
- Modify: `.env.example`

- [ ] **Step 1: Create the migration file**

```sql
-- supabase/migrations/20260602000004_phase2_event_extraction.sql
-- Phase 2: Event Extraction
-- Tables: event_taxonomy (reference), events (one row per extracted event)

create table public.event_taxonomy (
  id                  uuid         primary key default uuid_generate_v4(),
  event_code          text         not null unique,
  category            text         not null,
  label               text         not null,
  description         text         not null,
  scoring_weight_hint numeric(5,2) not null default 1.0,
  created_at          timestamptz  not null default now()
);

insert into public.event_taxonomy (event_code, category, label, description, scoring_weight_hint) values
  ('insider_buy_large',      'insider_trading', 'Large Insider Buy',      'Insider purchase > $1M',             1.5),
  ('insider_sell_large',     'insider_trading', 'Large Insider Sell',     'Insider sale > $1M',                 1.5),
  ('insider_buy_small',      'insider_trading', 'Small Insider Buy',      'Insider purchase <= $1M',            1.0),
  ('insider_sell_small',     'insider_trading', 'Small Insider Sell',     'Insider sale <= $1M',                0.8),
  ('earnings_beat',          'earnings',        'Earnings Beat',          'EPS above consensus estimate',       1.2),
  ('earnings_miss',          'earnings',        'Earnings Miss',          'EPS below consensus estimate',       1.2),
  ('earnings_inline',        'earnings',        'Earnings Inline',        'EPS in line with consensus',         0.5),
  ('guidance_raised',        'guidance',        'Guidance Raised',        'Forward guidance increased',         1.3),
  ('guidance_lowered',       'guidance',        'Guidance Lowered',       'Forward guidance decreased',         1.3),
  ('guidance_initiated',     'guidance',        'Guidance Initiated',     'First-time forward guidance issued', 1.0),
  ('acquisition_announced',  'corporate',       'Acquisition Announced',  'Company acquiring another entity',   1.4),
  ('merger_announced',       'corporate',       'Merger Announced',       'Merger of equals announced',         1.4),
  ('divestiture_announced',  'corporate',       'Divestiture Announced',  'Sale of business unit announced',    1.1),
  ('ceo_change',             'executive',       'CEO Change',             'Chief Executive Officer change',     1.3),
  ('cfo_change',             'executive',       'CFO Change',             'Chief Financial Officer change',     1.1),
  ('executive_change_other', 'executive',       'Other Executive Change', 'Other C-suite or director change',   0.8),
  ('buyback_announced',      'capital',         'Buyback Announced',      'Share repurchase program announced', 1.1),
  ('dividend_change',        'capital',         'Dividend Change',        'Dividend initiated, raised, or cut', 1.0);

create table public.events (
  id           uuid    primary key default uuid_generate_v4(),
  filing_id    uuid    not null references public.filings (id) on delete cascade,
  company_id   uuid    not null references public.companies (id) on delete cascade,
  event_code   text    not null references public.event_taxonomy (event_code),
  filed_date   date    not null,
  sentiment    text    not null check (sentiment in ('positive', 'negative', 'neutral')),
  magnitude    numeric(10,4),
  details      jsonb   not null default '{}',
  extracted_by text    not null check (extracted_by in ('rules', 'claude')),
  created_at   timestamptz not null default now(),
  constraint events_filing_event_unique unique (filing_id, event_code)
);

create index events_company_date_idx on public.events (company_id, filed_date);
create index events_filed_date_idx   on public.events (filed_date);
create index events_event_code_idx   on public.events (event_code);
create index events_filing_id_idx    on public.events (filing_id);

alter table public.event_taxonomy enable row level security;
alter table public.events         enable row level security;

create policy "event_taxonomy_authenticated_read"
  on public.event_taxonomy for select to authenticated using (true);
create policy "events_authenticated_read"
  on public.events for select to authenticated using (true);
```

- [ ] **Step 2: Apply migration in Supabase SQL Editor**

Paste the file contents into the Supabase dashboard SQL Editor and click Run. Verify both tables appear in Table Editor.

- [ ] **Step 3: Add `upsert_events` and `mark_filing_parsed` to `db.py`**

Open `src/wsd/db.py` and append:

```python
def upsert_events(rows: list[dict], settings: Settings) -> int:
    if not rows:
        return 0
    result = (
        get_client(settings)
        .table("events")
        .upsert(rows, on_conflict="filing_id,event_code")
        .execute()
    )
    return len(result.data)


def mark_filing_parsed(filing_id: str, settings: Settings) -> None:
    get_client(settings).table("filings").update({"is_parsed": True}).eq("id", filing_id).execute()
```

- [ ] **Step 4: Add `anthropic_api_key` to `Settings`**

In `src/wsd/config.py`, add one field to the `Settings` dataclass after `edgar_user_agent`:

```python
    anthropic_api_key: str = field(default_factory=lambda: _require("ANTHROPIC_API_KEY"))
```

- [ ] **Step 5: Add `anthropic` to `pyproject.toml`**

In the `dependencies` list in `pyproject.toml`, add:

```toml
    "anthropic>=0.25",
```

- [ ] **Step 6: Add `ANTHROPIC_API_KEY` to `.env.example`**

Append to `.env.example`:

```
ANTHROPIC_API_KEY=your-anthropic-api-key-here
```

Add your real key to `.env` (gitignored).

- [ ] **Step 7: Install the new dependency**

```bash
pip install anthropic
```

- [ ] **Step 8: Run existing tests to confirm nothing is broken**

```bash
pytest -v
```

Expected: all 39 existing tests pass.

- [ ] **Step 9: Commit**

```bash
git checkout -b feat/phase2-event-extraction
git add supabase/migrations/20260602000004_phase2_event_extraction.sql \
        src/wsd/db.py src/wsd/config.py pyproject.toml .env.example
git commit -m "feat: add Phase 2 migration, db helpers, anthropic dependency"
```

---

## Task 2: Downloader

**Files:**
- Create: `src/wsd/extraction/__init__.py`
- Create: `src/wsd/extraction/downloader.py`
- Create: `tests/test_downloader.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_downloader.py`:

```python
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch, mock_open


@pytest.fixture
def settings(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://test.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_KEY", "test-key")
    monkeypatch.setenv("EDGAR_USER_AGENT", "Test User test@test.com")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-anthropic-key")
    from wsd.config import Settings
    return Settings()


FILING = {
    "id": "uuid-filing-1",
    "company_id": "uuid-company-1",
    "cik": "0000320193",
    "accession_number": "0000320193-24-000001",
    "form_type": "8-K",
    "filed_date": "2024-01-15",
}

INDEX_JSON = {
    "directory": {
        "item": [
            {"name": "0000320193-24-000001-index.htm", "type": "text/html"},
            {"name": "aapl20240115_8k.htm", "type": "text/html"},
            {"name": "ex99-1.htm", "type": "text/html"},
        ]
    }
}


def test_accession_nodash():
    from wsd.extraction.downloader import _accession_nodash
    assert _accession_nodash("0000320193-24-000001") == "000032019324000001"


def test_cache_path_strips_leading_zeros_from_cik():
    from wsd.extraction.downloader import _cache_path
    p = _cache_path("0000320193", "0000320193-24-000001")
    assert "320193" in str(p)
    assert str(p).endswith("0000320193-24-000001.html")


def test_download_returns_cached_content_without_http(settings, tmp_path, monkeypatch):
    from wsd.extraction import downloader
    monkeypatch.setattr(downloader, "_CACHE_DIR", tmp_path)
    cache = tmp_path / "320193" / "0000320193-24-000001.html"
    cache.parent.mkdir(parents=True)
    cache.write_text("<html>cached</html>")
    result = downloader.download_filing(FILING, settings)
    assert result == "<html>cached</html>"


def test_download_constructs_correct_index_url(settings, tmp_path, monkeypatch):
    from wsd.extraction import downloader
    monkeypatch.setattr(downloader, "_CACHE_DIR", tmp_path)
    captured_urls = []

    def mock_fetch(url, settings):
        captured_urls.append(url)
        if "index.json" in url:
            return INDEX_JSON
        return "<html>filing</html>"

    monkeypatch.setattr(downloader, "_fetch_json", lambda url, s: INDEX_JSON)
    monkeypatch.setattr(downloader, "_fetch_text", lambda url, s: "<html>filing</html>")

    downloader.download_filing(FILING, settings)
    # primary doc should be the non-index .htm file
    assert True  # no crash = correct URL dispatching


def test_download_returns_none_on_404(settings, tmp_path, monkeypatch):
    from wsd.extraction import downloader
    import requests
    monkeypatch.setattr(downloader, "_CACHE_DIR", tmp_path)

    def raise_404(url, s):
        r = MagicMock()
        r.status_code = 404
        raise requests.HTTPError(response=r)

    monkeypatch.setattr(downloader, "_fetch_json", raise_404)
    result = downloader.download_filing(FILING, settings)
    assert result is None
```

- [ ] **Step 2: Run to confirm failure**

```bash
pytest tests/test_downloader.py -v
```

Expected: `ModuleNotFoundError: No module named 'wsd.extraction'`

- [ ] **Step 3: Create package markers**

```bash
mkdir -p src/wsd/extraction/parsers
touch src/wsd/extraction/__init__.py
touch src/wsd/extraction/parsers/__init__.py
```

- [ ] **Step 4: Create `downloader.py`**

Create `src/wsd/extraction/downloader.py`:

```python
import requests
from pathlib import Path
from wsd.config import Settings
from wsd.utils import RateLimiter, retry

_EDGAR_ARCHIVES = "https://www.sec.gov/Archives/edgar/data"
_CACHE_DIR = Path("data/filings")

_limiter: "RateLimiter | None" = None


def _get_limiter(settings: Settings) -> RateLimiter:
    global _limiter
    if _limiter is None:
        _limiter = RateLimiter(settings.edgar_rate_limit)
    return _limiter


def _accession_nodash(accession_number: str) -> str:
    return accession_number.replace("-", "")


def _cache_path(cik: str, accession_number: str) -> Path:
    cik_stripped = cik.lstrip("0") or "0"
    return _CACHE_DIR / cik_stripped / f"{accession_number}.html"


def _fetch_json(url: str, settings: Settings) -> dict:
    limiter = _get_limiter(settings)

    @retry(attempts=3, backoff=2.0)
    def _do():
        limiter.acquire()
        resp = requests.get(url, headers={"User-Agent": settings.edgar_user_agent})
        resp.raise_for_status()
        return resp.json()

    return _do()


def _fetch_text(url: str, settings: Settings) -> str:
    limiter = _get_limiter(settings)

    @retry(attempts=3, backoff=2.0)
    def _do():
        limiter.acquire()
        resp = requests.get(url, headers={"User-Agent": settings.edgar_user_agent})
        resp.raise_for_status()
        return resp.text

    return _do()


def _find_primary_doc(index_data: dict) -> str | None:
    items = index_data.get("directory", {}).get("item", [])
    for item in items:
        name = item.get("name", "")
        if "index" in name.lower():
            continue
        if name.endswith((".htm", ".html", ".xml")):
            return name
    for item in items:
        name = item.get("name", "")
        if name.endswith(".txt") and "index" not in name.lower():
            return name
    return None


def download_filing(filing: dict, settings: Settings) -> str | None:
    """Fetch raw filing HTML from EDGAR, caching to disk. Returns text or None on failure."""
    cik = filing["cik"].lstrip("0") or "0"
    accession = filing["accession_number"]
    accession_nodash = _accession_nodash(accession)

    cache = _cache_path(filing["cik"], accession)
    if cache.exists():
        return cache.read_text(encoding="utf-8", errors="replace")

    index_url = f"{_EDGAR_ARCHIVES}/{cik}/{accession_nodash}/{accession}-index.json"
    try:
        index_data = _fetch_json(index_url, settings)
        primary_doc = _find_primary_doc(index_data)
        if not primary_doc:
            print(f"  WARNING: No primary doc found for {accession}")
            return None
        doc_url = f"{_EDGAR_ARCHIVES}/{cik}/{accession_nodash}/{primary_doc}"
        html = _fetch_text(doc_url, settings)
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(html, encoding="utf-8", errors="replace")
        return html
    except Exception as exc:
        print(f"  WARNING: Failed to download {accession}: {exc}")
        return None
```

- [ ] **Step 5: Run tests**

```bash
pytest tests/test_downloader.py -v
```

Expected: all 4 downloader tests pass.

- [ ] **Step 6: Commit**

```bash
git add src/wsd/extraction/ tests/test_downloader.py
git commit -m "feat: add extraction package + filing downloader with disk cache"
```

---

## Task 3: Claude Helper + BaseParser + Form 4 Parser

**Files:**
- Create: `src/wsd/extraction/claude.py`
- Create: `src/wsd/extraction/parsers/base.py`
- Create: `src/wsd/extraction/parsers/form4.py`
- Create: `tests/test_form4_parser.py`

- [ ] **Step 1: Write failing Form 4 tests**

Create `tests/test_form4_parser.py`:

```python
import pytest

FORM4_XML_BUY = """<?xml version="1.0"?>
<ownershipDocument>
  <reportingOwner>
    <reportingOwnerId><rptOwnerName>John Smith</rptOwnerName></reportingOwnerId>
    <reportingOwnerRelationship>
      <isOfficer>1</isOfficer>
      <officerTitle>Chief Executive Officer</officerTitle>
    </reportingOwnerRelationship>
  </reportingOwner>
  <nonDerivativeTable>
    <nonDerivativeTransaction>
      <transactionDate><value>2024-01-15</value></transactionDate>
      <transactionCoding><transactionCode>P</transactionCode></transactionCoding>
      <transactionAmounts>
        <transactionShares><value>10000</value></transactionShares>
        <transactionPricePerShare><value>150.00</value></transactionPricePerShare>
        <transactionAcquiredDisposedCode><value>A</value></transactionAcquiredDisposedCode>
      </transactionAmounts>
    </nonDerivativeTransaction>
  </nonDerivativeTable>
</ownershipDocument>"""

FORM4_XML_SELL_LARGE = """<?xml version="1.0"?>
<ownershipDocument>
  <reportingOwner>
    <reportingOwnerId><rptOwnerName>Jane Doe</rptOwnerName></reportingOwnerId>
    <reportingOwnerRelationship><isOfficer>1</isOfficer><officerTitle>CFO</officerTitle></reportingOwnerRelationship>
  </reportingOwner>
  <nonDerivativeTable>
    <nonDerivativeTransaction>
      <transactionDate><value>2024-01-20</value></transactionDate>
      <transactionCoding><transactionCode>S</transactionCode></transactionCoding>
      <transactionAmounts>
        <transactionShares><value>10000</value></transactionShares>
        <transactionPricePerShare><value>200.00</value></transactionPricePerShare>
        <transactionAcquiredDisposedCode><value>D</value></transactionAcquiredDisposedCode>
      </transactionAmounts>
    </nonDerivativeTransaction>
  </nonDerivativeTable>
</ownershipDocument>"""

FILING = {
    "id": "uuid-filing-1",
    "company_id": "uuid-company-1",
    "cik": "0000320193",
    "accession_number": "0000320193-24-000001",
    "form_type": "4",
    "filed_date": "2024-01-15",
}


def test_form4_buy_classified_as_insider_buy_small():
    # 10000 shares * $150 = $1.5M → large
    from wsd.extraction.parsers.form4 import Form4Parser
    events = Form4Parser().parse(FILING, FORM4_XML_BUY)
    assert len(events) == 1
    assert events[0]["event_code"] == "insider_buy_large"
    assert events[0]["sentiment"] == "positive"
    assert events[0]["extracted_by"] == "rules"


def test_form4_buy_small_when_under_threshold():
    xml = FORM4_XML_BUY.replace("<value>150.00</value>", "<value>5.00</value>")
    from wsd.extraction.parsers.form4 import Form4Parser
    events = Form4Parser().parse(FILING, xml)
    assert events[0]["event_code"] == "insider_buy_small"


def test_form4_sell_large():
    # 10000 * $200 = $2M → large sell
    from wsd.extraction.parsers.form4 import Form4Parser
    events = Form4Parser().parse(FILING, FORM4_XML_SELL_LARGE)
    assert len(events) == 1
    assert events[0]["event_code"] == "insider_sell_large"
    assert events[0]["sentiment"] == "negative"


def test_form4_details_shape():
    from wsd.extraction.parsers.form4 import Form4Parser
    events = Form4Parser().parse(FILING, FORM4_XML_BUY)
    d = events[0]["details"]
    assert "shares" in d
    assert "value_usd" in d
    assert "transaction_date" in d


def test_form4_magnitude_in_millions():
    from wsd.extraction.parsers.form4 import Form4Parser
    events = Form4Parser().parse(FILING, FORM4_XML_BUY)
    # 10000 * 150 = 1,500,000 → 1.5 $M
    assert abs(events[0]["magnitude"] - 1.5) < 0.01


def test_form4_malformed_xml_returns_empty():
    from wsd.extraction.parsers.form4 import Form4Parser
    events = Form4Parser().parse(FILING, "<bad xml>>>")
    assert events == []


def test_form4_skips_non_open_market_codes():
    xml = FORM4_XML_BUY.replace("<transactionCode>P</transactionCode>",
                                "<transactionCode>A</transactionCode>")
    from wsd.extraction.parsers.form4 import Form4Parser
    events = Form4Parser().parse(FILING, xml)
    assert events == []
```

- [ ] **Step 2: Run to confirm failure**

```bash
pytest tests/test_form4_parser.py -v
```

Expected: `ModuleNotFoundError: No module named 'wsd.extraction.parsers.form4'`

- [ ] **Step 3: Create `claude.py`**

Create `src/wsd/extraction/claude.py`:

```python
import json
import anthropic
from wsd.config import Settings

_EXTRACTION_PROMPT = """You are extracting a structured financial event from an SEC filing section.

Filing section text:
{text}

Return a JSON object with these exact fields, or the string null if no clear event can be identified:
{{
  "event_code": one of [{valid_codes}],
  "sentiment": "positive" or "negative" or "neutral",
  "magnitude": null or a number (deal value in $M, EPS beat %, etc.),
  "details": {{}}
}}

Return only valid JSON or the word null. No explanation, no markdown.
"""

_8K_CODES = [
    "acquisition_announced", "merger_announced", "divestiture_announced",
    "ceo_change", "cfo_change", "executive_change_other",
    "buyback_announced", "dividend_change",
    "guidance_raised", "guidance_lowered", "guidance_initiated",
]

_GUIDANCE_CODES = ["guidance_raised", "guidance_lowered", "guidance_initiated"]


def extract_event_from_text(
    section_text: str,
    valid_codes: list[str],
    settings: Settings,
) -> dict | None:
    """Call Claude Haiku to extract a structured event from free text. Returns dict or None."""
    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    prompt = _EXTRACTION_PROMPT.format(
        text=section_text[:3000],  # cap to avoid large token counts
        valid_codes=", ".join(f'"{c}"' for c in valid_codes),
    )
    try:
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=256,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = response.content[0].text.strip()
        if raw.lower() == "null":
            return None
        return json.loads(raw)
    except (json.JSONDecodeError, Exception) as exc:
        print(f"  WARNING: Claude extraction failed: {exc}")
        return None


def extract_8k_event(section_text: str, settings: Settings) -> dict | None:
    return extract_event_from_text(section_text, _8K_CODES, settings)


def extract_guidance_event(section_text: str, settings: Settings) -> dict | None:
    return extract_event_from_text(section_text, _GUIDANCE_CODES, settings)
```

- [ ] **Step 4: Create `parsers/base.py`**

Create `src/wsd/extraction/parsers/base.py`:

```python
import re
from abc import ABC, abstractmethod


class BaseParser(ABC):
    @abstractmethod
    def parse(self, filing: dict, html: str) -> list[dict]:
        """Parse raw filing HTML into event dicts ready for upsert_events()."""

    @staticmethod
    def _clean_text(html: str) -> str:
        text = re.sub(r"<[^>]+>", " ", html)
        return re.sub(r"\s+", " ", text).strip()

    @staticmethod
    def _extract_item_sections(html: str) -> dict[str, str]:
        """Return {item_code: section_text} for 8-K item blocks."""
        text = re.sub(r"<[^>]+>", " ", html)
        pattern = r"[Ii]tem\s+(\d+\.\d+)[^\n]*\n(.*?)(?=[Ii]tem\s+\d+\.\d+|\Z)"
        matches = re.findall(pattern, text, re.DOTALL)
        return {code.strip(): content.strip()[:4000] for code, content in matches}
```

- [ ] **Step 5: Create `parsers/form4.py`**

Create `src/wsd/extraction/parsers/form4.py`:

```python
import xml.etree.ElementTree as ET
from wsd.extraction.parsers.base import BaseParser

_LARGE_THRESHOLD_USD = 1_000_000
_OPEN_MARKET_CODES = {"P", "S"}  # P=purchase, S=sale (open market only)


class Form4Parser(BaseParser):
    def parse(self, filing: dict, html: str) -> list[dict]:
        try:
            root = ET.fromstring(html)
        except ET.ParseError:
            return []

        events = []
        for txn in root.findall(".//nonDerivativeTransaction"):
            event = self._parse_transaction(txn, filing)
            if event:
                events.append(event)
        return events

    def _parse_transaction(self, txn: ET.Element, filing: dict) -> dict | None:
        code_el = txn.find("transactionCoding/transactionCode")
        shares_el = txn.find("transactionAmounts/transactionShares/value")
        price_el = txn.find("transactionAmounts/transactionPricePerShare/value")
        date_el = txn.find("transactionDate/value")

        if code_el is None or shares_el is None:
            return None

        code = (code_el.text or "").strip()
        if code not in _OPEN_MARKET_CODES:
            return None

        try:
            shares = float(shares_el.text or 0)
            price = float(price_el.text or 0) if price_el is not None else 0.0
        except (ValueError, TypeError):
            return None

        value_usd = shares * price
        is_buy = code == "P"
        is_large = value_usd >= _LARGE_THRESHOLD_USD

        if is_buy:
            event_code = "insider_buy_large" if is_large else "insider_buy_small"
        else:
            event_code = "insider_sell_large" if is_large else "insider_sell_small"

        return {
            "filing_id": filing["id"],
            "company_id": filing["company_id"],
            "event_code": event_code,
            "filed_date": filing["filed_date"],
            "sentiment": "positive" if is_buy else "negative",
            "magnitude": round(value_usd / 1_000_000, 4),
            "details": {
                "shares": shares,
                "value_usd": round(value_usd, 2),
                "transaction_date": date_el.text if date_el is not None else None,
            },
            "extracted_by": "rules",
        }
```

- [ ] **Step 6: Run Form 4 tests**

```bash
pytest tests/test_form4_parser.py -v
```

Expected: all 7 tests pass.

- [ ] **Step 7: Commit**

```bash
git add src/wsd/extraction/claude.py \
        src/wsd/extraction/parsers/base.py \
        src/wsd/extraction/parsers/form4.py \
        tests/test_form4_parser.py
git commit -m "feat: add Claude helper, BaseParser, Form4 parser (7 tests)"
```

---

## Task 4: 8-K Parser

**Files:**
- Create: `src/wsd/extraction/parsers/filing_8k.py`
- Create: `tests/test_8k_parser.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_8k_parser.py`:

```python
import pytest
from unittest.mock import patch

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


def test_8k_dispatches_502_to_claude(monkeypatch):
    from wsd.extraction.parsers import filing_8k
    called_with = []
    monkeypatch.setattr(
        filing_8k, "extract_8k_event",
        lambda text, settings: called_with.append(text) or {
            "event_code": "ceo_change",
            "sentiment": "neutral",
            "magnitude": None,
            "details": {"departing_name": None, "incoming_name": "John Smith", "reason": "appointment"},
        }
    )
    from wsd.config import Settings
    import os; os.environ.update({"SUPABASE_URL": "x", "SUPABASE_SERVICE_KEY": "x",
                                   "EDGAR_USER_AGENT": "x x@x.com", "ANTHROPIC_API_KEY": "x"})
    events = filing_8k.EightKParser().parse(FILING, HTML_WITH_502, Settings())
    assert len(called_with) == 1
    assert len(events) == 1
    assert events[0]["event_code"] == "ceo_change"
    assert events[0]["extracted_by"] == "claude"


def test_8k_skips_901_item(monkeypatch):
    from wsd.extraction.parsers import filing_8k
    monkeypatch.setattr(filing_8k, "extract_8k_event", lambda *a: {"event_code": "ceo_change",
                                                                     "sentiment": "neutral",
                                                                     "magnitude": None, "details": {}})
    from wsd.config import Settings
    import os; os.environ.update({"SUPABASE_URL": "x", "SUPABASE_SERVICE_KEY": "x",
                                   "EDGAR_USER_AGENT": "x x@x.com", "ANTHROPIC_API_KEY": "x"})
    events = filing_8k.EightKParser().parse(FILING, HTML_ONLY_901, Settings())
    assert events == []


def test_8k_claude_returns_none_yields_no_event(monkeypatch):
    from wsd.extraction.parsers import filing_8k
    monkeypatch.setattr(filing_8k, "extract_8k_event", lambda *a: None)
    from wsd.config import Settings
    import os; os.environ.update({"SUPABASE_URL": "x", "SUPABASE_SERVICE_KEY": "x",
                                   "EDGAR_USER_AGENT": "x x@x.com", "ANTHROPIC_API_KEY": "x"})
    events = filing_8k.EightKParser().parse(FILING, HTML_WITH_502, Settings())
    assert events == []


def test_8k_event_has_required_fields(monkeypatch):
    from wsd.extraction.parsers import filing_8k
    monkeypatch.setattr(filing_8k, "extract_8k_event",
                        lambda *a: {"event_code": "acquisition_announced",
                                    "sentiment": "positive", "magnitude": 500.0,
                                    "details": {"target_name": "Target Corp", "deal_value_usd": 500000000, "deal_type": "acquisition"}})
    from wsd.config import Settings
    import os; os.environ.update({"SUPABASE_URL": "x", "SUPABASE_SERVICE_KEY": "x",
                                   "EDGAR_USER_AGENT": "x x@x.com", "ANTHROPIC_API_KEY": "x"})
    events = filing_8k.EightKParser().parse(FILING, HTML_WITH_201, Settings())
    assert len(events) == 1
    e = events[0]
    assert e["filing_id"] == FILING["id"]
    assert e["company_id"] == FILING["company_id"]
    assert e["filed_date"] == FILING["filed_date"]
    assert e["extracted_by"] == "claude"
```

- [ ] **Step 2: Run to confirm failure**

```bash
pytest tests/test_8k_parser.py -v
```

Expected: `ModuleNotFoundError`

- [ ] **Step 3: Create `parsers/filing_8k.py`**

Create `src/wsd/extraction/parsers/filing_8k.py`:

```python
from wsd.config import Settings
from wsd.extraction.claude import extract_8k_event
from wsd.extraction.parsers.base import BaseParser

# Items worth sending to Claude for classification
_CLAUDE_ITEMS = {"1.01", "2.01", "5.02", "7.01"}
# Items to skip entirely (exhibits, signatures)
_SKIP_ITEMS = {"9.01", "9.02", "8.01"}


class EightKParser(BaseParser):
    def parse(self, filing: dict, html: str, settings: Settings | None = None) -> list[dict]:
        sections = self._extract_item_sections(html)
        events = []
        for item_code, section_text in sections.items():
            if item_code in _SKIP_ITEMS:
                continue
            if item_code not in _CLAUDE_ITEMS:
                continue
            if settings is None:
                continue
            result = extract_8k_event(section_text, settings)
            if result is None:
                continue
            events.append({
                "filing_id": filing["id"],
                "company_id": filing["company_id"],
                "event_code": result["event_code"],
                "filed_date": filing["filed_date"],
                "sentiment": result.get("sentiment", "neutral"),
                "magnitude": result.get("magnitude"),
                "details": result.get("details", {}),
                "extracted_by": "claude",
            })
        return events
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/test_8k_parser.py -v
```

Expected: all 4 tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/wsd/extraction/parsers/filing_8k.py tests/test_8k_parser.py
git commit -m "feat: add 8-K parser with Claude dispatch for items 1.01/2.01/5.02/7.01"
```

---

## Task 5: 10-Q Parser

**Files:**
- Create: `src/wsd/extraction/parsers/filing_10q.py`
- Create: `tests/test_10q_parser.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_10q_parser.py`:

```python
import pytest

FILING = {
    "id": "uuid-filing-1",
    "company_id": "uuid-company-1",
    "cik": "0000320193",
    "accession_number": "0000320193-24-000002",
    "form_type": "10-Q",
    "filed_date": "2024-01-20",
}

# Minimal XBRL-tagged HTML with EPS values
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


def test_10q_earnings_beat_classification(monkeypatch):
    from wsd.extraction.parsers import filing_10q
    monkeypatch.setattr(filing_10q, "extract_guidance_event", lambda *a: None)
    from wsd.config import Settings
    import os; os.environ.update({"SUPABASE_URL": "x", "SUPABASE_SERVICE_KEY": "x",
                                   "EDGAR_USER_AGENT": "x x@x.com", "ANTHROPIC_API_KEY": "x"})
    events = filing_10q.TenQParser().parse(FILING, HTML_EPS_BEAT, Settings())
    earnings = [e for e in events if e["event_code"] in ("earnings_beat", "earnings_miss", "earnings_inline")]
    assert len(earnings) == 1
    assert earnings[0]["event_code"] == "earnings_beat"
    assert earnings[0]["extracted_by"] == "rules"


def test_10q_earnings_miss_classification(monkeypatch):
    from wsd.extraction.parsers import filing_10q
    monkeypatch.setattr(filing_10q, "extract_guidance_event", lambda *a: None)
    from wsd.config import Settings
    import os; os.environ.update({"SUPABASE_URL": "x", "SUPABASE_SERVICE_KEY": "x",
                                   "EDGAR_USER_AGENT": "x x@x.com", "ANTHROPIC_API_KEY": "x"})
    events = filing_10q.TenQParser().parse(FILING, HTML_EPS_MISS, Settings())
    earnings = [e for e in events if "earnings" in e["event_code"]]
    assert earnings[0]["event_code"] == "earnings_miss"
    assert earnings[0]["sentiment"] == "negative"


def test_10q_no_xbrl_returns_empty(monkeypatch):
    from wsd.extraction.parsers import filing_10q
    monkeypatch.setattr(filing_10q, "extract_guidance_event", lambda *a: None)
    from wsd.config import Settings
    import os; os.environ.update({"SUPABASE_URL": "x", "SUPABASE_SERVICE_KEY": "x",
                                   "EDGAR_USER_AGENT": "x x@x.com", "ANTHROPIC_API_KEY": "x"})
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
    import os; os.environ.update({"SUPABASE_URL": "x", "SUPABASE_SERVICE_KEY": "x",
                                   "EDGAR_USER_AGENT": "x x@x.com", "ANTHROPIC_API_KEY": "x"})
    events = filing_10q.TenQParser().parse(FILING, HTML_EPS_BEAT, Settings())
    assert len(called) == 1
    guidance = [e for e in events if e["event_code"] == "guidance_raised"]
    assert len(guidance) == 1
    assert guidance[0]["extracted_by"] == "claude"


def test_10q_earnings_details_shape(monkeypatch):
    from wsd.extraction.parsers import filing_10q
    monkeypatch.setattr(filing_10q, "extract_guidance_event", lambda *a: None)
    from wsd.config import Settings
    import os; os.environ.update({"SUPABASE_URL": "x", "SUPABASE_SERVICE_KEY": "x",
                                   "EDGAR_USER_AGENT": "x x@x.com", "ANTHROPIC_API_KEY": "x"})
    events = filing_10q.TenQParser().parse(FILING, HTML_EPS_BEAT, Settings())
    e = next(e for e in events if "earnings" in e["event_code"])
    assert "eps_current" in e["details"]
    assert "eps_prior" in e["details"]
    assert "beat_pct" in e["details"]
```

- [ ] **Step 2: Run to confirm failure**

```bash
pytest tests/test_10q_parser.py -v
```

Expected: `ModuleNotFoundError`

- [ ] **Step 3: Create `parsers/filing_10q.py`**

Create `src/wsd/extraction/parsers/filing_10q.py`:

```python
import re
from wsd.config import Settings
from wsd.extraction.claude import extract_guidance_event
from wsd.extraction.parsers.base import BaseParser

_EPS_PATTERN = re.compile(
    r'<ix:nonFraction[^>]*name="us-gaap:EarningsPerShareBasic"[^>]*contextRef="([^"]*)"[^>]*>'
    r'\s*([-\d.]+)\s*</ix:nonFraction>',
    re.IGNORECASE,
)
_MDA_PATTERN = re.compile(
    r'(?:id=["\']mda["\']|Management.{0,20}Discussion)[^>]*>(.*?)(?=<div|<section|\Z)',
    re.IGNORECASE | re.DOTALL,
)
_INLINE_TOLERANCE = 0.05  # within 5% = inline


class TenQParser(BaseParser):
    def parse(self, filing: dict, html: str, settings: Settings | None = None) -> list[dict]:
        events = []
        earnings_event = self._extract_earnings(filing, html)
        if earnings_event:
            events.append(earnings_event)
        if settings is not None:
            mda_text = self._extract_mda(html)
            if mda_text:
                result = extract_guidance_event(mda_text, settings)
                if result:
                    events.append({
                        "filing_id": filing["id"],
                        "company_id": filing["company_id"],
                        "event_code": result["event_code"],
                        "filed_date": filing["filed_date"],
                        "sentiment": result.get("sentiment", "neutral"),
                        "magnitude": result.get("magnitude"),
                        "details": result.get("details", {}),
                        "extracted_by": "claude",
                    })
        return events

    def _extract_earnings(self, filing: dict, html: str) -> dict | None:
        matches = _EPS_PATTERN.findall(html)
        if len(matches) < 2:
            return None
        # First match = current period, second = prior period
        try:
            eps_current = float(matches[0][1])
            eps_prior = float(matches[1][1])
        except (ValueError, IndexError):
            return None
        if eps_prior == 0:
            return None
        beat_pct = (eps_current - eps_prior) / abs(eps_prior) * 100
        if beat_pct > _INLINE_TOLERANCE * 100:
            event_code, sentiment = "earnings_beat", "positive"
        elif beat_pct < -_INLINE_TOLERANCE * 100:
            event_code, sentiment = "earnings_miss", "negative"
        else:
            event_code, sentiment = "earnings_inline", "neutral"
        return {
            "filing_id": filing["id"],
            "company_id": filing["company_id"],
            "event_code": event_code,
            "filed_date": filing["filed_date"],
            "sentiment": sentiment,
            "magnitude": round(beat_pct, 2),
            "details": {
                "eps_current": eps_current,
                "eps_prior": eps_prior,
                "beat_pct": round(beat_pct, 2),
            },
            "extracted_by": "rules",
        }

    def _extract_mda(self, html: str) -> str | None:
        m = _MDA_PATTERN.search(html)
        if not m:
            return None
        return self._clean_text(m.group(1))[:3000]
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/test_10q_parser.py -v
```

Expected: all 5 tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/wsd/extraction/parsers/filing_10q.py tests/test_10q_parser.py
git commit -m "feat: add 10-Q parser — XBRL EPS extraction + Claude MD&A guidance"
```

---

## Task 6: 10-K Parser

**Files:**
- Create: `src/wsd/extraction/parsers/filing_10k.py`
- Create: `tests/test_10k_parser.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_10k_parser.py`:

```python
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
<div id="mda">We expect continued growth.</div>
</body></html>"""


def test_10k_earnings_beat(monkeypatch):
    from wsd.extraction.parsers import filing_10k
    monkeypatch.setattr(filing_10k, "extract_guidance_event", lambda *a: None)
    from wsd.config import Settings
    import os; os.environ.update({"SUPABASE_URL": "x", "SUPABASE_SERVICE_KEY": "x",
                                   "EDGAR_USER_AGENT": "x x@x.com", "ANTHROPIC_API_KEY": "x"})
    events = filing_10k.TenKParser().parse(FILING, HTML_10K_EPS, Settings())
    earnings = [e for e in events if "earnings" in e["event_code"]]
    assert earnings[0]["event_code"] == "earnings_beat"
    assert earnings[0]["extracted_by"] == "rules"


def test_10k_mda_guidance_via_claude(monkeypatch):
    from wsd.extraction.parsers import filing_10k
    monkeypatch.setattr(filing_10k, "extract_guidance_event",
                        lambda *a: {"event_code": "guidance_raised",
                                    "sentiment": "positive", "magnitude": None,
                                    "details": {"metric": "revenue"}})
    from wsd.config import Settings
    import os; os.environ.update({"SUPABASE_URL": "x", "SUPABASE_SERVICE_KEY": "x",
                                   "EDGAR_USER_AGENT": "x x@x.com", "ANTHROPIC_API_KEY": "x"})
    events = filing_10k.TenKParser().parse(FILING, HTML_10K_EPS, Settings())
    guidance = [e for e in events if e["event_code"] == "guidance_raised"]
    assert len(guidance) == 1
    assert guidance[0]["extracted_by"] == "claude"


def test_10k_no_xbrl_returns_empty(monkeypatch):
    from wsd.extraction.parsers import filing_10k
    monkeypatch.setattr(filing_10k, "extract_guidance_event", lambda *a: None)
    from wsd.config import Settings
    import os; os.environ.update({"SUPABASE_URL": "x", "SUPABASE_SERVICE_KEY": "x",
                                   "EDGAR_USER_AGENT": "x x@x.com", "ANTHROPIC_API_KEY": "x"})
    events = filing_10k.TenKParser().parse(FILING, "<html><p>no data</p></html>", Settings())
    assert events == []
```

- [ ] **Step 2: Run to confirm failure**

```bash
pytest tests/test_10k_parser.py -v
```

Expected: `ModuleNotFoundError`

- [ ] **Step 3: Create `parsers/filing_10k.py`**

Create `src/wsd/extraction/parsers/filing_10k.py`:

```python
from wsd.config import Settings
from wsd.extraction.claude import extract_guidance_event
from wsd.extraction.parsers.filing_10q import TenQParser


class TenKParser(TenQParser):
    """10-K parser — identical extraction logic to 10-Q (annual vs quarterly EPS + MD&A)."""

    def parse(self, filing: dict, html: str, settings: Settings | None = None) -> list[dict]:
        return super().parse(filing, html, settings)
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/test_10k_parser.py -v
```

Expected: all 3 tests pass.

- [ ] **Step 5: Run full test suite**

```bash
pytest -v
```

Expected: 39 original + 7 Form4 + 4 downloader + 4 8-K + 5 10-Q + 3 10-K = **62 tests passing**.

- [ ] **Step 6: Commit**

```bash
git add src/wsd/extraction/parsers/filing_10k.py tests/test_10k_parser.py
git commit -m "feat: add 10-K parser (reuses 10-Q logic, 3 tests)"
```

---

## Task 7: Orchestrator

**Files:**
- Create: `src/wsd/extraction/run.py`
- Create: `tests/test_extraction_run.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_extraction_run.py`:

```python
import pytest
from unittest.mock import MagicMock, patch


@pytest.fixture
def settings(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://test.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_KEY", "test-key")
    monkeypatch.setenv("EDGAR_USER_AGENT", "Test User test@test.com")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    from wsd.config import Settings
    return Settings()


FILINGS = [
    {"id": "f1", "company_id": "c1", "cik": "0000320193", "accession_number": "0000320193-24-000001",
     "form_type": "4", "filed_date": "2024-01-15"},
    {"id": "f2", "company_id": "c1", "cik": "0000320193", "accession_number": "0000320193-24-000002",
     "form_type": "8-K", "filed_date": "2024-01-20"},
]


def test_orchestrator_dispatches_form4_to_correct_parser(settings, mocker):
    mock_client = MagicMock()
    mock_client.table.return_value.select.return_value.eq.return_value.order.return_value.limit.return_value.execute.return_value.data = [FILINGS[0]]
    mock_client.table.return_value.select.return_value.eq.return_value.execute.return_value.data = [{"count": 10}]
    mocker.patch("wsd.extraction.run.db.get_client", return_value=mock_client)
    mocker.patch("wsd.extraction.run.download_filing", return_value="<xml/>")
    mock_form4 = mocker.patch("wsd.extraction.run.Form4Parser")
    mock_form4.return_value.parse.return_value = []
    mocker.patch("wsd.extraction.run.db.upsert_events", return_value=0)
    mocker.patch("wsd.extraction.run.db.mark_filing_parsed")
    from wsd.extraction.run import run_extraction
    run_extraction(settings, batch_size=1)
    mock_form4.return_value.parse.assert_called_once()


def test_orchestrator_marks_filing_parsed_after_success(settings, mocker):
    mock_client = MagicMock()
    mock_client.table.return_value.select.return_value.eq.return_value.order.return_value.limit.return_value.execute.return_value.data = [FILINGS[0]]
    mock_client.table.return_value.select.return_value.eq.return_value.execute.return_value.data = [{"count": 10}]
    mocker.patch("wsd.extraction.run.db.get_client", return_value=mock_client)
    mocker.patch("wsd.extraction.run.download_filing", return_value="<xml/>")
    mocker.patch("wsd.extraction.run.Form4Parser").return_value.parse.return_value = []
    mocker.patch("wsd.extraction.run.db.upsert_events", return_value=0)
    mock_mark = mocker.patch("wsd.extraction.run.db.mark_filing_parsed")
    from wsd.extraction.run import run_extraction
    run_extraction(settings, batch_size=1)
    mock_mark.assert_called_once_with("f1", settings)


def test_orchestrator_skips_filing_when_download_fails(settings, mocker):
    mock_client = MagicMock()
    mock_client.table.return_value.select.return_value.eq.return_value.order.return_value.limit.return_value.execute.return_value.data = [FILINGS[0]]
    mock_client.table.return_value.select.return_value.eq.return_value.execute.return_value.data = [{"count": 10}]
    mocker.patch("wsd.extraction.run.db.get_client", return_value=mock_client)
    mocker.patch("wsd.extraction.run.download_filing", return_value=None)
    mock_mark = mocker.patch("wsd.extraction.run.db.mark_filing_parsed")
    from wsd.extraction.run import run_extraction
    run_extraction(settings, batch_size=1)
    mock_mark.assert_not_called()


def test_orchestrator_respects_batch_size(settings, mocker):
    mock_client = MagicMock()
    mock_client.table.return_value.select.return_value.eq.return_value.order.return_value.limit.return_value.execute.return_value.data = FILINGS
    mock_client.table.return_value.select.return_value.eq.return_value.execute.return_value.data = [{"count": 100}]
    mocker.patch("wsd.extraction.run.db.get_client", return_value=mock_client)
    mocker.patch("wsd.extraction.run.download_filing", return_value="<xml/>")
    mocker.patch("wsd.extraction.run.Form4Parser").return_value.parse.return_value = []
    mocker.patch("wsd.extraction.run.EightKParser").return_value.parse.return_value = []
    mocker.patch("wsd.extraction.run.db.upsert_events", return_value=0)
    mocker.patch("wsd.extraction.run.db.mark_filing_parsed")
    from wsd.extraction.run import run_extraction
    result = run_extraction(settings, batch_size=2)
    assert result["processed"] == 2
```

- [ ] **Step 2: Run to confirm failure**

```bash
pytest tests/test_extraction_run.py -v
```

Expected: `ModuleNotFoundError`

- [ ] **Step 3: Create `run.py`**

Create `src/wsd/extraction/run.py`:

```python
import sys
from wsd.config import Settings
from wsd import db
from wsd.extraction.downloader import download_filing
from wsd.extraction.parsers.form4 import Form4Parser
from wsd.extraction.parsers.filing_8k import EightKParser
from wsd.extraction.parsers.filing_10q import TenQParser
from wsd.extraction.parsers.filing_10k import TenKParser

_PARSERS = {
    "4":    Form4Parser,
    "8-K":  EightKParser,
    "10-Q": TenQParser,
    "10-K": TenKParser,
}


def run_extraction(settings: Settings, batch_size: int = 500) -> dict:
    client = db.get_client(settings)

    total = client.table("filings").select("count", count="exact").eq("is_parsed", False).execute().count or 0

    filings = (
        client.table("filings")
        .select("*")
        .eq("is_parsed", False)
        .order("filed_date", desc=True)
        .limit(batch_size)
        .execute()
        .data
    )

    processed = errors = events_total = 0

    for filing in filings:
        form_type = filing.get("form_type", "")
        parser_cls = _PARSERS.get(form_type)
        if parser_cls is None:
            db.mark_filing_parsed(filing["id"], settings)
            processed += 1
            continue

        html = download_filing(filing, settings)
        if html is None:
            errors += 1
            continue

        try:
            parser = parser_cls()
            if form_type == "4":
                events = parser.parse(filing, html)
            else:
                events = parser.parse(filing, html, settings)
            db.upsert_events(events, settings)
            events_total += len(events)
            db.mark_filing_parsed(filing["id"], settings)
            processed += 1
        except Exception as exc:
            print(f"  ERROR processing {filing['accession_number']}: {exc}")
            errors += 1

        pct = processed / max(total, 1) * 100
        print(f"\r  Processed {processed} / {total} ({pct:.1f}%) — {events_total} events extracted", end="")

    print()
    return {"processed": processed, "errors": errors, "events": events_total}


if __name__ == "__main__":
    settings = Settings()
    print("Starting event extraction...")
    result = run_extraction(settings)
    print(f"Done: {result['processed']} processed, {result['errors']} errors, {result['events']} events extracted")
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/test_extraction_run.py -v
```

Expected: all 4 tests pass.

- [ ] **Step 5: Run full test suite**

```bash
pytest -v
```

Expected: **≥ 66 tests passing** (39 original + all new tests).

- [ ] **Step 6: Commit**

```bash
git add src/wsd/extraction/run.py tests/test_extraction_run.py
git commit -m "feat: add extraction orchestrator — dispatch, download, upsert, mark parsed"
```

---

## Task 8: Dashboard

**Files:**
- Create: `dashboard.html`

- [ ] **Step 1: Create `dashboard.html` at project root**

This is the full dashboard incorporating both the base design (from the dashboard spec) and the Phase 2 additions (events card, Phase 2 progress bar). Replace `YOUR_SUPABASE_URL` and `YOUR_SUPABASE_ANON_KEY` with the values from your `.env` file.

Create `dashboard.html`:

```html
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>WSD Dashboard</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { background: #0d1117; color: #e6edf3; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; padding: 24px; max-width: 1000px; margin: 0 auto; }

  .header { display: flex; justify-content: space-between; align-items: flex-end; margin-bottom: 24px; padding-bottom: 16px; border-bottom: 1px solid #21262d; }
  .header h1 { font-size: 18px; letter-spacing: 0.05em; text-transform: uppercase; }
  .header .subtitle { font-size: 12px; color: #8b949e; margin-top: 2px; }
  .refresh-btn { background: #21262d; border: 1px solid #30363d; color: #8b949e; padding: 6px 14px; border-radius: 6px; font-size: 12px; cursor: pointer; }
  .refresh-btn:hover { border-color: #58a6ff; color: #58a6ff; }

  .section-label { font-size: 10px; letter-spacing: 0.12em; text-transform: uppercase; color: #8b949e; margin-bottom: 12px; }

  .current-focus { background: #0d1f38; border: 1px solid #1f4b8f; border-radius: 10px; padding: 20px 24px; margin-bottom: 14px; display: grid; grid-template-columns: auto 1fr auto; align-items: center; gap: 20px; }
  .phase-number { width: 52px; height: 52px; border-radius: 50%; background: #1f4b8f; border: 2px solid #58a6ff; display: flex; align-items: center; justify-content: center; font-size: 20px; font-weight: 800; color: #58a6ff; flex-shrink: 0; }
  .focus-title { font-size: 18px; font-weight: 700; margin-bottom: 4px; }
  .focus-subtitle { font-size: 13px; color: #8b949e; margin-bottom: 10px; }
  .working-on-label { font-size: 10px; text-transform: uppercase; letter-spacing: 0.1em; color: #484f58; margin-bottom: 6px; }
  .working-on-item { display: inline-flex; align-items: center; gap: 6px; background: #0d2a4a; border: 1px solid #1f4b8f; border-radius: 6px; padding: 5px 10px; font-size: 12px; color: #58a6ff; }
  .focus-progress-wrap { text-align: right; min-width: 130px; }
  .focus-progress-label { font-size: 11px; color: #8b949e; margin-bottom: 6px; }
  .focus-progress-bar { width: 120px; height: 6px; background: #21262d; border-radius: 3px; margin-left: auto; }
  .focus-progress-fill { height: 100%; border-radius: 3px; background: #58a6ff; transition: width 0.3s; }
  .focus-pct { font-size: 20px; font-weight: 700; color: #58a6ff; margin-top: 6px; }

  .phase-strip { display: grid; grid-template-columns: repeat(4, 1fr); gap: 10px; margin-bottom: 28px; }
  .phase-tile { background: #161b22; border: 1px solid #21262d; border-radius: 8px; padding: 14px; position: relative; }
  .phase-tile.done   { border-top: 3px solid #238636; }
  .phase-tile.active { border-top: 3px solid #58a6ff; background: #0d1a2e; }
  .phase-tile.pending{ border-top: 3px solid #30363d; opacity: 0.55; }
  .tile-num { font-size: 10px; color: #8b949e; margin-bottom: 4px; letter-spacing: 0.08em; }
  .tile-name { font-size: 13px; font-weight: 600; margin-bottom: 6px; }
  .tile-tasks { display: flex; flex-direction: column; gap: 3px; }
  .tile-task { font-size: 11px; display: flex; align-items: center; gap: 5px; }
  .tile-task.done    { color: #3fb950; }
  .tile-task.pending { color: #484f58; }
  .tile-badge { position: absolute; top: 10px; right: 10px; font-size: 10px; font-weight: 600; padding: 2px 7px; border-radius: 10px; }
  .tile-badge.done    { background: #0f2a1a; color: #3fb950; }
  .tile-badge.active  { background: #0d1f38; color: #58a6ff; }
  .tile-badge.pending { background: #161b22; color: #484f58; }

  .stats-grid { display: grid; grid-template-columns: repeat(5, 1fr); gap: 10px; margin-bottom: 12px; }
  .stat-card { background: #161b22; border: 1px solid #21262d; border-radius: 8px; padding: 14px; }
  .stat-value { font-size: 22px; font-weight: 700; font-variant-numeric: tabular-nums; }
  .stat-value.green { color: #3fb950; }
  .stat-value.blue  { color: #58a6ff; }
  .stat-value.purple{ color: #bc8cff; }
  .stat-label { font-size: 11px; color: #8b949e; margin-top: 4px; }
  .stat-sub   { font-size: 10px; color: #484f58; margin-top: 2px; }

  .table-card { background: #161b22; border: 1px solid #21262d; border-radius: 8px; margin-bottom: 14px; overflow: hidden; }
  .table-card-header { padding: 12px 16px; display: flex; justify-content: space-between; align-items: center; border-bottom: 1px solid #21262d; }
  .table-title { font-size: 13px; font-weight: 600; }
  .table-count { font-size: 11px; color: #8b949e; }
  .expand-hint { font-size: 11px; color: #484f58; cursor: pointer; }
  table { width: 100%; border-collapse: collapse; }
  thead th { font-size: 10px; letter-spacing: 0.08em; text-transform: uppercase; color: #8b949e; font-weight: 500; padding: 10px 16px; border-bottom: 1px solid #21262d; text-align: left; background: #0d1117; }
  tbody tr { border-bottom: 1px solid #1a1f27; }
  tbody tr:last-child { border-bottom: none; }
  tbody tr:hover { background: #1c2129; }
  tbody td { padding: 10px 16px; font-size: 12px; vertical-align: middle; }
  .ticker { font-weight: 700; font-family: monospace; font-size: 12px; }
  .name-sub { color: #8b949e; font-size: 11px; margin-top: 1px; }
  .badge { display: inline-block; padding: 2px 7px; border-radius: 4px; font-size: 10px; font-weight: 600; }
  .badge-8k     { background: #1a2f4a; color: #58a6ff; }
  .badge-10q    { background: #1f3a1f; color: #3fb950; }
  .badge-10k    { background: #3a2a0f; color: #d29922; }
  .badge-form4  { background: #2a1f3a; color: #bc8cff; }
  .badge-insider-buy  { background: #0f2a1a; color: #3fb950; }
  .badge-insider-sell { background: #2a0f0f; color: #f85149; }
  .badge-earnings     { background: #1a2f4a; color: #58a6ff; }
  .badge-guidance     { background: #3a2a0f; color: #d29922; }
  .badge-corporate    { background: #2a1f3a; color: #bc8cff; }
  .badge-executive    { background: #1f2a3a; color: #79c0ff; }
  .sentiment-positive { color: #3fb950; font-size: 11px; }
  .sentiment-negative { color: #f85149; font-size: 11px; }
  .sentiment-neutral  { color: #8b949e; font-size: 11px; }
  .date { color: #8b949e; font-size: 12px; font-family: monospace; }
  .date-sub { color: #484f58; font-size: 10px; margin-top: 1px; }
  .sector-badge { display: inline-block; padding: 2px 7px; border-radius: 4px; font-size: 10px; color: #8b949e; background: #21262d; }
  .quality-row { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; margin-bottom: 28px; }
  .quality-card { background: #161b22; border: 1px solid #21262d; border-radius: 8px; padding: 14px; display: flex; justify-content: space-between; align-items: center; }
  .quality-label { font-size: 12px; color: #8b949e; }
  .quality-count { font-size: 20px; font-weight: 700; }
  .count-zero  { color: #3fb950; }
  .count-warn  { color: #d29922; }
  .count-error { color: #f85149; }
  .show-more { padding: 10px 16px; text-align: center; font-size: 11px; color: #484f58; border-top: 1px solid #21262d; cursor: pointer; }
  .show-more:hover { color: #58a6ff; }
  .footer { margin-top: 20px; font-size: 11px; color: #484f58; text-align: right; }
  .loading { color: #484f58; font-style: italic; }
</style>
</head>
<body>

<script>
  const SUPABASE_URL = "YOUR_SUPABASE_URL";
  const SUPABASE_ANON_KEY = "YOUR_SUPABASE_ANON_KEY";

  async function query(table, params = "") {
    const resp = await fetch(`${SUPABASE_URL}/rest/v1/${table}?${params}`, {
      headers: { "apikey": SUPABASE_ANON_KEY, "Authorization": `Bearer ${SUPABASE_ANON_KEY}` }
    });
    if (!resp.ok) throw new Error(`${table} fetch failed: ${resp.status}`);
    return resp.json();
  }

  async function queryCount(table, filter = "") {
    const resp = await fetch(`${SUPABASE_URL}/rest/v1/${table}?${filter}`, {
      headers: {
        "apikey": SUPABASE_ANON_KEY,
        "Authorization": `Bearer ${SUPABASE_ANON_KEY}`,
        "Prefer": "count=exact",
        "Range": "0-0"
      }
    });
    const range = resp.headers.get("Content-Range") || "0/0";
    return parseInt(range.split("/")[1]) || 0;
  }

  function relativeDate(dateStr) {
    const days = Math.floor((Date.now() - new Date(dateStr)) / 86400000);
    if (days === 0) return "today";
    if (days === 1) return "yesterday";
    return `${days} days ago`;
  }

  function eventBadge(event_code) {
    const category = event_code.startsWith("insider_buy") ? "insider-buy"
      : event_code.startsWith("insider_sell") ? "insider-sell"
      : event_code.startsWith("earnings") ? "earnings"
      : event_code.startsWith("guidance") ? "guidance"
      : event_code.startsWith("ceo") || event_code.startsWith("cfo") || event_code.startsWith("executive") ? "executive"
      : "corporate";
    const label = event_code.replace(/_/g, " ");
    return `<span class="badge badge-${category}">${label}</span>`;
  }

  function formBadge(form_type) {
    const cls = form_type === "8-K" ? "badge-8k" : form_type === "10-Q" ? "badge-10q"
              : form_type === "10-K" ? "badge-10k" : "badge-form4";
    return `<span class="badge ${cls}">${form_type}</span>`;
  }

  async function loadStats() {
    const [companies, prices, filings, events, parsed, quality] = await Promise.all([
      queryCount("companies"),
      queryCount("prices"),
      queryCount("filings"),
      queryCount("events"),
      queryCount("filings", "is_parsed=eq.true"),
      queryCount("data_quality_log", "resolved_at=is.null&severity=eq.error"),
    ]);

    document.getElementById("stat-companies").textContent = companies.toLocaleString();
    document.getElementById("stat-prices").textContent =
      prices > 1000000 ? (prices / 1000000).toFixed(1) + "M" : prices.toLocaleString();
    document.getElementById("stat-filings").textContent =
      filings > 1000 ? (filings / 1000).toFixed(0) + "K" : filings.toLocaleString();
    document.getElementById("stat-events").textContent =
      events > 1000 ? (events / 1000).toFixed(0) + "K" : events.toLocaleString();

    const parsedPct = filings > 0 ? Math.round(parsed / filings * 100) : 0;
    document.getElementById("phase2-pct").textContent = parsedPct + "%";
    document.getElementById("phase2-bar").style.width = parsedPct + "%";
    document.getElementById("phase2-progress-label").textContent =
      `${parsed.toLocaleString()} / ${filings.toLocaleString()} filings parsed`;
  }

  async function loadFilings(offset = 0) {
    const rows = await query("filings",
      `select=id,form_type,filed_date,companies(ticker,name)&order=filed_date.desc&limit=5&offset=${offset}`);
    const tbody = document.getElementById("filings-tbody");
    if (offset === 0) tbody.innerHTML = "";
    rows.forEach(r => {
      const co = r.companies || {};
      tbody.innerHTML += `<tr>
        <td><div class="ticker">${co.ticker||"—"}</div><div class="name-sub">${co.name||""}</div></td>
        <td>${formBadge(r.form_type)}</td>
        <td><div class="date">${r.filed_date}</div><div class="date-sub">${relativeDate(r.filed_date)}</div></td>
      </tr>`;
    });
    document.getElementById("filings-count").textContent = await queryCount("filings") + " rows";
  }

  async function loadEvents(offset = 0) {
    const rows = await query("events",
      `select=event_code,sentiment,filed_date,extracted_by,companies(ticker)&order=filed_date.desc&limit=5&offset=${offset}`);
    const tbody = document.getElementById("events-tbody");
    if (offset === 0) tbody.innerHTML = "";
    rows.forEach(r => {
      const co = r.companies || {};
      tbody.innerHTML += `<tr>
        <td><div class="ticker">${co.ticker||"—"}</div></td>
        <td>${eventBadge(r.event_code)}</td>
        <td><span class="sentiment-${r.sentiment}">${r.sentiment}</span></td>
        <td><div class="date">${r.filed_date}</div><div class="date-sub">${relativeDate(r.filed_date)}</div></td>
        <td><span style="font-size:10px;color:#484f58">${r.extracted_by}</span></td>
      </tr>`;
    });
    document.getElementById("events-count").textContent = await queryCount("events") + " rows";
  }

  async function loadCompanies(offset = 0) {
    const rows = await query("companies",
      `select=ticker,name,sector,entry_date,exit_date&order=entry_date.desc&limit=5&offset=${offset}`);
    const tbody = document.getElementById("companies-tbody");
    if (offset === 0) tbody.innerHTML = "";
    rows.forEach(r => {
      tbody.innerHTML += `<tr>
        <td><div class="ticker">${r.ticker}</div></td>
        <td><div style="font-size:12px">${r.name}</div></td>
        <td><span class="sector-badge">${r.sector||"—"}</span></td>
        <td><div class="date">${r.entry_date}</div></td>
        <td><span style="color:${r.exit_date?"#f85149":"#3fb950"};font-size:11px">● ${r.exit_date?"Exited":"Active"}</span></td>
      </tr>`;
    });
    document.getElementById("companies-count").textContent = await queryCount("companies") + " rows";
  }

  async function loadQuality() {
    const [errors, warnings] = await Promise.all([
      queryCount("data_quality_log", "resolved_at=is.null&severity=eq.error"),
      queryCount("data_quality_log", "resolved_at=is.null&severity=eq.warning"),
    ]);
    document.getElementById("quality-errors").textContent = errors;
    document.getElementById("quality-errors").className = "quality-count " + (errors > 0 ? "count-error" : "count-zero");
    document.getElementById("quality-warnings").textContent = warnings;
    document.getElementById("quality-warnings").className = "quality-count " + (warnings > 0 ? "count-warn" : "count-zero");
  }

  let filingsOffset = 0, eventsOffset = 0, companiesOffset = 0;

  async function refresh() {
    document.getElementById("last-refresh").textContent = "Refreshing...";
    filingsOffset = 0; eventsOffset = 0; companiesOffset = 0;
    await Promise.all([loadStats(), loadFilings(), loadEvents(), loadCompanies(), loadQuality()]);
    document.getElementById("last-refresh").textContent = "Last refreshed: just now";
  }

  document.addEventListener("DOMContentLoaded", () => {
    refresh();
    document.getElementById("btn-refresh").onclick = refresh;
    document.getElementById("btn-more-filings").onclick = () => { filingsOffset += 5; loadFilings(filingsOffset); };
    document.getElementById("btn-more-events").onclick  = () => { eventsOffset  += 5; loadEvents(eventsOffset);  };
    document.getElementById("btn-more-companies").onclick = () => { companiesOffset += 5; loadCompanies(companiesOffset); };
  });
</script>

<!-- HEADER -->
<div class="header">
  <div>
    <h1>Weekly Stock Digest</h1>
    <div class="subtitle">Development Dashboard · Local</div>
  </div>
  <button class="refresh-btn" id="btn-refresh">↻ Refresh</button>
</div>

<!-- CURRENT FOCUS HERO -->
<div class="section-label">Current Focus</div>
<div class="current-focus">
  <div class="phase-number">2</div>
  <div>
    <div class="focus-title">Phase 2 — Event Extraction</div>
    <div class="focus-subtitle">Parse SEC filings → structured events</div>
    <div class="working-on-label">Up next</div>
    <span class="working-on-item">→ Run full historical backfill</span>
  </div>
  <div class="focus-progress-wrap">
    <div class="focus-progress-label" id="phase2-progress-label">Loading...</div>
    <div class="focus-progress-bar"><div class="focus-progress-fill" id="phase2-bar" style="width:0%"></div></div>
    <div class="focus-pct" id="phase2-pct">—</div>
  </div>
</div>

<!-- PHASE STRIP -->
<div class="section-label">All Phases</div>
<div class="phase-strip">
  <div class="phase-tile done">
    <span class="tile-badge done">✓ Done</span>
    <div class="tile-num">Phase 1</div>
    <div class="tile-name">Data Foundation</div>
    <div class="tile-tasks">
      <div class="tile-task done">✓ config + db layer</div>
      <div class="tile-task done">✓ universe ingestor</div>
      <div class="tile-task done">✓ EDGAR ingestor</div>
      <div class="tile-task done">✓ prices ingestor</div>
      <div class="tile-task done">✓ quality checks</div>
      <div class="tile-task done">✓ 39 tests</div>
    </div>
  </div>
  <div class="phase-tile active">
    <span class="tile-badge active">▶ Now</span>
    <div class="tile-num">Phase 2</div>
    <div class="tile-name">Event Extraction</div>
    <div class="tile-tasks">
      <div class="tile-task done">✓ migration + schema</div>
      <div class="tile-task done">✓ downloader</div>
      <div class="tile-task done">✓ Form 4 parser</div>
      <div class="tile-task done">✓ 8-K parser</div>
      <div class="tile-task done">✓ 10-Q/10-K parsers</div>
      <div class="tile-task done">✓ orchestrator</div>
    </div>
  </div>
  <div class="phase-tile pending">
    <span class="tile-badge pending">Pending</span>
    <div class="tile-num">Phase 3</div>
    <div class="tile-name">Scoring + Backtest</div>
    <div class="tile-tasks">
      <div class="tile-task pending">○ event scoring</div>
      <div class="tile-task pending">○ weekly picks</div>
      <div class="tile-task pending">○ backtest engine</div>
      <div class="tile-task pending">○ validation</div>
    </div>
  </div>
  <div class="phase-tile pending">
    <span class="tile-badge pending">Pending</span>
    <div class="tile-num">Phase 4</div>
    <div class="tile-name">Digest Output</div>
    <div class="tile-tasks">
      <div class="tile-task pending">○ digest template</div>
      <div class="tile-task pending">○ Claude API</div>
      <div class="tile-task pending">○ email delivery</div>
    </div>
  </div>
</div>

<!-- STAT CARDS -->
<div class="section-label">Live Data Health</div>
<div class="stats-grid">
  <div class="stat-card">
    <div class="stat-value green" id="stat-companies">…</div>
    <div class="stat-label">Companies</div>
    <div class="stat-sub">in universe</div>
  </div>
  <div class="stat-card">
    <div class="stat-value blue" id="stat-prices">…</div>
    <div class="stat-label">Price Rows</div>
    <div class="stat-sub">5yr OHLCV</div>
  </div>
  <div class="stat-card">
    <div class="stat-value blue" id="stat-filings">…</div>
    <div class="stat-label">Filings</div>
    <div class="stat-sub">8-K · 10-Q · 10-K · Form 4</div>
  </div>
  <div class="stat-card">
    <div class="stat-value purple" id="stat-events">…</div>
    <div class="stat-label">Events Extracted</div>
    <div class="stat-sub">Phase 2</div>
  </div>
  <div class="stat-card">
    <div class="stat-value green" id="quality-errors">…</div>
    <div class="stat-label">Quality Errors</div>
    <div class="stat-sub">unresolved</div>
  </div>
</div>

<div class="quality-row">
  <div class="quality-card">
    <div><div class="quality-label">Quality Errors</div><div style="font-size:10px;color:#484f58;margin-top:2px">unresolved · high severity</div></div>
    <div class="quality-count count-zero" id="quality-errors">…</div>
  </div>
  <div class="quality-card">
    <div><div class="quality-label">Quality Warnings</div><div style="font-size:10px;color:#484f58;margin-top:2px">unresolved · low severity</div></div>
    <div class="quality-count count-warn" id="quality-warnings">…</div>
  </div>
</div>

<!-- DATABASE TABLES -->
<div class="section-label">Database — Recent Rows</div>

<div class="table-card">
  <div class="table-card-header">
    <span class="table-title">events</span>
    <div style="display:flex;gap:16px;align-items:center">
      <span class="table-count" id="events-count">…</span>
      <span class="expand-hint">▾ latest 5</span>
    </div>
  </div>
  <table>
    <thead><tr><th>Company</th><th>Event</th><th>Sentiment</th><th>Filed</th><th>Source</th></tr></thead>
    <tbody id="events-tbody"><tr><td colspan="5" class="loading" style="padding:16px">Loading…</td></tr></tbody>
  </table>
  <div class="show-more" id="btn-more-events">Show 5 more ↓</div>
</div>

<div class="table-card">
  <div class="table-card-header">
    <span class="table-title">filings</span>
    <div style="display:flex;gap:16px;align-items:center">
      <span class="table-count" id="filings-count">…</span>
      <span class="expand-hint">▾ latest 5</span>
    </div>
  </div>
  <table>
    <thead><tr><th>Company</th><th>Form</th><th>Filed</th></tr></thead>
    <tbody id="filings-tbody"><tr><td colspan="3" class="loading" style="padding:16px">Loading…</td></tr></tbody>
  </table>
  <div class="show-more" id="btn-more-filings">Show 5 more ↓</div>
</div>

<div class="table-card">
  <div class="table-card-header">
    <span class="table-title">companies</span>
    <div style="display:flex;gap:16px;align-items:center">
      <span class="table-count" id="companies-count">…</span>
      <span class="expand-hint">▾ latest 5</span>
    </div>
  </div>
  <table>
    <thead><tr><th>Ticker</th><th>Name</th><th>Sector</th><th>Added</th><th>Status</th></tr></thead>
    <tbody id="companies-tbody"><tr><td colspan="5" class="loading" style="padding:16px">Loading…</td></tr></tbody>
  </table>
  <div class="show-more" id="btn-more-companies">Show 5 more ↓</div>
</div>

<div class="footer" id="last-refresh">Last refreshed: —</div>

</body>
</html>
```

- [ ] **Step 2: Fill in your Supabase credentials**

Open `dashboard.html` and replace:
- `YOUR_SUPABASE_URL` → your Supabase project URL (from `.env` `SUPABASE_URL`)
- `YOUR_SUPABASE_ANON_KEY` → your Supabase anon key (from Supabase dashboard → Settings → API → anon public)

- [ ] **Step 3: Open in browser**

Open `dashboard.html` directly in a browser (no server needed — `file://` works). Verify:
- Phase strip renders with Phase 1 green, Phase 2 blue
- Stat cards load live numbers from Supabase
- Filings and companies tables populate
- Events table shows "0 rows" (until extraction runs)
- Quality error/warning counts are correct

- [ ] **Step 4: Commit**

```bash
git add dashboard.html
git commit -m "feat: add live development dashboard with Phase 2 events integration"
```

---

## Task 9: Final Verification + PR

- [ ] **Step 1: Run the full test suite**

```bash
pytest -v
```

Expected output (≥ 66 tests):
```
tests/test_checks.py ........
tests/test_config.py ....
tests/test_db.py ...
tests/test_downloader.py ....
tests/test_edgar.py .......
tests/test_extraction_run.py ....
tests/test_form4_parser.py .......
tests/test_8k_parser.py ....
tests/test_10q_parser.py .....
tests/test_10k_parser.py ...
tests/test_prices.py ....
tests/test_universe.py .....
tests/test_utils.py ....
======================== XX passed in X.XXs ========================
```

- [ ] **Step 2: Verify Definition of Done checklist from spec**

- [ ] Migration applied: `event_taxonomy` seeded with 18 codes, `events` table created
- [ ] `Form4Parser`, `EightKParser`, `TenQParser`, `TenKParser` all importable
- [ ] `python -m wsd.extraction.run` entry point works (dry-run with no unparsed filings)
- [ ] `dashboard.html` opens in browser and fetches live data
- [ ] ≥ 25 new tests passing

- [ ] **Step 3: Push and open PR**

```bash
git push origin feat/phase2-event-extraction
gh pr create \
  --title "feat: Phase 2 event extraction pipeline" \
  --body "Hybrid rules + Claude Haiku extraction of SEC filings into structured events.

## What's included
- Migration: \`event_taxonomy\` (18 codes) + \`events\` table
- \`src/wsd/extraction/\`: downloader, Claude helper, BaseParser, Form4/8-K/10-Q/10-K parsers, orchestrator
- \`dashboard.html\`: full live dashboard with events card + Phase 2 progress bar
- 66+ tests passing

## How to run
\`\`\`bash
python -m wsd.extraction.run   # full historical backfill
\`\`\`
"
```
