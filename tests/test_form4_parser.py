FORM4_XML_BUY = """<?xml version="1.0"?>
<ownershipDocument>
  <reportingOwner>
    <reportingOwnerId><rptOwnerName>John Smith</rptOwnerName></reportingOwnerId>
    <reportingOwnerRelationship>
      <isOfficer>1</isOfficer>
      <officerTitle>Chief Executive Officer</officerTitle>
    </reportingOwnerRelationship>
  </reportingOwner>
  <nonDerivativeTable>
    <nonDerivativeTransaction>
      <transactionDate><value>2024-01-15</value></transactionDate>
      <transactionCoding><transactionCode>P</transactionCode></transactionCoding>
      <transactionAmounts>
        <transactionShares><value>10000</value></transactionShares>
        <transactionPricePerShare><value>150.00</value></transactionPricePerShare>
        <transactionAcquiredDisposedCode><value>A</value></transactionAcquiredDisposedCode>
      </transactionAmounts>
    </nonDerivativeTransaction>
  </nonDerivativeTable>
</ownershipDocument>"""

FORM4_XML_SELL_LARGE = """<?xml version="1.0"?>
<ownershipDocument>
  <reportingOwner>
    <reportingOwnerId><rptOwnerName>Jane Doe</rptOwnerName></reportingOwnerId>
    <reportingOwnerRelationship><isOfficer>1</isOfficer><officerTitle>CFO</officerTitle></reportingOwnerRelationship>
  </reportingOwner>
  <nonDerivativeTable>
    <nonDerivativeTransaction>
      <transactionDate><value>2024-01-20</value></transactionDate>
      <transactionCoding><transactionCode>S</transactionCode></transactionCoding>
      <transactionAmounts>
        <transactionShares><value>10000</value></transactionShares>
        <transactionPricePerShare><value>200.00</value></transactionPricePerShare>
        <transactionAcquiredDisposedCode><value>D</value></transactionAcquiredDisposedCode>
      </transactionAmounts>
    </nonDerivativeTransaction>
  </nonDerivativeTable>
</ownershipDocument>"""

FILING = {
    "id": "uuid-filing-1",
    "company_id": "uuid-company-1",
    "cik": "0000320193",
    "accession_number": "0000320193-24-000001",
    "form_type": "4",
    "filed_date": "2024-01-15",
}


def test_form4_buy_large_classification():
    # 10000 * $150 = $1.5M → large
    from wsd.extraction.parsers.form4 import Form4Parser
    events = Form4Parser().parse(FILING, FORM4_XML_BUY)
    assert len(events) == 1
    assert events[0]["event_code"] == "insider_buy_large"
    assert events[0]["sentiment"] == "positive"
    assert events[0]["extracted_by"] == "rules"


def test_form4_buy_small_when_under_threshold():
    xml = FORM4_XML_BUY.replace("<value>150.00</value>", "<value>5.00</value>")
    from wsd.extraction.parsers.form4 import Form4Parser
    events = Form4Parser().parse(FILING, xml)
    assert events[0]["event_code"] == "insider_buy_small"


def test_form4_sell_large():
    # 10000 * $200 = $2M → large sell
    from wsd.extraction.parsers.form4 import Form4Parser
    events = Form4Parser().parse(FILING, FORM4_XML_SELL_LARGE)
    assert len(events) == 1
    assert events[0]["event_code"] == "insider_sell_large"
    assert events[0]["sentiment"] == "negative"


def test_form4_details_shape():
    from wsd.extraction.parsers.form4 import Form4Parser
    events = Form4Parser().parse(FILING, FORM4_XML_BUY)
    d = events[0]["details"]
    assert "shares" in d
    assert "value_usd" in d
    assert "transaction_date" in d


def test_form4_magnitude_in_millions():
    from wsd.extraction.parsers.form4 import Form4Parser
    events = Form4Parser().parse(FILING, FORM4_XML_BUY)
    # 10000 * 150 = 1,500,000 → 1.5 $M
    assert abs(events[0]["magnitude"] - 1.5) < 0.01


def test_form4_malformed_xml_returns_empty():
    from wsd.extraction.parsers.form4 import Form4Parser
    events = Form4Parser().parse(FILING, "<bad xml>>>")
    assert events == []


def test_form4_skips_non_open_market_codes():
    xml = FORM4_XML_BUY.replace("<transactionCode>P</transactionCode>",
                                "<transactionCode>A</transactionCode>")
    from wsd.extraction.parsers.form4 import Form4Parser
    events = Form4Parser().parse(FILING, xml)
    assert events == []
