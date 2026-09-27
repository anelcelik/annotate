import sys

import pytest

import hotkeys as H


@pytest.mark.parametrize("text, stored, shown", [
    ("<ctrl>+<shift>+a", "<ctrl>+<shift>+a", "Ctrl+Shift+A"),
    ("Ctrl+Shift+A",     "<ctrl>+<shift>+a", "Ctrl+Shift+A"),
    ("Ctrl+F5",          "<ctrl>+<f5>",      "Ctrl+F5"),
    ("<ctrl>+f5",        "<ctrl>+<f5>",      "Ctrl+F5"),   # what 5.0 stored
    ("Ctrl+Space",       "<ctrl>+<space>",   "Ctrl+Space"),
    ("Ctrl+Alt+PgUp",    "<ctrl>+<alt>+<page_up>", "Ctrl+Alt+PgUp"),
    ("Meta+S",           "<cmd>+s",          "Win+S"),
    ("Shift+Ctrl+R",     "<ctrl>+<shift>+r", "Ctrl+Shift+R"),  # order-insensitive
    ("Ctrl++",           "<ctrl>++",         "Ctrl++"),
])
def test_round_trip(text, stored, shown):
    assert H.canonical(text) == stored
    assert H.display(stored) == shown
    assert H.canonical(stored) == stored


@pytest.mark.parametrize("bad", ["", "Ctrl+", "Ctrl+Shift", "Ctrl+A+B", "Ctrl+Num+5"])
def test_unparseable(bad):
    assert H.canonical(bad) == ""


def test_stored_forms_are_valid_pynput():
    pynput = pytest.importorskip("pynput.keyboard")
    for text in ("Ctrl+F5", "Ctrl+Space", "Ctrl+Alt+Left", "Ctrl+Shift+!"):
        pynput.HotKey.parse(H.canonical(text))       # would raise ValueError


@pytest.mark.parametrize("combo, ok", [
    ("", True),                    # no shortcut is allowed
    ("<ctrl>+<alt>+r", True),
    ("<f9>", True),                # function keys may stand alone
    ("<shift>+<f9>", True),
    ("a", False),                  # would fire on every "a" typed anywhere
    ("<shift>+a", False),          # …or every capital A
    ("<esc>", False),
    ("<ctrl>+<esc>", False),
    ("<ctrl>+nonsense", False),
])
def test_problem(combo, ok):
    assert (H.problem(combo) == "") is ok


def test_virtual_keys():
    assert H.virtual_key("a") == 0x41
    assert H.virtual_key("7") == 0x37
    assert H.virtual_key("f1") == 0x70
    assert H.virtual_key("f24") == 0x87
    assert H.virtual_key("space") == 0x20
    assert H.virtual_key("page_down") == 0x22
    assert H.virtual_key("!", vk_scan=lambda ch: 0x0131) == 0x31
    assert H.virtual_key("§", vk_scan=lambda ch: -1) == 0


def test_win_modifiers():
    f = H.win_modifiers({"ctrl", "alt"})
    assert f == H.MOD_CONTROL | H.MOD_ALT | H.MOD_NOREPEAT


class FakeBackend:
    """Registers everything except what's in `taken`."""
    name = "fake"

    def __init__(self, taken=()):
        self.taken = set(taken)
        self.live = {}

    def apply(self, binds):
        self.live, failures = {}, {}
        for name, (combo, cb) in binds.items():
            if not combo or cb is None:
                continue
            if not H.parse(combo):
                failures[name] = "invalid"
            elif combo in self.taken:
                failures[name] = "taken"
            else:
                self.live[combo] = cb
        return failures

    def stop(self):
        self.live = {}


def test_one_bad_shortcut_leaves_the_others_working():
    backend = FakeBackend(taken={"<ctrl>+<alt>+r"})
    m = H.HotkeyManager(backend=backend)
    m.bind("toggle", "<ctrl>+<shift>+a", lambda: None)
    m.bind("record", "<ctrl>+<alt>+r", lambda: None)
    m.bind("ocr", "<ctrl>+nonsense", lambda: None)
    assert m.failures() == {"record": "taken", "ocr": "invalid"}
    assert m.is_global("toggle")
    assert not m.is_global("record")
    assert "<ctrl>+<shift>+a" in backend.live


def test_local_fallback_only_for_shortcuts_that_are_not_global():
    fired = []
    m = H.HotkeyManager(backend=FakeBackend(taken={"<ctrl>+<alt>+r"}))
    m.bind("toggle", "<ctrl>+<shift>+a", lambda: fired.append("toggle"))
    m.bind("record", "<ctrl>+<alt>+r", lambda: fired.append("record"))
    # Registered globally: the overlay must NOT also act on it (double fire).
    assert m.local_match("Ctrl+Shift+A") is None
    # Taken by another app: the overlay picks it up while it has focus.
    assert m.local_match("Ctrl+Alt+R") == "record"
    m.trigger("record")
    assert fired == ["record"]


def test_no_backend_means_everything_is_local():
    m = H.HotkeyManager(backend=None)
    m.bind("record", "<ctrl>+<alt>+r", lambda: None)
    assert not m.available
    assert m.failures() == {"record": "unavailable"}
    assert m.local_match("Ctrl+Alt+R") == "record"


def test_pynput_backend_skips_invalid_combos(monkeypatch):
    kb = pytest.importorskip("pynput.keyboard")
    started = {}

    class Listener:
        def __init__(self, mapping):
            started["mapping"] = mapping

        def start(self):
            pass

        def stop(self):
            pass

    monkeypatch.setattr(kb, "GlobalHotKeys", Listener)
    b = H._PynputBackend()
    failures = b.apply({"good": ("<ctrl>+<f5>", lambda: None),
                        "legacy": ("<ctrl>+f5", lambda: None)})
    assert failures == {"legacy": "invalid"}
    assert list(started["mapping"]) == ["<ctrl>+<f5>"]


@pytest.mark.skipif(sys.platform != "win32", reason="RegisterHotKey is Windows-only")
def test_win32_backend_registers_and_dispatches(qapp):
    """The part that can only be checked on real Windows: RegisterHotKey plus
    the Qt native event filter (signature, return value) delivering
    WM_HOTKEY to the callback."""
    import ctypes
    from PySide6.QtCore import QCoreApplication
    b = H._Win32Backend()
    fired = []
    try:
        failures = b.apply({"t": ("<ctrl>+<alt>+<shift>+<f11>",
                                  lambda: fired.append(1))})
        if failures.get("t") == "failed":
            pytest.skip("no interactive desktop on this runner")
        assert failures in ({}, {"t": "taken"})
        if failures:
            return
        hid = next(iter(b._ids))
        from ctypes import wintypes
        post = ctypes.windll.user32.PostMessageW
        post.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
        post(b._hwnd, H.WM_HOTKEY, hid, 0)
        for _ in range(20):
            QCoreApplication.processEvents()
        assert fired == [1]
    finally:
        b.stop()
