from wsd.config import Settings
from wsd.extraction.claude import extract_8k_event
from wsd.extraction.parsers.base import BaseParser

_CLAUDE_ITEMS = {"1.01", "2.01", "5.02", "7.01"}
_SKIP_ITEMS = {"9.01", "9.02", "8.01"}


class EightKParser(BaseParser):
    def parse(self, filing: dict, html: str, settings: Settings | None = None) -> list[dict]:
        sections = self._extract_item_sections(html)
        events = []
        for item_code, section_text in sections.items():
            if item_code in _SKIP_ITEMS:
                continue
            if item_code not in _CLAUDE_ITEMS:
                continue
            if settings is None:
                continue
            result = extract_8k_event(section_text, settings)
            if result is None:
                continue
            events.append({
                "filing_id": filing["id"],
                "company_id": filing["company_id"],
                "event_code": result["event_code"],
                "filed_date": filing["filed_date"],
                "sentiment": result.get("sentiment", "neutral"),
                "magnitude": result.get("magnitude"),
                "details": result.get("details", {}),
                "extracted_by": "claude",
            })
        return events
