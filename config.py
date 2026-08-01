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

# Qwen (Alibaba Cloud Model Studio) -- OpenAI-compatible endpoint, used for the
# independent second-opinion Skeptic and the Quant Checker agent. Both are cheap
# supporting checks, not the primary reasoning path, so they're kept on a
# separate cheap provider deliberately (see judge.md for how their output is
# actually weighed, not just logged).
QWEN_API_KEY = os.getenv("QWEN_API_KEY", "")
QWEN_BASE_URL = os.getenv("QWEN_BASE_URL", "https://dashscope-intl.aliyuncs.com/compatible-mode/v1")

# Gemini -- called via Google's OpenAI-compatible endpoint (same agents/compat_client.py
# code path as Qwen). Used for Bull/Bear (best faithfulness + calibration benchmarks
# found for a strictly-grounded persuasive-argument role) and both digest steps (best
# summarization-faithfulness benchmark, and the cheapest/fastest tier besides).
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_BASE_URL = os.getenv("GEMINI_BASE_URL", "https://generativelanguage.googleapis.com/v1beta/openai/")

# Model assigned per agent role -- chosen per-role from benchmarks matched to that
# role's actual job (see HANDOFF.md), not just "use the same provider everywhere":
#   Bull/Bear: grounding is the #1 rule in their prompts -> best faithfulness/
#     calibration benchmarks (Gemini).
#   Skeptic (original): critiquing another model's claims is a judge/critic task ->
#     best LLM-as-judge benchmark (Claude Sonnet).
#   Judge: must self-report a *calibrated* confidence, not just be accurate ->
#     best calibration benchmark, ConfidenceBench (Claude Opus).
#   Digests: pure faithful extraction, no reasoning needed -> best faithfulness
#     benchmark + cheapest/fastest (Gemini Flash).
MODEL_BULL = "gemini-3.1-pro"
MODEL_BEAR = "gemini-3.1-pro"
MODEL_SKEPTIC = "claude-sonnet-5"
MODEL_JUDGE = "claude-opus-5"
MODEL_DIGEST = "gemini-3.6-flash"  # cheap, faithful model for summarizing filings/news

# Qwen-backed supporting agents (see agents/skeptic_qwen_agent.py, agents/quant_checker_agent.py).
MODEL_SKEPTIC_QWEN = "qwen3.7-plus"
MODEL_QUANT_CHECKER = "qwen3.7-plus"

# Pricing per million tokens (input, output), in USD. Update if rates change.
# Source: Anthropic pricing page, Alibaba Cloud Model Studio pricing for Qwen,
# and Google AI pricing for Gemini -- all checked July 2026.
PRICING = {
    "claude-haiku-4-5-20251001": {"input": 1.00, "output": 5.00},
    "claude-sonnet-5": {"input": 2.00, "output": 10.00},  # intro pricing through Aug 31 2026
    "claude-opus-5": {"input": 5.00, "output": 25.00},
    "qwen3.7-plus": {"input": 0.32, "output": 1.28},
    "gemini-3.1-pro": {"input": 2.00, "output": 12.00},  # up to 200K context; $4/$18 above that
    "gemini-3.6-flash": {"input": 1.50, "output": 7.50},
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
