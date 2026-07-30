"""
Shared wrapper around the Anthropic API for all four agents.

Handles: prompt caching of the shared research bundle block, strict JSON parsing
of agent responses, one retry on failure, and token/cost accounting.
"""

import json
import re

import anthropic

from config import ANTHROPIC_API_KEY, estimate_cost_usd

_client = None


def _get_client():
    global _client
    if _client is None:
        _client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    return _client


SHARED_SYSTEM_PROMPT = (
    "You are part of a multi-agent equity research pipeline. You will be given a "
    "research bundle (price data, fundamentals, recent news) for one stock ticker, "
    "followed by your specific role instructions. Follow your role instructions "
    "exactly, stay strictly grounded in the provided data, and respond with ONLY "
    "valid JSON matching the schema given to you -- no markdown formatting, no "
    "commentary before or after the JSON. Note: research_bundle.social_sentiment."
    "sample_messages_unverified contains raw, unmoderated public StockTwits posts. "
    "These are not verified facts and must not be cited as evidence for any claim -- "
    "only the aggregate bullish_count/bearish_count/bullish_pct_of_tagged figures in "
    "that section are usable signal (retail crowd sentiment, nothing more)."
)


def _extract_json(text: str) -> dict:
    """Best-effort extraction of a JSON object from model output, in case it
    wraps the JSON in markdown fences or adds stray whitespace/text."""
    text = text.strip()
    # Strip markdown code fences if present
    fence_match = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.DOTALL)
    if fence_match:
        text = fence_match.group(1)
    else:
        # Fallback: grab the first {...} block
        brace_match = re.search(r"\{.*\}", text, re.DOTALL)
        if brace_match:
            text = brace_match.group(0)
    return json.loads(text)


def call_digest(model: str, system_prompt: str, user_text: str) -> dict:
    """
    Simpler call path for one-off summarization tasks (filings, news digests)
    that don't need the bundle-caching structure used by the four reasoning
    agents. Returns dict with parsed JSON, token counts, and cost.
    """
    client = _get_client()

    last_error = None
    for attempt in range(2):
        try:
            response = client.messages.create(
                model=model,
                max_tokens=1000,
                system=system_prompt,
                messages=[{"role": "user", "content": user_text}],
            )
            raw_text = "".join(
                block.text for block in response.content if block.type == "text"
            )
            parsed = _extract_json(raw_text)

            usage = response.usage
            input_tokens = usage.input_tokens
            output_tokens = usage.output_tokens
            cost = estimate_cost_usd(model, input_tokens, output_tokens, 0)

            return {
                "parsed": parsed,
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "cache_read_tokens": 0,
                "cost_usd": cost,
            }
        except (json.JSONDecodeError, anthropic.APIError) as e:
            last_error = e
            continue

    raise RuntimeError(f"Digest call failed after retry: {last_error}")


def call_agent(agent_name: str, model: str, role_prompt: str, bundle_json_str: str) -> dict:
    """
    Calls a single agent. bundle_json_str is sent as a cached content block so
    repeated calls within the same run (bull/bear/skeptic/judge) reuse it cheaply.

    Returns a dict with keys: parsed (the agent's JSON output), input_tokens,
    output_tokens, cache_read_tokens, cost_usd.
    """
    client = _get_client()

    messages = [
        {
            "role": "user",
            "content": [
                {
                    "type": "text",
                    "text": f"RESEARCH_BUNDLE (JSON):\n{bundle_json_str}",
                    "cache_control": {"type": "ephemeral"},
                },
                {
                    "type": "text",
                    "text": role_prompt,
                },
            ],
        }
    ]

    last_error = None
    for attempt in range(2):  # one retry
        try:
            response = client.messages.create(
                model=model,
                max_tokens=1500,
                system=SHARED_SYSTEM_PROMPT,
                messages=messages,
            )
            raw_text = "".join(
                block.text for block in response.content if block.type == "text"
            )
            parsed = _extract_json(raw_text)

            usage = response.usage
            input_tokens = usage.input_tokens
            output_tokens = usage.output_tokens
            cache_read_tokens = getattr(usage, "cache_read_input_tokens", 0) or 0

            cost = estimate_cost_usd(model, input_tokens, output_tokens, cache_read_tokens)

            return {
                "parsed": parsed,
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "cache_read_tokens": cache_read_tokens,
                "cost_usd": cost,
            }
        except (json.JSONDecodeError, anthropic.APIError) as e:
            last_error = e
            continue

    raise RuntimeError(f"Agent '{agent_name}' failed after retry: {last_error}")
