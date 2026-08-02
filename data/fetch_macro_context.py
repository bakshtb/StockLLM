"""
Deterministic macro-backdrop fetch. No LLM calls here.

Every other module in this bundle is ticker-specific; none of them tell the
agents anything about the market environment the ticker sits in. The same
P/E, RSI, or price move reads very differently in a risk-off, rising-rate
environment vs. a calm, low-rate one. Two free, well-known indices via
yfinance cover the near-term market mood:
  - ^VIX: the market's near-term volatility/fear gauge.
  - ^TNX: the 10-year Treasury yield, a proxy for the risk-free rate that
    directly pressures high-multiple growth stock valuations when it rises.
    Historically CBOE quoted this scaled by 10 (46.22 -> 4.622%), but the
    yfinance feed returns the plain percent directly (verified live: 4.622,
    not 46.22) -- no rescaling here.

FRED (Federal Reserve Bank of St. Louis) adds the slower-moving economic
backdrop those two don't cover -- inflation, employment, the policy rate,
and the yield curve shape:
  - CPIAUCSL: headline CPI (index level) -- converted to a YoY % change here,
    since the raw index number means nothing on its own.
  - UNRATE: unemployment rate, already a plain percent.
  - FEDFUNDS: effective federal funds rate, the Fed's actual policy lever.
  - T10Y2Y: the 10-year minus 2-year Treasury yield spread -- FRED publishes
    this pre-computed. A negative value ("inverted yield curve") is a
    well-known recession signal; fetched as-is, sign included.
FRED is entirely optional (FRED_API_KEY) -- macro_context works without it,
just without these four fields.

Not ticker-specific -- identical for every ticker checked on the same day,
by design.
"""

import datetime as dt

import requests
import yfinance as yf

from config import FRED_API_KEY

VIX_TICKER = "^VIX"
TREASURY_10Y_TICKER = "^TNX"

FRED_URL = "https://api.stlouisfed.org/fred/series/observations"
FRED_REQUEST_TIMEOUT = 10


def _level_and_change(index_ticker: str):
    hist = yf.Ticker(index_ticker).history(period="3mo")
    hist = hist[hist["Close"].notna()]
    if hist.empty:
        return None, None
    closes = hist["Close"]
    current = round(float(closes.iloc[-1]), 2)
    change_20d = round(float(closes.iloc[-1] - closes.iloc[-20]), 2) if len(closes) >= 20 else None
    return current, change_20d


def _fred_observations(series_id: str, limit: int = 13):
    """Most recent `limit` observations for a FRED series, newest first.
    Raises on any failure -- callers decide how to degrade."""
    params = {
        "series_id": series_id, "api_key": FRED_API_KEY, "file_type": "json",
        "sort_order": "desc", "limit": limit,
    }
    resp = requests.get(FRED_URL, params=params, timeout=FRED_REQUEST_TIMEOUT)
    resp.raise_for_status()
    data = resp.json()
    # FRED uses "." for a missing/not-yet-published observation, not a number.
    return [obs for obs in data.get("observations", []) if obs.get("value") not in (None, ".")]


def _fred_latest(series_id: str):
    obs = _fred_observations(series_id, limit=1)
    return round(float(obs[0]["value"]), 2) if obs else None


def _fred_yoy_pct_change(series_id: str):
    """For a monthly index series (e.g. CPI): latest value vs. the value
    closest to 12 months earlier, matched by date rather than a fixed list
    position. FRED series occasionally have a one-off missing month
    (observed live on CPIAUCSL: October 2025 came back "." -- a government
    shutdown delayed that release), which would silently misalign a
    fixed-position lookback by a month. Pulls extra observations as a
    buffer against one or two such gaps."""
    obs = _fred_observations(series_id, limit=15)
    if len(obs) < 13:
        return None
    latest = obs[0]
    latest_date = dt.datetime.strptime(latest["date"], "%Y-%m-%d")
    target_date = latest_date - dt.timedelta(days=365)
    year_ago = min(obs[1:], key=lambda o: abs((dt.datetime.strptime(o["date"], "%Y-%m-%d") - target_date).days))
    year_ago_val = float(year_ago["value"])
    if year_ago_val == 0:
        return None
    return round((float(latest["value"]) / year_ago_val - 1) * 100, 2)


def _fetch_fred_indicators() -> tuple[dict, list[str]]:
    fields = {"cpi_yoy_pct": None, "unemployment_rate_pct": None,
              "fed_funds_rate_pct": None, "yield_curve_10y_2y_pct": None}
    notes = []

    if not FRED_API_KEY:
        return fields, notes  # silently omitted, not an error -- this data source is optional

    try:
        fields["cpi_yoy_pct"] = _fred_yoy_pct_change("CPIAUCSL")
    except Exception:
        notes.append("FRED CPI fetch failed.")

    try:
        fields["unemployment_rate_pct"] = _fred_latest("UNRATE")
    except Exception:
        notes.append("FRED unemployment rate fetch failed.")

    try:
        fields["fed_funds_rate_pct"] = _fred_latest("FEDFUNDS")
    except Exception:
        notes.append("FRED fed funds rate fetch failed.")

    try:
        fields["yield_curve_10y_2y_pct"] = _fred_latest("T10Y2Y")
    except Exception:
        notes.append("FRED yield curve (10y-2y) fetch failed.")

    return fields, notes


def fetch_macro_context() -> dict:
    """
    Returns current VIX level and 10Y Treasury yield (each with their
    20-trading-day change), plus -- if FRED_API_KEY is set -- CPI inflation
    (YoY), unemployment rate, the fed funds rate, and the 10y-2y yield curve
    spread. Any individual piece that fails comes back null with a note
    rather than failing the whole fetch.
    """
    notes = []

    vix_level, vix_change_20d = None, None
    try:
        vix_level, vix_change_20d = _level_and_change(VIX_TICKER)
    except Exception:
        notes.append("VIX fetch failed.")

    yield_10y, yield_10y_change_20d = None, None
    try:
        yield_10y, yield_10y_change_20d = _level_and_change(TREASURY_10Y_TICKER)
    except Exception:
        notes.append("10Y Treasury yield fetch failed.")

    fred_fields, fred_notes = _fetch_fred_indicators()
    notes.extend(fred_notes)

    return {
        "vix_level": vix_level,
        "vix_change_20d": vix_change_20d,
        "treasury_10y_yield_pct": yield_10y,
        "treasury_10y_yield_change_20d_pct": yield_10y_change_20d,
        **fred_fields,
        "note": " ".join(notes) if notes else None,
    }


if __name__ == "__main__":
    import json
    print(json.dumps(fetch_macro_context(), indent=2))
