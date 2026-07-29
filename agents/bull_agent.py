"""Bull agent: builds the strongest case FOR buying, grounded in the research bundle."""

import os
from agents.client import call_agent
from config import MODEL_BULL

PROMPT_PATH = os.path.join(os.path.dirname(__file__), "prompts", "bull.md")


def run_bull_agent(bundle_json_str: str) -> dict:
    with open(PROMPT_PATH, "r") as f:
        role_prompt = f.read()
    return call_agent("bull", MODEL_BULL, role_prompt, bundle_json_str)
