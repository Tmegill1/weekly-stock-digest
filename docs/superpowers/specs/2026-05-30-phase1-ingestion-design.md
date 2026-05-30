# Phase 1 Ingestion — Design Spec
**Date:** 2026-05-30
**Scope:** WSD-1 through WSD-8 (Data Foundation)
**Status:** Approved

---

## Overview

Build the Python data ingestion pipeline for the Weekly Stock Digest. The pipeline pulls three sources of data — a static S&P 500 historical universe CSV, SEC EDGAR filing metadata, and yfinance price data — and writes them into the Supabase (PostgreSQL) database established in the Phase 1 migration.

The pipeline is the foundation for all downstream work (event extraction, scoring, backtest, digest). Its most critical invariant: every record must be stamped with the date it became **publicly available** (`filed_date` for filings, `trading_date` for prices). Violating this causes lookahead bias in the backtest and invalidates all results.

---

## Decisions Locked

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Package structure | `src/wsd/` proper package | Scales cleanly across 4 phases without reorganization |
| Universe source | Static historical S&P 500 CSV | Free, accurate, includes historical exits — prevents survivorship bias |
| Price history window | **5 years** (today − 5yr) | Keeps all-phase storage within Supabase free tier (~383 MB total across all 4 phases) |
| Price source | yfinance | Free, no API key, full OHLCV + adj_close |
| EDGAR access | Raw `requests` vs REST API | Full control over rate limiting, caching, retry — no dependency lag |
| Architecture | Independent modules + CLI | Each module runs standalone during dev; scales to orchestrator later |
| Concurrency | Synchronous only | EDGAR rate limit is the bottleneck anyway; async adds complexity for no gain |
| Rate limiting | Token bucket, 8 req/s | Stays under EDGAR's 10 req/s limit with headroom |
| Upsert strategy | Idempotent on natural unique keys | Re-running any ingestor is always safe |
| Error handling | Retry decorator + `data_quality_log` | Failures are logged and skipped, not crash-stopping |

---

## Storage Budget

All 4 phases combined fit within Supabase free tier (500 MB):

| Phase | Table | Est. Size |
|-------|-------|-----------|
| 1 | `companies` | < 1 MB |
| 1 | `prices` (5yr, 500 companies) | ~150 MB |
| 1 | `filings` metadata (10yr) | ~50 MB |
| 1 | `data_quality_log` | ~5 MB |
| 2 | `event_taxonomy` + `events` | ~76 MB |
| 3 | `event_returns` + `weekly_scores` | ~101 MB |
| 4 | `picks` paper log | < 1 MB |
| **Total** | | **~383 MB** ✅ |

---

## Project Structure

```
weekly-stock-digest/
├── src/
│   └── wsd/
│       ├── __init__.py
│       ├── config.py              # env vars + typed Settings dataclass
│       ├── db.py                  # Supabase client singleton + upsert helpers
│       ├── utils.py               # RateLimiter, @retry decorator, shared helpers
│       ├── ingestion/
│       │   ├── __init__.py
│       │   ├── universe.py        # CSV → companies table
│       │   ├── edgar.py           # EDGAR REST API → filings table
│       │   └── prices.py          # yfinance → prices table
│       └── quality/
│           ├── __init__.py
│           └── checks.py          # → data_quality_log table
├── data/
│   └── sp500_historical.csv       # static universe seed (committed to repo)
├── tests/
│   ├── __init__.py
│   ├── test_universe.py
│   ├── test_edgar.py
│   └── test_prices.py
├── docs/
│   └── superpowers/
│       └── specs/
│           └── 2026-05-30-phase1-ingestion-design.md
├── supabase/
│   └── migrations/
│       └── 20260530000001_phase1_data_foundation.sql
├── pyproject.toml
├── .env
├── .env.example
└── README.md
```

---

## Module Responsibilities

### `config.py`
- Reads `.env` using `python-dotenv`
- Exposes a single `Settings` dataclass with typed fields:
  - `supabase_url: str`
  - `supabase_service_key: str`
  - `edgar_user_agent: str` (required by SEC policy, e.g. `"Name email@example.com"`)
  - `edgar_rate_limit: int = 8` (requests/second)
  - `price_history_years: int = 5`
- Raises `ValueError` at import time if required fields are missing — fails fast before any network calls

### `db.py`
- Creates a single Supabase client using `service_role` key (bypasses RLS — correct for backend pipeline)
- Exposes four upsert helpers used by all ingestors:
  - `upsert_companies(rows: list[dict]) -> int` — conflict on `(cik, entry_date)`
  - `upsert_prices(rows: list[dict]) -> int` — conflict on `(company_id, trading_date)`
  - `upsert_filings(rows: list[dict]) -> int` — conflict on `accession_number`
  - `insert_quality_log(rows: list[dict]) -> None`
- Returns row counts for run summaries
- Keeps all SQL out of ingestion modules

### `utils.py`
- `RateLimiter(rate: int)` — token bucket implementation. Call `limiter.acquire()` before each EDGAR HTTP request
- `@retry(attempts=3, backoff=2.0)` — decorator for HTTP calls. Exponential backoff (2s, 4s, 8s). On 429, waits 60s before retrying. After all attempts exhausted, re-raises the exception for the caller to handle
- `edgar_get(url: str, settings: Settings) -> dict` — single EDGAR fetch with rate limiting + retry applied

### `ingestion/universe.py`
- Reads `data/sp500_historical.csv`
- Expected CSV columns: `ticker`, `cik`, `name`, `sector`, `industry`, `exchange`, `entry_date`, `exit_date`, `exit_reason`
- Validates each row: non-null `ticker`, `name`, `entry_date`; valid `exit_reason` if present
- Upserts into `companies` via `db.upsert_companies()`
- Logs invalid rows as warnings (does not crash)
- Entry point: `python -m wsd.ingestion.universe`
- Prints summary: `Universe loaded: 1847 rows upserted, 3 skipped (validation errors)`

### `ingestion/edgar.py`
- Queries `companies` for all rows where `cik IS NOT NULL`
- For each CIK, calls `https://data.sec.gov/submissions/CIK{cik:010d}.json`
- Parses the `filings.recent` and `filings.files` sections
- Filters to form types: `8-K`, `10-Q`, `10-K`, `4`
- Maps to filing rows: `company_id`, `cik`, `accession_number`, `form_type`, `filed_date`, `period_date`, `filing_url`
- **Never uses `period_date` as the event timestamp — always `filed_date`**
- Skips filings already in the table (accession_number unique constraint handles this at upsert)
- Respects rate limit via `utils.edgar_get()`
- Entry point: `python -m wsd.ingestion.edgar`
- Prints summary: `EDGAR ingestion complete: 487 processed, 13 skipped (no CIK), 2 errors`

### `ingestion/prices.py`
- Queries `companies` for all tickers (including `is_benchmark=true` for SPY)
- Queries `MAX(trading_date)` per company to determine incremental start date
- For new companies: `start = max(entry_date, today − 5 years)`
- For existing companies: `start = max_trading_date + 1 day`
- Downloads in batches of 50 tickers via `yf.download(tickers, start, end, auto_adjust=True)`
- Validates each row: `adj_close > 0`, `high >= low`
- Invalid rows are dropped and logged to `data_quality_log`
- Upserts via `db.upsert_prices()`
- Entry point: `python -m wsd.ingestion.prices`
- Prints summary: `Prices ingested: 1,247,840 rows upserted, 12 tickers failed, 34 rows dropped (validation)`

### `quality/checks.py`
Runs four checks and writes results to `data_quality_log`:

| Check | Logic | Severity |
|-------|-------|----------|
| `price_gap` | Trading days with no price record (using a calendar of expected market days) | `warning` |
| `stale_price` | `MAX(trading_date)` > 5 calendar days ago for any active company | `error` |
| `price_anomaly` | Single-day `adj_close` move > 50% (may indicate bad split adjustment) | `warning` |
| `missing_filing` | Active company with no 10-Q in the last 100 days | `warning` |

- Entry point: `python -m wsd.quality.checks`
- Marks previously-logged issues as `resolved_at = now()` if they no longer apply

---

## Data Flow

```
data/sp500_historical.csv
        │
        ▼
   universe.py  ──────────────────────► companies table
                                              │
                    ┌─────────────────────────┤
                    │                         │
                    ▼                         ▼
               edgar.py                  prices.py
           (reads CIKs)              (reads tickers)
                  │                          │
         EDGAR REST API                  yfinance
         data.sec.gov               (last 5 years only,
                  │                   batches of 50)
                  │                          │
                  ▼                          ▼
           filings table              prices table
                  │                          │
                  └─────────────────────────┤
                                             │
                                             ▼
                                        checks.py
                                             │
                                             ▼
                                    data_quality_log
```

**Ordering constraint:** `universe.py` must complete before `edgar.py` or `prices.py`. Both read from `companies`. The CLI prints a clear error and exits if `companies` is empty.

---

## Error Handling

| Scenario | Behaviour |
|----------|-----------|
| Network error (transient) | Retry 3× with exponential backoff (2s, 4s, 8s) |
| EDGAR 429 | Wait 60s, retry up to 3×. Log error if all retries fail |
| yfinance empty result for ticker | Log `data_quality_log` entry (`severity='warning'`), continue |
| Company has no CIK | Skip EDGAR ingestion for that company, log warning to stdout |
| Price row fails validation | Drop row, log to `data_quality_log` with raw values in `details` JSONB |
| Supabase upsert error | Log full error + affected rows to stdout, continue with next batch |

All errors direct the user to `data_quality_log` for details. No module crashes a full run on a single company failure.

---

## Dependencies (`pyproject.toml`)

```toml
[project]
name = "wsd"
version = "0.1.0"
requires-python = ">=3.12"

dependencies = [
    "supabase>=2.0",
    "yfinance>=0.2",
    "requests>=2.31",
    "python-dotenv>=1.0",
    "pandas>=2.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0",
    "pytest-mock>=3.0",
]
```

---

## CLI Entry Points

```bash
# Run in order for initial load:
python -m wsd.ingestion.universe    # ~1 min
python -m wsd.ingestion.edgar       # ~15-20 min (rate limited)
python -m wsd.ingestion.prices      # ~5-10 min (batched)
python -m wsd.quality.checks        # ~1 min

# Subsequent weekly runs (incremental):
python -m wsd.ingestion.edgar       # ~2 min (new filings only)
python -m wsd.ingestion.prices      # ~1 min (1 week of data)
python -m wsd.quality.checks        # ~1 min
```

---

## Out of Scope (Phase 1)

- Parsing filing content (Phase 2)
- Event extraction or scoring (Phase 2/3)
- Full-text filing storage — only metadata (URL + local path) is stored in `filings`
- Options data (Phase 5, deferred)
- Any UI or digest output

---

## Definition of Done

- [ ] `python -m wsd.ingestion.universe` loads ~1,500+ company rows (current + historical S&P 500 members)
- [ ] `python -m wsd.ingestion.edgar` populates `filings` with 8-K, 10-Q, 10-K, Form 4 for all companies with CIKs
- [ ] `python -m wsd.ingestion.prices` populates `prices` with 5 years of adj_close for all tickers including SPY
- [ ] All records have correct `filed_date` / `trading_date` (no period dates used as event timestamps)
- [ ] Re-running any module is idempotent (no duplicate rows)
- [ ] `python -m wsd.quality.checks` runs without crashing and writes to `data_quality_log`
- [ ] Total database size stays under 250 MB after initial load
