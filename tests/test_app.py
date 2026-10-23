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


def test_ai_summary_without_key_explains_instead_of_crashing(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr("dotenv.load_dotenv", lambda *a, **k: False)
    at = AppTest.from_file(APP, default_timeout=30).run()
    at.button[0].click().run()
    assert not at.exception
    assert any("no API key" in i.value for i in at.info)
