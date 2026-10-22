"""Deterministic data-quality checks. No AI here: every result must be reproducible."""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

REQUIRED_COLUMNS = ["month", "region", "product", "unit", "volume", "revenue_gbp"]
KEY = ["month", "region", "product"]


class SchemaError(ValueError):
    """Raised when a file is missing columns or has non-numeric values."""


@dataclass
class Issue:
    check: str                 # machine name, e.g. "duplicate_row"
    severity: str              # "critical", "high", "medium" or "info"
    file: str                  # "A" or "B"
    title: str                 # one-line human summary
    rows: list[dict] = field(default_factory=list)      # month/region/product of affected rows
    row_index: list[int] = field(default_factory=list)  # DataFrame index, for highlighting
    numbers: dict = field(default_factory=dict)         # numeric facts (used by the AI number-check)


def _keys(df: pd.DataFrame) -> list[dict]:
    out = []
    for r in df[KEY].itertuples(index=False):
        product = None if pd.isna(r.product) else r.product
        out.append({"month": r.month, "region": r.region, "product": product})
    return out


# ---------------------------------------------------------------- validation
def validate_schema(df: pd.DataFrame, file: str) -> pd.DataFrame:
    """Check required columns exist and numbers are numeric. Returns a cleaned copy."""
    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise SchemaError(f"File {file} is missing required column(s): {', '.join(missing)}")
    out = df[REQUIRED_COLUMNS].copy()
    for col in ["volume", "revenue_gbp"]:
        converted = pd.to_numeric(out[col], errors="coerce")
        bad = converted.isna() & out[col].notna()
        if bad.any():
            raise SchemaError(
                f"File {file}, column '{col}' has {int(bad.sum())} non-numeric value(s), "
                f"first at row {int(bad.idxmax()) + 2} of the file"
            )
        out[col] = converted
    for col in ["month", "region", "product", "unit"]:
        out[col] = out[col].astype("string").str.strip().replace("", pd.NA)
    return out


# ---------------------------------------------------------------- checks
def check_duplicates(df: pd.DataFrame, file: str) -> list[Issue]:
    """Rows that are exact copies of an earlier row."""
    extra = df[df.duplicated(keep="first")]
    if extra.empty:
        return []
    return [
        Issue(
            check="duplicate_row",
            severity="high",
            file=file,
            title=f"{len(extra)} duplicate row(s) in file {file}",
            rows=_keys(extra),
            row_index=extra.index.tolist(),
            numbers={
                "duplicate_rows": len(extra),
                "duplicated_volume": int(extra["volume"].sum()),
                "duplicated_revenue_gbp": round(float(extra["revenue_gbp"].sum()), 2),
            },
        )
    ]


def check_subtotal_rows(df: pd.DataFrame, file: str) -> list[Issue]:
    """Rows labelled like a total, or whose values equal the sum of the other rows
    in the same month and region."""
    label_hit = df["product"].fillna("").str.contains(r"\b(?:sub)?total\b", case=False, regex=True)

    body = df.drop_duplicates()
    grp = body.groupby(["month", "region"])
    vol_sum = grp["volume"].transform("sum")
    rev_sum = grp["revenue_gbp"].transform("sum")
    size = grp["volume"].transform("size")
    # A row equals the sum of the others when 2 * value == group sum.
    value_hit = (
        (size >= 3)
        & ((2 * body["volume"] - vol_sum).abs() <= 0.5)
        & ((2 * body["revenue_gbp"] - rev_sum).abs() <= 0.05)
    )
    hit_index = sorted(set(df.index[label_hit]) | set(body.index[value_hit]))
    if not hit_index:
        return []
    hits = df.loc[hit_index]
    return [
        Issue(
            check="subtotal_row",
            severity="critical",
            file=file,
            title=f"{len(hits)} subtotal row(s) mixed into product rows in file {file}",
            rows=_keys(hits),
            row_index=hit_index,
            numbers={
                "subtotal_rows": len(hits),
                "double_counted_volume": int(hits["volume"].sum()),
                "double_counted_revenue_gbp": round(float(hits["revenue_gbp"].sum()), 2),
            },
        )
    ]


def check_missing_values(df: pd.DataFrame, file: str) -> list[Issue]:
    """Blank cells in any required column."""
    null_rows = df[df[REQUIRED_COLUMNS].isna().any(axis=1)]
    if null_rows.empty:
        return []
    counts = {f"blank_{c}": int(n) for c, n in df[REQUIRED_COLUMNS].isna().sum().items() if n}
    return [
        Issue(
            check="missing_value",
            severity="medium",
            file=file,
            title=f"{len(null_rows)} row(s) with blank values in file {file}",
            rows=_keys(null_rows),
            row_index=null_rows.index.tolist(),
            numbers=counts,
        )
    ]


def check_missing_periods(
    df: pd.DataFrame, file: str, months: list[str], regions: list[str]
) -> list[Issue]:
    """Region-months that should exist (seen anywhere in either file) but have no rows here."""
    present = set(zip(df["month"], df["region"]))
    gaps = [(m, r) for r in regions for m in months if (m, r) not in present]
    if not gaps:
        return []
    return [
        Issue(
            check="missing_period",
            severity="high",
            file=file,
            title=f"{len(gaps)} region-month(s) with no data in file {file}",
            rows=[{"month": m, "region": r, "product": None} for m, r in gaps],
            numbers={"missing_region_months": len(gaps)},
        )
    ]


def check_unit_consistency(df: pd.DataFrame, file: str, max_ratio: float = 3.0) -> list[Issue]:
    """Rows whose implied price per unit is far from that product's typical price.
    A ratio near 1/24 usually means bottles were entered as cases."""
    valid = df[(df["volume"] > 0) & df["product"].notna()]
    price = valid["revenue_gbp"] / valid["volume"]
    ref = price.groupby(valid["product"]).transform("median")
    ratio = price / ref
    bad = ratio[(ratio < 1 / max_ratio) | (ratio > max_ratio)]
    if bad.empty:
        return []
    rows = valid.loc[bad.index]
    factors = (1 / bad).where(bad < 1, bad).round(1)
    return [
        Issue(
            check="unit_mismatch",
            severity="critical",
            file=file,
            title=f"{len(rows)} row(s) with an implausible price per unit in file {file}",
            rows=_keys(rows),
            row_index=bad.index.tolist(),
            numbers={
                "rows_flagged": len(rows),
                "implied_price_gbp": [round(float(p), 2) for p in price.loc[bad.index]],
                "typical_price_gbp": [round(float(p), 2) for p in ref.loc[bad.index]],
                "off_by_factor": [float(f) for f in factors],
            },
        )
    ]


def check_outliers(
    df: pd.DataFrame, file: str, exclude: list[int] | None = None, threshold: float = 5.0
) -> list[Issue]:
    """Volumes far from what is normal for that product, region AND month.

    1. Seasonality: each month gets a factor, the median across all product-regions of
       volume / that product-region's median (July is about 1.3, January about 0.7).
    2. Expected volume = product-region median x month factor.
    3. Deviation is measured on a log scale, log(volume / expected), so +100% and -50%
       count as equally far, and one scale works for big and small products.
    4. The spread (MAD) is pooled across ALL rows. With only 12 months per product-region,
       a per-group spread is unstable and makes ordinary noise look extreme.
    5. threshold=5.0 was chosen on seeds 0-199 and checked on unseen seeds 5000-5199
       (see scripts/outlier_sensitivity.py). Lower = more sensitive, more false alarms.
    Rows already explained by another check (e.g. a unit mix-up) are excluded."""
    valid = df[(df["product"].notna()) & (df["volume"] > 0)].drop(index=exclude or [], errors="ignore")
    if len(valid) < 10:
        return []
    pr_median = valid.groupby(["product", "region"])["volume"].transform("median")
    seasonal = (valid["volume"] / pr_median).groupby(valid["month"]).transform("median")
    expected = pr_median * seasonal

    log_dev = np.log(valid["volume"] / expected)
    centre = log_dev.median()
    mad = (log_dev - centre).abs().median()
    if mad == 0:
        return []
    z = 0.6745 * (log_dev - centre) / mad
    hits = z[z.abs() > threshold]
    if hits.empty:
        return []
    rows = valid.loc[hits.index]
    return [
        Issue(
            check="outlier",
            severity="high",
            file=file,
            title=f"{len(rows)} extreme value(s) in file {file}",
            rows=_keys(rows),
            row_index=hits.index.tolist(),
            numbers={
                "outlier_rows": len(rows),
                "volume": [int(v) for v in rows["volume"]],
                "expected_volume": [int(round(v)) for v in expected.loc[hits.index]],
                "robust_z": [round(float(v), 1) for v in hits],
            },
        )
    ]


def reconcile(
    a: pd.DataFrame, b: pd.DataFrame, found: list[Issue], tolerance_pct: float = 0.1
) -> list[Issue]:
    """Compare region-month totals of A and B. Each gap is either explained by an issue
    already found in that region-month, or reported as unexplained."""
    def totals(df: pd.DataFrame) -> pd.DataFrame:
        return df.groupby(["month", "region"])[["volume", "revenue_gbp"]].sum()

    t = totals(a).merge(
        totals(b), left_index=True, right_index=True, how="outer", suffixes=("_a", "_b")
    ).fillna(0)
    t["vol_gap"] = t["volume_a"] - t["volume_b"]
    t["rev_gap"] = (t["revenue_gbp_a"] - t["revenue_gbp_b"]).round(2)
    base = t["revenue_gbp_b"].abs().where(t["revenue_gbp_b"] != 0, 1)
    vol_base = t["volume_b"].abs().where(t["volume_b"] != 0, 1)
    t["rev_gap_pct"] = (100 * t["rev_gap"] / base).round(2)
    t["vol_gap_pct"] = (100 * t["vol_gap"] / vol_base).round(2)
    gaps = t[(t["rev_gap_pct"].abs() > tolerance_pct) | (t["vol_gap_pct"].abs() > tolerance_pct)]

    explained_by: dict[tuple, list[str]] = {}
    for issue in found:
        for r in issue.rows:
            explained_by.setdefault((r["month"], r["region"]), []).append(issue.check)

    explained, unexplained = [], []
    for (month, region), g in gaps.iterrows():
        entry = {
            "month": month,
            "region": region,
            "product": None,
            "revenue_gap_gbp": float(g["rev_gap"]),
            "revenue_gap_pct": float(g["rev_gap_pct"]),
            "volume_gap": int(g["vol_gap"]),
            "volume_gap_pct": float(g["vol_gap_pct"]),
        }
        causes = sorted(set(explained_by.get((month, region), [])))
        if causes:
            entry["explained_by"] = causes
            explained.append(entry)
        else:
            unexplained.append(entry)

    issues = []
    if unexplained:
        issues.append(
            Issue(
                check="reconciliation_gap",
                severity="high",
                file="A vs B",
                title=f"{len(unexplained)} region-month total(s) disagree with no explanation",
                rows=unexplained,
                numbers={"unexplained_gaps": len(unexplained)},
            )
        )
    if explained:
        issues.append(
            Issue(
                check="reconciliation_explained",
                severity="info",
                file="A vs B",
                title=f"{len(explained)} region-month gap(s) explained by issues above",
                rows=explained,
                numbers={"explained_gaps": len(explained)},
            )
        )
    return issues


# ---------------------------------------------------------------- pipeline
def run_all_checks(raw_a: pd.DataFrame, raw_b: pd.DataFrame) -> list[Issue]:
    """Validate both files, run every check, then reconcile the cleaned versions."""
    a = validate_schema(raw_a, "A")
    b = validate_schema(raw_b, "B")
    months = sorted(set(a["month"].dropna()) | set(b["month"].dropna()))
    regions = sorted(set(a["region"].dropna()) | set(b["region"].dropna()))

    issues: list[Issue] = []
    cleaned = {}
    for df, name in [(a, "A"), (b, "B")]:
        subtotals = check_subtotal_rows(df, name)
        dups = check_duplicates(df, name)
        drop = {i for issue in subtotals + dups for i in issue.row_index}
        body = df.drop(index=sorted(drop))

        units = check_unit_consistency(body, name)
        unit_rows = [i for issue in units for i in issue.row_index]
        issues += subtotals + dups
        issues += check_missing_values(body, name)
        issues += check_missing_periods(body, name, months, regions)
        issues += units
        issues += check_outliers(body, name, exclude=unit_rows)
        cleaned[name] = body

    issues += reconcile(cleaned["A"], cleaned["B"], issues)
    return issues