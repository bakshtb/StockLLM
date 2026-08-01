"""Quant checker agent: verifies numeric claims in the bull/bear cases against
the bundle's raw figures. Runs on Qwen -- see agents/prompts/quant_checker.md."""

import os
import json
from agents.qwen_client import call_qwen_agent
from config import MODEL_QUANT_CHECKER

PROMPT_PATH = os.path.join(os.path.dirname(__file__), "prompts", "quant_checker.md")


def run_quant_checker_agent(bundle_json_str: str, bull_case: dict, bear_case: dict) -> dict:
    with open(PROMPT_PATH, "r") as f:
        template = f.read()
    role_prompt = template.replace(
        "{{BULL_CASE}}", json.dumps(bull_case)
    ).replace(
        "{{BEAR_CASE}}", json.dumps(bear_case)
    )
    return call_qwen_agent("quant_checker", MODEL_QUANT_CHECKER, role_prompt, bundle_json_str)
