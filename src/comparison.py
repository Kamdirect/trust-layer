"""Compare three ways of finding problems in two versions of the same numbers.

  1. Exact match: what an analyst does with VLOOKUP or a pivot table. Total each
     month-region-product in both files, and flag every line that differs (revenue to the
     nearest pound, volume exactly) or exists in only one file.
  2. Simple rules: a careful analyst's standard checklist, with no statistics. Flag rows
     labelled "total" or with a blank product, exact duplicate rows and blank cells; then
     compare region-month totals and flag any gap over 0.1%.
  3. Trust Layer: every check in src/checks.py.

All three are scored in the same way on the same cases. Each flag is one item an analyst
must look at (a row, or a whole region-month). A planted problem counts as DETECTED when
every one of its rows is covered by at least one flag, of any type, in the same place. So
the baselines are not penalised for being unable to name the problem.
"""

from __future__ import annotations

import time

import pandas as pd

from src.checks import KEY, run_all_checks, validate_schema
from src.evaluate import NOT_SCORED, _matches


def _flag(month, region, product=None, rule="") -> dict:
    product = None if product is None or pd.isna(product) or product == "" else product
    return {"month": month, "region": region, "product": product, "rule": rule}


def exact_match(raw_a: pd.DataFrame, raw_b: pd.DataFrame) -> list[dict]:
    def lines(df):
        d = validate_schema(df, "X").copy()
        d["product"] = d["product"].fillna("")
        g = d.groupby(KEY, dropna=False).agg(volume=("volume", lambda s: s.sum(min_count=len(s))),
                                             revenue=("revenue_gbp", lambda s: s.sum(min_count=len(s))))
        return g
    a, b = lines(raw_a), lines(raw_b)
    both = a.merge(b, left_index=True, right_index=True, how="outer", suffixes=("_a", "_b"))
    flags = []
    for (month, region, product), r in both.iterrows():
        values = [r["volume_a"], r["volume_b"], r["revenue_a"], r["revenue_b"]]
        if any(pd.isna(v) for v in values):  # in one file only, or a blank cell
            differs = True
        else:
            differs = (r["volume_a"] != r["volume_b"]
                       or round(r["revenue_a"]) != round(r["revenue_b"]))
        if differs:
            flags.append(_flag(month, region, product, "line differs"))
    return flags


def simple_rules(raw_a: pd.DataFrame, raw_b: pd.DataFrame, tolerance_pct: float = 0.1) -> list[dict]:
    flags, bodies = [], {}
    for raw, name in [(raw_a, "A"), (raw_b, "B")]:
        d = validate_schema(raw, name)
        is_total = d["product"].isna() | d["product"].str.contains("total", case=False, na=False)
        dup = d.duplicated(keep="first")
        blank = d[["volume", "revenue_gbp"]].isna().any(axis=1)
        for mask, rule in [(is_total, "total or blank product"), (dup, "duplicate"), (blank & ~is_total, "blank cell")]:
            flags += [_flag(r.month, r.region, r.product, rule) for r in d[mask].itertuples()]
        bodies[name] = d[~is_total & ~dup]
    ta = bodies["A"].groupby(["month", "region"])[["volume", "revenue_gbp"]].sum()
    tb = bodies["B"].groupby(["month", "region"])[["volume", "revenue_gbp"]].sum()
    t = ta.merge(tb, left_index=True, right_index=True, how="outer", suffixes=("_a", "_b")).fillna(0)
    for (month, region), r in t.iterrows():
        rev_gap = abs(r["revenue_gbp_a"] - r["revenue_gbp_b"]) / max(abs(r["revenue_gbp_b"]), 1)
        vol_gap = abs(r["volume_a"] - r["volume_b"]) / max(abs(r["volume_b"]), 1)
        if max(rev_gap, vol_gap) * 100 > tolerance_pct:
            flags.append(_flag(month, region, None, "region-month total gap"))
    return flags


def trust_layer(raw_a: pd.DataFrame, raw_b: pd.DataFrame) -> list[dict]:
    issues = [i for i in run_all_checks(raw_a, raw_b) if i.check not in NOT_SCORED]
    return [_flag(r["month"], r["region"], r["product"], i.check) for i in issues for r in i.rows]


METHODS = {"Exact match": exact_match, "Simple rules": simple_rules, "Trust Layer": trust_layer}


def score_case(flags: list[dict], key: list[dict]) -> dict:
    planted_rows = [r for p in key for r in p["rows"]]
    detected = [all(any(_matches(f, r) for f in flags) for r in p["rows"]) for p in key]
    # Named: found by a flag whose rule is the planted problem's own type (Trust Layer only:
    # the baselines do not name problem types).
    named = [all(any(_matches(f, r) and f["rule"] == p["issue_type"] for f in flags)
                 for r in p["rows"]) for p in key]
    genuine = [any(_matches(f, r) for r in planted_rows) for f in flags]
    return {"detected": detected, "named": named, "flags": len(flags), "genuine_flags": sum(genuine)}


def run(cases: list[tuple[int, pd.DataFrame, pd.DataFrame, list[dict]]]) -> pd.DataFrame:
    """One row per (case, method, planted problem), plus one row per (case, method) with no
    problem for clean cases, so false alarms on clean data are counted too."""
    rows = []
    for seed, a, b, key in cases:
        for name, method in METHODS.items():
            start = time.perf_counter()
            flags = method(a, b)
            ms = 1000 * (time.perf_counter() - start)
            s = score_case(flags, key)
            base = {"case": seed, "method": name, "clean_case": not key, "flags": s["flags"],
                    "genuine_flags": s["genuine_flags"], "ms": ms}
            if not key:
                rows.append(base | {"issue_type": None, "detected": None})
            for p, hit, named in zip(key, s["detected"], s["named"]):
                rows.append(base | {"issue_type": p["issue_type"], "detected": hit, "named": named,
                                    "in_both_files": p["detail"].get("in_both_files", False),
                                    "detail": str(p["detail"])})
    return pd.DataFrame(rows)


def summarise(results: pd.DataFrame) -> pd.DataFrame:
    """Per method: recall, precision, false alarms on clean cases, review effort and speed."""
    out = {}
    for name, g in results.groupby("method", sort=False):
        per_case = g.drop_duplicates("case")
        planted = g.dropna(subset=["issue_type"])
        clean = per_case[per_case["clean_case"]]
        out[name] = {
            "problems detected (recall)": planted["detected"].mean(),
            "flags that were genuine (precision)": per_case["genuine_flags"].sum() / max(per_case["flags"].sum(), 1),
            "clean cases with any false alarm": (clean["flags"] > 0).mean(),
            "items to review per case": per_case["flags"].mean(),
            "false alarms per case": (per_case["flags"] - per_case["genuine_flags"]).mean(),
            "ms per case": per_case["ms"].mean(),
        }
    return pd.DataFrame(out)


def recall_by_type(results: pd.DataFrame) -> pd.DataFrame:
    planted = results.dropna(subset=["issue_type"])
    return planted.pivot_table(index="issue_type", columns="method", values="detected",
                               aggfunc="mean", sort=False)[list(METHODS)]
