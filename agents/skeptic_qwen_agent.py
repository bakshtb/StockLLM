"""
Independent second-opinion skeptic: same role and schema as agents/skeptic_agent.py,
but run on Qwen instead of Claude, deliberately unaware of the Claude skeptic's
output. Two independently-trained models checking the same bull/bear claims is a
real cross-model check that a single skeptic can't give itself -- see judge.md for
how the two reviews get weighed together (agreement is a strong signal, disagreement
is itself informative, not just noise to average away).
"""

import os
import json
from agents.qwen_client import call_qwen_agent
from config import MODEL_SKEPTIC_QWEN

# Reuses the same prompt file as the Claude skeptic -- identical task and
# schema is the point; only the model differs.
PROMPT_PATH = os.path.join(os.path.dirname(__file__), "prompts", "skeptic.md")


def run_skeptic_qwen_agent(bundle_json_str: str, bull_case: dict, bear_case: dict) -> dict:
    with open(PROMPT_PATH, "r") as f:
        template = f.read()
    role_prompt = template.replace(
        "{{BULL_CASE}}", json.dumps(bull_case)
    ).replace(
        "{{BEAR_CASE}}", json.dumps(bear_case)
    )
    return call_qwen_agent("skeptic_qwen", MODEL_SKEPTIC_QWEN, role_prompt, bundle_json_str)
