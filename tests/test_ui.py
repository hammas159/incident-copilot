"""Smoke tests for the Streamlit demo (the `ui` dependency group)."""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("streamlit")

from streamlit.testing.v1 import AppTest  # noqa: E402

APP_PATH = str(Path(__file__).resolve().parent.parent / "ui" / "app.py")


def _app() -> AppTest:
    at = AppTest.from_file(APP_PATH)
    at.run(timeout=15)
    assert not at.exception
    return at


def test_app_loads_without_exceptions():
    _app()


def test_extract_templates_runs():
    at = _app()
    button = next(b for b in at.button if b.label == "Extract templates")
    button.click().run(timeout=15)
    assert not at.exception


def test_correlate_incident_runs_and_finds_the_cause():
    at = _app()
    button = next(b for b in at.button if b.label == "Simulate a correlated incident")
    button.click().run(timeout=15)
    assert not at.exception
    assert any("checkout-service" in m.value for m in at.markdown)


def test_seasonal_scenario_runs():
    at = _app()
    at.radio[0].set_value("Daily seasonal pattern").run(timeout=15)
    assert not at.exception
