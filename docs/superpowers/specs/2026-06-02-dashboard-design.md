# Development Dashboard — Design Spec
**Date:** 2026-06-02
**Status:** Approved

---

## Overview

A single `dashboard.html` file at the project root that gives a full-picture view of the Weekly Stock Digest project: where we are across the 4-phase roadmap, what we're actively working on, and live health stats from the Supabase database.

No framework, no build step. Open `dashboard.html` in a browser and it fetches live data from Supabase on load.

---

## Decisions Locked

| Decision | Choice | Rationale |
|----------|--------|-----------|
| File location | `dashboard.html` at project root | Same pattern as `form` project — serve directly, no path to remember |
| Tech stack | Vanilla HTML/CSS/JS | No build step, no dependencies, matches project philosophy |
| Data source | Live JS fetch via Supabase REST API | Always current, no extra script to run, anon key in file is acceptable for a local dev tool |
| Layout | Stacked (full-width sections) | Works at any window width, natural top-to-bottom reading order |
| Phase detail | Task-level checkboxes per phase tile | Hardcoded — phase tasks don't change daily, manual update is fine |
| DB visibility | Recent rows preview (latest 5, expandable) | Real data insight without becoming a full admin tool |

---

## Layout — Top to Bottom

### 1. Header
- Project name ("Weekly Stock Digest"), subtitle ("Development Dashboard · Local")
- Refresh button (top-right) — re-fetches all live data

### 2. Current Focus Hero
The most prominent element. Shows at a glance:
- Large phase number circle (highlighted in blue when active)
- Phase name + description
- "Up next" label with the immediate next action
- Phase progress bar + percentage (tasks done / total tasks)

This section is **hardcoded** — updated manually as work progresses.

### 3. All Phases Strip
Four side-by-side tiles (Phase 1–4), each showing:
- Phase name and number
- Task-level checklist (✓ done, ○ pending, → active)
- Status badge: `✓ Done` (green), `▶ Now` (blue), `Pending` (gray)

Color coding:
- Done: green left border (`#238636`)
- Active: blue left border + dark blue background (`#0d1a2e`)
- Pending: gray, 55% opacity

This section is **hardcoded**.

### 4. Live Data Health — Database Tables
Three expandable table cards, each fetched live from Supabase on load:

| Card | Columns shown | Sort | Default rows |
|------|--------------|------|--------------|
| `filings` | Company (ticker + name), Form (badge), Filed (date + relative), Period | `filed_date DESC` | 5 |
| `companies` | Ticker, Name, Sector, Added date, Status | `entry_date DESC` | 5 |
| `data_quality_log` | Check name, Company, Severity, Details, Logged | `created_at DESC` | 5 |

- "Show 10 more ↓" button appends the next page (offset-based)
- Form type badges are color-coded: 8-K (blue), 10-Q (green), 10-K (amber), Form 4 (purple)
- Quality severity: warning (amber), error (red)

### 5. Footer
"Last refreshed: X seconds ago · live data from Supabase"

---

## Supabase Queries (REST via fetch)

```js
// Row counts
GET /rest/v1/companies?select=count          → companies count
GET /rest/v1/prices?select=count             → prices count
GET /rest/v1/filings?select=count            → filings count
GET /rest/v1/data_quality_log?select=count&resolved_at=is.null  → open quality issues

// Recent rows
GET /rest/v1/filings?select=*,companies(ticker,name)&order=filed_date.desc&limit=5
GET /rest/v1/companies?select=*&order=entry_date.desc&limit=5
GET /rest/v1/data_quality_log?select=*,companies(ticker)&resolved_at=is.null&order=created_at.desc&limit=5

// "Show more" uses &offset=N
```

Auth header: `apikey: <SUPABASE_ANON_KEY>` — the dashboard reads the anon key and Supabase URL from a small inline `<script>` block at the top of the file. Since the anon key is already in `.env.example` (public, not secret) this is safe to commit. The service role key is never used here.

---

## Visual Design Tokens

| Token | Value |
|-------|-------|
| Background | `#0d1117` |
| Card background | `#161b22` |
| Active card bg | `#0d1a2e` |
| Border | `#21262d` |
| Active border | `#1f4b8f` |
| Text primary | `#e6edf3` |
| Text secondary | `#8b949e` |
| Text muted | `#484f58` |
| Green (done) | `#3fb950` |
| Blue (active) | `#58a6ff` |
| Amber (warning) | `#d29922` |
| Red (error) | `#f85149` |

---

## Out of Scope

- Auto-refresh interval (manual Refresh button is enough)
- Prices table view (too many rows to browse meaningfully; counts suffice)
- Search / filter within tables (future addition if needed)
- Authentication (local dev tool only)

---

## Definition of Done

- [ ] Open `dashboard.html` in browser with no server — phases render immediately (hardcoded)
- [ ] On load, all three DB table cards fetch and populate with live Supabase data
- [ ] "Show more" loads next 10 rows per table
- [ ] Refresh button re-fetches all live data
- [ ] Current Focus hero correctly reflects the active phase and next task
