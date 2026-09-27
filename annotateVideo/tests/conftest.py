"""Shared setup: an offscreen QApplication and in-memory settings.

Run from annotateVideo/:   python -m pytest tests
"""
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

import pytest  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance() or QApplication(sys.argv)
    yield app


@pytest.fixture
def A(qapp):
    import annotate
    annotate._apply_dlg_theme("light")
    return annotate


@pytest.fixture
def settings(A, tmp_path):
    s = A.SettingsManager.__new__(A.SettingsManager)
    s._path = tmp_path / "settings.json"
    s._data = dict(A._DEFAULT_SETTINGS)
    return s


@pytest.fixture
def overlay(A, settings, monkeypatch):
    """A real overlay + dock, with no global hotkey backend."""
    monkeypatch.setattr(sys, "argv", ["annotate.py"])
    mgr = A.HotkeyManager(backend=None)
    ov = A.AnnotationOverlay(settings, mgr)
    yield ov
    ov.toast.hide()
    ov.toolbar.set_chrome_visible(False)
    ov.hide()
