"""
Deterministic insider transaction fetch. No LLM calls here.

Pulls recent Form 4 filings (insider buy/sell disclosures) from SEC EDGAR --
free, public, no API key. This is one of the more genuinely useful signals
available: insiders buying with their own money is a real vote of confidence.
"""

import xml.etree.ElementTree as ET

from data.edgar_utils import get_cik_for_ticker, get_submissions, fetch_document

MAX_FORM4_TO_PARSE = 8


def _parse_form4_xml(xml_text: str) -> list[dict]:
    """Extracts transaction rows from a Form 4 ownershipDocument XML."""
    transactions = []
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return transactions

    ns = ""  # Form 4 XML typically has no namespace prefix

    owner_name_el = root.find(".//reportingOwner/reportingOwnerId/rptOwnerName")
    owner_name = owner_name_el.text if owner_name_el is not None else "unknown"

    relationship = root.find(".//reportingOwner/reportingOwnerRelationship")
    title = None
    if relationship is not None:
        is_officer = relationship.findtext("isOfficer")
        officer_title = relationship.findtext("officerTitle")
        is_director = relationship.findtext("isDirector")
        truthy = {"1", "true"}
        if is_officer and is_officer.strip().lower() in truthy and officer_title:
            title = officer_title
        elif is_director and is_director.strip().lower() in truthy:
            title = "Director"

    for txn in root.findall(".//nonDerivativeTransaction"):
        date = txn.findtext("./transactionDate/value")
        code = txn.findtext("./transactionAmounts/transactionAcquiredDisposedCode/value") \
            or txn.findtext("./transactionCoding/transactionCode")
        shares = txn.findtext("./transactionAmounts/transactionShares/value")
        price = txn.findtext("./transactionAmounts/transactionPricePerShare/value")
        acquired_disposed = txn.findtext("./transactionAmounts/transactionAcquiredDisposedCode/value")

        transactions.append({
            "owner": owner_name,
            "title": title or "unknown",
            "date": date,
            "direction": "buy" if acquired_disposed == "A" else "sell" if acquired_disposed == "D" else "unknown",
            "shares": float(shares) if shares else None,
            "price_per_share": float(price) if price else None,
        })

    return transactions


def fetch_insider_transactions(ticker: str) -> dict:
    """
    Returns recent insider Form 4 transactions. If the ticker/CIK can't be
    resolved or EDGAR is unreachable, returns an empty list with a note rather
    than raising -- insider data is a nice-to-have, not a hard requirement.
    """
    try:
        cik = get_cik_for_ticker(ticker)
        if not cik:
            return {"transactions": [], "note": f"Could not resolve SEC CIK for ticker '{ticker}'."}

        submissions = get_submissions(cik)
        recent = submissions.get("filings", {}).get("recent", {})
        forms = recent.get("form", [])
        accession_numbers = recent.get("accessionNumber", [])
        primary_documents = recent.get("primaryDocument", [])

        form4_indices = [i for i, f in enumerate(forms) if f == "4"][:MAX_FORM4_TO_PARSE]

        all_transactions = []
        for i in form4_indices:
            try:
                # primaryDocument for Form 4s often points into an "xslF345X06/"
                # (or similar) viewer subfolder, which EDGAR serves as
                # pre-rendered HTML rather than the raw XML. The actual XML
                # sits at the accession root under the same filename, so strip
                # any such viewer-folder prefix before fetching.
                doc_path = primary_documents[i]
                if "/" in doc_path:
                    doc_path = doc_path.rsplit("/", 1)[-1]
                xml_text = fetch_document(cik, accession_numbers[i], doc_path)
                all_transactions.extend(_parse_form4_xml(xml_text))
            except Exception:
                continue  # skip individual filing failures, don't fail the whole fetch

        return {"transactions": all_transactions[:20], "note": None}

    except Exception as e:
        return {"transactions": [], "note": f"Insider data fetch failed: {e}"}


if __name__ == "__main__":
    import sys
    import json
    ticker = sys.argv[1] if len(sys.argv) > 1 else "AAPL"
    print(json.dumps(fetch_insider_transactions(ticker), indent=2))
