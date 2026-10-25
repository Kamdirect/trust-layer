"""Tests for the independent test cases and the three-way comparison."""

import pandas as pd

from src.comparison import exact_match, score_case, simple_rules, trust_layer
from src.independent_cases import make_case


def test_cases_are_reproducible_and_clean_cases_have_no_answer_key():
    a1, b1, k1 = make_case(7)
    a2, b2, k2 = make_case(7)
    pd.testing.assert_frame_equal(a1, a2)
    assert k1 == k2
    assert make_case(7, clean=True)[2] == []


def test_each_planted_problem_has_its_own_region_month():
    for seed in range(20):
        _, _, key = make_case(seed, clean=False)
        places = [(r["month"], r["region"]) for p in key for r in p["rows"][:1]]
        assert len(places) == len(set(places))


def test_harmless_finance_differences_exist_but_are_not_in_the_answer_key():
    a, b, key = make_case(3, clean=True)
    assert key == []
    assert (a["revenue_gbp"].round(2) != b["revenue_gbp"].round(2)).any()


def test_exact_match_flags_harmless_differences_simple_rules_do_not():
    a, b, _ = make_case(3, clean=True)
    assert len(exact_match(a, b)) > 10
    assert len(simple_rules(a, b)) < len(exact_match(a, b))


def test_an_error_in_both_files_is_invisible_to_comparison_but_not_to_trust_layer():
    a, _, _ = make_case(11, clean=True)
    a = a.copy()
    row = a.index[5]
    a.loc[row, ["volume", "revenue_gbp"]] *= 10      # a typo in the source system ...
    b = a.copy()                                     # ... so both files carry it
    where = {"month": a.loc[row, "month"], "region": a.loc[row, "region"],
             "product": a.loc[row, "product"]}
    key = [{"issue_type": "outlier", "rows": [where], "detail": {}}]
    assert score_case(exact_match(a, b), key)["detected"] == [False]
    assert score_case(trust_layer(a, b), key)["detected"] == [True]


def test_score_case_by_hand():
    key = [{"issue_type": "duplicate_row", "rows": [{"month": "2025-01", "region": "X", "product": "P"}]}]
    flags = [{"month": "2025-01", "region": "X", "product": None, "rule": "region-month total gap"},
             {"month": "2025-02", "region": "X", "product": "P", "rule": "duplicate"}]
    s = score_case(flags, key)
    assert s["detected"] == [True]          # a region-month flag covers the row
    assert s["named"] == [False]            # but it did not name the problem
    assert (s["flags"], s["genuine_flags"]) == (2, 1)
