"""
Deterministic DEF 14A (annual proxy statement) fetch. No LLM calls here.

The proxy is where executive compensation, the "pay vs. performance" comparison,
and governance/board detail live -- content the 10-Q/10-K don't cover. Filed
once a year, so less timely than other filings, but rich when available.
"""

from data.edgar_utils import get_cik_for_ticker, get_submissions, fetch_document
from data.edgar_text import strip_html, select_prose_window
from config import MAX_FILING_CHARS

# Two patterns for the same thing, because filers phrase the real heading
# differently and neither alone is universal (found live: AAPL defines the
# "(CD&A)" abbreviation right at the heading; MBLY never defines it at all,
# and its real heading only self-identifies via "...this Compensation
# Discussion and Analysis section describes/explains..."). Critically,
# proxies -- unlike 10-K/10-Q Item headings -- routinely reference the CD&A
# section BY NAME again afterward (a pay-vs-performance table, a say-on-pay
# proposal), so "last occurrence wins" alone is not safe here the way it is
# for edgar_text.select_prose_window's Item-number headings; both patterns
# below specifically require self-referential language ("(CD&A)" or
# "section describes/explains") that a mere backward citation ("as discussed
# in the Compensation Discussion and Analysis section of...") doesn't use,
# and the last MATCHING occurrence of that narrower pattern is the real
# heading in both filers tested live.
CDA_HEADING = r"Compensation Discussion and Analysis\s*.{0,10}CD&A|Compensation Discussion and Analysis[^.]{0,100}?(?:explains|describes)"


def fetch_proxy_raw(ticker: str) -> dict:
    """
    Returns the most recent DEF 14A as plain text (cover info + Compensation
    Discussion and Analysis section where found). Never raises -- this is a
    valuable extra, not a hard requirement for the pipeline to run.
    """
    try:
        cik = get_cik_for_ticker(ticker)
        if not cik:
            return {"filing_date": None, "text": None, "note": f"Could not resolve SEC CIK for ticker '{ticker}'."}

        submissions = get_submissions(cik)
        recent = submissions.get("filings", {}).get("recent", {})
        forms = recent.get("form", [])
        dates = recent.get("filingDate", [])
        accession_numbers = recent.get("accessionNumber", [])
        primary_documents = recent.get("primaryDocument", [])

        idx = next((i for i, f in enumerate(forms) if f == "DEF 14A"), None)
        if idx is None:
            return {"filing_date": None, "text": None, "note": "No recent DEF 14A proxy statement found."}

        filing_date = dates[idx]
        html = fetch_document(cik, accession_numbers[idx], primary_documents[idx])
        text = select_prose_window(
            strip_html(html), MAX_FILING_CHARS, CDA_HEADING,
            "skipped ahead to Compensation Discussion and Analysis",
        )

        if len(text) < 200:
            return {"filing_date": filing_date, "text": None, "note": f"Proxy text too short/empty ({filing_date})."}

        return {"filing_date": filing_date, "text": text, "note": None}

    except Exception as e:
        return {"filing_date": None, "text": None, "note": f"Proxy fetch failed: {e}"}


if __name__ == "__main__":
    import sys
    import json
    ticker = sys.argv[1] if len(sys.argv) > 1 else "AAPL"
    print(json.dumps(fetch_proxy_raw(ticker), indent=2))
