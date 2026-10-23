"""Measure the AI layer: run the real model several times on the sample data and count how
many sentences the number check had to remove. Costs well under $0.01 per run with Haiku.

Run from the project root (needs ANTHROPIC_API_KEY in .env):
    python -m scripts.evaluate_ai
"""

import json
import sys
from datetime import date
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv

from src.checks import run_all_checks
from src.explain import MODEL, _SENTENCE_SPLIT, explain

RUNS = 10
OUT = Path("docs/ai_evaluation.json")


def main() -> None:
    load_dotenv()
    a = pd.read_csv("data/sales_system.csv")
    b = pd.read_csv("data/finance_report.csv")
    issues = run_all_checks(a, b)

    results, failures = [], []
    for run in range(1, RUNS + 1):
        ex = explain(issues)
        if ex.error:
            failures.append({"run": run, "error": ex.error})
            print(f"Run {run:>2}: FAILED - {ex.error}")
            continue
        total = len([s for s in _SENTENCE_SPLIT.split(ex.raw) if s.strip()])
        results.append({"run": run, "sentences": total, "removed": ex.rejected, "raw": ex.raw})
        print(f"Run {run:>2}: {total} sentences, {len(ex.rejected)} removed by the number check")

    if not results:
        sys.exit("Every run failed; nothing to measure.")
    sentences = sum(r["sentences"] for r in results)
    removed = sum(len(r["removed"]) for r in results)
    print(f"\nModel: {MODEL}")
    print(f"Runs that produced a summary: {len(results)} / {RUNS}")
    print(f"Total: {sentences} sentences, {removed} removed ({100 * removed / sentences:.1f}%)")
    print("Sentences shown to users with an unsupported number: 0 (removed by design)")

    OUT.write_text(
        json.dumps(
            {"date": date.today().isoformat(), "model": MODEL, "runs": RUNS,
             "failed_runs": failures, "sentences": sentences, "removed": removed,
             "results": results},
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"Every answer and every removed sentence saved to {OUT} for review.")


if __name__ == "__main__":
    main()
