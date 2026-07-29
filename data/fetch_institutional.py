"""
Deterministic institutional ownership fetch. No LLM calls here.

NOTE / limitation: this gives a current snapshot of top institutional holders
and overall % held by institutions (via yfinance), not a true quarter-over-quarter
13F delta. A real "who's been buying/selling" trend would require diffing
consecutive 13F filings from SEC EDGAR across time, which is a heavier lift --
flagged honestly here rather than faked.
"""

import yfinance as yf


def fetch_institutional_ownership(ticker: str) -> dict:
    tk = yf.Ticker(ticker)

    top_holders = []
    try:
        holders_df = tk.institutional_holders
        if holders_df is not None and not holders_df.empty:
            for _, row in holders_df.head(5).iterrows():
                top_holders.append({
                    "holder": row.get("Holder"),
                    "shares": int(row.get("Shares")) if row.get("Shares") is not None else None,
                    "pct_out": float(row.get("pctHeld") or row.get("% Out") or 0) or None,
                    "value": row.get("Value"),
                })
    except Exception:
        pass

    pct_institutions = None
    pct_insiders = None
    try:
        major = tk.major_holders
        if major is not None and not major.empty:
            # yfinance major_holders format varies by version; try to find rows by label
            for _, row in major.iterrows():
                label = " ".join(str(v) for v in row.values).lower()
                if "institutions" in label and "%" in label:
                    pct_institutions = row.iloc[0]
                elif "insiders" in label and "%" in label:
                    pct_insiders = row.iloc[0]
    except Exception:
        pass

    return {
        "top_institutional_holders": top_holders,
        "pct_held_by_institutions": pct_institutions,
        "pct_held_by_insiders": pct_insiders,
        "note": "Snapshot of current holders, not a quarter-over-quarter change -- true 13F delta tracking not yet implemented.",
    }


if __name__ == "__main__":
    import sys
    import json
    ticker = sys.argv[1] if len(sys.argv) > 1 else "AAPL"
    print(json.dumps(fetch_institutional_ownership(ticker), indent=2))
