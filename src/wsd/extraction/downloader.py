import requests
from pathlib import Path
from wsd.config import Settings
from wsd.utils import RateLimiter, retry

_EDGAR_ARCHIVES = "https://www.sec.gov/Archives/edgar/data"
_CACHE_DIR = Path("data/filings")

_limiter: "RateLimiter | None" = None


def _get_limiter(settings: Settings) -> RateLimiter:
    global _limiter
    if _limiter is None:
        _limiter = RateLimiter(settings.edgar_rate_limit)
    return _limiter


def _accession_nodash(accession_number: str) -> str:
    return accession_number.replace("-", "")


def _cache_path(cik: str, accession_number: str) -> Path:
    cik_stripped = cik.lstrip("0") or "0"
    return _CACHE_DIR / cik_stripped / f"{accession_number}.html"


def _fetch_json(url: str, settings: Settings) -> dict:
    limiter = _get_limiter(settings)

    @retry(attempts=3, backoff=2.0)
    def _do():
        limiter.acquire()
        resp = requests.get(url, headers={"User-Agent": settings.edgar_user_agent})
        resp.raise_for_status()
        return resp.json()

    return _do()


def _fetch_text(url: str, settings: Settings) -> str:
    limiter = _get_limiter(settings)

    @retry(attempts=3, backoff=2.0)
    def _do():
        limiter.acquire()
        resp = requests.get(url, headers={"User-Agent": settings.edgar_user_agent})
        resp.raise_for_status()
        return resp.text

    return _do()


def _find_primary_doc(index_data: dict) -> str | None:
    items = index_data.get("directory", {}).get("item", [])
    for item in items:
        name = item.get("name", "")
        if "index" in name.lower():
            continue
        if name.endswith((".htm", ".html", ".xml")):
            return name
    for item in items:
        name = item.get("name", "")
        if name.endswith(".txt") and "index" not in name.lower():
            return name
    return None


def download_filing(filing: dict, settings: Settings) -> str | None:
    """Fetch raw filing HTML from EDGAR, caching to disk. Returns text or None on failure."""
    cik = filing["cik"].lstrip("0") or "0"
    accession = filing["accession_number"]
    accession_nodash = _accession_nodash(accession)

    cache = _cache_path(filing["cik"], accession)
    if cache.exists():
        return cache.read_text(encoding="utf-8", errors="replace")

    index_url = f"{_EDGAR_ARCHIVES}/{cik}/{accession_nodash}/{accession}-index.json"
    try:
        index_data = _fetch_json(index_url, settings)
        primary_doc = _find_primary_doc(index_data)
        if not primary_doc:
            print(f"  WARNING: No primary doc found for {accession}")
            return None
        doc_url = f"{_EDGAR_ARCHIVES}/{cik}/{accession_nodash}/{primary_doc}"
        html = _fetch_text(doc_url, settings)
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(html, encoding="utf-8", errors="replace")
        return html
    except Exception as exc:
        print(f"  WARNING: Failed to download {accession}: {exc}")
        return None
