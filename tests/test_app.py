"""Smoke tests for the Streamlit app: it must load the sample data and show the right numbers."""

from pathlib import Path

import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

APP = str(Path(__file__).parents[1] / "app.py")


@pytest.fixture(autouse=True)
def isolated(monkeypatch, tmp_path):
    """App tests must never use a real API key or another test's cached answer.
    Without this, a developer's .env or .streamlit/secrets.toml made the tests call the
    real API (and pass or fail depending on the machine)."""
    monkeypatch.chdir(tmp_path)  # .streamlit/secrets.toml is looked up from here...
    monkeypatch.setenv("HOME", str(tmp_path))  # ...and from the home folder
    monkeypatch.setenv("USERPROFILE", str(tmp_path))  # (Windows home folder)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr("dotenv.load_dotenv", lambda *a, **k: False)
    st.cache_data.clear()
    yield
    st.cache_data.clear()


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


def test_ai_summary_without_key_explains_instead_of_crashing(monkeypatch):
    at = AppTest.from_file(APP, default_timeout=30).run()
    at.button[0].click().run()
    assert not at.exception
    assert any("no API key" in i.value for i in at.info)


def test_ai_failure_is_not_cached(monkeypatch):
    """A failed call must not be replayed after the key is fixed (bug found in production)."""
    from src.explain import Explanation

    answers = iter([Explanation(error="AI summary unavailable: AuthenticationError."),
                    Explanation(text="6 issues were found.", raw="6 issues were found.")])
    monkeypatch.setattr("src.explain.explain", lambda issues, **k: next(answers))
    at = AppTest.from_file(APP, default_timeout=30).run()
    at.button[0].click().run()
    assert any("AuthenticationError" in i.value for i in at.info)
    at.button[0].click().run()
    assert any("6 issues were found." in m.value for m in at.markdown)
