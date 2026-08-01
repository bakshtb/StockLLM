"""
Wrapper around Qwen (Alibaba Cloud Model Studio) for the two supporting agents
that run on Qwen instead of Anthropic: the independent second-opinion Skeptic
and the Quant Checker. Kept separate from agents/client.py because the two
providers' APIs differ (OpenAI-compatible here vs. Anthropic's own SDK there,
including how prompt caching is expressed) -- see judge.md for how these
agents' output actually gets weighed by the Judge, not just logged.
"""

import json

import openai

from agents.client import _extract_json
from config import QWEN_API_KEY, QWEN_BASE_URL, estimate_cost_usd

_client = None


def _get_client():
    global _client
    if _client is None:
        _client = openai.OpenAI(api_key=QWEN_API_KEY, base_url=QWEN_BASE_URL)
    return _client


QWEN_SYSTEM_PROMPT = (
    "You are part of a multi-agent equity research pipeline. You will be given a "
    "research bundle (price data, fundamentals, recent news) for one stock ticker, "
    "followed by your specific role instructions. Follow your role instructions "
    "exactly, stay strictly grounded in the provided data, and respond with ONLY "
    "valid JSON matching the schema given to you -- no markdown formatting, no "
    "commentary before or after the JSON."
)


def call_qwen_agent(agent_name: str, model: str, role_prompt: str, bundle_json_str: str) -> dict:
    """
    Calls a single Qwen-backed agent. Returns a dict with keys: parsed (the
    agent's JSON output), input_tokens, output_tokens, cache_read_tokens
    (always 0 -- Qwen's context caching is transparent/automatic rather than
    an explicit cache_control block like Anthropic's, so it isn't separately
    reported here), cost_usd.
    """
    client = _get_client()

    messages = [
        {"role": "system", "content": QWEN_SYSTEM_PROMPT},
        {"role": "user", "content": f"RESEARCH_BUNDLE (JSON):\n{bundle_json_str}\n\n{role_prompt}"},
    ]

    last_error = None
    for attempt in range(2):  # one retry, matches agents/client.py's behavior
        try:
            response = client.chat.completions.create(
                model=model,
                max_tokens=1500,
                messages=messages,
                response_format={"type": "json_object"},
            )
            raw_text = response.choices[0].message.content
            parsed = _extract_json(raw_text)

            usage = response.usage
            input_tokens = usage.prompt_tokens
            output_tokens = usage.completion_tokens

            cost = estimate_cost_usd(model, input_tokens, output_tokens, 0)

            return {
                "parsed": parsed,
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "cache_read_tokens": 0,
                "cost_usd": cost,
            }
        except (json.JSONDecodeError, openai.APIError) as e:
            last_error = e
            continue

    raise RuntimeError(f"Qwen agent '{agent_name}' failed after retry: {last_error}")
