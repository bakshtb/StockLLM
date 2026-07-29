"""
Deterministic Form 144 fetch. No LLM calls here.

Form 144 is a NOTICE OF PROPOSED SALE filed by an insider before they sell
restricted/control stock -- it's a leading signal (stated intent to sell)
rather than Form 4's lagging one (the sale already happened).
"""

import xml.etree.ElementTree as ET

from data.edgar_utils import get_cik_for_ticker, get_submissions, fetch_document, strip_xml_namespaces

MAX_FORM144_TO_PARSE = 8


def _parse_form144_xml(xml_text: str) -> dict | None:
    try:
        root = strip_xml_namespaces(ET.fromstring(xml_text))
    except ET.ParseError:
        return None

    issuer_info = root.find(".//issuerInfo")
    if issuer_info is None:
        return None

    seller = issuer_info.findtext("nameOfPersonForWhoseAccountTheSecuritiesAreToBeSold")
    relationships = [r.text for r in issuer_info.findall(".//relationshipToIssuer") if r.text]

    sec_info = root.find(".//securitiesInformation")
    units_sold = sec_info.findtext("noOfUnitsSold") if sec_info is not None else None
    market_value = sec_info.findtext("aggregateMarketValue") if sec_info is not None else None
    approx_sale_date = sec_info.findtext("approxSaleDate") if sec_info is not None else None

    return {
        "seller": seller or "unknown",
        "relationship": ", ".join(relationships) if relationships else "unknown",
        "shares_proposed_to_sell": float(units_sold) if units_sold else None,
        "aggregate_market_value_usd": float(market_value) if market_value else None,
        "approx_sale_date": approx_sale_date,
    }


def fetch_form144_notices(ticker: str) -> dict:
    """
    Returns recent Form 144 notices (proposed insider stock sales). If the
    ticker/CIK can't be resolved or EDGAR is unreachable, returns an empty
    list with a note rather than raising -- this is a nice-to-have signal,
    not a hard requirement.
    """
    try:
        cik = get_cik_for_ticker(ticker)
        if not cik:
            return {"notices": [], "note": f"Could not resolve SEC CIK for ticker '{ticker}'."}

        submissions = get_submissions(cik)
        recent = submissions.get("filings", {}).get("recent", {})
        forms = recent.get("form", [])
        accession_numbers = recent.get("accessionNumber", [])
        primary_documents = recent.get("primaryDocument", [])

        form144_indices = [i for i, f in enumerate(forms) if f == "144"][:MAX_FORM144_TO_PARSE]

        notices = []
        for i in form144_indices:
            try:
                doc_path = primary_documents[i]
                if "/" in doc_path:
                    doc_path = doc_path.rsplit("/", 1)[-1]
                xml_text = fetch_document(cik, accession_numbers[i], doc_path)
                parsed = _parse_form144_xml(xml_text)
                if parsed:
                    notices.append(parsed)
            except Exception:
                continue  # skip individual filing failures, don't fail the whole fetch

        return {"notices": notices, "note": None}

    except Exception as e:
        return {"notices": [], "note": f"Form 144 fetch failed: {e}"}


if __name__ == "__main__":
    import sys
    import json
    ticker = sys.argv[1] if len(sys.argv) > 1 else "AAPL"
    print(json.dumps(fetch_form144_notices(ticker), indent=2))
