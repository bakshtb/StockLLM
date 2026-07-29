"""Skeptic agent: critiques the bull and bear cases for unsupported claims and data gaps."""

import os
import json
from agents.client import call_agent
from config import MODEL_SKEPTIC

PROMPT_PATH = os.path.join(os.path.dirname(__file__), "prompts", "skeptic.md")


def run_skeptic_agent(bundle_json_str: str, bull_case: dict, bear_case: dict) -> dict:
    with open(PROMPT_PATH, "r") as f:
        template = f.read()
    role_prompt = template.replace(
        "{{BULL_CASE}}", json.dumps(bull_case)
    ).replace(
        "{{BEAR_CASE}}", json.dumps(bear_case)
    )
    return call_agent("skeptic", MODEL_SKEPTIC, role_prompt, bundle_json_str)
