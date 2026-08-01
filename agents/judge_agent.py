"""Judge agent: weighs bull, bear, both skeptic reviews, and the quant check to
produce the final recommendation."""

import os
import json
from agents.client import call_agent
from config import MODEL_JUDGE

PROMPT_PATH = os.path.join(os.path.dirname(__file__), "prompts", "judge.md")


def run_judge_agent(
    bundle_json_str: str, bull_case: dict, bear_case: dict,
    skeptic_review: dict, skeptic_qwen_review: dict, quant_check: dict,
) -> dict:
    with open(PROMPT_PATH, "r") as f:
        template = f.read()
    role_prompt = template.replace(
        "{{BULL_CASE}}", json.dumps(bull_case)
    ).replace(
        "{{BEAR_CASE}}", json.dumps(bear_case)
    ).replace(
        "{{SKEPTIC_REVIEW}}", json.dumps(skeptic_review)
    ).replace(
        "{{SKEPTIC_QWEN_REVIEW}}", json.dumps(skeptic_qwen_review)
    ).replace(
        "{{QUANT_CHECK}}", json.dumps(quant_check)
    )
    return call_agent("judge", MODEL_JUDGE, role_prompt, bundle_json_str)
