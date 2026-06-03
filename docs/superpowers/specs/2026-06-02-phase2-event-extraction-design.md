# Phase 2 Event Extraction — Design Spec
**Date:** 2026-06-02
**Scope:** WSD-9 through WSD-20 (Event Extraction)
**Status:** Approved

---

## Overview

Parse the 47K SEC filings stored in the `filings` table into structured events and store them in two new tables: `event_taxonomy` (reference) and `events` (one row per extracted event). Events feed directly into Phase 3 scoring and are visible in the development dashboard.

**Extraction approach:** Hybrid — rules-based for structured filing data (Form 4 XML, 8-K item codes), Claude API only for free-text sections where structure matters (8-K item text, 10-Q/10-K MD&A). Keeps API costs proportional to signal value.

**Scope:** Full historical backfill of all 47K existing filings + incremental processing of new filings on each weekly run.

---

## Decisions Locked

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Event storage | `events` + `event_taxonomy` tables | Taxonomy as reference table gives Phase 3 scoring weight hints; JSONB details handles variable per-type structure |
| Extraction method | Hybrid rules + Claude API | Rules for structured data (Form 4, 8-K item numbers); Claude only for free text where classification matters |
| Claude scope | 8-K items 1.01/2.01/5.02/7.01, 10-Q/10-K MD&A | High-signal sections only — Form 4 is pure XML, no LLM needed |
| Unique constraint | `(filing_id, event_code)` | One event of each type per filing; re-running is safe |
| Progress tracking | `filings.is_parsed` flag | Orchestrator flips to `true` after successful extraction; dashboard shows live % |
| Filing download | Fetch from EDGAR + cache to disk | `raw_storage_path` column in `filings` updated after download |
| Dashboard integration | Events table card + stat card in `dashboard.html` | Total events count + latest 5 rows; Phase 2 progress bar uses `is_parsed` % |
| Testing | Unit tests for every new module | Same standard as Phase 1 (pytest + pytest-mock) |

---

## Database Schema

### Migration: `20260602000004_phase2_event_extraction.sql`

#### `event_taxonomy`

```sql
create table public.event_taxonomy (
  id                  uuid    primary key default uuid_generate_v4(),
  event_code          text    not null unique,   -- e.g. 'insider_buy_large'
  category            text    not null,          -- 'insider_trading', 'earnings', etc.
  label               text    not null,          -- 'Large Insider Buy'
  description         text    not null,
  scoring_weight_hint numeric(5,2) not null default 1.0,
  created_at          timestamptz not null default now()
);
```

Seeded in the same migration with ~18 event codes across 6 categories:

| Category | Event Codes |
|----------|------------|
| `insider_trading` | `insider_buy_large`, `insider_sell_large`, `insider_buy_small`, `insider_sell_small` |
| `earnings` | `earnings_beat`, `earnings_miss`, `earnings_inline` |
| `guidance` | `guidance_raised`, `guidance_lowered`, `guidance_initiated` |
| `corporate` | `acquisition_announced`, `merger_announced`, `divestiture_announced` |
| `executive` | `ceo_change`, `cfo_change`, `executive_change_other` |
| `capital` | `buyback_announced`, `dividend_change` |

`scoring_weight_hint`: higher = more signal. `insider_buy_large` = 1.5, `ceo_change` = 1.3, `earnings_beat` = 1.2, etc. Phase 3 uses these as starting weights.

#### `events`

```sql
create table public.events (
  id           uuid    primary key default uuid_generate_v4(),
  filing_id    uuid    not null references public.filings (id) on delete cascade,
  company_id   uuid    not null references public.companies (id) on delete cascade,
  event_code   text    not null references public.event_taxonomy (event_code),
  filed_date   date    not null,   -- denormalized from filing — use for all backtest queries
  sentiment    text    not null check (sentiment in ('positive', 'negative', 'neutral')),
  magnitude    numeric(10,4),      -- e.g. EPS beat %, insider trade value in $M. Null if not applicable.
  details      jsonb   not null default '{}',  -- event-specific structured data
  extracted_by text    not null check (extracted_by in ('rules', 'claude')),
  created_at   timestamptz not null default now(),

  constraint events_filing_event_unique unique (filing_id, event_code)
);

create index events_company_date_idx  on public.events (company_id, filed_date);
create index events_filed_date_idx    on public.events (filed_date);
create index events_event_code_idx    on public.events (event_code);
create index events_filing_id_idx     on public.events (filing_id);
```

**`details` JSONB shapes by event type:**

| Event type | Details shape |
|-----------|--------------|
| `insider_buy_*` / `insider_sell_*` | `{shares, value_usd, insider_name, insider_title, transaction_date}` |
| `earnings_beat` / `earnings_miss` | `{eps_actual, eps_estimate, beat_pct, revenue_actual, revenue_estimate}` |
| `guidance_raised` / `guidance_lowered` | `{metric, prior_guidance, new_guidance, change_pct}` |
| `acquisition_announced` | `{target_name, deal_value_usd, deal_type}` |
| `ceo_change` / `cfo_change` | `{departing_name, incoming_name, reason}` |
| `buyback_announced` | `{amount_usd, pct_of_shares}` |

---

## Module Structure

```
src/wsd/extraction/
├── __init__.py
├── downloader.py          # Fetch raw filing HTML from EDGAR → cache to disk
├── run.py                 # Orchestrator: iterate unparsed filings → parse → upsert → mark done
└── parsers/
    ├── __init__.py
    ├── base.py            # Abstract BaseParser: parse(filing, html) → list[dict]
    ├── form4.py           # Form 4: rules-based XML parsing (no Claude)
    ├── filing_8k.py       # 8-K: item code extraction (rules) + Claude for items 1.01/2.01/5.02
    ├── filing_10q.py      # 10-Q: XBRL financial tables (rules) + Claude for MD&A
    └── filing_10k.py      # 10-K: same pattern as 10-Q

tests/
├── test_downloader.py     # Mock HTTP: correct URL construction, caching, rate limiting
├── test_form4_parser.py   # Form 4 XML fixtures → expected insider trade events
├── test_8k_parser.py      # 8-K HTML fixtures → item extraction; mock Claude responses
├── test_10q_parser.py     # 10-Q HTML fixtures → financial table parsing; mock Claude
├── test_10k_parser.py     # 10-K HTML fixtures → same as 10-Q
└── test_extraction_run.py # Orchestrator: mock DB + parsers, verify flow end-to-end
```

---

## Module Responsibilities

### `downloader.py`
- Constructs EDGAR document index URL from `cik` and `accession_number`:
  `https://www.sec.gov/Archives/edgar/data/{cik}/{accession_no_dashes}/`
- Fetches the filing index JSON to find the primary document filename
- Downloads the primary document HTML
- Caches to `data/filings/{cik}/{accession_number}.html`
- Updates `filings.raw_storage_path` in the DB
- Respects EDGAR rate limit via existing `RateLimiter` from `utils.py`
- Returns cached content on repeat calls (skip download if file exists)

### `parsers/base.py`
- `BaseParser` abstract class with one method: `parse(filing: dict, html: str) -> list[dict]`
- Each returned dict is a validated event ready for `db.upsert_events()`
- Shared helpers: `_extract_item_sections(html)`, `_clean_text(html)`

### `parsers/form4.py`
- Form 4 is XML — parse with `xml.etree.ElementTree` (stdlib, no extra deps)
- Extracts: `transactionDate`, `transactionShares`, `transactionPricePerShare`, `transactionAcquiredDisposedCode` (A=buy, D=sell), `reportingOwnerRelationship`
- Classifies as `insider_buy_large` if value > $1M, `insider_buy_small` otherwise (same for sell)
- Sentiment: buy = positive, sell = negative
- `extracted_by = 'rules'`

### `parsers/filing_8k.py`
- Extract 8-K item numbers with regex: `Item\s+(\d+\.\d+)` pattern
- Items handled by rules alone: item 9.01 (exhibits only — skip), item 8.01 (other events — skip)
- Items sent to Claude: 1.01 (material agreements), 2.01 (acquisitions), 5.02 (director/officer changes), 7.01 (Regulation FD — guidance)
- Claude prompt returns structured JSON: `{event_code, sentiment, magnitude, details}`
- Falls back gracefully if Claude returns unparseable output (log warning, skip event)
- `extracted_by = 'rules'` or `'claude'` per event

### `parsers/filing_10q.py` and `filing_10k.py`
- Extract EPS and revenue from XBRL inline tags (`ix:nonFraction`) using regex — rules-based
- Compare against prior period to classify `earnings_beat` / `earnings_miss` / `earnings_inline`
- Send MD&A section text to Claude → classify guidance signals
- `extracted_by = 'rules'` for financial figures, `'claude'` for guidance events

### `run.py`
- Queries `filings WHERE is_parsed = false ORDER BY filed_date DESC LIMIT {batch_size}`
- Default batch size: 500 (configurable via `Settings`)
- For each filing: download → dispatch parser → upsert events → flip `is_parsed = true`
- Prints progress: `Processed 1,500 / 47,382 filings (3.2%) — 4,821 events extracted`
- Entry point: `python -m wsd.extraction.run`
- On subsequent weekly runs: only processes newly ingested filings (all prior are `is_parsed = true`)

---

## Claude API Integration

```python
# Called only for high-signal free-text sections
client = anthropic.Anthropic()
response = client.messages.create(
    model="claude-haiku-4-5-20251001",   # cheapest — structured extraction task
    max_tokens=256,
    messages=[{"role": "user", "content": EXTRACTION_PROMPT.format(text=section_text)}]
)
```

**Prompt contract:** Claude always returns a JSON object or `null`. If `null`, the section is skipped. Invalid JSON triggers a warning log and skip — never a crash.

**Cost estimate:** ~8K filings need Claude (8-K items + 10-Q/10-K MD&A). At Haiku pricing (~$0.25/M input tokens), total historical backfill ≈ $2–5.

**New dependency:** `anthropic>=0.25` added to `pyproject.toml`.

---

## Data Flow

```
filings (is_parsed=false)
        │
        ▼
  downloader.py
  → EDGAR Archives URL
  → cache HTML to data/filings/{cik}/{accession}.html
  → update filings.raw_storage_path
        │
        ▼
  parser dispatch (form4 / 8k / 10q / 10k)
  → rules-based extraction
  → Claude API (selective: 8-K items, MD&A)
        │
        ▼
  events table
  ← event_taxonomy (reference codes)
        │
  filings.is_parsed = true
        │
        ▼
  dashboard.html (Supabase REST)
  → stat card: total events extracted
  → events table card: latest 5 rows (company, event type, sentiment, date)
  → Phase 2 progress bar: is_parsed=true count / total filings
```

---

## Unit Tests

One test file per module. All external calls (EDGAR HTTP, Claude API, Supabase) are mocked.

| Test file | What it covers |
|-----------|---------------|
| `test_downloader.py` | Correct EDGAR URL construction from CIK + accession; cache hit skips HTTP; rate limiter called; `raw_storage_path` updated in DB |
| `test_form4_parser.py` | Buy vs sell classification; large vs small threshold ($1M); correct `details` JSONB shape; malformed XML returns empty list |
| `test_8k_parser.py` | Item number regex extraction; items 1.01/2.01/5.02 trigger Claude; item 9.01 skipped; Claude mock returns valid JSON event; Claude mock returns null → skip gracefully; Claude mock returns invalid JSON → log warning, skip |
| `test_10q_parser.py` | XBRL EPS extraction; beat/miss/inline classification; MD&A section sent to Claude mock; missing XBRL data returns empty list without crash |
| `test_10k_parser.py` | Same coverage as 10-Q |
| `test_extraction_run.py` | Orchestrator queries unparsed filings; dispatches correct parser per form_type; events upserted; `is_parsed` flipped to true; batch size respected |

Target: **≥ 25 new tests**, all passing before Phase 2 is considered complete.

---

## Error Handling

| Scenario | Behaviour |
|----------|-----------|
| EDGAR 404 on filing download | Log warning, skip filing, do NOT flip `is_parsed` |
| EDGAR 429 | Wait 60s, retry 3×. Same as Phase 1 |
| Claude returns null / unparseable JSON | Log warning, skip that event, continue |
| Claude API error / timeout | Log error, skip filing's Claude-dependent events, flip `is_parsed = true` (rules-based events still saved) |
| XBRL tags not found in 10-Q/10-K | Return empty events list, log info — filing still marked parsed |
| Supabase upsert error | Log error + affected rows, continue to next filing |

---

## Dashboard Updates (`dashboard.html`)

When Phase 2 is built, `dashboard.html` gets three additions:

1. **Stat card** — "Events Extracted" with live count from `events` table
2. **Phase 2 progress bar** — `SELECT count(*) FROM filings WHERE is_parsed = true` / total filings
3. **`events` table card** — latest 5 rows: Company (ticker), Event Type (badge), Sentiment, Filed Date, Extracted By

These are additive changes to the existing dashboard — no existing cards removed.

---

## Dependencies

New addition to `pyproject.toml`:
```toml
"anthropic>=0.25",
```

No other new dependencies. `xml.etree.ElementTree` and `re` are stdlib.

---

## Storage Budget Check

| Table | Est. rows | Est. size |
|-------|-----------|-----------|
| `event_taxonomy` | 18 | < 1 KB |
| `events` | ~150K (avg 3/filing) | ~50 MB |
| Updated `filings` (raw_storage_path) | 47K | < 1 MB additional |
| **Phase 2 total** | | **~51 MB** ✅ (within 76 MB budget) |

---

## CLI

```bash
# Full historical backfill (run once):
python -m wsd.extraction.run           # ~2-4 hours (EDGAR rate limited + Claude calls)

# Subsequent weekly runs (incremental — only new filings):
python -m wsd.extraction.run           # ~5-10 min
```

---

## Definition of Done

- [ ] Migration applied: `event_taxonomy` seeded with 18 event codes, `events` table created
- [ ] `python -m wsd.extraction.run` processes all unparsed filings without crashing
- [ ] Form 4 insider trades extracted correctly (buy/sell/size classification)
- [ ] 8-K item codes extracted; Claude called only for items 1.01, 2.01, 5.02, 7.01
- [ ] 10-Q/10-K financial figures extracted from XBRL; MD&A guidance classified via Claude
- [ ] Re-running is idempotent (unique constraint on `filing_id, event_code`)
- [ ] `filings.is_parsed = true` for all processed filings
- [ ] `dashboard.html` updated with events stat card, events table card, Phase 2 progress bar
- [ ] ≥ 25 new unit tests, all passing
- [ ] `anthropic` package added to `pyproject.toml`
