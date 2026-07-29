"""
Deterministic Schedule 13D/13G fetch. No LLM calls here.

These are beneficial-ownership filings for stakes over 5% of a class of
stock. The distinction that matters: a 13G is a passive holder (index funds,
routine institutional managers -- yfinance's top-holders list is mostly
these already); a 13D means the filer states an intent to actively influence
the company (an activist building a position, a founder, an acquirer) and
includes a "Purpose of Transaction" narrative that a 13G never has. An
amendment (/A) means the position changed since the last filing.
"""

import xml.etree.ElementTree as ET

from data.edgar_utils import get_cik_for_ticker, get_submissions, fetch_document, strip_xml_namespaces

MAX_FILINGS_TO_PARSE = 8


def _first_text(elem, tag_names: list[str]):
    for tag in tag_names:
        val = elem.findtext(f".//{tag}")
        if val:
            return val
    return None


def _parse_13dg_xml(xml_text: str, is_13d: bool) -> dict | None:
    try:
        root = strip_xml_namespaces(ET.fromstring(xml_text))
    except ET.ParseError:
        return None

    reporting_person = _first_text(root, ["reportingPersonName"])
    shares = _first_text(root, ["aggregateAmountOwned", "reportingPersonBeneficiallyOwnedAggregateNumberOfShares"])
    percent = _first_text(root, ["percentOfClass", "classPercent"])
    person_type = _first_text(root, ["typeOfReportingPerson"])

    result = {
        "reporting_person": reporting_person or "unknown",
        "shares_owned": float(shares) if shares else None,
        "percent_of_class": float(percent) if percent else None,
        "type_of_reporting_person": person_type,
        "purpose": None,
    }

    if is_13d:
        purpose = root.findtext(".//item4/transactionPurpose")
        if purpose:
            result["purpose"] = purpose.strip()[:800]

    return result


def fetch_beneficial_ownership(ticker: str) -> dict:
    """
    Returns recent Schedule 13D/13G (and amendment) filings -- who holds a
    >5% stake, whether they're active (13D) or passive (13G), and their
    stated purpose if active. Never raises -- this is a valuable extra, not
    a hard requirement for the pipeline to run.
    """
    try:
        cik = get_cik_for_ticker(ticker)
        if not cik:
            return {"filings": [], "note": f"Could not resolve SEC CIK for ticker '{ticker}'."}

        submissions = get_submissions(cik)
        recent = submissions.get("filings", {}).get("recent", {})
        forms = recent.get("form", [])
        dates = recent.get("filingDate", [])
        accession_numbers = recent.get("accessionNumber", [])
        primary_documents = recent.get("primaryDocument", [])

        matches = [i for i, f in enumerate(forms) if "13D" in f or "13G" in f][:MAX_FILINGS_TO_PARSE]

        filings = []
        for i in matches:
            try:
                form = forms[i]
                doc_path = primary_documents[i]
                if "/" in doc_path:
                    doc_path = doc_path.rsplit("/", 1)[-1]
                xml_text = fetch_document(cik, accession_numbers[i], doc_path)
                parsed = _parse_13dg_xml(xml_text, is_13d="13D" in form)
                if parsed:
                    parsed["form"] = "13D" if "13D" in form else "13G"
                    parsed["is_amendment"] = form.endswith("/A")
                    parsed["filing_date"] = dates[i]
                    filings.append(parsed)
            except Exception:
                continue  # skip individual filing failures, don't fail the whole fetch

        return {"filings": filings, "note": None}

    except Exception as e:
        return {"filings": [], "note": f"Beneficial ownership fetch failed: {e}"}


if __name__ == "__main__":
    import sys
    import json
    ticker = sys.argv[1] if len(sys.argv) > 1 else "AAPL"
    print(json.dumps(fetch_beneficial_ownership(ticker), indent=2))
