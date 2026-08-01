"""
Qwen-specific wrapper around agents/compat_client.py's shared OpenAI-compatible
call logic, used by the two Qwen-backed supporting agents: the independent
second-opinion Skeptic and the Quant Checker.
"""

from agents.compat_client import call_compat_agent
from config import QWEN_API_KEY, QWEN_BASE_URL


def call_qwen_agent(agent_name: str, model: str, role_prompt: str, bundle_json_str: str) -> dict:
    return call_compat_agent(agent_name, QWEN_API_KEY, QWEN_BASE_URL, model, role_prompt, bundle_json_str)
