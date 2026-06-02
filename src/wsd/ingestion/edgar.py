import sys
from wsd.config import Settings
from wsd import db
from wsd.utils import edgar_get

EDGAR_BASE = "https://data.sec.gov/submissions"
TARGET_FORMS = {"8-K", "10-Q", "10-K", "4"}


def ingest_edgar(settings: Settings) -> dict:
    client = db.get_client(settings)
    companies = (
        client.table("companies")
        .select("id,cik,ticker")
        .not_.is_("cik", "null")
        .execute()
        .data
    )

    if not companies:
        print("ERROR: No companies with CIKs found. Run universe ingestion first.")
        sys.exit(1)

    processed = errors = 0

    for company in companies:
        try:
            filings = _fetch_filings(company["cik"], company["id"], settings)
            db.upsert_filings(filings, settings)
            processed += 1
        except Exception as exc:
            print(f"  ERROR {company['ticker']}: {exc}")
            errors += 1

    return {"processed": processed, "errors": errors}


def _fetch_filings(cik: str, company_id: str, settings: Settings) -> list[dict]:
    cik_padded = cik.strip().zfill(10)
    data = edgar_get(f"{EDGAR_BASE}/CIK{cik_padded}.json", settings)

    rows: list[dict] = []
    rows.extend(_parse_filing_block(data.get("filings", {}).get("recent", {}), company_id, cik))

    for file_ref in data.get("filings", {}).get("files", []):
        page = edgar_get(f"{EDGAR_BASE}/{file_ref['name']}", settings)
        rows.extend(_parse_filing_block(page, company_id, cik))

    return rows


def _parse_filing_block(block: dict, company_id: str, cik: str) -> list[dict]:
    if not block:
        return []

    rows: list[dict] = []
    for form, accession, filed, period in zip(
        block.get("form", []),
        block.get("accessionNumber", []),
        block.get("filingDate", []),
        block.get("reportDate", []),
    ):
        if form not in TARGET_FORMS:
            continue
        # Null out period_date if it's after filed_date (EDGAR data quality issue
        # seen on some Form 4s where reportDate > filingDate)
        safe_period = (period or None) if (not period or period <= filed) else None
        rows.append({
            "company_id": company_id,
            "cik": cik,
            "accession_number": accession,
            "form_type": form,
            "filed_date": filed,        # public availability date — always filed_date
            "period_date": safe_period,
            "filing_url": f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={cik}&type={form}",
            "is_parsed": False,
        })

    return rows


if __name__ == "__main__":
    settings = Settings()
    print("Starting EDGAR ingestion...")
    result = ingest_edgar(settings)
    print(f"EDGAR ingestion complete: {result['processed']} processed, {result['errors']} errors")
