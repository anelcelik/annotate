"""
hotkeys.py — global shortcuts, and the one text format they are stored in.

Stored format (settings.json) is pynput's, so settings written by older
versions keep working:  "<ctrl>+<shift>+a", "<ctrl>+<alt>+<f5>".  Modifiers and
multi-character keys sit in angle brackets, a single character stands alone,
and "" means "no shortcut".

Windows registers each shortcut with RegisterHotKey. That takes the key away
from the app in front, so a shortcut can never do two things at once, and it
fails outright when another program already owns the combination — which is
reported back instead of silently doing nothing. It also costs nothing per
keystroke, unlike a keyboard hook that runs Python for every key pressed in
every app.

X11 still uses pynput. Wayland has no global shortcuts at all.
"""

import os
import platform

from PyQt6.QtCore import QAbstractNativeEventFilter, QTimer
from PyQt6.QtWidgets import QApplication, QWidget

IS_WIN = platform.system() == "Windows"

MODIFIERS = ("ctrl", "alt", "shift", "cmd")          # canonical order

_MOD_ALIASES = {
    "ctrl": "ctrl", "control": "ctrl", "ctrl_l": "ctrl", "ctrl_r": "ctrl",
    "alt": "alt", "alt_l": "alt", "alt_r": "alt", "alt_gr": "alt",
    "shift": "shift", "shift_l": "shift", "shift_r": "shift",
    "cmd": "cmd", "meta": "cmd", "win": "cmd", "super": "cmd",
}

# QKeySequence.toString() names → canonical (pynput) key names
_QT_NAMES = {
    "space": "space", "left": "left", "right": "right", "up": "up",
    "down": "down", "home": "home", "end": "end", "pgup": "page_up",
    "pgdown": "page_down", "ins": "insert", "del": "delete", "tab": "tab",
    "return": "enter", "enter": "enter", "backspace": "backspace",
    "print": "print_screen", "pause": "pause", "esc": "esc",
}

NAMED_KEYS = {
    "space", "left", "right", "up", "down", "home", "end", "page_up",
    "page_down", "insert", "delete", "tab", "enter", "backspace",
    "print_screen", "pause", "esc",
} | {f"f{i}" for i in range(1, 25)}

_DISPLAY = {
    "space": "Space", "left": "Left", "right": "Right", "up": "Up",
    "down": "Down", "home": "Home", "end": "End", "page_up": "PgUp",
    "page_down": "PgDown", "insert": "Ins", "delete": "Del", "tab": "Tab",
    "enter": "Enter", "backspace": "Backspace", "print_screen": "PrtSc",
    "pause": "Pause", "esc": "Esc",
}
_MOD_DISPLAY = {"ctrl": "Ctrl", "alt": "Alt", "shift": "Shift", "cmd": "Win"}


def _split(text: str) -> list[str]:
    """Split on '+', keeping a literal '+' key ("Ctrl++")."""
    parts, cur = [], ""
    for ch in text:
        if ch == "+" and cur:
            parts.append(cur)
            cur = ""
        else:
            cur += ch
    if cur:
        parts.append(cur)
    return parts


def parse(combo: str | None) -> tuple[frozenset, str] | None:
    """(modifiers, key) for a combo in stored or Qt format, None if unusable."""
    text = (combo or "").strip()
    if not text:
        return None
    mods, key = set(), None
    for raw in _split(text):
        token = raw.strip()
        low = token.strip("<>").lower() if len(token) > 1 else token.lower()
        if low in _MOD_ALIASES:
            mods.add(_MOD_ALIASES[low])
            continue
        if key is not None:                    # two non-modifier keys
            return None
        low = _QT_NAMES.get(low, low)
        if len(low) == 1 or low in NAMED_KEYS:
            key = low
        else:
            return None
    if key is None:
        return None
    return frozenset(mods), key


def canonical(combo: str | None) -> str:
    """Stored form of a combo ("" if it cannot be parsed)."""
    parsed = parse(combo)
    if not parsed:
        return ""
    mods, key = parsed
    out = [f"<{m}>" for m in MODIFIERS if m in mods]
    out.append(key if len(key) == 1 else f"<{key}>")
    return "+".join(out)


def display(combo: str | None) -> str:
    """Human form: "Ctrl+Alt+R". Empty string for no shortcut."""
    parsed = parse(combo)
    if not parsed:
        return ""
    mods, key = parsed
    out = [_MOD_DISPLAY[m] for m in MODIFIERS if m in mods]
    out.append(_DISPLAY.get(key, key.upper()))
    return "+".join(out)


def problem(combo: str | None) -> str:
    """Why this combo cannot be a global shortcut ("" if it can, or if it is
    empty — empty means "no shortcut", which is allowed)."""
    if not (combo or "").strip():
        return ""
    parsed = parse(combo)
    if not parsed:
        return "That key can't be used as a shortcut."
    mods, key = parsed
    if key == "esc":
        return "Esc is taken — it switches the overlay to click-through."
    is_fkey = key.startswith("f") and key[1:].isdigit()
    if not (mods & {"ctrl", "alt", "cmd"}) and not is_fkey:
        return ("Add Ctrl, Alt or Win — on its own, or with only Shift, "
                "this key would fire every time you type it.")
    return ""


def matches(combo_a: str | None, combo_b: str | None) -> bool:
    a, b = parse(combo_a), parse(combo_b)
    return a is not None and a == b


# ── Windows: RegisterHotKey ──────────────────────────────────────────────────

MOD_ALT, MOD_CONTROL, MOD_SHIFT, MOD_WIN, MOD_NOREPEAT = 0x1, 0x2, 0x4, 0x8, 0x4000
WM_HOTKEY = 0x0312
ERROR_HOTKEY_ALREADY_REGISTERED = 1409

_VK_NAMED = {
    "space": 0x20, "page_up": 0x21, "page_down": 0x22, "end": 0x23,
    "home": 0x24, "left": 0x25, "up": 0x26, "right": 0x27, "down": 0x28,
    "print_screen": 0x2C, "insert": 0x2D, "delete": 0x2E, "tab": 0x09,
    "enter": 0x0D, "backspace": 0x08, "pause": 0x13, "esc": 0x1B,
}


def virtual_key(key: str, vk_scan=None) -> int:
    """Windows virtual-key code for a canonical key name (0 if unknown).

    `vk_scan` is user32.VkKeyScanW, passed in so this stays testable off
    Windows; it resolves punctuation for the current keyboard layout.
    """
    if key in _VK_NAMED:
        return _VK_NAMED[key]
    if key.startswith("f") and key[1:].isdigit():
        n = int(key[1:])
        return 0x6F + n if 1 <= n <= 24 else 0
    if len(key) == 1:
        if key.isascii() and key.isalnum():
            return ord(key.upper())
        if vk_scan is not None:
            res = vk_scan(key) & 0xFFFF
            if res != 0xFFFF:
                return res & 0xFF
    return 0


def win_modifiers(mods) -> int:
    flags = MOD_NOREPEAT
    if "ctrl" in mods:
        flags |= MOD_CONTROL
    if "alt" in mods:
        flags |= MOD_ALT
    if "shift" in mods:
        flags |= MOD_SHIFT
    if "cmd" in mods:
        flags |= MOD_WIN
    return flags


class _Win32Backend(QAbstractNativeEventFilter):
    """RegisterHotKey against a hidden window of our own, WM_HOTKEY picked up
    by an application-wide native event filter.

    A real window rather than hWnd=NULL: thread messages are dropped by any
    modal loop Windows runs on our thread (a native file dialog, a window
    being dragged), a message addressed to a window is not.
    """

    name = "win32"

    def __init__(self):
        super().__init__()
        import ctypes
        from ctypes import wintypes
        self._ctypes = ctypes
        self._wintypes = wintypes
        u = ctypes.WinDLL("user32", use_last_error=True)
        u.RegisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int,
                                     wintypes.UINT, wintypes.UINT]
        u.RegisterHotKey.restype = wintypes.BOOL
        u.UnregisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int]
        u.UnregisterHotKey.restype = wintypes.BOOL
        u.VkKeyScanW.argtypes = [wintypes.WCHAR]
        u.VkKeyScanW.restype = ctypes.c_short
        u.IsWindow.argtypes = [wintypes.HWND]
        u.IsWindow.restype = wintypes.BOOL
        self._user32 = u
        self._sink = QWidget()                 # never shown
        self._hwnd = int(self._sink.winId())
        self._own_hwnd = False
        if not u.IsWindow(self._hwnd):
            # Qt's "offscreen" platform (CI, --self-test) has no real windows,
            # so use a plain message-only window instead. WM_HOTKEY still
            # arrives through the event loop and the same native filter.
            u.CreateWindowExW.argtypes = [
                wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR,
                wintypes.DWORD, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                ctypes.c_int, wintypes.HWND, wintypes.HMENU,
                wintypes.HINSTANCE, wintypes.LPVOID]
            u.CreateWindowExW.restype = wintypes.HWND
            HWND_MESSAGE = wintypes.HWND(-3)
            hwnd = u.CreateWindowExW(0, "STATIC", "Screen Annotator Pro hotkeys",
                                     0, 0, 0, 0, 0, HWND_MESSAGE, None, None, None)
            if hwnd:
                self._hwnd, self._own_hwnd = int(hwnd), True
        self._ids: dict[int, object] = {}
        QApplication.instance().installNativeEventFilter(self)

    def apply(self, binds: dict) -> dict:
        for hid in list(self._ids):
            self._user32.UnregisterHotKey(self._hwnd, hid)
        self._ids.clear()
        failures = {}
        for hid, (name, (combo, callback)) in enumerate(binds.items(), start=1):
            if not combo or callback is None:
                continue
            parsed = parse(combo)
            vk = virtual_key(parsed[1], self._user32.VkKeyScanW) if parsed else 0
            if not vk:
                failures[name] = "invalid"
                continue
            if self._user32.RegisterHotKey(self._hwnd, hid,
                                           win_modifiers(parsed[0]), vk):
                self._ids[hid] = callback
            else:
                err = self._ctypes.get_last_error()
                failures[name] = ("taken" if err == ERROR_HOTKEY_ALREADY_REGISTERED
                                  else "failed")
        return failures

    def stop(self):
        for hid in list(self._ids):
            self._user32.UnregisterHotKey(self._hwnd, hid)
        self._ids.clear()
        if self._own_hwnd:
            self._user32.DestroyWindow.argtypes = [self._wintypes.HWND]
            self._user32.DestroyWindow(self._hwnd)
            self._own_hwnd = False

    def nativeEventFilter(self, event_type, message):
        try:
            if bytes(event_type) != b"windows_generic_MSG":
                return False, 0
            msg = self._wintypes.MSG.from_address(int(message))
            if msg.message != WM_HOTKEY:
                return False, 0
            callback = self._ids.get(int(msg.wParam))
            if callback is None:
                return False, 0
            # Run it after the filter returns — never inside Windows' dispatch.
            QTimer.singleShot(0, callback)
            return True, 0
        except Exception:
            return False, 0


# ── X11: pynput ──────────────────────────────────────────────────────────────

class _PynputBackend:
    name = "pynput"

    def __init__(self):
        self._listener = None

    def apply(self, binds: dict) -> dict:
        self.stop()
        from pynput import keyboard as kb
        mapping, failures = {}, {}
        for name, (combo, callback) in binds.items():
            if not combo or callback is None:
                continue
            try:
                kb.HotKey.parse(combo)
            except Exception:
                # One bad entry used to take every shortcut down with it.
                failures[name] = "invalid"
                continue
            if combo in mapping:
                failures[name] = "taken"
                continue
            mapping[combo] = callback
        if mapping:
            self._listener = kb.GlobalHotKeys(mapping)
            self._listener.daemon = True
            self._listener.start()
        return failures

    def stop(self):
        if self._listener:
            try:
                self._listener.stop()
            except Exception:
                pass
            self._listener = None


def _on_wayland() -> bool:
    return bool(os.environ.get("WAYLAND_DISPLAY")
                or os.environ.get("XDG_SESSION_TYPE", "").lower() == "wayland")


def _pick_backend():
    if IS_WIN:
        try:
            return _Win32Backend()
        except Exception:
            return None
    if _on_wayland():
        return None
    try:
        import pynput.keyboard  # noqa: F401
        return _PynputBackend()
    except Exception:
        return None


class HotkeyManager:
    """Global shortcuts, kept as one named table.

    `failures()` says which ones did not take and why ("taken" by another
    app, "invalid", or "unavailable" where the platform has no global
    shortcuts), so Settings can say so instead of the shortcut silently doing
    nothing.
    """

    def __init__(self, backend="auto"):
        self._binds: dict[str, tuple[str, object]] = {}
        self._failures: dict[str, str] = {}
        self._backend = _pick_backend() if backend == "auto" else backend

    @property
    def available(self) -> bool:
        return self._backend is not None

    def bind(self, name: str, combo: str, callback):
        self._binds[name] = (canonical(combo) or (combo or ""), callback)
        self._apply()

    def rebind(self, name: str, combo: str):
        if name in self._binds:
            self._binds[name] = (canonical(combo) or (combo or ""),
                                 self._binds[name][1])
            self._apply()

    def combo(self, name: str) -> str:
        return self._binds.get(name, ("", None))[0]

    def failures(self) -> dict[str, str]:
        return dict(self._failures)

    def is_global(self, name: str) -> bool:
        """True when the shortcut is live system-wide (so a local key handler
        must leave it alone, or it would fire twice)."""
        combo, _ = self._binds.get(name, ("", None))
        return bool(combo) and self.available and name not in self._failures

    def local_match(self, combo: str) -> str | None:
        """Name of a bound shortcut that is NOT live globally and matches
        `combo` — the in-app fallback where global shortcuts can't work."""
        for name, (bound, callback) in self._binds.items():
            if callback and bound and not self.is_global(name) \
                    and matches(bound, combo):
                return name
        return None

    def trigger(self, name: str):
        _, callback = self._binds.get(name, ("", None))
        if callback:
            callback()

    def stop(self):
        if self._backend:
            self._backend.stop()

    def _apply(self):
        if self._backend is None:
            self._failures = {n: "unavailable" for n, (c, cb) in self._binds.items()
                              if c and cb}
            return
        try:
            self._failures = self._backend.apply(self._binds)
        except Exception:
            self._failures = {n: "failed" for n, (c, cb) in self._binds.items()
                              if c and cb}
