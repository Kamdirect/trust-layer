"""Trust Layer: find where two versions of the same numbers disagree, and why.

Run locally:  python -m streamlit run app.py
"""

import os
from pathlib import Path

import streamlit as st
from dotenv import load_dotenv

from src.checks import SchemaError, run_all_checks, validate_schema
from src.explain import MODEL, explain
from src.report import (
    NEXT_STEPS,
    issues_table,
    markdown_report,
    problems,
    read_table,
    rows_table,
    summary,
)

DATA = Path(__file__).parent / "data"
MAX_AI_CALLS_PER_SESSION = 5

# API key: from .env locally, or from Streamlit "Secrets" when deployed. Never in code.
load_dotenv()
try:
    if "ANTHROPIC_API_KEY" in st.secrets:
        os.environ["ANTHROPIC_API_KEY"] = st.secrets["ANTHROPIC_API_KEY"]
except Exception:  # no secrets file: fine, the AI summary will say it is unavailable
    pass


@st.cache_data(show_spinner=False, ttl=3600)
def ai_summary(_issues, cache_key: str):
    """One model call per distinct set of results; repeat clicks reuse the answer."""
    return explain(_issues)
SEVERITY_ICON = {"critical": "🔴", "high": "🟠", "medium": "🟡", "info": "🔵"}

st.set_page_config(page_title="Trust Layer", page_icon="🔎", layout="wide")
st.title("🔎 Trust Layer")
st.caption(
    "Upload two versions of the same numbers. Trust Layer tells you where they disagree, "
    "why, and what to check, before a wrong number reaches a manager."
)

# ------------------------------------------------------------------ inputs
with st.sidebar:
    st.header("1. Choose data")
    use_sample = st.toggle("Use the sample data", value=True)
    if use_sample:
        st.info(
            "Synthetic drinks sales with 6 planted problems. "
            "No real company data is used."
        )
        file_a = DATA / "sales_system.csv"
        file_b = DATA / "finance_report.csv"
    else:
        file_a = st.file_uploader("File A: sales system extract", type=["csv", "xlsx"])
        file_b = st.file_uploader("File B: finance report", type=["csv", "xlsx"])
        st.caption(
            "Required columns: month, region, product, unit, volume, revenue_gbp. "
            "Max 20 MB per file."
        )

if not file_a or not file_b:
    st.info("Upload both files in the sidebar, or switch on the sample data.")
    st.stop()

try:
    raw_a = read_table(file_a)
    raw_b = read_table(file_b)
    issues = run_all_checks(raw_a, raw_b)
    view_a = validate_schema(raw_a, "A")
except (SchemaError, ValueError) as exc:
    st.error(f"**Could not check these files.** {exc}")
    st.stop()

# ------------------------------------------------------------------ summary
s = summary(issues)
c1, c2, c3 = st.columns(3)
c1.metric("Issues found", s["issues"])
c2.metric("Critical", s["critical"])
c3.metric("Rows affected", s["rows_affected"])

if s["issues"] == 0:
    st.success("No issues found. The two files agree and pass every check.")

# ------------------------------------------------------------------ AI summary
st.subheader("AI summary")
st.caption(
    f"Written by {MODEL} from the check results only: the files themselves are never sent. "
    "Any sentence containing a number, month or product not found in the results is removed "
    "automatically and listed below."
)
calls = st.session_state.setdefault("ai_calls", 0)
if st.button("Write AI summary", disabled=calls >= MAX_AI_CALLS_PER_SESSION):
    st.session_state["ai_calls"] = calls + 1
    with st.spinner("Writing summary..."):
        cache_key = repr([(i.check, i.file, i.rows, i.numbers) for i in issues])
        st.session_state["explanation"] = ai_summary(issues, cache_key)
explanation = st.session_state.get("explanation")
if explanation is not None:
    if explanation.error:
        st.info(explanation.error)
    else:
        st.markdown(explanation.text)
        if explanation.rejected:
            with st.expander(f"⚠️ {len(explanation.rejected)} sentence(s) removed by the number check"):
                for sentence in explanation.rejected:
                    st.markdown(f"- {sentence}")
        else:
            st.caption("✅ Every number in this summary was found in the check results.")

st.subheader("Issues")
st.dataframe(issues_table(issues), hide_index=True, width="stretch")

# ------------------------------------------------------------------ detail
st.subheader("Details")
for issue in problems(issues):
    with st.expander(f"{SEVERITY_ICON[issue.severity]} {issue.title}"):
        st.write(f"Check: `{issue.check}` · File: {issue.file}")
        if issue.check in NEXT_STEPS:
            st.markdown(f"**What to check:** {NEXT_STEPS[issue.check]}")
        st.json(issue.numbers, expanded=False)
        st.dataframe(rows_table(issue), hide_index=True, width="stretch")

explained = [i for i in issues if i.check == "reconciliation_explained"]
if explained:
    with st.expander(f"{SEVERITY_ICON['info']} {explained[0].title}"):
        st.write("These A-vs-B gaps are caused by the issues above, so they are not counted again.")
        st.dataframe(rows_table(explained[0]), hide_index=True, width="stretch")

# ------------------------------------------------------------------ file A, highlighted
st.subheader("File A with flagged rows highlighted")
flagged_by: dict[int, list[str]] = {}
for issue in issues:
    if issue.file == "A":
        for i in issue.row_index:
            flagged_by.setdefault(i, []).append(issue.check)
table_a = view_a.assign(flagged_by=[", ".join(flagged_by.get(i, [])) for i in view_a.index])
only_flagged = st.toggle("Show flagged rows only", value=True)
shown = table_a.loc[sorted(flagged_by)] if only_flagged else table_a
st.dataframe(
    shown.style.apply(
        lambda row: ["background-color: #ffd6d6" if row["flagged_by"] else ""] * len(row), axis=1
    ).format({"revenue_gbp": "{:,.2f}", "volume": "{:,.0f}"}),
    width="stretch",
)
st.caption("Row numbers are positions in File A, counting from 0 (spreadsheet row = number + 2).")

# ------------------------------------------------------------------ download
st.download_button(
    "Download report (Markdown)",
    data=markdown_report(
        issues, explanation=explanation.text if explanation and not explanation.error else None
    ),
    file_name="trust_layer_report.md",
    mime="text/markdown",
)
st.caption("The checks never change your data. They only report what they find.")
