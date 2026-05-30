# Weekly Stock Digest

An educational research tool that produces a weekly digest analyzing publicly listed companies using SEC filings and free financial data. Each week it surfaces a ranked set of stocks alongside a data-backed explanation of *why* each looks interesting, and tracks how prior picks have performed against a benchmark.

> **Disclaimer:** This is a research and education tool, not a financial advisory product. All output explains reasoning and shows data — it does not tell you to buy or sell. Every output carries a "not investment advice" disclaimer.

---

## What it does

1. **Ingests** SEC EDGAR filings (8-K, 10-Q, 10-K, Form 4) and daily price data for a defined stock universe
2. **Extracts** structured events from filings: earnings surprises, 8-K item codes, insider transactions
3. **Scores** each company each week using event-study logic — how does this event type historically affect abnormal returns?
4. **Generates** a weekly digest with ranked picks, auditable reasoning, and a performance chart vs. SPY and a naive baseline
5. **Logs** every pick in an immutable paper-trading log so performance can be tracked honestly over time

---

## Project phases

| Phase | Epic | Status |
|-------|------|--------|
| 1 | Data Foundation — EDGAR + price ingestion, point-in-time storage | To Do |
| 2 | Event Extraction — 8-K parsing, earnings surprises, insider transactions | To Do |
| 3 | Scoring + Backtesting — event-study model, backtest harness, benchmarks | To Do |
| 4 | Weekly Digest — generator, performance chart, paper-trading log, scheduler | To Do |
| 5 *(deferred)* | Options Spread Module — options chain data, Greeks, spread selection | Deferred |

---

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                     Ingestion Layer                      │
│   SEC EDGAR (8-K, 10-Q, 10-K, Form 4)  +  Price Data   │
│   Every record stamped with public-availability date     │
└───────────────────────┬─────────────────────────────────┘
                        │
┌───────────────────────▼─────────────────────────────────┐
│                    Event Extraction                       │
│   8-K item codes │ Earnings surprises │ Form 4 insiders  │
│   Shared event taxonomy with expected-impact direction   │
└───────────────────────┬─────────────────────────────────┘
                        │
┌───────────────────────▼─────────────────────────────────┐
│               Scoring + Backtest Harness                  │
│   Abnormal return = actual − market-predicted return     │
│   Historical distributions by event type                 │
│   Composite score per company per week                   │
│   Strict point-in-time backtest vs. SPY + naive baseline │
└───────────────────────┬─────────────────────────────────┘
                        │
┌───────────────────────▼─────────────────────────────────┐
│                   Weekly Digest                           │
│   Ranked picks + auditable reasons + confidence          │
│   Performance chart (portfolio vs. SPY vs. naive)        │
│   Immutable paper-trading log                            │
│   Auto-generated weekly on a schedule                    │
└─────────────────────────────────────────────────────────┘
```

**Storage:** Local database. All tables support point-in-time queries via `public_date` fields.

---

## Key design decisions

These four decisions must be locked before any code is written (see [WSD-31](https://tylermegill9.atlassian.net/browse/WSD-31)):

| Decision | Constraint |
|----------|-----------|
| **Stock universe** | Start with S&P 500 — not all US equities (volume and cost balloon) |
| **Holding period** | One primary window (e.g., 1 week or 1 month) — state it consistently everywhere |
| **Pick format** | Numeric composite score + stored data-point reasons, not just prose |
| **Benchmark** | SPY (market) **and** naive equal-weighted baseline — both required |

---

## Known risks and mitigations

| Risk | Mitigation |
|------|-----------|
| **Survivorship bias** | Universe built from historical S&P 500 membership including delisted/bankrupt companies |
| **Lookahead bias** | Every record stamped with filing date (not period end date); enforced at data access layer |
| **Flaky price data** | Cache aggressively, store locally — never rely on live API calls during scoring/backtest |
| **Tiny event samples** | Report sample size (n) on every signal; suppress picks where n is below threshold |
| **Overstated backtest returns** | Transaction cost and slippage applied to all backtest entries/exits |

---

## Event study model

The scoring model is built on event studies:

1. Extract discrete events from filings (8-K item codes, earnings surprises, Form 4 insider transactions)
2. For each historical event, compute: `Abnormal Return = Stock Return − Market-Predicted Return`
3. Aggregate across many similar events → mean abnormal return + confidence interval per event type
4. When a new filing arrives, classify its event type and look up the historical distribution
5. Combine signals from recent events into a weekly composite score per company

Statistical power comes from the volume of historical events, not from finding one analogue. Confidence is always reported alongside the signal.

---

## Data sources

| Source | Data | Notes |
|--------|------|-------|
| [SEC EDGAR](https://www.sec.gov/cgi-bin/browse-edgar) | 8-K, 10-Q, 10-K, Form 4 | Free. Requires `User-Agent` header. Rate limit: 10 req/s. |
| Price data (TBD) | Daily OHLCV + adjusted close | Free sources (e.g., yfinance) are flaky — cache aggressively |
| Historical S&P 500 membership | Universe definition | Required to avoid survivorship bias |

---

## Definition of done (v1)

A weekly digest is generated automatically, lists scored picks with auditable reasoning, charts portfolio performance vs. SPY and a naive baseline, and the scoring framework has been validated on a bias-free backtest.

---

## Jira board

Issues tracked at [tylermegill9.atlassian.net/jira/software/projects/WSD](https://tylermegill9.atlassian.net/jira/software/projects/WSD/boards)

---

*This project is for educational and research purposes only. It is not investment advice.*
