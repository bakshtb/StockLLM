"""
Deterministic valuation fetch via Financial Modeling Prep. No LLM calls here.

Adds two things not already in the bundle:
  - A DCF (discounted cash flow) fair-value estimate -- a second, independent
    valuation anchor alongside yfinance's own analyst price targets, for the
    Bull/Bear/Judge fair-value estimate (see agents/prompts/*.md).
  - PEG ratio (P/E relative to earnings growth) -- fundamentals.pe_ratio and
    forward_pe exist already, but nothing in the bundle adjusts P/E for
    growth, which is the whole point of a PEG ratio and a genuinely different
    read on "expensive vs. cheap" than a bare P/E.

FMP's API has moved between versioned endpoint paths over time (v3 -- marked
"legacy" but still live -- vs. their newer "stable" namespace); this uses the
v3 paths since they're the most consistently documented. Entirely optional
(FMP_API_KEY) -- if the key is missing or either endpoint's shape has moved
again, this comes back empty with a note rather than breaking the bundle.
"""

import requests

from config import FMP_API_KEY

FMP_BASE_URL = "https://financialmodelingprep.com/api/v3"
FMP_REQUEST_TIMEOUT = 10


def fetch_fmp_valuation(ticker: str) -> dict:
    """
    Returns FMP's DCF fair-value estimate and PEG ratio for this ticker.
    Never raises -- this is a valuable extra, not a hard requirement for the
    pipeline to run.
    """
    result = {"dcf_value": None, "dcf_stock_price": None, "peg_ratio": None, "note": None}

    if not FMP_API_KEY:
        return result  # silently omitted, not an error -- this data source is optional

    notes = []

    try:
        resp = requests.get(
            f"{FMP_BASE_URL}/discounted-cash-flow/{ticker}",
            params={"apikey": FMP_API_KEY}, timeout=FMP_REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()
        if data:
            row = data[0] if isinstance(data, list) else data
            result["dcf_value"] = round(float(row["dcf"]), 2) if row.get("dcf") is not None else None
            result["dcf_stock_price"] = round(float(row["Stock Price"]), 2) if row.get("Stock Price") is not None else None
    except Exception as e:
        notes.append(f"FMP DCF fetch failed: {e}")

    try:
        resp = requests.get(
            f"{FMP_BASE_URL}/ratios-ttm/{ticker}",
            params={"apikey": FMP_API_KEY}, timeout=FMP_REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()
        if data:
            row = data[0] if isinstance(data, list) else data
            peg = row.get("pegRatioTTM")
            result["peg_ratio"] = round(float(peg), 2) if peg is not None else None
    except Exception as e:
        notes.append(f"FMP ratios fetch failed: {e}")

    result["note"] = " ".join(notes) if notes else None
    return result


if __name__ == "__main__":
    import sys
    import json
    ticker = sys.argv[1] if len(sys.argv) > 1 else "AAPL"
    print(json.dumps(fetch_fmp_valuation(ticker), indent=2))
