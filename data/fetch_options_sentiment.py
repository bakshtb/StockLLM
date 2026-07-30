"""
Deterministic options-market sentiment fetch. No LLM calls here.

Two signals from the live options chain, both free via yfinance:
  - Put/call ratio (volume and open interest): a rough proxy for whether
    options traders are positioning more bearishly or bullishly right now.
  - Implied volatility skew: OTM put IV minus OTM call IV. Positive skew
    (puts pricier than calls) means the market is paying up for downside
    protection -- a fear signal independent of price action.

Uses the nearest expiration at least MIN_DAYS_TO_EXPIRY out (falls back to
the furthest available if none qualify) rather than the very nearest
expiration, which is often a thinly-traded weekly with noisy quotes. Deep
out-of-the-money strikes routinely carry stale/garbage IV quotes (observed
live: 0.00001 on far OTM AAPL contracts with no recent trades), so IV points
are only taken from strikes with actual volume or open interest -- ask price
was tried first but is unreliable (observed live: 0 on every strike for some
tickers/sessions even when volume is clearly present), so it isn't used as
the liquidity filter.
"""

import datetime as dt

import yfinance as yf

MIN_DAYS_TO_EXPIRY = 25
OTM_PCT = 0.10  # how far from spot counts as "OTM" for the skew calculation


def _nearest_valid_strike(df, target_price):
    """Closest strike (by absolute distance to target_price) among rows with
    actual volume or open interest, i.e. a contract that's actually traded
    rather than a stale/placeholder listing."""
    has_activity = df["volume"].fillna(0) > 0
    has_activity |= df["openInterest"].fillna(0) > 0
    valid = df[has_activity]
    if valid.empty:
        return None
    idx = (valid["strike"] - target_price).abs().idxmin()
    return valid.loc[idx]


def fetch_options_sentiment(ticker: str, current_price) -> dict:
    """
    Returns put/call volume & open-interest ratios plus ATM/OTM implied
    volatility and the resulting skew. Many tickers (small caps, foreign
    listings) have no listed options at all -- returns an empty result with
    a note in that case, not an error.
    """
    result = {
        "expiration_used": None, "days_to_expiry": None,
        "put_call_volume_ratio": None, "put_call_open_interest_ratio": None,
        "atm_call_iv": None, "atm_put_iv": None,
        "otm_put_iv": None, "otm_call_iv": None, "iv_skew_put_minus_call": None,
        "note": None,
    }
    if not current_price:
        result["note"] = "No current price available to anchor ATM/OTM strike selection."
        return result

    try:
        tk = yf.Ticker(ticker)
        expirations = tk.options
        if not expirations:
            result["note"] = "No listed options found for this ticker."
            return result

        today = dt.date.today()
        chosen_exp = expirations[-1]  # fallback: furthest out available
        for exp in expirations:
            days_out = (dt.date.fromisoformat(exp) - today).days
            if days_out >= MIN_DAYS_TO_EXPIRY:
                chosen_exp = exp
                break
        days_to_expiry = (dt.date.fromisoformat(chosen_exp) - today).days

        chain = tk.option_chain(chosen_exp)
        calls, puts = chain.calls, chain.puts

        call_volume = calls["volume"].fillna(0).sum()
        put_volume = puts["volume"].fillna(0).sum()
        call_oi = calls["openInterest"].fillna(0).sum()
        put_oi = puts["openInterest"].fillna(0).sum()

        put_call_volume_ratio = round(float(put_volume / call_volume), 3) if call_volume else None
        put_call_oi_ratio = round(float(put_oi / call_oi), 3) if call_oi else None

        atm_call = _nearest_valid_strike(calls, current_price)
        atm_put = _nearest_valid_strike(puts, current_price)
        otm_call = _nearest_valid_strike(calls, current_price * (1 + OTM_PCT))
        otm_put = _nearest_valid_strike(puts, current_price * (1 - OTM_PCT))

        atm_call_iv = round(float(atm_call["impliedVolatility"]), 4) if atm_call is not None else None
        atm_put_iv = round(float(atm_put["impliedVolatility"]), 4) if atm_put is not None else None
        otm_call_iv = round(float(otm_call["impliedVolatility"]), 4) if otm_call is not None else None
        otm_put_iv = round(float(otm_put["impliedVolatility"]), 4) if otm_put is not None else None

        result.update({
            "expiration_used": chosen_exp,
            "days_to_expiry": days_to_expiry,
            "put_call_volume_ratio": put_call_volume_ratio,
            "put_call_open_interest_ratio": put_call_oi_ratio,
            "atm_call_iv": atm_call_iv,
            "atm_put_iv": atm_put_iv,
            "otm_put_iv": otm_put_iv,
            "otm_call_iv": otm_call_iv,
            "iv_skew_put_minus_call": round(otm_put_iv - otm_call_iv, 4) if otm_put_iv is not None and otm_call_iv is not None else None,
            "note": (
                "Put/call ratios are reliable (real volume/open interest). Implied volatility "
                "fields are yfinance passthrough and are frequently stale or uncalculated by "
                "Yahoo -- observed live returning near-zero ATM IV and an identical flat value "
                "across unrelated tickers, which is not realistic market pricing. Weight "
                "iv_skew_put_minus_call accordingly; do not treat it as a trustworthy fear gauge."
            ),
        })
        return result

    except Exception as e:
        result["note"] = f"Options sentiment fetch failed: {e}"
        return result


if __name__ == "__main__":
    import sys
    import json
    ticker = sys.argv[1] if len(sys.argv) > 1 else "AAPL"
    from data.fetch_prices import fetch_price_summary
    price = fetch_price_summary(ticker)
    print(json.dumps(fetch_options_sentiment(ticker, price.get("current_price")), indent=2))
