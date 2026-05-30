# Phase 1 Ingestion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the `src/wsd/` Python package that ingests the historical S&P 500 universe, SEC EDGAR filings, and 5 years of price data into the Supabase database.

**Architecture:** Independent CLI modules (`universe`, `edgar`, `prices`, `quality`) sharing a common config, Supabase client, and utilities layer. Each module is runnable standalone via `python -m wsd.ingestion.<module>`. All data writes are idempotent upserts.

**Tech Stack:** Python 3.12, supabase-py v2, yfinance, requests, pandas, python-dotenv, pytest, pytest-mock

---

## File Map

| File | Action | Purpose |
|------|--------|---------|
| `pyproject.toml` | Create | Package config + dependencies |
| `src/wsd/__init__.py` | Create | Package marker |
| `src/wsd/config.py` | Create | `Settings` dataclass — reads `.env`, validates required vars |
| `src/wsd/db.py` | Create | Supabase client + typed upsert helpers |
| `src/wsd/utils.py` | Create | `RateLimiter`, `@retry` decorator, `edgar_get()` |
| `src/wsd/ingestion/__init__.py` | Create | Package marker |
| `src/wsd/ingestion/universe.py` | Create | CSV → `companies` table |
| `src/wsd/ingestion/edgar.py` | Create | EDGAR REST API → `filings` table |
| `src/wsd/ingestion/prices.py` | Create | yfinance → `prices` table |
| `src/wsd/quality/__init__.py` | Create | Package marker |
| `src/wsd/quality/checks.py` | Create | Four data quality checks → `data_quality_log` |
| `data/sp500_historical.csv` | Create | Static historical S&P 500 universe seed |
| `tests/__init__.py` | Create | Test package marker |
| `tests/test_config.py` | Create | Settings validation tests |
| `tests/test_db.py` | Create | Upsert helper tests |
| `tests/test_utils.py` | Create | RateLimiter + retry + edgar_get tests |
| `tests/test_universe.py` | Create | CSV parsing + validation tests |
| `tests/test_edgar.py` | Create | EDGAR response parsing tests |
| `tests/test_prices.py` | Create | Batch download + validation tests |
| `tests/test_checks.py` | Create | Quality check logic tests |
| `.env` | Create | Local secrets (gitignored) |

---

## Task 1: Project Scaffold

**Files:**
- Create: `pyproject.toml`
- Create: `src/wsd/__init__.py`
- Create: `src/wsd/ingestion/__init__.py`
- Create: `src/wsd/quality/__init__.py`
- Create: `tests/__init__.py`
- Create: `.env`

- [ ] **Step 1: Create `pyproject.toml`**

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "wsd"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = [
    "supabase>=2.0",
    "yfinance>=0.2",
    "requests>=2.31",
    "python-dotenv>=1.0",
    "pandas>=2.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0",
    "pytest-mock>=3.0",
]

[tool.hatch.build.targets.wheel]
packages = ["src/wsd"]

[tool.pytest.ini_options]
testpaths = ["tests"]
```

- [ ] **Step 2: Create package markers**

```bash
mkdir -p src/wsd/ingestion src/wsd/quality tests
touch src/wsd/__init__.py src/wsd/ingestion/__init__.py src/wsd/quality/__init__.py tests/__init__.py
```

- [ ] **Step 3: Create `.env` from `.env.example`**

```bash
cp .env.example .env
```

Then fill in your real values:
```
SUPABASE_URL=https://ypvwatcztbubwrpojpan.supabase.co
SUPABASE_SERVICE_KEY=<your-service-role-key-from-supabase-dashboard>
EDGAR_USER_AGENT="Tyler Megill tyler.megill9@gmail.com"
```

- [ ] **Step 4: Install the package in editable mode**

```bash
pip install -e ".[dev]"
```

Expected output ends with: `Successfully installed wsd-0.1.0`

- [ ] **Step 5: Verify pytest finds the test directory**

```bash
pytest --collect-only
```

Expected: `no tests ran` (no tests written yet, no errors)

- [ ] **Step 6: Commit**

```bash
git checkout -b feat/phase1-ingestion-pipeline
git add pyproject.toml src/ tests/
git commit -m "feat: scaffold wsd package structure"
```

---

## Task 2: `config.py` — Settings

**Files:**
- Create: `src/wsd/config.py`
- Create: `tests/test_config.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_config.py
import pytest
from datetime import date, timedelta


def test_settings_loads_required_vars(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://test.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_KEY", "test-service-key")
    monkeypatch.setenv("EDGAR_USER_AGENT", "Test User test@test.com")
    from wsd.config import Settings
    s = Settings()
    assert s.supabase_url == "https://test.supabase.co"
    assert s.supabase_service_key == "test-service-key"
    assert s.edgar_user_agent == "Test User test@test.com"
    assert s.edgar_rate_limit == 8
    assert s.price_history_years == 5


def test_settings_raises_on_missing_supabase_url(monkeypatch):
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.setenv("SUPABASE_SERVICE_KEY", "test-key")
    monkeypatch.setenv("EDGAR_USER_AGENT", "Test User test@test.com")
    from wsd.config import Settings
    with pytest.raises(ValueError, match="SUPABASE_URL"):
        Settings()


def test_settings_raises_on_missing_service_key(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://test.supabase.co")
    monkeypatch.delenv("SUPABASE_SERVICE_KEY", raising=False)
    monkeypatch.setenv("EDGAR_USER_AGENT", "Test User test@test.com")
    from wsd.config import Settings
    with pytest.raises(ValueError, match="SUPABASE_SERVICE_KEY"):
        Settings()


def test_settings_raises_on_missing_edgar_user_agent(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://test.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_KEY", "test-key")
    monkeypatch.delenv("EDGAR_USER_AGENT", raising=False)
    from wsd.config import Settings
    with pytest.raises(ValueError, match="EDGAR_USER_AGENT"):
        Settings()


def test_price_start_date_is_five_years_ago(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://test.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_KEY", "test-key")
    monkeypatch.setenv("EDGAR_USER_AGENT", "Test User test@test.com")
    from wsd.config import Settings
    s = Settings()
    expected = date.today() - timedelta(days=365 * 5)
    assert s.price_start_date == expected
```

- [ ] **Step 2: Run tests — verify they fail**

```bash
pytest tests/test_config.py -v
```

Expected: `ImportError: cannot import name 'Settings' from 'wsd.config'`

- [ ] **Step 3: Implement `config.py`**

```python
# src/wsd/config.py
import os
from dataclasses import dataclass, field
from datetime import date, timedelta
from dotenv import load_dotenv

load_dotenv()


def _require(key: str) -> str:
    value = os.environ.get(key, "").strip()
    if not value:
        raise ValueError(f"Required environment variable '{key}' is missing or empty")
    return value


@dataclass
class Settings:
    supabase_url: str = field(default_factory=lambda: _require("SUPABASE_URL"))
    supabase_service_key: str = field(default_factory=lambda: _require("SUPABASE_SERVICE_KEY"))
    edgar_user_agent: str = field(default_factory=lambda: _require("EDGAR_USER_AGENT"))
    edgar_rate_limit: int = 8
    price_history_years: int = 5

    @property
    def price_start_date(self) -> date:
        return date.today() - timedelta(days=365 * self.price_history_years)
```

- [ ] **Step 4: Run tests — verify they pass**

```bash
pytest tests/test_config.py -v
```

Expected: `5 passed`

- [ ] **Step 5: Commit**

```bash
git add src/wsd/config.py tests/test_config.py
git commit -m "feat: add Settings dataclass with env validation"
```

---

## Task 3: `db.py` — Supabase Client + Upsert Helpers

**Files:**
- Create: `src/wsd/db.py`
- Create: `tests/test_db.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_db.py
import pytest
from unittest.mock import MagicMock, patch


@pytest.fixture
def settings(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://test.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_KEY", "test-key")
    monkeypatch.setenv("EDGAR_USER_AGENT", "Test User test@test.com")
    from wsd.config import Settings
    return Settings()


def test_upsert_companies_returns_row_count(settings, mocker):
    mock_execute = MagicMock()
    mock_execute.return_value.data = [{"id": "1"}, {"id": "2"}]
    mocker.patch("wsd.db.get_client", return_value=MagicMock(
        table=lambda name: MagicMock(
            upsert=lambda rows, on_conflict=None: MagicMock(execute=mock_execute)
        )
    ))
    from wsd.db import upsert_companies
    count = upsert_companies([{"ticker": "AAPL"}, {"ticker": "MSFT"}], settings)
    assert count == 2


def test_upsert_companies_returns_zero_for_empty_list(settings, mocker):
    mocker.patch("wsd.db.get_client")
    from wsd.db import upsert_companies
    count = upsert_companies([], settings)
    assert count == 0


def test_upsert_prices_returns_zero_for_empty_list(settings, mocker):
    mocker.patch("wsd.db.get_client")
    from wsd.db import upsert_prices
    count = upsert_prices([], settings)
    assert count == 0


def test_upsert_filings_returns_zero_for_empty_list(settings, mocker):
    mocker.patch("wsd.db.get_client")
    from wsd.db import upsert_filings
    count = upsert_filings([], settings)
    assert count == 0


def test_insert_quality_log_does_nothing_for_empty_list(settings, mocker):
    mock_client = mocker.patch("wsd.db.get_client")
    from wsd.db import insert_quality_log
    insert_quality_log([], settings)
    mock_client.return_value.table.assert_not_called()
```

- [ ] **Step 2: Run tests — verify they fail**

```bash
pytest tests/test_db.py -v
```

Expected: `ImportError: cannot import name 'upsert_companies' from 'wsd.db'`

- [ ] **Step 3: Implement `db.py`**

```python
# src/wsd/db.py
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
```

- [ ] **Step 4: Run tests — verify they pass**

```bash
pytest tests/test_db.py -v
```

Expected: `5 passed`

- [ ] **Step 5: Commit**

```bash
git add src/wsd/db.py tests/test_db.py
git commit -m "feat: add Supabase client and upsert helpers"
```

---

## Task 4: `utils.py` — Rate Limiter, Retry, EDGAR Fetch

**Files:**
- Create: `src/wsd/utils.py`
- Create: `tests/test_utils.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_utils.py
import pytest
import requests
from unittest.mock import MagicMock, patch, call


@pytest.fixture
def settings(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://test.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_KEY", "test-key")
    monkeypatch.setenv("EDGAR_USER_AGENT", "Test User test@test.com")
    from wsd.config import Settings
    return Settings()


def test_rate_limiter_allows_burst():
    from wsd.utils import RateLimiter
    limiter = RateLimiter(rate=10)
    # Should not raise or block for a single acquire
    limiter.acquire()


def test_retry_succeeds_on_first_attempt():
    from wsd.utils import retry
    call_count = 0

    @retry(attempts=3, backoff=0.01)
    def succeeds():
        nonlocal call_count
        call_count += 1
        return "ok"

    result = succeeds()
    assert result == "ok"
    assert call_count == 1


def test_retry_retries_on_request_exception():
    from wsd.utils import retry
    call_count = 0

    @retry(attempts=3, backoff=0.01)
    def fails_twice():
        nonlocal call_count
        call_count += 1
        if call_count < 3:
            raise requests.RequestException("connection error")
        return "ok"

    result = fails_twice()
    assert result == "ok"
    assert call_count == 3


def test_retry_raises_after_max_attempts():
    from wsd.utils import retry
    call_count = 0

    @retry(attempts=3, backoff=0.01)
    def always_fails():
        nonlocal call_count
        call_count += 1
        raise requests.RequestException("always fails")

    with pytest.raises(requests.RequestException):
        always_fails()
    assert call_count == 3


def test_edgar_get_returns_json(settings, mocker):
    mock_response = MagicMock()
    mock_response.json.return_value = {"cik": "0000320193"}
    mock_response.raise_for_status = MagicMock()
    mocker.patch("requests.get", return_value=mock_response)
    mocker.patch("wsd.utils._get_limiter")

    from wsd.utils import edgar_get
    result = edgar_get("https://data.sec.gov/submissions/CIK0000320193.json", settings)
    assert result == {"cik": "0000320193"}


def test_edgar_get_includes_user_agent_header(settings, mocker):
    mock_response = MagicMock()
    mock_response.json.return_value = {}
    mock_response.raise_for_status = MagicMock()
    mock_get = mocker.patch("requests.get", return_value=mock_response)
    mocker.patch("wsd.utils._get_limiter")

    from wsd.utils import edgar_get
    edgar_get("https://data.sec.gov/submissions/CIK0000320193.json", settings)
    _, kwargs = mock_get.call_args
    assert kwargs["headers"]["User-Agent"] == "Test User test@test.com"
```

- [ ] **Step 2: Run tests — verify they fail**

```bash
pytest tests/test_utils.py -v
```

Expected: `ImportError: cannot import name 'RateLimiter' from 'wsd.utils'`

- [ ] **Step 3: Implement `utils.py`**

```python
# src/wsd/utils.py
import time
import threading
import functools
import requests
from wsd.config import Settings

_limiter_instance: "RateLimiter | None" = None
_limiter_lock = threading.Lock()


def _get_limiter(rate: int) -> "RateLimiter":
    global _limiter_instance
    with _limiter_lock:
        if _limiter_instance is None:
            _limiter_instance = RateLimiter(rate)
    return _limiter_instance


class RateLimiter:
    def __init__(self, rate: int) -> None:
        self.rate = rate
        self._tokens = float(rate)
        self._last = time.monotonic()
        self._lock = threading.Lock()

    def acquire(self) -> None:
        with self._lock:
            now = time.monotonic()
            elapsed = now - self._last
            self._tokens = min(float(self.rate), self._tokens + elapsed * self.rate)
            self._last = now
            if self._tokens < 1:
                sleep_time = (1.0 - self._tokens) / self.rate
                time.sleep(sleep_time)
                self._tokens = 0.0
            else:
                self._tokens -= 1.0


def retry(attempts: int = 3, backoff: float = 2.0):
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            last_exc: Exception | None = None
            for attempt in range(attempts):
                try:
                    return func(*args, **kwargs)
                except requests.HTTPError as exc:
                    wait = 60.0 if exc.response is not None and exc.response.status_code == 429 else backoff ** attempt
                    time.sleep(wait)
                    last_exc = exc
                except requests.RequestException as exc:
                    time.sleep(backoff ** attempt)
                    last_exc = exc
            raise last_exc  # type: ignore[misc]
        return wrapper
    return decorator


def edgar_get(url: str, settings: Settings) -> dict:
    limiter = _get_limiter(settings.edgar_rate_limit)

    @retry(attempts=3, backoff=2.0)
    def _fetch() -> dict:
        limiter.acquire()
        response = requests.get(url, headers={"User-Agent": settings.edgar_user_agent})
        response.raise_for_status()
        return response.json()

    return _fetch()
```

- [ ] **Step 4: Run tests — verify they pass**

```bash
pytest tests/test_utils.py -v
```

Expected: `6 passed`

- [ ] **Step 5: Commit**

```bash
git add src/wsd/utils.py tests/test_utils.py
git commit -m "feat: add RateLimiter, retry decorator, and edgar_get helper"
```

---

## Task 5: Source the S&P 500 Historical CSV

**Files:**
- Create: `data/sp500_historical.csv`

- [ ] **Step 1: Download the historical S&P 500 dataset**

```bash
mkdir -p data
curl -L "https://raw.githubusercontent.com/datasets/s-and-p-500-companies-historical/main/data/constituents-financials.csv" -o data/sp500_raw.csv 2>/dev/null || echo "Download failed — use manual method below"
```

If the above URL fails, the dataset is also available at:
`https://github.com/datasets/s-and-p-500-companies-historical`

Download and place the CSV at `data/sp500_raw.csv`.

- [ ] **Step 2: Inspect the raw file to understand its columns**

```bash
head -3 data/sp500_raw.csv
```

Note the column names. The universe.py expects: `ticker, cik, name, sector, industry, exchange, entry_date, exit_date, exit_reason`

- [ ] **Step 3: Create `data/sp500_historical.csv` with the correct headers**

If the raw file has different column names, create a normalized version. At minimum it must have `ticker`, `name`, and `entry_date`. Other fields can be empty.

Example format:
```csv
ticker,cik,name,sector,industry,exchange,entry_date,exit_date,exit_reason
AAPL,0000320193,Apple Inc,Information Technology,Technology Hardware,NASDAQ,1982-11-30,,
```

- [ ] **Step 4: Verify the file is well-formed**

```bash
python3 -c "
import csv
with open('data/sp500_historical.csv') as f:
    rows = list(csv.DictReader(f))
print(f'{len(rows)} rows')
print('Columns:', list(rows[0].keys()) if rows else 'empty')
"
```

Expected: `>= 500 rows`, columns include `ticker`, `name`, `entry_date`

- [ ] **Step 5: Commit the CSV**

```bash
git add data/sp500_historical.csv
git commit -m "data: add historical S&P 500 constituent CSV"
```

---

## Task 6: `ingestion/universe.py` — Universe Ingestion

**Files:**
- Create: `src/wsd/ingestion/universe.py`
- Create: `tests/test_universe.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_universe.py
import pytest
import csv
import io
from pathlib import Path
from unittest.mock import patch, MagicMock


@pytest.fixture
def settings(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://test.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_KEY", "test-key")
    monkeypatch.setenv("EDGAR_USER_AGENT", "Test User test@test.com")
    from wsd.config import Settings
    return Settings()


VALID_CSV = """ticker,cik,name,sector,industry,exchange,entry_date,exit_date,exit_reason
AAPL,0000320193,Apple Inc,Technology,Hardware,NASDAQ,1982-11-30,,
MSFT,0000789019,Microsoft Corp,Technology,Software,NASDAQ,1994-06-01,,
ENRN,,Enron Corp,Energy,Oil & Gas,NYSE,1986-01-01,2001-11-30,bankrupt
"""


def _make_csv(tmp_path: Path, content: str) -> Path:
    p = tmp_path / "test.csv"
    p.write_text(content)
    return p


def test_load_universe_upserts_valid_rows(settings, tmp_path, mocker):
    mock_upsert = mocker.patch("wsd.ingestion.universe.db.upsert_companies", return_value=3)
    from wsd.ingestion.universe import load_universe
    result = load_universe(settings, csv_path=_make_csv(tmp_path, VALID_CSV))
    assert result["upserted"] == 3
    assert result["skipped"] == 0
    mock_upsert.assert_called_once()
    rows = mock_upsert.call_args[0][0]
    assert len(rows) == 3


def test_load_universe_skips_row_missing_ticker(settings, tmp_path, mocker):
    mocker.patch("wsd.ingestion.universe.db.upsert_companies", return_value=1)
    bad_csv = "ticker,cik,name,sector,industry,exchange,entry_date,exit_date,exit_reason\n,0000320193,Apple Inc,Technology,Hardware,NASDAQ,1982-11-30,,\nMSFT,0000789019,Microsoft Corp,Technology,Software,NASDAQ,1994-06-01,,\n"
    from wsd.ingestion.universe import load_universe
    result = load_universe(settings, csv_path=_make_csv(tmp_path, bad_csv))
    assert result["skipped"] == 1


def test_load_universe_skips_row_missing_entry_date(settings, tmp_path, mocker):
    mocker.patch("wsd.ingestion.universe.db.upsert_companies", return_value=1)
    bad_csv = "ticker,cik,name,sector,industry,exchange,entry_date,exit_date,exit_reason\nAAPL,0000320193,Apple Inc,Technology,Hardware,NASDAQ,,,\nMSFT,0000789019,Microsoft Corp,Technology,Software,NASDAQ,1994-06-01,,\n"
    from wsd.ingestion.universe import load_universe
    result = load_universe(settings, csv_path=_make_csv(tmp_path, bad_csv))
    assert result["skipped"] == 1


def test_load_universe_skips_invalid_exit_reason(settings, tmp_path, mocker):
    mocker.patch("wsd.ingestion.universe.db.upsert_companies", return_value=1)
    bad_csv = "ticker,cik,name,sector,industry,exchange,entry_date,exit_date,exit_reason\nAAPL,0000320193,Apple Inc,Technology,Hardware,NASDAQ,1982-11-30,2020-01-01,INVALID\nMSFT,0000789019,Microsoft Corp,Technology,Software,NASDAQ,1994-06-01,,\n"
    from wsd.ingestion.universe import load_universe
    result = load_universe(settings, csv_path=_make_csv(tmp_path, bad_csv))
    assert result["skipped"] == 1


def test_validate_row_maps_fields_correctly(tmp_path, mocker):
    from wsd.ingestion.universe import _validate_row
    raw = {
        "ticker": "AAPL",
        "cik": "0000320193",
        "name": "Apple Inc",
        "sector": "Technology",
        "industry": "Hardware",
        "exchange": "NASDAQ",
        "entry_date": "1982-11-30",
        "exit_date": "",
        "exit_reason": "",
    }
    row, error = _validate_row(raw)
    assert error is None
    assert row["ticker"] == "AAPL"
    assert row["cik"] == "0000320193"
    assert row["exit_date"] is None
    assert row["exit_reason"] is None
```

- [ ] **Step 2: Run tests — verify they fail**

```bash
pytest tests/test_universe.py -v
```

Expected: `ImportError: cannot import name 'load_universe'`

- [ ] **Step 3: Implement `universe.py`**

```python
# src/wsd/ingestion/universe.py
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

    upserted = db.upsert_companies(rows, settings)
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
```

- [ ] **Step 4: Run tests — verify they pass**

```bash
pytest tests/test_universe.py -v
```

Expected: `5 passed`

- [ ] **Step 5: Commit**

```bash
git add src/wsd/ingestion/universe.py tests/test_universe.py
git commit -m "feat: add universe ingestion from S&P 500 CSV"
```

---

## Task 7: `ingestion/edgar.py` — EDGAR Filing Ingestion

**Files:**
- Create: `src/wsd/ingestion/edgar.py`
- Create: `tests/test_edgar.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_edgar.py
import pytest
from unittest.mock import MagicMock, patch


@pytest.fixture
def settings(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://test.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_KEY", "test-key")
    monkeypatch.setenv("EDGAR_USER_AGENT", "Test User test@test.com")
    from wsd.config import Settings
    return Settings()


EDGAR_RESPONSE = {
    "filings": {
        "recent": {
            "form": ["8-K", "10-Q", "DEF 14A", "4", "10-K"],
            "accessionNumber": [
                "0000320193-24-000001",
                "0000320193-24-000002",
                "0000320193-24-000003",
                "0000320193-24-000004",
                "0000320193-24-000005",
            ],
            "filingDate": ["2024-01-15", "2024-01-20", "2024-02-01", "2024-02-10", "2024-02-15"],
            "reportDate": ["2024-01-14", "2023-12-31", "2023-12-31", "2024-02-09", "2023-09-30"],
        },
        "files": [],
    }
}


def test_parse_filing_block_filters_to_target_forms():
    from wsd.ingestion.edgar import _parse_filing_block
    rows = _parse_filing_block(EDGAR_RESPONSE["filings"]["recent"], "company-uuid-123", "0000320193")
    form_types = {r["form_type"] for r in rows}
    assert form_types == {"8-K", "10-Q", "4", "10-K"}
    assert "DEF 14A" not in form_types


def test_parse_filing_block_uses_filed_date_not_period_date():
    from wsd.ingestion.edgar import _parse_filing_block
    rows = _parse_filing_block(EDGAR_RESPONSE["filings"]["recent"], "company-uuid-123", "0000320193")
    eight_k = next(r for r in rows if r["form_type"] == "8-K")
    assert eight_k["filed_date"] == "2024-01-15"
    assert eight_k["period_date"] == "2024-01-14"


def test_parse_filing_block_sets_company_id_and_cik():
    from wsd.ingestion.edgar import _parse_filing_block
    rows = _parse_filing_block(EDGAR_RESPONSE["filings"]["recent"], "company-uuid-123", "0000320193")
    assert all(r["company_id"] == "company-uuid-123" for r in rows)
    assert all(r["cik"] == "0000320193" for r in rows)


def test_parse_filing_block_sets_is_parsed_false():
    from wsd.ingestion.edgar import _parse_filing_block
    rows = _parse_filing_block(EDGAR_RESPONSE["filings"]["recent"], "company-uuid-123", "0000320193")
    assert all(r["is_parsed"] is False for r in rows)


def test_parse_filing_block_returns_empty_for_empty_block():
    from wsd.ingestion.edgar import _parse_filing_block
    rows = _parse_filing_block({}, "company-uuid-123", "0000320193")
    assert rows == []


def test_ingest_edgar_exits_if_no_companies(settings, mocker):
    mock_client = MagicMock()
    mock_client.table.return_value.select.return_value.not_.return_value.is_.return_value.execute.return_value.data = []
    mocker.patch("wsd.ingestion.edgar.db.get_client", return_value=mock_client)

    from wsd.ingestion.edgar import ingest_edgar
    with pytest.raises(SystemExit):
        ingest_edgar(settings)
```

- [ ] **Step 2: Run tests — verify they fail**

```bash
pytest tests/test_edgar.py -v
```

Expected: `ImportError: cannot import name '_parse_filing_block'`

- [ ] **Step 3: Implement `edgar.py`**

```python
# src/wsd/ingestion/edgar.py
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
    url = f"{EDGAR_BASE}/CIK{cik_padded}.json"
    data = edgar_get(url, settings)

    rows: list[dict] = []
    recent = data.get("filings", {}).get("recent", {})
    rows.extend(_parse_filing_block(recent, company_id, cik))

    for file_ref in data.get("filings", {}).get("files", []):
        page = edgar_get(f"{EDGAR_BASE}/{file_ref['name']}", settings)
        rows.extend(_parse_filing_block(page, company_id, cik))

    return rows


def _parse_filing_block(block: dict, company_id: str, cik: str) -> list[dict]:
    if not block:
        return []

    form_types = block.get("form", [])
    accessions = block.get("accessionNumber", [])
    filed_dates = block.get("filingDate", [])
    period_dates = block.get("reportDate", [])

    rows: list[dict] = []
    for form, accession, filed, period in zip(form_types, accessions, filed_dates, period_dates):
        if form not in TARGET_FORMS:
            continue
        rows.append({
            "company_id": company_id,
            "cik": cik,
            "accession_number": accession,
            "form_type": form,
            "filed_date": filed,           # public availability date — always filed_date
            "period_date": period or None,
            "filing_url": f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={cik}&type={form}",
            "is_parsed": False,
        })

    return rows


if __name__ == "__main__":
    settings = Settings()
    print("Starting EDGAR ingestion...")
    result = ingest_edgar(settings)
    print(
        f"EDGAR ingestion complete: {result['processed']} processed, "
        f"{result['errors']} errors"
    )
```

- [ ] **Step 4: Run tests — verify they pass**

```bash
pytest tests/test_edgar.py -v
```

Expected: `6 passed`

- [ ] **Step 5: Commit**

```bash
git add src/wsd/ingestion/edgar.py tests/test_edgar.py
git commit -m "feat: add EDGAR filing ingestion"
```

---

## Task 8: `ingestion/prices.py` — Price Ingestion

**Files:**
- Create: `src/wsd/ingestion/prices.py`
- Create: `tests/test_prices.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_prices.py
import pytest
import pandas as pd
from datetime import date, timedelta
from unittest.mock import MagicMock, patch


@pytest.fixture
def settings(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://test.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_KEY", "test-key")
    monkeypatch.setenv("EDGAR_USER_AGENT", "Test User test@test.com")
    from wsd.config import Settings
    return Settings()


def _make_price_df(dates: list[str]) -> pd.DataFrame:
    idx = pd.to_datetime(dates)
    return pd.DataFrame({
        "Open": [100.0] * len(dates),
        "High": [105.0] * len(dates),
        "Low": [98.0] * len(dates),
        "Close": [102.0] * len(dates),
        "Volume": [1_000_000] * len(dates),
    }, index=idx)


def test_build_price_rows_maps_fields_correctly():
    from wsd.ingestion.prices import _build_price_rows
    df = _make_price_df(["2024-01-02", "2024-01-03"])
    rows = _build_price_rows(df, "company-uuid-123", "AAPL")
    assert len(rows) == 2
    assert rows[0]["company_id"] == "company-uuid-123"
    assert rows[0]["trading_date"] == "2024-01-02"
    assert rows[0]["adj_close"] == 102.0
    assert rows[0]["high"] == 105.0
    assert rows[0]["low"] == 98.0


def test_build_price_rows_drops_invalid_adj_close():
    from wsd.ingestion.prices import _build_price_rows
    df = _make_price_df(["2024-01-02"])
    df.loc[df.index[0], "Close"] = 0.0
    rows = _build_price_rows(df, "company-uuid-123", "AAPL")
    assert rows == []


def test_build_price_rows_drops_high_less_than_low():
    from wsd.ingestion.prices import _build_price_rows
    df = _make_price_df(["2024-01-02"])
    df.loc[df.index[0], "High"] = 50.0
    df.loc[df.index[0], "Low"] = 100.0
    rows = _build_price_rows(df, "company-uuid-123", "AAPL")
    assert rows == []


def test_get_start_date_uses_max_date_plus_one_if_exists():
    from wsd.ingestion.prices import _get_start_date
    max_dates = {"company-uuid-123": "2024-06-01"}
    price_start = date(2020, 1, 1)
    entry_date = date(2015, 1, 1)
    result = _get_start_date("company-uuid-123", max_dates, price_start, entry_date)
    assert result == date(2024, 6, 2)


def test_get_start_date_uses_price_start_for_new_company():
    from wsd.ingestion.prices import _get_start_date
    max_dates = {}
    price_start = date(2020, 1, 1)
    entry_date = date(2015, 1, 1)
    result = _get_start_date("company-uuid-123", max_dates, price_start, entry_date)
    assert result == price_start


def test_get_start_date_uses_entry_date_if_later_than_price_start():
    from wsd.ingestion.prices import _get_start_date
    max_dates = {}
    price_start = date(2020, 1, 1)
    entry_date = date(2022, 6, 1)
    result = _get_start_date("company-uuid-123", max_dates, price_start, entry_date)
    assert result == entry_date
```

- [ ] **Step 2: Run tests — verify they fail**

```bash
pytest tests/test_prices.py -v
```

Expected: `ImportError: cannot import name '_build_price_rows'`

- [ ] **Step 3: Implement `prices.py`**

```python
# src/wsd/ingestion/prices.py
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
        cid = row["company_id"]
        td = row["trading_date"]
        if cid not in max_dates or td > max_dates[cid]:
            max_dates[cid] = td

    price_start = settings.price_start_date
    end = date.today()
    total_upserted = failed = dropped = 0

    for i in range(0, len(companies), BATCH_SIZE):
        batch = companies[i : i + BATCH_SIZE]
        u, f, d = _ingest_batch(batch, max_dates, price_start, end, settings)
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
        c["ticker"]: _get_start_date(
            c["id"], max_dates, price_start, date.fromisoformat(c["entry_date"])
        )
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
            ticker_start = pd.Timestamp(starts[ticker])
            df = df[df.index >= ticker_start].dropna(subset=["Close"])
            valid_rows = _build_price_rows(df, company["id"], ticker)
            dropped += len(df) - len(valid_rows)
            rows.extend(valid_rows)
        except Exception as exc:
            print(f"  ERROR processing {ticker}: {exc}")
            failed += 1

    upserted = db.upsert_prices(rows, settings) if rows else 0
    return upserted, failed, dropped


def _build_price_rows(df: pd.DataFrame, company_id: str, ticker: str) -> list[dict]:
    rows: list[dict] = []
    for dt, row in df.iterrows():
        adj_close = float(row.get("Close", 0) or 0)
        high = float(row.get("High", 0) or 0)
        low = float(row.get("Low", 0) or 0)

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


def _get_start_date(
    company_id: str,
    max_dates: dict[str, str],
    price_start: date,
    entry_date: date,
) -> date:
    if company_id in max_dates:
        return date.fromisoformat(max_dates[company_id]) + timedelta(days=1)
    return max(price_start, entry_date)


def _log_ticker_failure(ticker: str, company_id: str, settings: Settings) -> None:
    db.insert_quality_log(
        [{
            "check_type": "other",
            "company_id": company_id,
            "severity": "warning",
            "message": f"yfinance returned no data for ticker {ticker}",
            "details": {"ticker": ticker},
        }],
        settings,
    )


if __name__ == "__main__":
    settings = Settings()
    print("Starting price ingestion...")
    result = ingest_prices(settings)
    print(
        f"Prices ingested: {result['upserted']:,} rows upserted, "
        f"{result['failed']} tickers failed, "
        f"{result['dropped']} rows dropped (validation)"
    )
```

- [ ] **Step 4: Run tests — verify they pass**

```bash
pytest tests/test_prices.py -v
```

Expected: `6 passed`

- [ ] **Step 5: Commit**

```bash
git add src/wsd/ingestion/prices.py tests/test_prices.py
git commit -m "feat: add price ingestion via yfinance with 5-year window"
```

---

## Task 9: `quality/checks.py` — Data Quality Checks

**Files:**
- Create: `src/wsd/quality/checks.py`
- Create: `tests/test_checks.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_checks.py
import pytest
import pandas as pd
from datetime import date, timedelta
from unittest.mock import MagicMock


@pytest.fixture
def settings(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://test.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_KEY", "test-key")
    monkeypatch.setenv("EDGAR_USER_AGENT", "Test User test@test.com")
    from wsd.config import Settings
    return Settings()


def test_check_stale_prices_flags_old_data():
    from wsd.quality.checks import _check_stale_prices
    old_date = (date.today() - timedelta(days=10)).isoformat()
    rows = [{"company_id": "uuid-1", "max": old_date}]
    logs = _check_stale_prices(rows)
    assert len(logs) == 1
    assert logs[0]["check_type"] == "stale_price"
    assert logs[0]["severity"] == "error"
    assert logs[0]["company_id"] == "uuid-1"


def test_check_stale_prices_ignores_recent_data():
    from wsd.quality.checks import _check_stale_prices
    recent = (date.today() - timedelta(days=2)).isoformat()
    rows = [{"company_id": "uuid-1", "max": recent}]
    logs = _check_stale_prices(rows)
    assert logs == []


def test_check_price_anomalies_flags_large_moves():
    from wsd.quality.checks import _check_price_anomalies
    rows = [
        {"company_id": "uuid-1", "trading_date": "2024-01-01", "adj_close": 100.0},
        {"company_id": "uuid-1", "trading_date": "2024-01-02", "adj_close": 160.0},
    ]
    logs = _check_price_anomalies(rows)
    assert len(logs) == 1
    assert logs[0]["check_type"] == "price_anomaly"
    assert logs[0]["company_id"] == "uuid-1"


def test_check_price_anomalies_ignores_normal_moves():
    from wsd.quality.checks import _check_price_anomalies
    rows = [
        {"company_id": "uuid-1", "trading_date": "2024-01-01", "adj_close": 100.0},
        {"company_id": "uuid-1", "trading_date": "2024-01-02", "adj_close": 102.0},
    ]
    logs = _check_price_anomalies(rows)
    assert logs == []


def test_check_missing_filings_flags_companies_without_recent_10q():
    from wsd.quality.checks import _check_missing_filings
    active_companies = [{"id": "uuid-1", "ticker": "AAPL"}]
    filings_by_company: dict[str, list] = {}  # no filings for uuid-1
    logs = _check_missing_filings(active_companies, filings_by_company)
    assert len(logs) == 1
    assert logs[0]["check_type"] == "missing_filing"
    assert logs[0]["company_id"] == "uuid-1"


def test_check_missing_filings_ignores_companies_with_recent_10q():
    from wsd.quality.checks import _check_missing_filings
    active_companies = [{"id": "uuid-1", "ticker": "AAPL"}]
    recent = (date.today() - timedelta(days=30)).isoformat()
    filings_by_company = {"uuid-1": [{"filed_date": recent}]}
    logs = _check_missing_filings(active_companies, filings_by_company)
    assert logs == []
```

- [ ] **Step 2: Run tests — verify they fail**

```bash
pytest tests/test_checks.py -v
```

Expected: `ImportError: cannot import name '_check_stale_prices'`

- [ ] **Step 3: Implement `checks.py`**

```python
# src/wsd/quality/checks.py
from datetime import date, timedelta
import pandas as pd
from wsd.config import Settings
from wsd import db

STALE_THRESHOLD_DAYS = 5
ANOMALY_THRESHOLD = 0.50
MISSING_FILING_DAYS = 100
ANOMALY_LOOKBACK_DAYS = 90
GAP_LOOKBACK_DAYS = 30


def run_checks(settings: Settings) -> dict:
    client = db.get_client(settings)
    logs: list[dict] = []

    # stale prices
    stale_rows = (
        client.table("prices")
        .select("company_id, trading_date.max()")
        .execute()
        .data
    )
    logs.extend(_check_stale_prices(stale_rows))

    # price anomalies
    cutoff_anomaly = (date.today() - timedelta(days=ANOMALY_LOOKBACK_DAYS)).isoformat()
    anomaly_rows = (
        client.table("prices")
        .select("company_id, trading_date, adj_close")
        .gte("trading_date", cutoff_anomaly)
        .execute()
        .data
    )
    logs.extend(_check_price_anomalies(anomaly_rows))

    # missing 10-Q filings
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

    errors = sum(1 for l in logs if l["severity"] == "error")
    warnings = sum(1 for l in logs if l["severity"] == "warning")
    return {"errors": errors, "warnings": warnings}


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

    anomalies = df[df["pct_change"].abs() > ANOMALY_THRESHOLD].dropna()
    logs: list[dict] = []
    for _, row in anomalies.iterrows():
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
```

- [ ] **Step 4: Run tests — verify they pass**

```bash
pytest tests/test_checks.py -v
```

Expected: `6 passed`

- [ ] **Step 5: Commit**

```bash
git add src/wsd/quality/checks.py tests/test_checks.py
git commit -m "feat: add data quality checks (stale prices, anomalies, missing filings)"
```

---

## Task 10: Full Test Suite + End-to-End Smoke Test

**Files:** No new files — verification only

- [ ] **Step 1: Run the full test suite**

```bash
pytest -v
```

Expected: All tests pass. Note the exact count (should be ~28 tests).

- [ ] **Step 2: Smoke test — universe ingestion (real Supabase)**

```bash
python -m wsd.ingestion.universe
```

Expected output:
```
Loading universe from CSV...
Universe loaded: XXXX rows upserted, N skipped (validation errors)
```

Verify in Supabase dashboard: `companies` table has rows, SPY row exists with `is_benchmark=true`.

- [ ] **Step 3: Smoke test — EDGAR ingestion (limited run)**

To avoid running all 500 companies on first test, temporarily edit `edgar.py` to slice companies:

```python
# In ingest_edgar(), after fetching companies, add temporarily:
companies = companies[:5]  # test with first 5 only
```

Then run:
```bash
python -m wsd.ingestion.edgar
```

Expected:
```
Starting EDGAR ingestion...
EDGAR ingestion complete: 5 processed, 0 errors
```

Verify in Supabase: `filings` table has rows. Check that `filed_date` is populated (not `period_date`).

Remove the `[:5]` slice before committing.

- [ ] **Step 4: Smoke test — price ingestion (limited run)**

Temporarily slice to 5 companies in `prices.py`:

```python
# In ingest_prices(), after fetching companies, add temporarily:
companies = companies[:5]
```

Then run:
```bash
python -m wsd.ingestion.prices
```

Expected:
```
Starting price ingestion...
Prices ingested: X,XXX rows upserted, 0 tickers failed, 0 rows dropped (validation)
```

Verify in Supabase: `prices` table has rows. Spot-check that `adj_close > 0` and dates are within the last 5 years.

Remove the `[:5]` slice before committing.

- [ ] **Step 5: Smoke test — quality checks**

```bash
python -m wsd.quality.checks
```

Expected (before full data load — many companies will have no 10-Q yet):
```
Running data quality checks...
Checks complete: 0 errors, N warnings
```

- [ ] **Step 6: Final commit and push**

```bash
git add -A
git commit -m "test: verify full pipeline end-to-end smoke test passes"
git push -u origin feat/phase1-ingestion-pipeline
```

- [ ] **Step 7: Open PR**

```bash
gh pr create \
  --title "Phase 1: Python ingestion pipeline (universe, EDGAR, prices, quality)" \
  --body "Implements WSD-2 through WSD-8. Adds src/wsd/ package with config, db, utils, ingestion, and quality modules. All modules tested with pytest. Full pipeline verified end-to-end against Supabase."
```
