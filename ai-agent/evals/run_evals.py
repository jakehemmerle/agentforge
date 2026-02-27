#!/usr/bin/env python3
"""Mocked eval harness for the OpenEMR AI agent.

Runs evals using fixture-backed mock tools (no Docker / OpenEMR required):
  1. Loads eval cases from eval_cases.yaml (with optional category/tag filters)
  2. Creates a LangSmith dataset with scenario + query inputs
  3. Builds a per-scenario LangGraph with mock tools returning fixture data
  4. Runs evaluators from evaluators.py and prints a results summary

Usage:
    cd ai-agent
    uv run python -m evals.run_evals
    uv run python -m evals.run_evals --category happy_path
    uv run python -m evals.run_evals --tags single_tool appointments
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path
from uuid import uuid4

import yaml

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_EVALS_DIR = Path(__file__).parent
_AI_AGENT_DIR = _EVALS_DIR.parent


# ---------------------------------------------------------------------------
# Load eval cases from YAML
# ---------------------------------------------------------------------------


def _load_cases(
    category: str | None = None, tags: list[str] | None = None
) -> list[dict]:
    """Load eval cases from eval_cases.yaml with optional filters."""
    with open(_EVALS_DIR / "eval_cases.yaml") as f:
        data = yaml.safe_load(f)
    cases = data["cases"]
    if category:
        cases = [c for c in cases if c.get("category") == category]
    if tags:
        tag_set = set(tags)
        cases = [c for c in cases if tag_set & set(c.get("tags", []))]
    return cases


# ---------------------------------------------------------------------------
# Target function — builds a scenario-specific graph per case
# ---------------------------------------------------------------------------


async def agent_target(inputs: dict) -> dict:
    """Invoke a scenario-specific eval graph and return response + tool calls."""
    from langchain_core.messages import AIMessage, HumanMessage

    from evals.eval_graph import create_eval_graph

    scenario = inputs["scenario"]
    graph = create_eval_graph(scenario)

    result = await graph.ainvoke(
        {"messages": [HumanMessage(content=inputs["query"])], "user_id": "eval"},
        config={"configurable": {"thread_id": str(uuid4())}},
    )

    messages = result["messages"]

    # Extract tool names and final (non-tool-call) AI response
    tool_names: list[str] = []
    final_response = ""
    for msg in messages:
        if isinstance(msg, AIMessage):
            if msg.tool_calls:
                tool_names.extend(tc["name"] for tc in msg.tool_calls)
            elif msg.content:
                final_response = msg.content

    return {"response": final_response, "tool_calls": tool_names}


# ---------------------------------------------------------------------------
# Run evals
# ---------------------------------------------------------------------------


async def run_evals(category: str | None = None, tags: list[str] | None = None) -> None:
    """Main entry point — load cases, create dataset, run evaluators."""
    from dotenv import load_dotenv

    load_dotenv(_AI_AGENT_DIR / ".env")

    from langsmith import Client
    from langsmith.evaluation import aevaluate

    from evals.evaluators import ALL_EVALUATORS

    # 1. Load cases
    cases = _load_cases(category=category, tags=tags)
    if not cases:
        print("No eval cases matched the given filters.")
        sys.exit(1)
    print(f"Loaded {len(cases)} eval cases.")

    # 2. Create LangSmith dataset
    print("Creating LangSmith dataset...")
    ls = Client()
    dataset_name = "openemr-agent-mocked"

    # Delete existing dataset if present (idempotent)
    try:
        existing = ls.read_dataset(dataset_name=dataset_name)
        ls.delete_dataset(dataset_id=existing.id)
        print("  Replaced existing dataset.")
    except Exception:
        pass

    dataset = ls.create_dataset(
        dataset_name=dataset_name,
        description=f"Mocked evals for the OpenEMR AI agent ({len(cases)} cases).",
    )

    for case in cases:
        ls.create_example(
            inputs={"query": case["query"], "scenario": case["scenario"]},
            outputs={
                "expected": case["expected"],
                "no_hallucination": case.get("no_hallucination", False),
            },
            dataset_id=dataset.id,
            metadata={"name": case["name"], "category": case.get("category", "")},
        )
    print(f"  Created dataset with {len(cases)} examples.")

    # 3. Run evals
    print("\nRunning evals (this may take a few minutes)...")
    results = await aevaluate(
        agent_target,
        data=dataset_name,
        evaluators=ALL_EVALUATORS,
        experiment_prefix="openemr-mocked",
        max_concurrency=4,
    )

    # 4. Print results summary
    print("\n" + "=" * 60)
    print("EVAL RESULTS")
    print("=" * 60)

    total = 0
    passed = 0
    async for result in results:
        total += 1
        example = (
            result.get("example")
            if isinstance(result, dict)
            else getattr(result, "example", None)
        )
        if example is not None:
            metadata = example.metadata if hasattr(example, "metadata") else {}
            name = (metadata or {}).get("name", f"case-{total}")
        else:
            name = f"case-{total}"

        eval_results_obj = (
            result.get("evaluation_results")
            if isinstance(result, dict)
            else getattr(result, "evaluation_results", None)
        )
        if isinstance(eval_results_obj, dict):
            eval_list = eval_results_obj.get("results", [])
        elif isinstance(eval_results_obj, list):
            eval_list = eval_results_obj
        else:
            eval_list = (
                getattr(eval_results_obj, "results", []) if eval_results_obj else []
            )

        scores = {}
        for r in eval_list:
            key = r.get("key") if isinstance(r, dict) else getattr(r, "key", None)
            score_val = (
                r.get("score") if isinstance(r, dict) else getattr(r, "score", None)
            )
            if key is not None and score_val is not None:
                scores[key] = score_val

        all_pass = scores and all(s == 1.0 for s in scores.values())
        if all_pass:
            passed += 1
        status = "PASS" if all_pass else "FAIL"
        print(f"  [{status}] {name}")
        for key, score in scores.items():
            marker = "ok" if score == 1.0 else "!!"
            print(f"         [{marker}] {key}: {score:.2f}")

    print(f"\n  {passed}/{total} evals passed")
    print("  Results also visible in LangSmith UI -> dataset 'openemr-agent-mocked'")
    print("=" * 60)

    if passed < total:
        sys.exit(1)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run mocked eval harness for OpenEMR AI agent"
    )
    parser.add_argument(
        "--category",
        help="Filter by category (happy_path, negative, adversarial)",
    )
    parser.add_argument(
        "--tags",
        nargs="+",
        help="Filter by tags (e.g., single_tool appointments)",
    )
    args = parser.parse_args()
    asyncio.run(run_evals(category=args.category, tags=args.tags))


if __name__ == "__main__":
    main()
