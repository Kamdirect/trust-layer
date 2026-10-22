"""Score the checks against the answer key, then stress-test them on many random datasets.

Run from the project root:  python -m src.evaluate
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from src.checks import Issue, run_all_checks
from src.synthetic_data import generate_clean, plant_issues

# Issues that describe consequences of other issues, not problems in their own right.
NOT_SCORED = {"reconciliation_explained"}


def _norm(product):
    return None if product in (None, "") or pd.isna(product) else product


def _matches(found_row: dict, planted_row: dict) -> bool:
    """Same month and region; product must match unless either side is a whole region-month."""
    if (found_row["month"], found_row["region"]) != (planted_row["month"], planted_row["region"]):
        return False
    fp, pp = _norm(found_row["product"]), _norm(planted_row["product"])
    return fp is None or pp is None or fp == pp


def score(issues: list[Issue], answer_key: list[dict]) -> dict:
    """Return which planted issues were caught and which flagged rows were false alarms."""
    scored = [i for i in issues if i.check not in NOT_SCORED]
    results = []
    for planted in answer_key:
        same_type = [i for i in scored if i.check == planted["issue_type"]]
        caught = all(
            any(_matches(fr, pr) for i in same_type for fr in i.rows) for pr in planted["rows"]
        )
        results.append({"issue_id": planted["issue_id"], "issue_type": planted["issue_type"], "caught": caught})

    false_alarms = []
    for issue in scored:
        planted_rows = [pr for p in answer_key if p["issue_type"] == issue.check for pr in p["rows"]]
        for fr in issue.rows:
            if not any(_matches(fr, pr) for pr in planted_rows):
                false_alarms.append({"check": issue.check, **{k: fr[k] for k in ("month", "region", "product")}})

    return {
        "caught": sum(r["caught"] for r in results),
        "planted": len(answer_key),
        "results": results,
        "false_alarms": false_alarms,
    }


def stress_test(n_seeds: int = 200) -> dict:
    """Run the checks on n_seeds random datasets, with and without planted problems."""
    clean_runs_with_alarm, planted_caught, planted_total, alarm_rows = 0, 0, 0, 0
    for seed in range(n_seeds):
        clean = generate_clean(seed)
        clean_issues = [i for i in run_all_checks(clean, clean.copy()) if i.check not in NOT_SCORED]
        clean_runs_with_alarm += bool(clean_issues)

        a, b, key = plant_issues(clean)
        s = score(run_all_checks(a, b), key)
        planted_caught += s["caught"]
        planted_total += s["planted"]
        alarm_rows += len(s["false_alarms"])
    return {
        "datasets": n_seeds,
        "planted_caught": planted_caught,
        "planted_total": planted_total,
        "false_alarm_rows_with_planted": alarm_rows,
        "clean_datasets_with_any_alarm": clean_runs_with_alarm,
    }


def main() -> None:
    a = pd.read_csv("data/sales_system.csv")
    b = pd.read_csv("data/finance_report.csv")
    key = json.loads(Path("data/answer_key.json").read_text(encoding="utf-8"))

    s = score(run_all_checks(a, b), key)
    print("=== Score on the committed dataset ===")
    for r in s["results"]:
        print(f"  #{r['issue_id']} {r['issue_type']:<20} {'CAUGHT' if r['caught'] else 'MISSED'}")
    print(f"  Caught {s['caught']} of {s['planted']} planted issues, {len(s['false_alarms'])} false alarm(s)")
    for fa in s["false_alarms"]:
        print(f"    false alarm: {fa}")

    print("\n=== Stress test: 200 random datasets ===")
    st = stress_test(200)
    print(f"  Planted issues caught:              {st['planted_caught']} / {st['planted_total']}")
    print(f"  False-alarm rows (planted data):    {st['false_alarm_rows_with_planted']}")
    print(f"  Clean datasets with any alarm:      {st['clean_datasets_with_any_alarm']} / {st['datasets']}")


if __name__ == "__main__":
    main()