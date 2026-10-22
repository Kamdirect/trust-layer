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


def issues_table(issues: list[Issue]) -> pd.DataFrame:
    """One row per issue, for display."""
    return pd.DataFrame(
        [
            {
                "severity": i.severity,
                "check": i.check,
                "file": i.file,
                "issue": i.title,
                "rows affected": len(i.rows),
            }
            for i in sorted(issues, key=lambda i: SEVERITY_ORDER.get(i.severity, 9))
        ],
        columns=["severity", "check", "file", "issue", "rows affected"],
    )


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
    for i in sorted(issues, key=lambda i: SEVERITY_ORDER.get(i.severity, 9)):
        lines += [f"## [{i.severity.upper()}] {i.title}", "", f"Check: `{i.check}` · File: {i.file}", ""]
        if i.check in NEXT_STEPS:
            lines += [f"**What to check:** {NEXT_STEPS[i.check]}", ""]
        if i.numbers:
            lines += [f"- {k}: {v}" for k, v in i.numbers.items()] + [""]
        if i.rows:
            lines += [_md_table(rows_table(i).head(20)), ""]
    return "\n".join(lines)