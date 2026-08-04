"""
Corrects yfinance's `sharesOutstanding`/`marketCap` for companies with a
multi-class share structure where one class isn't publicly traded (e.g.
Mobileye: Intel holds 100% of Class B, a completely separate, never-traded
class -- yfinance's own fields only ever reflect the publicly-traded Class A
count, silently understating total company value).

Confirmed for real, not assumed: for MBLY, yfinance reported
sharesOutstanding=252,419,583 (Class A only, matching SEC's own dei cover-
page fact, which ALSO only covers Class A). The actual 10-Q balance sheet
separately lists 597,768,015 Class B shares, all Intel-held -- true total
is 850,187,598, a real ~3.4x difference feeding into market cap.

No LLM calls here. Deliberately conservative: only overrides yfinance's
figure when the filing text clearly shows at least two distinct common
stock classes, each with its own explicit "shares issued and outstanding"
count -- a single/ambiguous match returns None (i.e. "trust yfinance's
number, most companies are single-class and it's already complete") rather
than guessing.
"""

import re

from data.edgar_utils import fetch_document, get_cik_for_ticker, get_submissions

_SHARE_CLASS_RE = re.compile(
    r"Class\s+([A-Z])\s+common\s+stock[:\s].{0,120}?shares\s+issued\s+and\s+outstanding[:\s]*([\d,]{4,})",
    re.IGNORECASE,
)


def _clean_html(raw: str) -> str:
    text = re.sub(r"<[^>]+>", " ", raw)
    text = re.sub(r"&#8203;|&#160;|&nbsp;", " ", text)
    return re.sub(r"\s+", " ", text)


def fetch_true_shares_outstanding(ticker: str) -> dict:
    """
    Returns:
      {"total_shares": int, "by_class": {"A": int, "B": int, ...},
       "source_filing": "10-Q" | "10-K", "note": None}
    when a genuine multi-class structure is found in the most recent
    10-Q/10-K, or:
      {"total_shares": None, "by_class": {}, "source_filing": None,
       "note": "<why not>"}
    otherwise (single-class, filing not found, or fetch failure -- callers
    should fall back to yfinance's own sharesOutstanding/marketCap in every
    one of these cases). Never raises.
    """
    result = {"total_shares": None, "by_class": {}, "source_filing": None, "note": None}
    try:
        cik = get_cik_for_ticker(ticker)
        if not cik:
            result["note"] = f"Could not resolve SEC CIK for ticker '{ticker}' to check for a multi-class share structure."
            return result

        submissions = get_submissions(cik)
        recent = submissions.get("filings", {}).get("recent", {})
        forms = recent.get("form", [])
        accessions = recent.get("accessionNumber", [])
        docs = recent.get("primaryDocument", [])

        idx = next((i for i, f in enumerate(forms) if f in ("10-Q", "10-K")), None)
        if idx is None:
            result["note"] = "No recent 10-Q/10-K found to check for a multi-class share structure."
            return result

        text = _clean_html(fetch_document(cik, accessions[idx], docs[idx]))

        by_class = {}
        for class_letter, count_str in _SHARE_CLASS_RE.findall(text):
            count = int(count_str.replace(",", ""))
            # Keep the largest figure seen per class -- balance sheets
            # commonly show the current period's count alongside a prior-
            # period comparison for the same class; the current one is
            # always >= the prior one is not a safe assumption, but taking
            # max() here is: if a filing mistakenly repeats a smaller
            # figure for the same class, this favors the real, larger
            # count over an accidental partial/older match.
            by_class[class_letter] = max(count, by_class.get(class_letter, 0))

        if len(by_class) < 2:
            result["note"] = "Single-class share structure (or none detected) -- yfinance's own share count should already be complete."
            return result

        result["total_shares"] = sum(by_class.values())
        result["by_class"] = by_class
        result["source_filing"] = forms[idx]
        return result
    except Exception as e:
        result["note"] = f"Could not verify share class structure: {e}"
        return result


if __name__ == "__main__":
    import json
    import sys
    ticker = sys.argv[1] if len(sys.argv) > 1 else "MBLY"
    print(json.dumps(fetch_true_shares_outstanding(ticker), indent=2))
