"""Settings migration, review prompt rules, the overlay window, dialogs,
Windows integration fallbacks and the build's drop rules."""
import os
import subprocess
import sys
from pathlib import Path

import pytest
from PyQt6.QtCore import QEvent, QPointF, Qt
from PyQt6.QtGui import QKeyEvent

HERE = Path(__file__).resolve().parent.parent


# ── settings migration ────────────────────────────────────────────────────────

def migrated(A, saved):
    data = {**A._DEFAULT_SETTINGS, **saved}
    A._migrate_hotkeys(data, saved)
    return data


def test_old_browser_clashing_defaults_are_replaced(A):
    d = migrated(A, {"ocr_hotkey": "<ctrl>+t", "rec_hotkey": "<ctrl>+<shift>+r",
                     "hotkey": "<ctrl>+<shift>+a"})
    assert d["ocr_hotkey"] == "<ctrl>+<alt>+t"
    assert d["rec_hotkey"] == "<ctrl>+<alt>+r"
    assert d["hotkey"] == "<ctrl>+<shift>+a"          # the app's identity stays
    assert d["hotkeys_version"] == 2


def test_custom_shortcuts_are_kept_and_repaired(A):
    d = migrated(A, {"rec_hotkey": "<ctrl>+f9", "ocr_hotkey": "<alt>+q"})
    assert d["rec_hotkey"] == "<ctrl>+<f9>"            # 5.0 stored it unusably
    assert d["ocr_hotkey"] == "<alt>+q"


def test_migration_runs_once(A):
    d = migrated(A, {"ocr_hotkey": "<ctrl>+t", "hotkeys_version": 2})
    assert d["ocr_hotkey"] == "<ctrl>+t"               # chosen after 5.1: respected


# ── review prompt ─────────────────────────────────────────────────────────────

def test_review_needs_successes_on_several_days(A, settings):
    assert not A.review_due(settings)
    for day in ("2026-10-01", "2026-10-01", "2026-10-01"):
        A.note_success(settings, today=day)
    assert settings.get("review_successes") == 3
    assert settings.get("review_days") == ["2026-10-01"]
    assert not A.review_due(settings)                   # all on one day
    A.note_success(settings, today="2026-10-02")
    assert A.review_due(settings)


def test_review_respects_answers(A, settings):
    for day in ("2026-10-01", "2026-10-02", "2026-10-03"):
        A.note_success(settings, today=day)
    settings.set("review_state", "never")
    assert not A.review_due(settings)
    settings.set("review_state", "later")
    settings.set("review_after", 2_000_000_000)
    assert not A.review_due(settings, now=1_900_000_000)
    assert A.review_due(settings, now=2_000_000_001)


# ── overlay window ────────────────────────────────────────────────────────────

def test_empty_overlay_stays_off_screen(overlay):
    assert overlay.wanted
    assert overlay.passthrough
    assert not overlay.isVisible()                      # nothing to show


def test_overlay_appears_for_drawing_and_marks(A, overlay):
    overlay.set_passthrough(False)
    assert overlay.isVisible()
    overlay.canvas._commit(A.RedactShape(QPointF(1, 1), QPointF(50, 50)))
    overlay.set_passthrough(True)
    assert overlay.isVisible()                          # marks to display
    overlay.canvas.clear()
    assert not overlay.isVisible()                      # empty again


def test_visibility_toggle_and_recording_pin(overlay):
    overlay.toggle()
    assert not overlay.wanted
    overlay.pin_on_screen(True)
    assert not overlay.isVisible()                      # put away wins
    overlay.toggle()
    assert overlay.isVisible()                          # pinned while recording
    overlay.pin_on_screen(False)
    assert not overlay.isVisible()


def test_clear_shows_undo_toast(A, overlay):
    overlay.canvas._commit(A.RedactShape(QPointF(1, 1), QPointF(50, 50)))
    overlay.clear_marks()
    assert overlay.toast.isVisible()
    assert "Cleared 1 mark" in overlay.toast._label.text()
    overlay.toast._run_action()
    assert len(overlay.canvas._shapes) == 1


def key(overlay, k, mods=Qt.KeyboardModifier.NoModifier):
    overlay.keyPressEvent(QKeyEvent(QEvent.Type.KeyPress, k, mods))


def test_tool_letters_ignore_ctrl(overlay):
    overlay.toolbar._activate("pen")
    key(overlay, Qt.Key.Key_S, Qt.KeyboardModifier.ControlModifier)
    assert overlay.canvas.tool == "pen"                 # Ctrl+S is not "Steps"
    key(overlay, Qt.Key.Key_S)
    assert overlay.canvas.tool == "steps"


def test_record_key_fires_once_when_not_global(overlay):
    """Without global shortcuts the overlay handles the record combo itself —
    once. (5.0 fired it from a hard-coded handler AND the global hook.)"""
    fired = []
    overlay._hotkeys.bind("record", "<ctrl>+<alt>+r", lambda: fired.append(1))
    key(overlay, Qt.Key.Key_R,
        Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.AltModifier)
    assert fired == [1]
    assert overlay.canvas.tool != "rect"


def test_c_clears_but_ctrl_c_does_not(A, overlay):
    overlay.canvas._commit(A.RedactShape(QPointF(1, 1), QPointF(50, 50)))
    key(overlay, Qt.Key.Key_C, Qt.KeyboardModifier.ControlModifier)
    assert len(overlay.canvas._shapes) == 1
    key(overlay, Qt.Key.Key_C)
    assert overlay.canvas._shapes == []


def test_exit_asks_when_marks_would_be_lost(A, overlay, monkeypatch):
    asked, quit_ = [], []
    monkeypatch.setattr(A.ConfirmDialog, "exec", lambda self: asked.append(1) or 0)
    monkeypatch.setattr(A.QApplication, "quit", staticmethod(lambda: quit_.append(1)))
    overlay.request_exit()
    assert (asked, quit_) == ([], [1])                  # nothing to lose: just go
    quit_.clear()
    overlay.canvas._commit(A.RedactShape(QPointF(1, 1), QPointF(50, 50)))
    overlay.request_exit()
    assert (asked, quit_) == ([1], [])                  # asked, and Cancel kept it


# ── OCR availability ──────────────────────────────────────────────────────────

def test_ocr_tool_hidden_without_engine(A, settings, monkeypatch):
    monkeypatch.setattr(A, "_ocr_available", False)
    monkeypatch.setattr(sys, "argv", ["annotate.py"])
    ov = A.AnnotationOverlay(settings, A.HotkeyManager(backend=None))
    try:
        assert "ocr" not in ov.toolbar._tool_btns
        ov.toolbar._activate("ocr")
        assert ov.canvas.tool != "ocr"
        help_text = [r[0] for r in A.HelpDialog(settings)._tools()]
        assert "Snip & Read" not in [t for t in (x for x in help_text)]
    finally:
        ov.toolbar.set_chrome_visible(False)


# ── settings dialog ───────────────────────────────────────────────────────────

def test_settings_rejects_unsafe_and_duplicate_shortcuts(A, overlay, settings):
    dlg = A.SettingsDialog(settings, overlay._hotkeys, overlay)
    toggle, err = dlg._hk_fields["hotkey"]
    toggle.set_combo("a")
    assert not dlg._check_shortcuts()
    assert err.text()
    toggle.set_combo("<ctrl>+<alt>+r")                  # same as record
    assert not dlg._check_shortcuts()
    assert "Start / stop recording" in err.text()
    assert "Draw / click-through" in dlg._hk_fields["rec_hotkey"][1].text()
    toggle.set_combo("<ctrl>+<alt>+<f5>")
    assert dlg._check_shortcuts()
    assert dlg._hk_fields["rec_hotkey"][1].text() == ""   # clash message gone
    dlg._save()
    assert settings.get("hotkey") == "<ctrl>+<alt>+<f5>"
    dlg.close()


def test_settings_can_clear_a_shortcut(A, overlay, settings):
    dlg = A.SettingsDialog(settings, overlay._hotkeys, overlay)
    field, _ = dlg._hk_fields["visibility_hotkey"]
    field.set_combo("")
    assert dlg._check_shortcuts()
    dlg._save()
    assert settings.get("visibility_hotkey") == ""
    dlg.close()


def test_help_lists_the_configured_shortcuts(A, settings):
    settings.set("rec_hotkey", "<ctrl>+<alt>+<f9>")
    rows = dict(A.HelpDialog(settings)._shortcuts())
    assert "Ctrl+Alt+F9" in rows
    assert "Esc" in rows and "Click-through" in rows["Esc"]


# ── Windows integration, off Windows ──────────────────────────────────────────

@pytest.mark.skipif(sys.platform == "win32", reason="checks the non-Windows fallbacks")
def test_platform_fallbacks(monkeypatch):
    import platform_win as PW
    monkeypatch.setattr(sys, "argv", ["annotate.py"])
    assert not PW.is_packaged()
    assert PW.startup_status() == "unsupported"
    assert PW.set_startup(True)[0] is False
    assert not PW.launched_at_startup()
    assert not PW.request_store_rating(0, lambda rated: None)
    monkeypatch.setattr(sys, "argv", ["annotate.py", "--minimized"])
    assert PW.launched_at_startup()


@pytest.mark.skipif(sys.platform != "win32", reason="needs Windows + pywinrt")
def test_winrt_names_exist():
    """The WinRT names platform_win uses, checked against the real pywinrt."""
    from winrt.runtime.interop import initialize_with_window  # noqa: F401
    from winrt.windows.applicationmodel import AppInstance, StartupTask, StartupTaskState
    from winrt.windows.applicationmodel.activation import ActivationKind
    from winrt.windows.services.store import StoreContext, StoreRateAndReviewStatus
    assert ActivationKind.STARTUP_TASK
    assert StartupTaskState.ENABLED_BY_POLICY
    assert StoreRateAndReviewStatus.SUCCEEDED == 0
    assert hasattr(StartupTask, "get_async") and hasattr(AppInstance,
                                                         "get_activated_event_args")
    assert hasattr(StoreContext, "get_default")


# ── run as a script: one module, one theme ────────────────────────────────────

def test_running_as_script_keeps_one_module(tmp_path):
    """The dock's `import annotate` loaded a second copy when the app ran as
    __main__, and that copy never got the dark theme."""
    home = tmp_path / "home"
    cfg = home / ".config" / "ScreenAnnotatorPro"
    cfg.mkdir(parents=True)
    (cfg / "settings.json").write_text('{"theme": "dark"}')
    code = r'''
import runpy, sys
sys.argv = ["annotate.py", "--minimized"]
from PyQt6 import QtWidgets as W
def fake_exec(self=None):
    m, a = sys.modules["__main__"], sys.modules.get("annotate")
    print("SAME" if a is m else "COPY", a._current_dlg_theme)
    return 0
W.QApplication.exec = fake_exec
try:
    runpy.run_path("annotate.py", run_name="__main__")
except SystemExit:
    pass
'''
    env = dict(os.environ, HOME=str(home), APPDATA=str(home / ".config"),
               QT_QPA_PLATFORM="offscreen")
    out = subprocess.run([sys.executable, "-c", code], cwd=HERE, env=env,
                         capture_output=True, text=True, timeout=60)
    assert "SAME dark" in out.stdout, out.stdout + out.stderr


# ── build drop rules ──────────────────────────────────────────────────────────

SHIPPED_5_0 = """
_internal/ffmpeg.exe
_internal/PyQt6/Qt6/bin/opengl32sw.dll
_internal/PyQt6/Qt6/bin/Qt6Core.dll
_internal/PyQt6/Qt6/bin/Qt6Gui.dll
_internal/PyQt6/Qt6/bin/Qt6Widgets.dll
_internal/PyQt6/Qt6/bin/Qt6Pdf.dll
_internal/PyQt6/Qt6/plugins/platforms/qwindows.dll
_internal/PyQt6/Qt6/plugins/platforms/qoffscreen.dll
_internal/PyQt6/Qt6/plugins/platforms/qminimal.dll
_internal/PyQt6/Qt6/plugins/imageformats/qico.dll
_internal/PyQt6/Qt6/plugins/imageformats/qjpeg.dll
_internal/PyQt6/Qt6/plugins/imageformats/qpdf.dll
_internal/PyQt6/Qt6/plugins/styles/qmodernwindowsstyle.dll
_internal/PyQt6/Qt6/translations/qtbase_de.qm
""".split()


def test_build_filters_keep_what_the_app_needs():
    import build_filters as bf
    kept = [p for p in SHIPPED_5_0 if bf.keep_binary(p) and bf.keep_data(p)]
    assert kept == [
        "_internal/ffmpeg.exe",
        "_internal/PyQt6/Qt6/bin/Qt6Core.dll",
        "_internal/PyQt6/Qt6/bin/Qt6Gui.dll",
        "_internal/PyQt6/Qt6/bin/Qt6Widgets.dll",
        "_internal/PyQt6/Qt6/plugins/platforms/qwindows.dll",
        "_internal/PyQt6/Qt6/plugins/platforms/qoffscreen.dll",
        "_internal/PyQt6/Qt6/plugins/imageformats/qico.dll",
        "_internal/PyQt6/Qt6/plugins/styles/qmodernwindowsstyle.dll",
    ]
    assert bf.keep_data(r"PyQt6\Qt6\translations\qt_de.qm") is False
    assert "PIL" in bf.LITE_EXCLUDES and "_ssl" in bf.LITE_EXCLUDES


def test_idle_overlay_lets_go_of_its_window_and_comes_back(overlay):
    overlay.set_passthrough(False)
    overlay.set_passthrough(True)
    assert not overlay.isVisible()
    assert overlay._release_timer.isActive()
    overlay._release_window()                       # what the timer does
    assert not overlay.testAttribute(Qt.WidgetAttribute.WA_WState_Created)
    overlay.set_passthrough(False)                  # next use re-creates it
    assert overlay.isVisible()
    assert not overlay._release_timer.isActive()
