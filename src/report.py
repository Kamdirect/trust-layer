"""Turn check results into things people read: a summary, a table and a downloadable report."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import BinaryIO

import pandas as pd

from src.checks import Issue

SEVERITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "info": 3}
MAX_FILE_MB = 20

# What a person should do next for each kind of issue. Fixed text, written by a human.
NEXT_STEPS = {
    "subtotal_row": "Remove these rows before summing, or filter on product. Ask the owner of the extract to export without subtotals.",
    "duplicate_row": "Check whether the extract was run twice. Keep one copy of each row.",
    "missing_value": "Find the blank cells in the source system and fill or exclude them before reporting.",
    "missing_period": "Confirm whether the upload for this region-month failed. Re-run the extract for that period.",
    "unit_mismatch": "Check the unit of measure on these rows. A factor near 24 usually means bottles were entered as cases.",
    "outlier": "Check the source transaction for a typo (for example an extra zero) before using this number.",
    "reconciliation_gap": "Ask finance for the journal or adjustment behind this difference. It is not explained by any data issue.",
}


def read_table(file: BinaryIO | str | Path, name: str | None = None) -> pd.DataFrame:
    """Read a CSV or Excel file. Raises ValueError with a readable message on failure."""
    name = name or getattr(file, "name", str(file))
    size = getattr(file, "size", None)
    if size is not None and size > MAX_FILE_MB * 1024 * 1024:
        raise ValueError(f"{name} is larger than {MAX_FILE_MB} MB.")
    suffix = Path(name).suffix.lower()
    try:
        if suffix == ".csv":
            return pd.read_csv(file)
        if suffix in (".xlsx", ".xls"):
            return pd.read_excel(file)
    except Exception as exc:  # pandas raises many different error types
        raise ValueError(f"Could not read {name}: {exc}") from exc
    raise ValueError(f"{name}: only .csv and .xlsx files are supported.")


def problems(issues: list[Issue]) -> list[Issue]:
    """Issues that need action (excludes 'info' items), most severe first."""
    real = [i for i in issues if i.severity != "info"]
    return sorted(real, key=lambda i: SEVERITY_ORDER.get(i.severity, 9))


def summary(issues: list[Issue]) -> dict:
    real = problems(issues)
    return {
        "issues": len(real),
        "critical": sum(i.severity == "critical" for i in real),
        "rows_affected": sum(len(i.rows) for i in real),
    }


def impact(issue: Issue, issues: list[Issue]) -> dict:
    """How much money and volume an issue puts at stake, so the biggest problems go first.

    Taken from the issue's own numbers where it has them (subtotals, duplicates, finance
    gaps), otherwise from the A-vs-B gap it causes in the same region-month. None when the
    size cannot be measured: for example, an error present in both files causes no gap."""
    n = issue.numbers
    if issue.check == "subtotal_row":
        return {"gbp": n["double_counted_revenue_gbp"], "cases": n["double_counted_volume"]}
    if issue.check == "duplicate_row":
        return {"gbp": n["duplicated_revenue_gbp"], "cases": n["duplicated_volume"]}
    if issue.check == "reconciliation_gap":
        return {"gbp": round(sum(abs(r["revenue_gap_gbp"]) for r in issue.rows), 2),
                "cases": sum(abs(r["volume_gap"]) for r in issue.rows)}
    places = {(r["month"], r["region"]) for r in issue.rows}
    gaps = [r for i in issues if i.check == "reconciliation_explained" for r in i.rows
            if (r["month"], r["region"]) in places and issue.check in r.get("explained_by", [])]
    if gaps:
        return {"gbp": round(sum(abs(r["revenue_gap_gbp"]) for r in gaps), 2),
                "cases": sum(abs(r["volume_gap"]) for r in gaps)}
    if issue.check == "outlier":
        return {"gbp": None, "cases": int(sum(abs(v - e) for v, e in
                                              zip(n["volume"], n["expected_volume"])))}
    return {"gbp": None, "cases": None}


def issues_table(issues: list[Issue]) -> pd.DataFrame:
    """One row per issue, most severe first and, within a severity, largest money at stake first."""
    rows = []
    for i in issues:
        size = impact(i, issues) if i.check != "reconciliation_explained" else {"gbp": None, "cases": None}
        rows.append({"severity": i.severity, "check": i.check, "file": i.file, "issue": i.title,
                     "rows affected": len(i.rows), "£ at stake": size["gbp"],
                     "cases at stake": size["cases"]})
    df = pd.DataFrame(rows, columns=["severity", "check", "file", "issue", "rows affected",
                                     "£ at stake", "cases at stake"])
    df["_order"] = df["severity"].map(SEVERITY_ORDER).fillna(9)
    return (df.sort_values(["_order", "£ at stake", "cases at stake"], ascending=[True, False, False],
                           na_position="last").drop(columns="_order").reset_index(drop=True))


def rows_table(issue: Issue) -> pd.DataFrame:
    """The affected rows of one issue, with any extra numeric detail (e.g. reconciliation gaps)."""
    df = pd.DataFrame(issue.rows)
    if "explained_by" in df:
        df["explained_by"] = df["explained_by"].apply(", ".join)
    return df


def _md_table(df: pd.DataFrame) -> str:
    """Minimal Markdown table, so the report needs no extra libraries."""
    cells = df.astype(object).where(df.notna(), "")
    header = "| " + " | ".join(map(str, df.columns)) + " |"
    rule = "|" + "---|" * len(df.columns)
    body = ["| " + " | ".join(map(str, row)) + " |" for row in cells.itertuples(index=False)]
    return "\n".join([header, rule, *body])


def markdown_report(issues: list[Issue], explanation: str | None = None) -> str:
    """A plain-text report someone can save, email or paste into a ticket."""
    s = summary(issues)
    lines = [
        "# Trust Layer reconciliation report",
        f"Generated {date.today().isoformat()}.",
        "",
        f"**{s['issues']} issue(s), {s['critical']} critical, {s['rows_affected']} row(s) affected.**",
        "",
        "All findings below come from deterministic checks. No data was changed.",
        "",
    ]
    if explanation:
        lines += ["## Plain-English summary (AI-written, number-checked)", "", explanation, ""]
    order = {row["issue"]: n for n, row in issues_table(issues).iterrows()}
    for i in sorted(issues, key=lambda i: order.get(i.title, 99)):
        lines += [f"## [{i.severity.upper()}] {i.title}", "", f"Check: `{i.check}` · File: {i.file}", ""]
        if i.check in NEXT_STEPS:
            lines += [f"**What to check:** {NEXT_STEPS[i.check]}", ""]
            size = impact(i, issues)
            if size["gbp"] is not None or size["cases"] is not None:
                parts = [f"£{size['gbp']:,.0f}" if size["gbp"] is not None else None,
                         f"{size['cases']:,} cases" if size["cases"] is not None else None]
                lines += ["**At stake:** " + ", ".join(p for p in parts if p), ""]
        if i.numbers:
            lines += [f"- {k}: {v}" for k, v in i.numbers.items()] + [""]
        if i.rows:
            lines += [_md_table(rows_table(i).head(20)), ""]
    return "\n".join(lines)