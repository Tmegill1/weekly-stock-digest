import csv
import sys
from pathlib import Path
from wsd.config import Settings
from wsd import db

VALID_EXIT_REASONS = {"delisted", "acquired", "bankrupt", "removed_from_index"}
_DATA_DIR = Path(__file__).parent.parent.parent.parent / "data"


def load_universe(settings: Settings, csv_path: Path | None = None) -> dict:
    if csv_path is None:
        csv_path = _DATA_DIR / "sp500_historical.csv"

    rows: list[dict] = []
    skipped = 0

    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for line_num, raw in enumerate(reader, start=2):
            row, error = _validate_row(raw)
            if error:
                print(f"  WARNING row {line_num}: {error} — skipping")
                skipped += 1
                continue
            rows.append(row)

    # Deduplicate on (cik, entry_date) — dual-class shares (e.g. FOXA/FOX)
    # share a CIK; keep only the first ticker encountered.
    seen: set[tuple] = set()
    deduped: list[dict] = []
    for row in rows:
        key = (row.get("cik"), row["entry_date"])
        if key in seen:
            print(f"  INFO dedup: skipping {row['ticker']} (same CIK+entry_date as earlier row)")
            skipped += 1
            continue
        seen.add(key)
        deduped.append(row)

    upserted = db.upsert_companies(deduped, settings)
    return {"upserted": upserted, "skipped": skipped}


def _validate_row(raw: dict) -> tuple[dict | None, str | None]:
    ticker = (raw.get("ticker") or "").strip()
    name = (raw.get("name") or "").strip()
    entry_date = (raw.get("entry_date") or "").strip()

    if not ticker:
        return None, "missing ticker"
    if not name:
        return None, "missing name"
    if not entry_date:
        return None, "missing entry_date"

    exit_reason = (raw.get("exit_reason") or "").strip() or None
    if exit_reason and exit_reason not in VALID_EXIT_REASONS:
        return None, f"invalid exit_reason '{exit_reason}'"

    return {
        "ticker": ticker,
        "cik": (raw.get("cik") or "").strip() or None,
        "name": name,
        "sector": (raw.get("sector") or "").strip() or None,
        "industry": (raw.get("industry") or "").strip() or None,
        "exchange": (raw.get("exchange") or "").strip() or None,
        "entry_date": entry_date,
        "exit_date": (raw.get("exit_date") or "").strip() or None,
        "exit_reason": exit_reason,
    }, None


if __name__ == "__main__":
    settings = Settings()
    print("Loading universe from CSV...")
    result = load_universe(settings)
    print(f"Universe loaded: {result['upserted']} rows upserted, {result['skipped']} skipped (validation errors)")
