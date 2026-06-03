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
    anthropic_api_key: str = field(default_factory=lambda: _require("ANTHROPIC_API_KEY"))
    edgar_rate_limit: int = 8
    price_history_years: int = 5

    @property
    def price_start_date(self) -> date:
        return date.today() - timedelta(days=365 * self.price_history_years)
