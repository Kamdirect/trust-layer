"""AI layer: a plain-English summary of the check results, with a number guardrail.

The model is sent ONLY the check results (never the raw data). Every sentence it writes
is then checked in code: a sentence containing any number that does not appear in the
check results is removed and shown separately. The AI never changes or adds findings.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field

from src.checks import Issue
from src.report import NEXT_STEPS, problems, summary

MODEL = "claude-haiku-5-5"
MAX_ROWS_PER_ISSUE = 10

SYSTEM_PROMPT = """You are a careful data-quality analyst writing for a busy finance manager.
You are given the results of deterministic data checks as JSON. Write a short summary:
- one sentence with the overall picture,
- one bullet per issue, most severe first: what is wrong and what to check first,
- a final sentence on which issue to fix first and why.

Strict rules:
- Use ONLY facts in the JSON. Do not guess causes that the JSON does not state.
- Every number you write must appear in the JSON exactly as given. Do not add, subtract,
  multiply, round or convert numbers, and do not compute percentages or totals.
- Write months exactly as in the JSON (for example 2025-03) and products by their full name.
- Plain English, no headings, under 180 words."""

# Numbers like 6, 2,500, 103854.08, 5.49, 0.3 (also inside £2,500 or 5.49% or x24).
_NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?")
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+|\n+")
_MONTH = re.compile(r"\b\d{4}-\d{2}\b")


@dataclass
class Explanation:
    text: str = ""                                    # sentences that passed the check
    rejected: list[str] = field(default_factory=list)  # sentences removed by the check
    raw: str = ""                                     # the model's full answer, for audit
    error: str | None = None                          # set when no summary could be made


def build_facts(issues: list[Issue]) -> dict:
    """The only information the model sees: summary counts and each issue's findings."""
    facts = {"summary": summary(issues), "issues": []}
    for issue in problems(issues):
        facts["issues"].append(
            {
                "check": issue.check,
                "severity": issue.severity,
                "file": issue.file,
                "title": issue.title,
                "numbers": issue.numbers,
                "rows": issue.rows[:MAX_ROWS_PER_ISSUE],
                "what_to_check": NEXT_STEPS.get(issue.check, ""),
            }
        )
    explained = [i for i in issues if i.check == "reconciliation_explained"]
    if explained:
        facts["explained_gaps"] = explained[0].rows[:MAX_ROWS_PER_ISSUE]
    return facts


def _numbers_in(text: str) -> list[str]:
    return [m.replace(",", "") for m in _NUMBER.findall(text)]


def _walk(value):
    """Yield every value nested anywhere in dicts and lists."""
    if isinstance(value, dict):
        for v in value.values():
            yield from _walk(v)
    elif isinstance(value, list):
        for v in value:
            yield from _walk(v)
    else:
        yield value


def allowed_numbers(facts: dict) -> set[float]:
    """Numbers from numeric fields only. Digits inside dates ("2025-12") or product names
    ("Cola 500ml") are NOT allowed as free-standing numbers, so "12%" can't sneak through."""
    return {
        float(v) for v in _walk(facts) if isinstance(v, (int, float)) and not isinstance(v, bool)
    }


def allowed_labels(facts: dict) -> tuple[set[str], set[str]]:
    """Months and product names that appear in the facts."""
    months, products = set(), set()
    for v in _walk(facts):
        if isinstance(v, str):
            months.update(_MONTH.findall(v))
    for issue in facts["issues"]:
        for row in issue["rows"]:
            if row.get("product"):
                products.add(row["product"])
    return months, products


def _is_supported(number: str, allowed: set[float]) -> bool:
    """A number in the text is supported if some fact equals it, allowing only for the
    text showing fewer decimal places (e.g. 103854.08 written as 103,854)."""
    value = float(number)
    decimals = len(number.split(".")[1]) if "." in number else 0
    return any(round(a, decimals) == value for a in allowed)


def check_numbers(
    text: str, allowed: set[float], months: set[str] = frozenset(), products: set[str] = frozenset()
) -> tuple[str, list[str]]:
    """Split text into sentences; keep those whose numbers, months and products are all
    in the facts. Labels are removed before numbers are checked."""
    kept, rejected = [], []
    for sentence in (s.strip() for s in _SENTENCE_SPLIT.split(text)):
        if not sentence:
            continue
        rest = sentence
        for product in sorted(products, key=len, reverse=True):
            rest = rest.replace(product, " ")
        ok = all(m in months for m in _MONTH.findall(rest))
        rest = _MONTH.sub(" ", rest)
        ok = ok and all(_is_supported(n, allowed) for n in _numbers_in(rest))
        (kept if ok else rejected).append(sentence)
    return "\n".join(kept), rejected


def _default_client():
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        return None
    import anthropic  # imported here so the rest of the app works without the package

    return anthropic.Anthropic(api_key=key, timeout=30, max_retries=2)


def explain(issues: list[Issue], client=None, model: str = MODEL) -> Explanation:
    """Ask the model for a summary, then apply the number check. Never raises."""
    client = client or _default_client()
    if client is None:
        return Explanation(error="AI summary unavailable: no API key is configured.")

    facts = build_facts(issues)
    try:
        response = client.messages.create(
            model=model,
            max_tokens=1500,
            # A short summary of given facts needs no up-front reasoning. On Haiku 5.5 thinking
            # is on by default and its tokens count toward max_tokens; left on, it sometimes used
            # the whole budget and returned no text (found by scripts/evaluate_ai.py).
            thinking={"type": "disabled"},
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": "Check results (JSON):\n" + json.dumps(facts)}],
        )
    except Exception as exc:  # network, auth, rate or spend limit: report, don't crash
        return Explanation(error=f"AI summary unavailable: {type(exc).__name__}.")

    raw = "".join(b.text for b in response.content if getattr(b, "type", "") == "text").strip()
    if not raw:
        reason = getattr(response, "stop_reason", "unknown")
        return Explanation(error=f"AI summary unavailable: the model returned no text (stop reason: {reason}).")
    months, products = allowed_labels(facts)
    text, rejected = check_numbers(raw, allowed_numbers(facts), months, products)
    return Explanation(text=text, rejected=rejected, raw=raw)
