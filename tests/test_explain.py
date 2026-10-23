"""Tests for the AI layer. A fake model is used, so no API calls are made and no cost is incurred."""

from types import SimpleNamespace

import pandas as pd
import pytest

from src.checks import run_all_checks
from src.explain import allowed_labels, allowed_numbers, build_facts, check_numbers, explain


class FakeClient:
    """Pretends to be the Anthropic client and returns a fixed answer."""

    def __init__(self, answer: str = "", fail: bool = False):
        self.answer, self.fail, self.sent = answer, fail, None
        self.messages = self

    def create(self, **kwargs):
        if self.fail:
            raise ConnectionError("network down")
        self.sent = kwargs
        return SimpleNamespace(content=[SimpleNamespace(type="text", text=self.answer)])


@pytest.fixture(scope="module")
def issues():
    a = pd.read_csv("data/sales_system.csv")
    b = pd.read_csv("data/finance_report.csv")
    return run_all_checks(a, b)


def test_facts_contain_findings_but_no_raw_data(issues):
    facts = build_facts(issues)
    assert facts["summary"] == {"issues": 6, "critical": 2, "rows_affected": 9}
    # 287 raw rows exist; the model must only ever see the flagged ones.
    assert sum(len(i["rows"]) for i in facts["issues"]) == 9


def test_supported_numbers_pass_including_rounding(issues):
    allowed = allowed_numbers(build_facts(issues))
    text = (
        "There are 6 issues, 2 of them critical. "
        "Subtotal rows double-count GBP 103,854 of revenue. "
        "West revenue is 2,500.00 lower in finance."
    )
    kept, rejected = check_numbers(text, allowed)
    assert rejected == []
    assert kept.count("\n") == 2


def test_unsupported_numbers_are_removed(issues):
    allowed = allowed_numbers(build_facts(issues))
    text = (
        "There are 6 issues. "
        "Revenue is overstated by about 12%. "      # computed by the model: not in the facts
        "The unit error inflates volume by 19,182 cases."  # in facts: explained gap
    )
    kept, rejected = check_numbers(text, allowed)
    assert rejected == ["Revenue is overstated by about 12%."]
    assert "19,182" in kept


def test_digits_inside_dates_and_names_do_not_count_as_facts(issues):
    facts = build_facts(issues)
    allowed = allowed_numbers(facts)
    months, products = allowed_labels(facts)
    assert 11 not in allowed and 330 not in allowed  # from "2025-11" and "Lemon Soda 330ml"
    text = (
        "The Orange Juice 1L row for North in 2025-11 is 10x too large. "  # 10x is not a fact
        "The Lemon Soda 330ml row in 2025-05 is off by a factor of 24.1. "  # all supported
        "Revenue is 11% too high. "  # 11 only appears inside a date
        "The problem started in 2025-12."  # a month that is not in the facts
    )
    kept, rejected = check_numbers(text, allowed, months, products)
    assert kept == "The Lemon Soda 330ml row in 2025-05 is off by a factor of 24.1."
    assert len(rejected) == 3


def test_explain_applies_the_check_to_model_output(issues):
    fake = FakeClient("6 issues were found. Fixing them saves GBP 50,000.")
    result = explain(issues, client=fake)
    assert result.text == "6 issues were found."
    assert result.rejected == ["Fixing them saves GBP 50,000."]
    # The model was sent check results only, as JSON.
    assert "Check results (JSON)" in fake.sent["messages"][0]["content"]
    assert fake.sent["thinking"] == {"type": "disabled"}


def test_explain_never_crashes(issues, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert "no API key" in explain(issues).error
    assert "ConnectionError" in explain(issues, client=FakeClient(fail=True)).error
    assert "no text" in explain(issues, client=FakeClient(answer="")).error
