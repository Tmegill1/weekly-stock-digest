import xml.etree.ElementTree as ET
from wsd.extraction.parsers.base import BaseParser

_LARGE_THRESHOLD_USD = 1_000_000
_OPEN_MARKET_CODES = {"P", "S"}  # P=purchase, S=sale (open market only)


class Form4Parser(BaseParser):
    def parse(self, filing: dict, html: str) -> list[dict]:
        try:
            root = ET.fromstring(html)
        except ET.ParseError:
            return []

        events = []
        for txn in root.findall(".//nonDerivativeTransaction"):
            event = self._parse_transaction(txn, filing)
            if event:
                events.append(event)
        return events

    def _parse_transaction(self, txn: ET.Element, filing: dict) -> dict | None:
        code_el = txn.find("transactionCoding/transactionCode")
        shares_el = txn.find("transactionAmounts/transactionShares/value")
        price_el = txn.find("transactionAmounts/transactionPricePerShare/value")
        date_el = txn.find("transactionDate/value")

        if code_el is None or shares_el is None:
            return None

        code = (code_el.text or "").strip()
        if code not in _OPEN_MARKET_CODES:
            return None

        try:
            shares = float(shares_el.text or 0)
            price = float(price_el.text or 0) if price_el is not None else 0.0
        except (ValueError, TypeError):
            return None

        value_usd = shares * price
        is_buy = code == "P"
        is_large = value_usd >= _LARGE_THRESHOLD_USD

        if is_buy:
            event_code = "insider_buy_large" if is_large else "insider_buy_small"
        else:
            event_code = "insider_sell_large" if is_large else "insider_sell_small"

        return {
            "filing_id": filing["id"],
            "company_id": filing["company_id"],
            "event_code": event_code,
            "filed_date": filing["filed_date"],
            "sentiment": "positive" if is_buy else "negative",
            "magnitude": round(value_usd / 1_000_000, 4),
            "details": {
                "shares": shares,
                "value_usd": round(value_usd, 2),
                "transaction_date": date_el.text if date_el is not None else None,
            },
            "extracted_by": "rules",
        }
