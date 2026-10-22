"""Tests for file loading and the downloadable report."""

import io

import pandas as pd
import pytest

from src.checks import run_all_checks
from src.report import markdown_report, read_table, summary


def test_read_table_rejects_unsupported_file_type():
    with pytest.raises(ValueError, match="only .csv and .xlsx"):
        read_table(io.BytesIO(b"hello"), name="notes.txt")


def test_read_table_reports_unreadable_excel():
    with pytest.raises(ValueError, match="Could not read"):
        read_table(io.BytesIO(b"this is not an excel file"), name="broken.xlsx")


def test_report_matches_summary_and_includes_next_steps():
    a = pd.read_csv("data/sales_system.csv")
    b = pd.read_csv("data/finance_report.csv")
    issues = run_all_checks(a, b)
    report = markdown_report(issues)
    assert summary(issues) == {"issues": 6, "critical": 2, "rows_affected": 9}
    assert "**6 issue(s), 2 critical, 9 row(s) affected.**" in report
    assert report.count("**What to check:**") == 6
    """Smoke tests for the Streamlit app: it must load the sample data and show the right numbers."""

from pathlib import Path

from streamlit.testing.v1 import AppTest

APP = str(Path(__file__).parents[1] / "app.py")


def test_app_runs_on_sample_data():
    at = AppTest.from_file(APP, default_timeout=30).run()
    assert not at.exception
    metrics = {m.label: m.value for m in at.metric}
    assert metrics == {"Issues found": "6", "Critical": "2", "Rows affected": "9"}


def test_app_asks_for_files_when_sample_is_off():
    at = AppTest.from_file(APP, default_timeout=30).run()
    at.sidebar.toggle[0].set_value(False).run()
    assert not at.exception
    assert "Upload both files" in at.info[0].value
    """Tests for file loading and the downloadable report."""

import io

import pandas as pd
import pytest

from src.checks import run_all_checks
from src.report import markdown_report, read_table, summary


def test_read_table_rejects_unsupported_file_type():
    with pytest.raises(ValueError, match="only .csv and .xlsx"):
        read_table(io.BytesIO(b"hello"), name="notes.txt")


def test_read_table_reports_unreadable_excel():
    with pytest.raises(ValueError, match="Could not read"):
        read_table(io.BytesIO(b"this is not an excel file"), name="broken.xlsx")


def test_report_matches_summary_and_includes_next_steps():
    a = pd.read_csv("data/sales_system.csv")
    b = pd.read_csv("data/finance_report.csv")
    issues = run_all_checks(a, b)
    report = markdown_report(issues)
    assert summary(issues) == {"issues": 6, "critical": 2, "rows_affected": 9}
    assert "**6 issue(s), 2 critical, 9 row(s) affected.**" in report
    assert report.count("**What to check:**") == 6