"""
SEC filing fetch, split into two stages:

  1. fetch_filings_raw()  -- deterministic, no LLM calls. Fetches the most
     recent 10-K, 10-Q, AND 8-K independently (all three, not just whichever
     is newest) -- they cover different things: the 10-K has the full annual
     Risk Factors section and audited financials that a 10-Q only references
     rather than repeats; the 10-Q has the latest quarterly figures/MD&A; the
     8-K captures the latest material event, which right after earnings
     season is usually the press release itself. For an 8-K, also looks for
     an attached press-release exhibit (EX-99.x) -- the primaryDocument for
     an 8-K is just the cover page ("see attached exhibit"); the actual
     earnings release with real numbers and management quotes lives in a
     separate exhibit file in the same accession folder. This is "get all
     the data" -- it runs in --dry-run too.
  2. summarize_filing()  -- takes that raw text and summarizes it with a cheap
     model (Haiku) in a single combined call. This is the "shrink" stage --
     costs a small amount, skipped in --dry-run.

fetch_filings_digest() is a convenience wrapper that runs both stages back to
back, kept for standalone/CLI use.
"""

from data.edgar_utils import get_cik_for_ticker, get_submissions, fetch_document, find_exhibit_document
from data.edgar_text import strip_html, select_prose_window
from agents.gemini_client import call_gemini_digest
from config import MODEL_DIGEST, MAX_FILING_CHARS

DIGEST_SYSTEM_PROMPT = (
    "You are a financial filing summarizer. You will be given raw text from up to three "
    "SEC filings for the same company: a 10-K (annual report), a 10-Q (quarterly report), "
    "and/or an 8-K (current report, possibly including an earnings press release exhibit). "
    "Extract only the key facts an equity analyst would care about across all of them: "
    "revenue/earnings figures if present, guidance changes, major risks disclosed, and any "
    "notable events. Do not add outside knowledge or speculation -- only summarize what's "
    "actually in the text. If filings overlap, don't repeat the same fact twice. Respond "
    'with ONLY valid JSON: {"key_points": ["...", "..."]}'
)

# The bare phrase "Management's Discussion and Analysis" gets cited in
# unrelated cross-references throughout a 10-K (e.g. the forward-looking-
# statements boilerplate), which select_prose_window's "last occurrence"
# rule can't distinguish from the TOC/real heading using the phrase alone.
# Item 2 is the MD&A item number in a 10-Q, Item 7 in a 10-K -- prefixing
# with the item number cuts out most incidental cross-references, and the
# real section (always the LAST such occurrence) is who's left.
MD_A_HEADING = r"Item\s*(2|7)\.?\s*Management['’]s Discussion and Analysis"
FILING_TYPES = ["10-K", "10-Q", "8-K"]


def _find_earnings_exhibit(cik: str, accession_number: str) -> str | None:
    """Returns the earnings press release exhibit's filename, if this 8-K has one."""
    try:
        return find_exhibit_document(cik, accession_number, "EX-99")
    except Exception:
        return None


def _fetch_one_filing_raw(cik: str, filing_type: str, forms, dates, accession_numbers, primary_documents) -> dict:
    idx = next((i for i, f in enumerate(forms) if f == filing_type), None)
    if idx is None:
        return {"filing_type": filing_type, "filing_date": None, "text": None, "note": f"No recent {filing_type} filing found."}

    filing_date = dates[idx]
    accession_number = accession_numbers[idx]

    html = fetch_document(cik, accession_number, primary_documents[idx])
    text = strip_html(html)

    if filing_type == "8-K":
        exhibit_name = _find_earnings_exhibit(cik, accession_number)
        if exhibit_name:
            exhibit_html = fetch_document(cik, accession_number, exhibit_name)
            exhibit_text = strip_html(exhibit_html)
            # cover page is boilerplate; the exhibit (press release) is the real content
            text = text[:500] + " [...earnings press release exhibit follows...] " + exhibit_text
        text = text[:MAX_FILING_CHARS]
    else:
        text = select_prose_window(text, MAX_FILING_CHARS, MD_A_HEADING, "skipped ahead to Management's Discussion and Analysis")

    if len(text) < 200:
        return {"filing_type": filing_type, "filing_date": filing_date, "text": None,
                 "note": f"Filing text too short/empty ({filing_type}, {filing_date})."}

    return {"filing_type": filing_type, "filing_date": filing_date, "text": text, "note": None}


def fetch_filings_raw(ticker: str) -> dict:
    """
    Returns the most recent 10-K, 10-Q, and 8-K as plain text, keyed by
    filing type -- e.g. {"10-K": {...}, "10-Q": {...}, "8-K": {...}}. No LLM
    calls. Never raises -- filings data is a valuable extra, not a hard
    requirement for the pipeline to run.
    """
    try:
        cik = get_cik_for_ticker(ticker)
        if not cik:
            note = f"Could not resolve SEC CIK for ticker '{ticker}'."
            return {t: {"filing_type": t, "filing_date": None, "text": None, "note": note} for t in FILING_TYPES}

        submissions = get_submissions(cik)
        recent = submissions.get("filings", {}).get("recent", {})
        forms = recent.get("form", [])
        dates = recent.get("filingDate", [])
        accession_numbers = recent.get("accessionNumber", [])
        primary_documents = recent.get("primaryDocument", [])

        return {
            t: _fetch_one_filing_raw(cik, t, forms, dates, accession_numbers, primary_documents)
            for t in FILING_TYPES
        }

    except Exception as e:
        note = f"Filing fetch failed: {e}"
        return {t: {"filing_type": t, "filing_date": None, "text": None, "note": note} for t in FILING_TYPES}


def summarize_filing(filings_raw: dict) -> dict:
    """
    Takes the output of fetch_filings_raw() and summarizes all filings that
    have text into ONE combined digest via a cheap model (a single call
    rather than one per filing, to control cost). This is the only
    LLM-calling function in this module.
    """
    available = [f for f in filings_raw.values() if f.get("text")]
    if not available:
        notes = [f.get("note") for f in filings_raw.values() if f.get("note")]
        return {"digest": None, "note": "; ".join(notes) or "No filing text available to summarize.", "cost_usd": 0.0}

    combined_text = "\n\n=====\n\n".join(
        f"FILING_TYPE: {f['filing_type']}\nFILING_DATE: {f['filing_date']}\n\nFILING_TEXT:\n{f['text']}"
        for f in available
    )

    try:
        digest_result = call_gemini_digest(MODEL_DIGEST, DIGEST_SYSTEM_PROMPT, combined_text)
        return {
            "digest": digest_result["parsed"],
            "cost_usd": digest_result["cost_usd"],
            "input_tokens": digest_result["input_tokens"],
            "output_tokens": digest_result["output_tokens"],
            "model": digest_result["model"],
            "note": None,
        }
    except Exception as e:
        return {"digest": None, "note": f"Filings digest failed: {e}", "cost_usd": 0.0}


def fetch_filings_digest(ticker: str) -> dict:
    """Convenience wrapper: raw fetch + summarize in one call. Standalone/CLI use."""
    raw = fetch_filings_raw(ticker)
    return summarize_filing(raw)


if __name__ == "__main__":
    import sys
    import json
    ticker = sys.argv[1] if len(sys.argv) > 1 else "AAPL"
    print(json.dumps(fetch_filings_digest(ticker), indent=2))
