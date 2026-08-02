"""
Qwen-specific wrapper around agents/compat_client.py's shared OpenAI-compatible
call logic. Used by the two Qwen-backed supporting agents (the independent
second-opinion Skeptic and the Quant Checker) and by the filings digest --
see config.py for why the filings digest specifically runs on Qwen.
"""

from agents.compat_client import call_compat_agent, call_compat_digest
from config import QWEN_API_KEY, QWEN_BASE_URL


def call_qwen_agent(agent_name: str, model: str, role_prompt: str, bundle_json_str: str) -> dict:
    return call_compat_agent(agent_name, QWEN_API_KEY, QWEN_BASE_URL, model, role_prompt, bundle_json_str)


def call_qwen_digest(model: str, system_prompt: str, user_text: str) -> dict:
    return call_compat_digest(QWEN_API_KEY, QWEN_BASE_URL, model, system_prompt, user_text)
