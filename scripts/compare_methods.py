"""The comparison experiment: exact matching vs simple rules vs Trust Layer, on 200
independent cases that were not used to build or tune anything.

Procedure (so the result can be trusted):
  - The checks in src/checks.py were finished before src/independent_cases.py was written.
  - The comparison code was debugged on cases 900-939 only.
  - The reported run uses cases 1000-1199. It was run once, and nothing in the checks was
    changed after seeing it.

Run from the project root:  python -m scripts.compare_methods   (about 30 seconds, free)
"""

import warnings
from pathlib import Path

import pandas as pd

from src.comparison import recall_by_type, run, summarise
from src.independent_cases import make_case

SEEDS = range(1000, 1200)
DOCS = Path("docs")


def main() -> None:
    warnings.simplefilter("ignore")
    cases = [(s, *make_case(s)) for s in SEEDS]
    results = run(cases)
    summary, by_type = summarise(results), recall_by_type(results)
    planted = results.dropna(subset=["issue_type"])
    tl = planted[planted["method"] == "Trust Layer"]

    pd.set_option("display.width", 140)
    n_clean = int(results.drop_duplicates("case")["clean_case"].sum())
    print(f"{len(cases)} independent cases ({n_clean} with no problems), "
          f"{len(planted) // 3} planted problems\n")
    print(summary.round(3).to_string())
    print("\nShare of planted problems detected, by type")
    print(by_type.round(3).to_string())

    both = planted[planted["issue_type"].isin(["unit_mismatch", "outlier"])]
    split = both.pivot_table(index="in_both_files", columns="method", values="detected",
                             aggfunc="mean")[list(summary.columns)]
    split.index = split.index.map({True: "error in BOTH files", False: "error in file A only"})
    print("\nUnit mix-ups and wrong values: does it matter which file the error is in?")
    print(split.round(3).to_string())

    out = tl[tl["issue_type"] == "outlier"].assign(
        factor=lambda d: d["detail"].str.extract(r"'factor': ([\d.]+)")[0].astype(float))
    print("\nTrust Layer, wrong values detected by size of error")
    print(out.groupby("factor")["detected"].agg(["mean", "size"]).round(3).to_string())
    print(f"\nTrust Layer named the right problem type for {tl['named'].mean():.1%} of planted problems.")

    misses = tl[~tl["detected"].astype(bool)][["case", "issue_type", "detail"]]
    print(f"\nTrust Layer misses ({len(misses)}):")
    print(misses.to_string(index=False) if len(misses) else "  none")

    DOCS.mkdir(exist_ok=True)
    summary.round(4).to_csv(DOCS / "method_comparison.csv")
    by_type.round(4).to_csv(DOCS / "method_comparison_by_type.csv")
    results.to_csv(DOCS / "method_comparison_results.csv", index=False)
    print(f"\nSaved {DOCS / 'method_comparison.csv'}, _by_type.csv and _results.csv")


if __name__ == "__main__":
    main()
