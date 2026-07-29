"""
Deterministic balance sheet / cash flow health fetch. No LLM calls here.

Pulls the most recent annual figures for debt, cash, and free cash flow --
a classic gap in headline-driven analysis (a cheap-looking stock with a broken
balance sheet is a value trap).
"""

import yfinance as yf


def _latest_value(df, row_names: list[str]):
    """yfinance financial statement row names vary by ticker/version; try a few."""
    if df is None or df.empty:
        return None
    for name in row_names:
        if name in df.index:
            series = df.loc[name].dropna()
            if not series.empty:
                return float(series.iloc[0])
    return None


def fetch_balance_sheet_health(ticker: str) -> dict:
    tk = yf.Ticker(ticker)

    try:
        info = tk.info or {}
    except Exception:
        info = {}

    try:
        balance_sheet = tk.balance_sheet
    except Exception:
        balance_sheet = None

    try:
        cashflow = tk.cashflow
    except Exception:
        cashflow = None

    total_debt = info.get("totalDebt") or _latest_value(balance_sheet, ["Total Debt", "TotalDebt"])
    total_cash = info.get("totalCash") or _latest_value(balance_sheet, ["Cash And Cash Equivalents", "Cash", "CashAndCashEquivalents"])
    operating_cash_flow = _latest_value(cashflow, ["Operating Cash Flow", "Total Cash From Operating Activities", "CashFlowFromOperations"])
    capex = _latest_value(cashflow, ["Capital Expenditure", "CapitalExpenditures", "CapitalExpenditure"])

    free_cash_flow = None
    if operating_cash_flow is not None and capex is not None:
        free_cash_flow = operating_cash_flow + capex  # capex is typically stored as negative

    return {
        "total_debt": total_debt,
        "total_cash": total_cash,
        "debt_to_equity": info.get("debtToEquity"),
        "current_ratio": info.get("currentRatio"),
        "free_cash_flow": free_cash_flow,
        "operating_cash_flow": operating_cash_flow,
        "note": "Most recent annual figures available from Yahoo Finance; coverage varies by ticker/exchange.",
    }


if __name__ == "__main__":
    import sys
    import json
    ticker = sys.argv[1] if len(sys.argv) > 1 else "AAPL"
    print(json.dumps(fetch_balance_sheet_health(ticker), indent=2))
