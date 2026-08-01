"""
Shared call logic for any OpenAI-compatible provider (Qwen via Alibaba Cloud
Model Studio, Gemini via Google's OpenAI-compatibility endpoint) using the
same "send the bundle + role prompt, expect strict JSON back" contract used
throughout this pipeline. Anthropic's own agents/client.py stays separate
since its API -- and its explicit cache_control prompt-caching mechanism --
differs enough from the OpenAI shape to not be worth forcing in here.

agents/qwen_client.py and agents/gemini_client.py are both thin wrappers
around call_compat_agent()/call_compat_digest() that just supply their
provider's api_key/base_url.
"""

import json

import openai

from agents.client import _extract_json
from config import estimate_cost_usd

COMPAT_SYSTEM_PROMPT = (
    "You are part of a multi-agent equity research pipeline. You will be given a "
    "research bundle (price data, fundamentals, recent news) for one stock ticker, "
    "followed by your specific role instructions. Follow your role instructions "
    "exactly, stay strictly grounded in the provided data, and respond with ONLY "
    "valid JSON matching the schema given to you -- no markdown formatting, no "
    "commentary before or after the JSON."
)

_clients = {}  # keyed by (api_key, base_url) -- each provider gets its own cached client


def _get_client(api_key: str, base_url: str):
    key = (api_key, base_url)
    if key not in _clients:
        _clients[key] = openai.OpenAI(api_key=api_key, base_url=base_url)
    return _clients[key]


def call_compat_agent(
    agent_name: str, api_key: str, base_url: str, model: str, role_prompt: str, bundle_json_str: str,
) -> dict:
    """
    Calls a single agent hosted behind an OpenAI-compatible endpoint. Returns
    a dict with keys: parsed (the agent's JSON output), input_tokens,
    output_tokens, cache_read_tokens (always 0 -- neither provider's context
    caching is reported as a separate explicit token count the way
    Anthropic's is), cost_usd.
    """
    client = _get_client(api_key, base_url)

    messages = [
        {"role": "system", "content": COMPAT_SYSTEM_PROMPT},
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
                "model": model,
            }
        except (json.JSONDecodeError, openai.APIError) as e:
            last_error = e
            continue

    raise RuntimeError(f"Agent '{agent_name}' ({model}) failed after retry: {last_error}")


def call_compat_digest(api_key: str, base_url: str, model: str, system_prompt: str, user_text: str) -> dict:
    """
    Simpler call path for one-off summarization tasks (filings, news digests),
    mirroring agents/client.py's call_digest() but for an OpenAI-compatible
    provider. Returns dict with parsed JSON, token counts, cost, and model.
    """
    client = _get_client(api_key, base_url)

    last_error = None
    for attempt in range(2):
        try:
            response = client.chat.completions.create(
                model=model,
                max_tokens=1000,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_text},
                ],
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
                "model": model,
            }
        except (json.JSONDecodeError, openai.APIError) as e:
            last_error = e
            continue

    raise RuntimeError(f"Digest call ({model}) failed after retry: {last_error}")
