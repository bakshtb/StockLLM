"""
Orchestrates the full pipeline: bull + bear (independent) -> two independent
skeptic reviews (Claude + Qwen) + a Qwen quant check (all three independent of
each other) -> judge. Logs every agent call to the database as it goes.
"""

import json

from agents.bull_agent import run_bull_agent
from agents.bear_agent import run_bear_agent
from agents.skeptic_agent import run_skeptic_agent
from agents.skeptic_qwen_agent import run_skeptic_qwen_agent
from agents.quant_checker_agent import run_quant_checker_agent
from agents.judge_agent import run_judge_agent
from storage import db


def run_pipeline(run_id: int, ticker: str, bundle: dict, starting_cost_usd: float = 0.0) -> dict:
    """
    Runs the full agent pipeline for a research bundle that's already been
    fetched and logged under run_id (see main.py). starting_cost_usd carries
    over any cost already spent on digest steps (filings/news summarization)
    so the final total_cost_usd reflects the true cost of the whole run.
    Returns the judge's final parsed output plus a cost summary.
    Raises RuntimeError if any agent fails after its retry.
    """
    bundle_json_str = json.dumps(bundle)
    total_cost = starting_cost_usd

    try:
        # Bull and bear are independent of each other -- run sequentially here for
        # simplicity; can be parallelized later with threads/async if desired.
        bull_result = run_bull_agent(bundle_json_str)
        db.save_agent_output(
            run_id, "bull", bull_result.get("model", "bull-model"),
            bull_result["input_tokens"], bull_result["output_tokens"],
            bull_result["cache_read_tokens"], bull_result["cost_usd"],
            bull_result["parsed"],
        )
        total_cost += bull_result["cost_usd"]

        bear_result = run_bear_agent(bundle_json_str)
        db.save_agent_output(
            run_id, "bear", bear_result.get("model", "bear-model"),
            bear_result["input_tokens"], bear_result["output_tokens"],
            bear_result["cache_read_tokens"], bear_result["cost_usd"],
            bear_result["parsed"],
        )
        total_cost += bear_result["cost_usd"]

        # Skeptic (Claude), Skeptic-Qwen, and the Quant Checker are all
        # independent of each other -- each sees only the bundle + bull/bear,
        # never each other's output, so their agreement/disagreement is a
        # genuine signal for the judge rather than one review echoing another.
        skeptic_result = run_skeptic_agent(bundle_json_str, bull_result["parsed"], bear_result["parsed"])
        db.save_agent_output(
            run_id, "skeptic", skeptic_result.get("model", "skeptic-model"),
            skeptic_result["input_tokens"], skeptic_result["output_tokens"],
            skeptic_result["cache_read_tokens"], skeptic_result["cost_usd"],
            skeptic_result["parsed"],
        )
        total_cost += skeptic_result["cost_usd"]

        skeptic_qwen_result = run_skeptic_qwen_agent(bundle_json_str, bull_result["parsed"], bear_result["parsed"])
        db.save_agent_output(
            run_id, "skeptic_qwen", skeptic_qwen_result.get("model", "skeptic-qwen-model"),
            skeptic_qwen_result["input_tokens"], skeptic_qwen_result["output_tokens"],
            skeptic_qwen_result["cache_read_tokens"], skeptic_qwen_result["cost_usd"],
            skeptic_qwen_result["parsed"],
        )
        total_cost += skeptic_qwen_result["cost_usd"]

        quant_check_result = run_quant_checker_agent(bundle_json_str, bull_result["parsed"], bear_result["parsed"])
        db.save_agent_output(
            run_id, "quant_checker", quant_check_result.get("model", "quant-checker-model"),
            quant_check_result["input_tokens"], quant_check_result["output_tokens"],
            quant_check_result["cache_read_tokens"], quant_check_result["cost_usd"],
            quant_check_result["parsed"],
        )
        total_cost += quant_check_result["cost_usd"]

        judge_result = run_judge_agent(
            bundle_json_str, bull_result["parsed"], bear_result["parsed"],
            skeptic_result["parsed"], skeptic_qwen_result["parsed"], quant_check_result["parsed"],
        )
        db.save_agent_output(
            run_id, "judge", judge_result.get("model", "judge-model"),
            judge_result["input_tokens"], judge_result["output_tokens"],
            judge_result["cache_read_tokens"], judge_result["cost_usd"],
            judge_result["parsed"],
        )
        total_cost += judge_result["cost_usd"]

        judge_output = judge_result["parsed"]
        db.finalize_run(
            run_id,
            judge_output.get("recommendation", "unknown"),
            judge_output.get("confidence", 0),
            total_cost,
            status="complete",
        )

        return {
            "run_id": run_id,
            "bull": bull_result["parsed"],
            "bear": bear_result["parsed"],
            "skeptic": skeptic_result["parsed"],
            "skeptic_qwen": skeptic_qwen_result["parsed"],
            "quant_check": quant_check_result["parsed"],
            "judge": judge_output,
            "total_cost_usd": round(total_cost, 4),
        }

    except Exception as e:
        db.finalize_run(run_id, "error", 0, total_cost, status="failed")
        raise RuntimeError(f"Pipeline failed for {ticker} (run_id={run_id}): {e}") from e
