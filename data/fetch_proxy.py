"""
DEF 14A (annual proxy statement) fetch + digest, split into two stages
(mirrors data/fetch_filings.py's own fetch_filings_raw()/summarize_filing()
split):

  1. fetch_proxy_raw()  -- deterministic, no LLM calls. Windows the same
     fetched text into TWO sizes: `text` (capped at MAX_FILING_CHARS) is
     what lands in the bundle every reasoning agent sees; `digest_text`
     (capped at the larger MAX_FILING_CHARS_FOR_DIGEST) is only ever read
     by summarize_proxy() below and never leaves this module.
  2. summarize_proxy()  -- summarizes `digest_text` with Qwen (same model/
     reasoning as the filings digest -- see config.MODEL_FILINGS_DIGEST).
     Skipped in --dry-run, like every other digest.

The proxy is where executive compensation, the "pay vs. performance" comparison,
and governance/board detail live -- content the 10-Q/10-K don't cover. Filed
once a year, so less timely than other filings, but rich when available.
"""

from data.edgar_utils import get_cik_for_ticker, get_submissions, fetch_document
from data.edgar_text import strip_html, select_prose_window
from agents.qwen_client import call_qwen_digest
from config import MODEL_FILINGS_DIGEST, MAX_FILING_CHARS, MAX_FILING_CHARS_FOR_DIGEST

DIGEST_SYSTEM_PROMPT = (
    "You are a financial filing summarizer. You will be given raw text from a company's "
    "DEF 14A annual proxy statement (executive compensation, pay-vs-performance, and "
    "governance/board detail). Extract only the key facts an equity analyst would care "
    "about: executive pay changes, pay-vs-performance disclosures, notable governance or "
    "board changes, and any say-on-pay results if present. Do not add outside knowledge or "
    'speculation -- only summarize what\'s actually in the text. Respond with ONLY valid '
    'JSON: {"key_points": ["...", "..."]}'
)

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
    Discussion and Analysis section where found). Also carries `digest_text`,
    a larger window meant only for summarize_proxy() below -- callers
    building the bundle for the reasoning agents should use `text`, not
    `digest_text` (see data/bundle.py, which strips digest_text back out
    before the bundle is assembled). No LLM calls here. Never raises --
    this is a valuable extra, not a hard requirement for the pipeline to run.
    """
    try:
        cik = get_cik_for_ticker(ticker)
        if not cik:
            return {"filing_date": None, "text": None, "digest_text": None, "note": f"Could not resolve SEC CIK for ticker '{ticker}'."}

        submissions = get_submissions(cik)
        recent = submissions.get("filings", {}).get("recent", {})
        forms = recent.get("form", [])
        dates = recent.get("filingDate", [])
        accession_numbers = recent.get("accessionNumber", [])
        primary_documents = recent.get("primaryDocument", [])

        idx = next((i for i, f in enumerate(forms) if f == "DEF 14A"), None)
        if idx is None:
            return {"filing_date": None, "text": None, "digest_text": None, "note": "No recent DEF 14A proxy statement found."}

        filing_date = dates[idx]
        html = fetch_document(cik, accession_numbers[idx], primary_documents[idx])
        full_text = strip_html(html)
        text = select_prose_window(
            full_text, MAX_FILING_CHARS, CDA_HEADING,
            "skipped ahead to Compensation Discussion and Analysis",
        )
        digest_text = select_prose_window(
            full_text, MAX_FILING_CHARS_FOR_DIGEST, CDA_HEADING,
            "skipped ahead to Compensation Discussion and Analysis",
        )

        if len(text) < 200:
            return {"filing_date": filing_date, "text": None, "digest_text": None, "note": f"Proxy text too short/empty ({filing_date})."}

        return {"filing_date": filing_date, "text": text, "digest_text": digest_text, "note": None}

    except Exception as e:
        return {"filing_date": None, "text": None, "digest_text": None, "note": f"Proxy fetch failed: {e}"}


def summarize_proxy(proxy_raw: dict) -> dict:
    """
    Takes the output of fetch_proxy_raw() and summarizes it via Qwen. Reads
    `digest_text` (the larger window), not `text` (the smaller one the
    reasoning agents get) -- this is the only LLM-calling function in this
    module. Mirrors data/fetch_filings.py's summarize_filing().
    """
    digest_text = proxy_raw.get("digest_text")
    if not digest_text:
        return {"digest": None, "note": proxy_raw.get("note") or "No proxy text available to summarize.", "cost_usd": 0.0}

    user_text = f"FILING_TYPE: DEF 14A\nFILING_DATE: {proxy_raw.get('filing_date')}\n\nFILING_TEXT:\n{digest_text}"

    try:
        digest_result = call_qwen_digest(MODEL_FILINGS_DIGEST, DIGEST_SYSTEM_PROMPT, user_text)
        return {
            "digest": digest_result["parsed"],
            "cost_usd": digest_result["cost_usd"],
            "input_tokens": digest_result["input_tokens"],
            "output_tokens": digest_result["output_tokens"],
            "model": digest_result["model"],
            "note": None,
        }
    except Exception as e:
        return {"digest": None, "note": f"Proxy digest failed: {e}", "cost_usd": 0.0}


def fetch_proxy_digest(ticker: str) -> dict:
    """Convenience wrapper: raw fetch + summarize in one call. Standalone/CLI use."""
    raw = fetch_proxy_raw(ticker)
    return summarize_proxy(raw)


if __name__ == "__main__":
    import sys
    import json
    ticker = sys.argv[1] if len(sys.argv) > 1 else "AAPL"
    print(json.dumps(fetch_proxy_digest(ticker), indent=2))
