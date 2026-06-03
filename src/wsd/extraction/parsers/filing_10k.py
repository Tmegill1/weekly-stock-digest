from wsd.config import Settings
from wsd.extraction.claude import extract_guidance_event
from wsd.extraction.parsers.filing_10q import TenQParser


class TenKParser(TenQParser):
    """10-K parser — identical extraction logic to 10-Q (annual vs quarterly EPS + MD&A)."""

    def parse(self, filing: dict, html: str, settings: Settings | None = None) -> list[dict]:
        return super().parse(filing, html, settings)
