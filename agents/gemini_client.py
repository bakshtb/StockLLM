"""
Gemini-specific wrapper around agents/compat_client.py's shared OpenAI-compatible
call logic (Google's Gemini API exposes an OpenAI-compatible endpoint). Used by
Bull, Bear, and the news digest -- see config.py for why those specific roles
run on Gemini (the filings digest runs on Qwen instead -- agents/qwen_client.py).
"""

from agents.compat_client import call_compat_agent, call_compat_digest
from config import GEMINI_API_KEY, GEMINI_BASE_URL


def call_gemini_agent(agent_name: str, model: str, role_prompt: str, bundle_json_str: str) -> dict:
    return call_compat_agent(agent_name, GEMINI_API_KEY, GEMINI_BASE_URL, model, role_prompt, bundle_json_str)


def call_gemini_digest(model: str, system_prompt: str, user_text: str) -> dict:
    return call_compat_digest(GEMINI_API_KEY, GEMINI_BASE_URL, model, system_prompt, user_text)
