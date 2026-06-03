import re
from abc import ABC, abstractmethod


class BaseParser(ABC):
    @abstractmethod
    def parse(self, filing: dict, html: str) -> list[dict]:
        """Parse raw filing HTML into event dicts ready for upsert_events()."""

    @staticmethod
    def _clean_text(html: str) -> str:
        text = re.sub(r"<[^>]+>", " ", html)
        return re.sub(r"\s+", " ", text).strip()

    @staticmethod
    def _extract_item_sections(html: str) -> dict[str, str]:
        """Return {item_code: section_text} for 8-K item blocks."""
        text = re.sub(r"<[^>]+>", " ", html)
        pattern = r"[Ii]tem\s+(\d+\.\d+)[^\n]*\n(.*?)(?=[Ii]tem\s+\d+\.\d+|\Z)"
        matches = re.findall(pattern, text, re.DOTALL)
        return {code.strip(): content.strip()[:4000] for code, content in matches}
