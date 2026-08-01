"""Bear agent: builds the strongest case AGAINST buying, grounded in the
research bundle. Runs on Gemini -- see config.py for why."""

import os
from agents.gemini_client import call_gemini_agent
from config import MODEL_BEAR

PROMPT_PATH = os.path.join(os.path.dirname(__file__), "prompts", "bear.md")


def run_bear_agent(bundle_json_str: str) -> dict:
    with open(PROMPT_PATH, "r") as f:
        role_prompt = f.read()
    return call_gemini_agent("bear", MODEL_BEAR, role_prompt, bundle_json_str)
