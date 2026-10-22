"""Automated tests for the data-quality checks. Run with:  python -m pytest"""

import pandas as pd
import pytest

from src.checks import (
    SchemaError,
    check_duplicates,
    check_missing_periods,
    check_outliers,
    check_subtotal_rows,
    check_unit_consistency,
    run_all_checks,
    validate_schema,
)
from src.evaluate import score
from src.synthetic_data import generate_clean, plant_issues


def make(rows):
    """Build a small, valid table from (month, region, product, volume, revenue) tuples."""
    df = pd.DataFrame(rows, columns=["month", "region", "product", "volume", "revenue_gbp"])
    df.insert(3, "unit", "cases")
    return validate_schema(df, "A")


SMALL = [
    ("2025-01", "North", "Cola", 100, 960.0),
    ("2025-01", "North", "Water", 200, 960.0),
    ("2025-01", "North", "Juice", 50, 720.0),
]


@pytest.fixture(scope="module")
def clean():
    return validate_schema(generate_clean(seed=0), "A")


# ------------------------------------------------------------ one test per check
def test_schema_rejects_missing_column():
    df = pd.DataFrame({"month": ["2025-01"], "region": ["North"]})
    with pytest.raises(SchemaError, match="missing required column"):
        validate_schema(df, "A")


def test_schema_rejects_text_in_number_column():
    df = pd.DataFrame(
        [("2025-01", "North", "Cola", "cases", "lots", 10.0)],
        columns=["month", "region", "product", "unit", "volume", "revenue_gbp"],
    )
    with pytest.raises(SchemaError, match="non-numeric"):
        validate_schema(df, "A")


def test_duplicates_found_and_counted():
    df = make(SMALL + [SMALL[0], SMALL[0]])
    [issue] = check_duplicates(df, "A")
    assert issue.numbers["duplicate_rows"] == 2


def test_labelled_subtotal_found():
    df = make(SMALL + [("2025-01", "North", "North Total", 350, 2640.0)])
    [issue] = check_subtotal_rows(df, "A")
    assert issue.rows[0]["product"] == "North Total"


def test_unlabelled_subtotal_found_by_value():
    # Blank product name, but its numbers equal the sum of the other three rows.
    df = make(SMALL + [("2025-01", "North", "", 350, 2640.0)])
    [issue] = check_subtotal_rows(df, "A")
    assert issue.rows[0]["product"] is None


def test_missing_period_found():
    df = make(SMALL)
    [issue] = check_missing_periods(df, "A", months=["2025-01", "2025-02"], regions=["North"])
    assert issue.rows == [{"month": "2025-02", "region": "North", "product": None}]


def test_unit_mixup_found_with_factor(clean):
    df = clean.copy()
    df.loc[0, "volume"] = df.loc[0, "volume"] * 24  # bottles entered as cases
    [issue] = check_unit_consistency(df, "A")
    assert issue.row_index == [0]
    assert 20 <= issue.numbers["off_by_factor"][0] <= 28


def test_outlier_found(clean):
    df = clean.copy()
    df.loc[10, "volume"] = df.loc[10, "volume"] * 3
    [issue] = check_outliers(df, "A")
    assert 10 in issue.row_index


# ------------------------------------------------------------ no false alarms
def test_clean_data_raises_no_structural_issues(clean):
    """Seasonal peaks are normal and must not trip the checks."""
    issues = run_all_checks(clean, clean.copy())
    assert [i.check for i in issues] == []


# ------------------------------------------------------------ end to end
def test_all_six_planted_issues_caught():
    a, b, key = plant_issues(generate_clean(seed=42))
    result = score(run_all_checks(a, b), key)
    assert result["caught"] == 6
    assert result["false_alarms"] == []