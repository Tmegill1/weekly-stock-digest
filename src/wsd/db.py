from supabase import create_client, Client
from wsd.config import Settings

_clients: dict[str, Client] = {}


def get_client(settings: Settings) -> Client:
    if settings.supabase_url not in _clients:
        _clients[settings.supabase_url] = create_client(
            settings.supabase_url, settings.supabase_service_key
        )
    return _clients[settings.supabase_url]


def upsert_companies(rows: list[dict], settings: Settings) -> int:
    if not rows:
        return 0
    result = (
        get_client(settings)
        .table("companies")
        .upsert(rows, on_conflict="cik,entry_date")
        .execute()
    )
    return len(result.data)


def upsert_prices(rows: list[dict], settings: Settings) -> int:
    if not rows:
        return 0
    result = (
        get_client(settings)
        .table("prices")
        .upsert(rows, on_conflict="company_id,trading_date")
        .execute()
    )
    return len(result.data)


def upsert_filings(rows: list[dict], settings: Settings) -> int:
    if not rows:
        return 0
    result = (
        get_client(settings)
        .table("filings")
        .upsert(rows, on_conflict="accession_number")
        .execute()
    )
    return len(result.data)


def insert_quality_log(rows: list[dict], settings: Settings) -> None:
    if not rows:
        return
    get_client(settings).table("data_quality_log").insert(rows).execute()


def upsert_events(rows: list[dict], settings: Settings) -> int:
    if not rows:
        return 0
    result = (
        get_client(settings)
        .table("events")
        .upsert(rows, on_conflict="filing_id,event_code")
        .execute()
    )
    return len(result.data)


def mark_filing_parsed(filing_id: str, settings: Settings) -> None:
    get_client(settings).table("filings").update({"is_parsed": True}).eq("id", filing_id).execute()
