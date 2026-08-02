"""
Tests for data/fetch_insider.py's _parse_form4_xml() -- specifically the fix
for a real bug found by hand (see HANDOFF.md): the code only read whether an
insider's holdings went up or down, which meant a routine stock grant/award
(millions of shares, no price, code "A") was indistinguishable from a real
open-market purchase with the insider's own cash (code "P"). Both used to be
labeled "buy" with no way to tell them apart -- exactly the distinction that
matters for "is this a genuine vote of confidence."
"""

from data.fetch_insider import _parse_form4_xml, _transaction_nature


def _form4_xml(transaction_code: str, acquired_disposed: str, shares: str, price: str | None) -> str:
    price_block = f"<transactionPricePerShare><value>{price}</value></transactionPricePerShare>" if price else ""
    return f"""<?xml version="1.0"?>
<ownershipDocument>
  <reportingOwner>
    <reportingOwnerId>
      <rptOwnerName>Test Person</rptOwnerName>
    </reportingOwnerId>
    <reportingOwnerRelationship>
      <isOfficer>1</isOfficer>
      <officerTitle>CEO</officerTitle>
    </reportingOwnerRelationship>
  </reportingOwner>
  <nonDerivativeTable>
    <nonDerivativeTransaction>
      <transactionDate><value>2026-07-10</value></transactionDate>
      <transactionCoding>
        <transactionFormType>4</transactionFormType>
        <transactionCode>{transaction_code}</transactionCode>
      </transactionCoding>
      <transactionAmounts>
        <transactionShares><value>{shares}</value></transactionShares>
        {price_block}
        <transactionAcquiredDisposedCode><value>{acquired_disposed}</value></transactionAcquiredDisposedCode>
      </transactionAmounts>
    </nonDerivativeTransaction>
  </nonDerivativeTable>
</ownershipDocument>"""


class TestParseForm4Xml:
    def test_open_market_purchase_is_flagged_as_open_market(self):
        xml = _form4_xml(transaction_code="P", acquired_disposed="A", shares="1000", price="150.00")
        txns = _parse_form4_xml(xml)
        assert len(txns) == 1
        t = txns[0]
        assert t["direction"] == "buy"
        assert t["transaction_code"] == "P"
        assert t["transaction_nature"] == "open market purchase"
        assert t["is_open_market"] is True
        assert t["price_per_share"] == 150.00

    def test_grant_or_award_is_not_flagged_as_open_market(self):
        # This is the real bug this fix addresses: a CEO's RSU vesting --
        # millions of shares, no price, code "A" -- must NOT be treated the
        # same as a real open-market purchase, even though direction is
        # still "buy" (holdings really did go up).
        xml = _form4_xml(transaction_code="A", acquired_disposed="A", shares="13988788", price=None)
        txns = _parse_form4_xml(xml)
        t = txns[0]
        assert t["direction"] == "buy"  # still true -- holdings did increase
        assert t["transaction_code"] == "A"
        assert t["transaction_nature"] == "grant or award"
        assert t["is_open_market"] is False  # the part that actually matters
        assert t["price_per_share"] is None

    def test_option_exercise_is_not_flagged_as_open_market(self):
        xml = _form4_xml(transaction_code="M", acquired_disposed="A", shares="5000", price=None)
        txns = _parse_form4_xml(xml)
        t = txns[0]
        assert t["transaction_nature"] == "option exercise"
        assert t["is_open_market"] is False

    def test_open_market_sale_is_flagged_as_open_market(self):
        xml = _form4_xml(transaction_code="S", acquired_disposed="D", shares="500", price="145.50")
        txns = _parse_form4_xml(xml)
        t = txns[0]
        assert t["direction"] == "sell"
        assert t["is_open_market"] is True

    def test_unknown_code_falls_back_to_other_with_code_shown(self):
        xml = _form4_xml(transaction_code="Z", acquired_disposed="A", shares="100", price=None)
        txns = _parse_form4_xml(xml)
        assert txns[0]["transaction_nature"] == "other (Z)"
        assert txns[0]["is_open_market"] is False

    def test_missing_transaction_code_is_unknown_not_open_market(self):
        xml = _form4_xml(transaction_code="", acquired_disposed="A", shares="100", price=None).replace(
            "<transactionCode></transactionCode>", "<transactionCode/>"
        )
        txns = _parse_form4_xml(xml)
        assert txns[0]["is_open_market"] is False


class TestTransactionNature:
    def test_none_code_is_unknown(self):
        assert _transaction_nature(None) == "unknown"

    def test_known_codes(self):
        assert _transaction_nature("P") == "open market purchase"
        assert _transaction_nature("S") == "open market sale"
        assert _transaction_nature("A") == "grant or award"
        assert _transaction_nature("M") == "option exercise"
        assert _transaction_nature("G") == "gift"

    def test_unrecognized_code_includes_raw_code(self):
        assert _transaction_nature("Q") == "other (Q)"
