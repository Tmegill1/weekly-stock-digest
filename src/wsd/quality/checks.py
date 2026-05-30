from datetime import date, timedelta
import pandas as pd
from wsd.config import Settings
from wsd import db

STALE_THRESHOLD_DAYS = 5
ANOMALY_THRESHOLD = 0.50
MISSING_FILING_DAYS = 100
ANOMALY_LOOKBACK_DAYS = 90


def run_checks(settings: Settings) -> dict:
    client = db.get_client(settings)
    logs: list[dict] = []

    stale_rows = client.table("prices").select("company_id, trading_date.max()").execute().data
    logs.extend(_check_stale_prices(stale_rows))

    cutoff_anomaly = (date.today() - timedelta(days=ANOMALY_LOOKBACK_DAYS)).isoformat()
    anomaly_rows = (
        client.table("prices")
        .select("company_id, trading_date, adj_close")
        .gte("trading_date", cutoff_anomaly)
        .execute()
        .data
    )
    logs.extend(_check_price_anomalies(anomaly_rows))

    active = (
        client.table("companies")
        .select("id, ticker")
        .is_("exit_date", "null")
        .eq("is_benchmark", False)
        .execute()
        .data
    )
    cutoff_filing = (date.today() - timedelta(days=MISSING_FILING_DAYS)).isoformat()
    recent_filings = (
        client.table("filings")
        .select("company_id, filed_date")
        .eq("form_type", "10-Q")
        .gte("filed_date", cutoff_filing)
        .execute()
        .data
    )
    filings_by_company: dict[str, list] = {}
    for f in recent_filings:
        filings_by_company.setdefault(f["company_id"], []).append(f)
    logs.extend(_check_missing_filings(active, filings_by_company))

    if logs:
        db.insert_quality_log(logs, settings)

    return {
        "errors": sum(1 for l in logs if l["severity"] == "error"),
        "warnings": sum(1 for l in logs if l["severity"] == "warning"),
    }


def _check_stale_prices(rows: list[dict]) -> list[dict]:
    cutoff = (date.today() - timedelta(days=STALE_THRESHOLD_DAYS)).isoformat()
    logs: list[dict] = []
    for row in rows:
        max_date = row.get("max")
        if max_date and max_date < cutoff:
            logs.append({
                "check_type": "stale_price",
                "company_id": row["company_id"],
                "severity": "error",
                "message": f"Most recent price is {max_date}, more than {STALE_THRESHOLD_DAYS} days old",
                "details": {"max_trading_date": max_date},
            })
    return logs


def _check_price_anomalies(rows: list[dict]) -> list[dict]:
    if not rows:
        return []
    df = pd.DataFrame(rows)
    df["trading_date"] = pd.to_datetime(df["trading_date"])
    df = df.sort_values(["company_id", "trading_date"])
    df["pct_change"] = df.groupby("company_id")["adj_close"].pct_change()

    logs: list[dict] = []
    for _, row in df[df["pct_change"].abs() > ANOMALY_THRESHOLD].dropna().iterrows():
        logs.append({
            "check_type": "price_anomaly",
            "company_id": row["company_id"],
            "severity": "warning",
            "message": f"adj_close moved {row['pct_change']:.0%} on {row['trading_date'].date()}",
            "details": {
                "trading_date": row["trading_date"].date().isoformat(),
                "pct_change": round(float(row["pct_change"]), 4),
                "adj_close": float(row["adj_close"]),
            },
        })
    return logs


def _check_missing_filings(
    active_companies: list[dict],
    filings_by_company: dict[str, list],
) -> list[dict]:
    logs: list[dict] = []
    for company in active_companies:
        if not filings_by_company.get(company["id"]):
            logs.append({
                "check_type": "missing_filing",
                "company_id": company["id"],
                "severity": "warning",
                "message": f"No 10-Q in the last {MISSING_FILING_DAYS} days for {company['ticker']}",
                "details": {"ticker": company["ticker"]},
            })
    return logs


if __name__ == "__main__":
    settings = Settings()
    print("Running data quality checks...")
    result = run_checks(settings)
    print(f"Checks complete: {result['errors']} errors, {result['warnings']} warnings")
    if result["errors"] > 0:
        print("Query data_quality_log for details.")
