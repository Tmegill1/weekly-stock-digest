from wsd.config import Settings
from wsd import db
from wsd.extraction.downloader import download_filing
from wsd.extraction.parsers.form4 import Form4Parser
from wsd.extraction.parsers.filing_8k import EightKParser
from wsd.extraction.parsers.filing_10q import TenQParser
from wsd.extraction.parsers.filing_10k import TenKParser

def run_extraction(settings: Settings, batch_size: int = 500) -> dict:
    parsers = {
        "4":    Form4Parser,
        "8-K":  EightKParser,
        "10-Q": TenQParser,
        "10-K": TenKParser,
    }

    client = db.get_client(settings)

    total = client.table("filings").select("id", count="exact").eq("is_parsed", False).execute().count or 0

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
        parser_cls = parsers.get(form_type)

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
