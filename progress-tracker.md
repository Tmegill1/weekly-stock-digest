# Progress Tracker — Weekly Stock Digest

A day-by-day log of what was accomplished.

---

## 2026-05-30

- Set up Atlassian MCP authentication
- Reviewed all 30 Jira issues across 5 epics; updated with acceptance criteria
- Created `README.md` with architecture overview, phase table, risk mitigations
- Chose tech stack: Python + Supabase (PostgreSQL)
- Locked 5-year price history window to stay within Supabase free tier (~383MB total)
- Wrote and applied Phase 1 database migration — `companies`, `prices`, `filings`, `data_quality_log` tables + RLS + helper functions
- Completed Phase 1 brainstorm + design spec (`docs/superpowers/specs/2026-05-30-phase1-ingestion-design.md`)
- Wrote 10-task TDD implementation plan (`docs/superpowers/plans/2026-05-30-phase1-ingestion.md`)
- Implemented full Phase 1 ingestion pipeline:
  - `src/wsd/config.py` — Settings dataclass
  - `src/wsd/db.py` — Supabase client + upsert helpers
  - `src/wsd/utils.py` — RateLimiter, retry decorator, edgar_get
  - `src/wsd/ingestion/universe.py` — S&P 500 CSV → companies table
  - `src/wsd/ingestion/edgar.py` — EDGAR REST API → filings table
  - `src/wsd/ingestion/prices.py` — yfinance → prices table
  - `src/wsd/quality/checks.py` — 4 data quality checks
- **39 tests written and passing**
- Merged PR #1 (schema + README) and PR #2 (full ingestion pipeline)

---

## 2026-06-02

- Fixed 3 bugs found during smoke tests (PR #3):
  - Companies upsert: replaced partial unique index with full unique constraint for PostgREST compatibility
  - Universe dedup on `(cik, entry_date)` to handle dual-class share companies (e.g. FOXA/FOX)
  - EDGAR `period_date` nulled when it exceeds `filed_date` (Form 4 data quality issue)
  - Quality checks: replaced invalid PostgREST aggregate with `max_trading_dates()` RPC
- Cloned `https://github.com/aaroneiceman/form` to `/mnt/c/Users/Tyler/form` for reference
- Designed and built local development dashboard (`dashboard.html`):
  - Phase roadmap strip (4 phases with task-level detail)
  - Current focus hero with live progress bar
  - Live Supabase data: companies, prices, filings, events stat cards
  - DB table viewers with recent rows + "Show more" pagination
  - Color-coded badges for form types and event categories
- Designed Phase 2 Event Extraction (design spec + implementation plan)
- Implemented full Phase 2 extraction pipeline:
  - Applied Supabase migration: `event_taxonomy` (18 event codes) + `events` tables
  - `src/wsd/extraction/downloader.py` — EDGAR HTML fetch + disk cache
  - `src/wsd/extraction/claude.py` — Claude Haiku API helper (graceful fallback)
  - `src/wsd/extraction/parsers/form4.py` — Form 4 XML → insider trade events (rules)
  - `src/wsd/extraction/parsers/filing_8k.py` — 8-K item extraction + Claude for free text
  - `src/wsd/extraction/parsers/filing_10q.py` — XBRL EPS extraction + Claude for MD&A
  - `src/wsd/extraction/parsers/filing_10k.py` — same pattern as 10-Q
  - `src/wsd/extraction/run.py` — orchestrator (iterates unparsed filings, dispatches, marks done)
- Made `ANTHROPIC_API_KEY` optional — backfill runs rules-only without API credits
- **69 tests written and passing** (29 new Phase 2 tests)
- Merged PRs #3, #4, #5, #6
- Started HTTP server on port 8080 to serve dashboard.html (required for Supabase fetch)

---

## Upcoming

- [ ] Run Phase 2 historical backfill: `C:\Python312\python.exe -m wsd.extraction.run`
- [ ] Phase 3 — Scoring + Backtest (event scoring, weekly picks, backtest engine, validation)
- [ ] Phase 4 — Digest Output (digest template, Claude API summary, email delivery)
- [ ] Add `ANTHROPIC_API_KEY` to `.env` for Claude-based event extraction (8-K free text, MD&A guidance)
