"""
Central config: model choices per agent, and current per-token pricing so we can
log actual $ cost per run. Update PRICING if Anthropic's rates change.
"""

import os
from dotenv import load_dotenv

load_dotenv()

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
FINNHUB_API_KEY = os.getenv("FINNHUB_API_KEY", "")
MONTHLY_SPEND_LIMIT_USD = float(os.getenv("MONTHLY_SPEND_LIMIT_USD", "50"))

# Model assigned per agent role. Deliberately not all Opus -- see project spec's
# Cost Management section. Update these model IDs if Anthropic renames/replaces them.
MODEL_BULL = "claude-haiku-4-5-20251001"
MODEL_BEAR = "claude-haiku-4-5-20251001"
MODEL_SKEPTIC = "claude-sonnet-5"
MODEL_JUDGE = "claude-opus-5"
MODEL_DIGEST = "claude-haiku-4-5-20251001"  # cheap model for summarizing filings/news

# Pricing per million tokens (input, output), in USD. Update if rates change.
# Source: Anthropic pricing page, checked July 2026.
PRICING = {
    "claude-haiku-4-5-20251001": {"input": 1.00, "output": 5.00},
    "claude-sonnet-5": {"input": 2.00, "output": 10.00},  # intro pricing through Aug 31 2026
    "claude-opus-5": {"input": 5.00, "output": 25.00},
}

# Cache reads cost 10% of base input price
CACHE_READ_DISCOUNT = 0.10

# How many news headlines to pass to the agents (keep low to control token cost)
MAX_NEWS_ITEMS = 15

# SEC EDGAR requires a descriptive User-Agent identifying who's making requests
# (name + contact email). Set this in .env or EDGAR will rate-limit/block you.
SEC_EDGAR_USER_AGENT = os.getenv("SEC_EDGAR_USER_AGENT", "StockLLM research-tool contact@example.com")

# Caps to keep digest LLM calls (filings, news) cheap and fast
MAX_FILING_CHARS = 15000       # raw filing text truncated to this before summarizing
MAX_NEWS_ARTICLES_TO_FETCH = 8  # how many full articles we attempt to fetch for the news digest

DB_PATH = os.getenv("DB_PATH", os.path.join(os.path.dirname(__file__), "storage", "stockllm.db"))

# Where generated JSON bundles and HTML dashboards get written by default
# (both the CLI and the webapp/ Flask app use this). The Home Assistant
# add-on points this at /data/output (its persistent volume) via run.sh;
# local/CLI use defaults to a plain output/ folder next to this file.
OUTPUT_DIR = os.getenv("OUTPUT_DIR", os.path.join(os.path.dirname(__file__), "output"))


def estimate_cost_usd(model: str, input_tokens: int, output_tokens: int, cache_read_tokens: int = 0) -> float:
    """Rough cost estimate for a single agent call in USD."""
    rates = PRICING.get(model)
    if not rates:
        return 0.0
    regular_input = max(input_tokens - cache_read_tokens, 0)
    cost = (
        regular_input * rates["input"] / 1_000_000
        + cache_read_tokens * rates["input"] * CACHE_READ_DISCOUNT / 1_000_000
        + output_tokens * rates["output"] / 1_000_000
    )
    return round(cost, 6)
