import re
from wsd.config import Settings
from wsd.extraction.claude import extract_guidance_event
from wsd.extraction.parsers.base import BaseParser

_EPS_PATTERN = re.compile(
    r'<ix:nonFraction[^>]*name="us-gaap:EarningsPerShareBasic"[^>]*contextRef="([^"]*)"[^>]*>'
    r'\s*([-\d.]+)\s*</ix:nonFraction>',
    re.IGNORECASE,
)
_MDA_PATTERN = re.compile(
    r'(?:id=["\']mda["\']|Management.{0,20}Discussion)[^>]*>(.*?)(?=<div|<section|\Z)',
    re.IGNORECASE | re.DOTALL,
)
_INLINE_TOLERANCE_PCT = 5.0  # within 5% = inline


class TenQParser(BaseParser):
    def parse(self, filing: dict, html: str, settings: Settings | None = None) -> list[dict]:
        events = []
        earnings_event = self._extract_earnings(filing, html)
        if earnings_event:
            events.append(earnings_event)
        if settings is not None:
            mda_text = self._extract_mda(html)
            if mda_text:
                result = extract_guidance_event(mda_text, settings)
                if result:
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

    def _extract_earnings(self, filing: dict, html: str) -> dict | None:
        matches = _EPS_PATTERN.findall(html)
        if len(matches) < 2:
            return None
        try:
            eps_current = float(matches[0][1])
            eps_prior = float(matches[1][1])
        except (ValueError, IndexError):
            return None
        if eps_prior == 0:
            return None
        beat_pct = (eps_current - eps_prior) / abs(eps_prior) * 100
        if beat_pct > _INLINE_TOLERANCE_PCT:
            event_code, sentiment = "earnings_beat", "positive"
        elif beat_pct < -_INLINE_TOLERANCE_PCT:
            event_code, sentiment = "earnings_miss", "negative"
        else:
            event_code, sentiment = "earnings_inline", "neutral"
        return {
            "filing_id": filing["id"],
            "company_id": filing["company_id"],
            "event_code": event_code,
            "filed_date": filing["filed_date"],
            "sentiment": sentiment,
            "magnitude": round(beat_pct, 2),
            "details": {
                "eps_current": eps_current,
                "eps_prior": eps_prior,
                "beat_pct": round(beat_pct, 2),
            },
            "extracted_by": "rules",
        }

    def _extract_mda(self, html: str) -> str | None:
        m = _MDA_PATTERN.search(html)
        if not m:
            return None
        return self._clean_text(m.group(1))[:3000]
