import sys
from datetime import date, timedelta
import pandas as pd
import yfinance as yf
from wsd.config import Settings
from wsd import db

BATCH_SIZE = 50


def ingest_prices(settings: Settings) -> dict:
    client = db.get_client(settings)
    companies = client.table("companies").select("id,ticker,entry_date").execute().data

    if not companies:
        print("ERROR: No companies found. Run universe ingestion first.")
        sys.exit(1)

    existing = client.table("prices").select("company_id,trading_date").execute().data
    max_dates: dict[str, str] = {}
    for row in existing:
        cid, td = row["company_id"], row["trading_date"]
        if cid not in max_dates or td > max_dates[cid]:
            max_dates[cid] = td

    price_start = settings.price_start_date
    end = date.today()
    total_upserted = failed = dropped = 0

    for i in range(0, len(companies), BATCH_SIZE):
        u, f, d = _ingest_batch(companies[i : i + BATCH_SIZE], max_dates, price_start, end, settings)
        total_upserted += u
        failed += f
        dropped += d

    return {"upserted": total_upserted, "failed": failed, "dropped": dropped}


def _ingest_batch(
    batch: list[dict],
    max_dates: dict[str, str],
    price_start: date,
    end: date,
    settings: Settings,
) -> tuple[int, int, int]:
    ticker_map = {c["ticker"]: c for c in batch}
    tickers = list(ticker_map.keys())

    starts = {
        c["ticker"]: _get_start_date(c["id"], max_dates, price_start, date.fromisoformat(c["entry_date"]))
        for c in batch
    }
    batch_start = min(starts.values())

    try:
        raw = yf.download(
            tickers=" ".join(tickers),
            start=batch_start.isoformat(),
            end=end.isoformat(),
            auto_adjust=True,
            progress=False,
            group_by="ticker",
        )
    except Exception as exc:
        print(f"  ERROR downloading batch: {exc}")
        return 0, len(tickers), 0

    rows: list[dict] = []
    failed = dropped = 0

    for ticker in tickers:
        company = ticker_map[ticker]
        try:
            df = raw[ticker] if len(tickers) > 1 else raw
            if df is None or df.empty:
                _log_ticker_failure(ticker, company["id"], settings)
                failed += 1
                continue
            df = df[df.index >= pd.Timestamp(starts[ticker])].dropna(subset=["Close"])
            valid = _build_price_rows(df, company["id"], ticker)
            dropped += len(df) - len(valid)
            rows.extend(valid)
        except Exception as exc:
            print(f"  ERROR processing {ticker}: {exc}")
            failed += 1

    upserted = db.upsert_prices(rows, settings) if rows else 0
    return upserted, failed, dropped


def _build_price_rows(df: pd.DataFrame, company_id: str, ticker: str) -> list[dict]:
    rows: list[dict] = []
    for dt, row in df.iterrows():
        adj_close = float(row.get("Close") or 0)
        high = float(row.get("High") or 0)
        low = float(row.get("Low") or 0)
        if adj_close <= 0 or high < low:
            continue
        rows.append({
            "company_id": company_id,
            "trading_date": dt.date().isoformat(),
            "open": float(row["Open"]) if pd.notna(row.get("Open")) else None,
            "high": high,
            "low": low,
            "close": adj_close,
            "adj_close": adj_close,
            "volume": int(row["Volume"]) if pd.notna(row.get("Volume")) else None,
        })
    return rows


def _get_start_date(company_id: str, max_dates: dict[str, str], price_start: date, entry_date: date) -> date:
    if company_id in max_dates:
        return date.fromisoformat(max_dates[company_id]) + timedelta(days=1)
    return max(price_start, entry_date)


def _log_ticker_failure(ticker: str, company_id: str, settings: Settings) -> None:
    db.insert_quality_log([{
        "check_type": "other",
        "company_id": company_id,
        "severity": "warning",
        "message": f"yfinance returned no data for ticker {ticker}",
        "details": {"ticker": ticker},
    }], settings)


if __name__ == "__main__":
    settings = Settings()
    print("Starting price ingestion...")
    result = ingest_prices(settings)
    print(f"Prices ingested: {result['upserted']:,} rows upserted, {result['failed']} tickers failed, {result['dropped']} rows dropped (validation)")
