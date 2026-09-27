#!/usr/bin/env python3
"""
Screen Annotation Tool  (PySide6)
================================
Fullscreen transparent overlay — draw on your screen like a whiteboard.

Tools: Select, Pen, Line, Arrow, Rectangle, Circle, Ruler,
       Text, Callout, Steps, Highlight, Eraser,
       Blur, Pixelate, Redact, Laser Pointer

Install:  pip install PySide6-Essentials
Run:      python annotate.py
Exit:     Esc or ✕ in toolbar

Windows notes
─────────────
• Requires Windows 10/11 with Desktop Window Manager (DWM) enabled for
  transparent compositing.  Works in both light and dark mode.
• Global hotkey (Ctrl+Shift+A) requires:  pip install pynput
• High-DPI monitors are handled automatically.
"""

import sys, os, json, math, random as _rng, shutil, subprocess, threading, time, platform
import importlib.util
from datetime import date
from pathlib import Path

# Run as a script this module is "__main__", and dock_toolbar's
# `import annotate` would load a second, independent copy of it — one whose
# dialog theme was never applied, so Settings opened from the dock came up
# light in dark mode. Register this copy under its real name first.
if __name__ == "__main__":
    sys.modules.setdefault("annotate", sys.modules[__name__])

import hotkeys
import ocr_win
import platform_win
from PySide6.QtWidgets import (
    QToolTip,
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QPushButton, QSlider, QLabel, QColorDialog, QGraphicsDropShadowEffect,
    QGraphicsBlurEffect, QGraphicsScene, QGraphicsPixmapItem,
    QFrame, QSystemTrayIcon, QMenu, QFileDialog,
    QDialog, QCheckBox, QTextEdit, QComboBox, QScrollArea, QProgressBar,
    QLineEdit, QTabWidget,
)
from PySide6.QtCore import (
    Qt, QEvent, QObject, QPoint, QPointF, QRect, QRectF, QUrl, QThread, QTimer,
    QKeyCombination, QMargins, QSizeF,
    Signal, Slot,
)
from PySide6.QtGui import (
    QPainter, QPen, QColor, QFont, QBrush,
    QPolygonF, QPainterPath, QPainterPathStroker, QFontMetrics, QFontMetricsF,
    QPixmap, QCursor, QIcon,
    QKeySequence, QDesktopServices, QImage,
)

from video_recorder import (
    FFMPEG_HELP, QUALITY_PRESETS, RecordConfig, ScreenRecorder,
    HardwareRecorder, gpu_recording_possible, resolve_audio_device,
    can_exclude_from_capture, default_output_dir, exclude_from_capture,
    ffmpeg_version, find_ffmpeg,
    format_elapsed, list_audio_devices, pick_region_natively,
    screen_under_cursor, virtual_desktop_rect,
    EXPORT_FORMATS, GIF_RATES, GIF_WIDTHS, MediaConverter, export_path,
    probe_duration,
)

# ── Resource path helper (dev + PyInstaller bundle) ───────────────────────────
def _resource(rel: str) -> str:
    base = getattr(sys, '_MEIPASS', os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, rel)


def _third_party_notices() -> str:
    """Path of the bundled open-source notices ("" if this copy has none)."""
    for rel in (os.path.join("licenses", "THIRD_PARTY_NOTICES.txt"),
                "THIRD_PARTY_NOTICES.txt"):
        path = _resource(rel)
        if os.path.isfile(path):
            return path
    return ""


# ── Custom cursors ─────────────────────────────────────────────────────────────
_CROSS_CURSOR: QCursor | None = None

def _cross_cursor() -> QCursor:
    """White crosshair with dark outline, HiDPI-aware — crisp at any scale."""
    global _CROSS_CURSOR
    if _CROSS_CURSOR is not None:
        return _CROSS_CURSOR

    app   = QApplication.instance()
    ratio = app.devicePixelRatio() if app else 1.0

    # Logical size of the cursor in device-independent pixels
    sz_l, half_l, gap_l = 33, 16, 5

    # Create the pixmap at physical resolution, then declare the logical size
    # via setDevicePixelRatio so Qt renders it crisply at every DPI.
    pix = QPixmap(int(sz_l * ratio), int(sz_l * ratio))
    pix.setDevicePixelRatio(ratio)
    pix.fill(QColor(0, 0, 0, 0))

    p = QPainter(pix)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)

    arms = [
        (0,            half_l, half_l - gap_l, half_l),
        (half_l + gap_l, half_l, sz_l,         half_l),
        (half_l, 0,            half_l, half_l - gap_l),
        (half_l, half_l + gap_l, half_l, sz_l),
    ]
    # Dark shadow stroke then white foreground
    for color, width in [
        (QColor(0, 0, 0, 160),   3.0),
        (QColor(255, 255, 255, 240), 1.5),
    ]:
        p.setPen(QPen(color, width, Qt.PenStyle.SolidLine, Qt.PenCapStyle.FlatCap))
        for x1, y1, x2, y2 in arms:
            p.drawLine(x1, y1, x2, y2)
    p.end()

    # Hotspot in logical pixels (centre of the cursor)
    _CROSS_CURSOR = QCursor(pix, half_l, half_l)
    return _CROSS_CURSOR


# ── App identity ───────────────────────────────────────────────────────────────
VERSION = "5.7.0"

# ── Platform detection ─────────────────────────────────────────────────────────
IS_WIN = platform.system() == "Windows"
IS_MAC = platform.system() == "Darwin"

# ── Settings ───────────────────────────────────────────────────────────────────
_DEFAULT_SETTINGS: dict = {
    # Switches drawing on and off — the one you reach for constantly.
    "hotkey":         "<ctrl>+<shift>+a",
    # Takes the overlay off the screen entirely, marks and all.
    "visibility_hotkey": "<ctrl>+<shift>+h",
    # Ctrl+T and Ctrl+Shift+R were the defaults until 5.1 — new tab and hard
    # reload in every browser. See _migrate_hotkeys().
    "ocr_hotkey":    "<ctrl>+<alt>+t",
    "hotkeys_version": 2,
    "text_box":       False,           # Text tool: False, True (box) or "bubble"
    "shape_fill":     "none",          # Rectangle/Circle: "none", "tint", "solid"
    "arrow_heads":    1,               # Arrow: 1 or 2 heads
    "stamp_kind":     "check",         # Stamp: check, cross, excl, quest, star
    "rec_countdown":  True,            # 3-2-1 before a recording starts
    "hold_to_draw":   "off",           # "off", "rctrl", "rshift": hold to draw
    "marks_dir":      "",              # where marks were last saved / opened
    "fade_ink":       False,           # marks disappear after a few seconds
    "fx_halo":        False,           # highlight around the cursor
    "fx_ripples":     False,           # ripple on every click
    "fx_keys":        False,           # show pressed shortcuts on screen
    "show_hints":     True,            # hover hints on buttons
    "eraser_mode":    "shapes",        # shapes | pixels
    "start_on_boot":  False,
    "theme":          "light",
    # Where you last put the dock (or the collapsed puck) — None means
    # "never moved, use the default resting spot".
    # 1.0 is the original dock size; smaller fits a dock that runs off the
    # edge on a small or unscalable display.
    "dock_scale":     0.78,
    "dock_collapsed": False,
    "dock_x":         None,
    "dock_y":         None,
    # ── Recording ──────────────────────────────────────────────────────────
    # ── Store review prompt ────────────────────────────────────────────────
    "review_state":   "pending",       # pending | later | never | done
    "review_after":   0,               # epoch seconds; stays quiet until then
    "usage_seconds":  0,               # time the app has actually been in use
    "review_successes": 0,             # screenshots / recordings that worked
    "review_days":    [],              # distinct days the app did its job
    "rec_hotkey":     "<ctrl>+<alt>+r",
    "screenshot_hotkey": "<ctrl>+<print_screen>",
    "zoom_hotkey":    "",              # none by default — M in the app
    "shot_dir":       "",              # "" = Pictures\Screenshots
    "tips_done":      False,           # first-run tips shown (or skipped)
    "rec_fps":        30,
    "rec_quality":    "balanced",      # high | balanced | small
    "rec_area":       "all",           # all | screen | region
    "rec_cursor":     True,
    "rec_audio":      False,
    "rec_audio_dev":  "",              # "" = system default input
    "rec_dir":        "",              # "" = Videos/ScreenAnnotatorPro
    "rec_chrome_notice_seen": False,   # the "dock hides while recording" note
    # On by default: this is how recording behaved before cd4b855 reverted to
    # always hiding/parking the dock. WDA_EXCLUDEFROMCAPTURE was reported
    # unreliable at the time, but per-window it either takes or it doesn't
    # (see RecordingController._clear_chrome) — when it doesn't, recording
    # falls back to the old hide/park behavior automatically. Turn this off
    # if you ever catch the dock in a finished recording despite it.
    "rec_keep_dock_live": True,
    # Capture + encode on the graphics chip (one screen; falls back to the
    # CPU recorder by itself if this machine can't). Opt-in while it is new:
    # CI has no GPU to prove it on.
    "rec_hardware":   False,
    "board_style":    "white",         # whiteboard: white | black
}

def _settings_path() -> Path:
    if IS_WIN:
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    else:
        base = Path.home() / ".config"
    return base / "ScreenAnnotatorPro" / "settings.json"

class SettingsManager:
    def __init__(self):
        self._path = _settings_path()
        self._data = dict(_DEFAULT_SETTINGS)
        self.is_new = not self._path.exists()      # first run on this PC
        self._load()

    def _load(self):
        if self._path.exists():
            try:
                saved = json.loads(self._path.read_text(encoding="utf-8"))
                self._data = {**_DEFAULT_SETTINGS, **saved}
                _migrate_hotkeys(self._data, saved)
            except Exception:
                pass

    def save(self):
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps(self._data, indent=2), encoding="utf-8")

    def get(self, key):
        return self._data.get(key, _DEFAULT_SETTINGS.get(key))

    def set(self, key, value):
        self._data[key] = value


# ── Hotkeys ────────────────────────────────────────────────────────────────────
# The format, validation and the per-platform registration live in hotkeys.py.

HotkeyManager = hotkeys.HotkeyManager

# settings key → (hotkey name, label shown in Settings / Help / errors)
HOTKEY_SETTINGS = {
    "hotkey":            ("toggle",     "Draw / click-through"),
    "visibility_hotkey": ("visibility", "Show / hide the overlay"),
    "ocr_hotkey":        ("ocr",        "Snip & Read"),
    "rec_hotkey":        ("record",     "Start / stop recording"),
    "screenshot_hotkey": ("screenshot", "Screenshot"),
    "zoom_hotkey":       ("zoom",       "Magnifier"),
}

_OLD_DEFAULT_HOTKEYS = {
    "ocr_hotkey": "<ctrl>+t",               # new browser tab
    "rec_hotkey": "<ctrl>+<shift>+r",       # hard reload in browsers
}


def _migrate_hotkeys(data: dict, saved: dict):
    """Once, on the first 5.1 launch: move people off the two defaults that
    collided with browsers, and repair combos older versions stored in a form
    pynput rejected ("<ctrl>+f5") — one of those used to kill every shortcut.

    settings.json holds every key after the first save, so a value equal to
    the old default can't be told apart from a deliberate choice; it is
    treated as the default, which it almost always is.
    """
    if int(saved.get("hotkeys_version", 1) or 1) >= 2:
        return
    for key, old in _OLD_DEFAULT_HOTKEYS.items():
        if data.get(key) == old:
            data[key] = _DEFAULT_SETTINGS[key]
    for key in HOTKEY_SETTINGS:
        fixed = hotkeys.canonical(data.get(key))
        if fixed:
            data[key] = fixed
    data["hotkeys_version"] = 2


def shortcut_label(settings: "SettingsManager", key: str) -> str:
    """How a configured shortcut reads in the UI ("Ctrl+Alt+R", or "no shortcut")."""
    return hotkeys.display(settings.get(key)) or "no shortcut"


# ── Snip & Read availability ──────────────────────────────────────────────────
# On Windows, Snip & Read runs on the OCR engine built into Windows
# (ocr_win.py) — nothing to bundle, so the Store build has it too. Elsewhere
# it needs EasyOCR installed. Where neither is there the tool hides itself: a
# button that can only say "not available" is worse than no button.
# (find_spec checks for EasyOCR without importing Torch.)

_ocr_available: bool | None = None


def ocr_available() -> bool:
    global _ocr_available
    if _ocr_available is None:
        try:
            _ocr_available = (ocr_win.available()
                              or importlib.util.find_spec("easyocr") is not None)
        except (ImportError, ValueError):
            _ocr_available = False
    return _ocr_available

# ── Click-through ──────────────────────────────────────────────────────────────
# The overlay covers the whole desktop, so while it accepts input nothing
# underneath can be reached — no clicks, no typing, no switching apps. That is
# right while you are drawing and wrong the rest of the time, which is what
# click-through mode fixes: the marks stay on screen, the input goes past them.
#
# It has to be done at the window-manager level. A Qt-side "ignore this event"
# is too late — the OS has already decided the click belongs to this window.

GWL_EXSTYLE        = -20
WS_EX_TRANSPARENT  = 0x00000020
WS_EX_LAYERED      = 0x00080000


def _set_click_through(widget, on: bool) -> bool:
    """Let mouse input fall through a window while it stays visible."""
    # Qt's own attribute is what makes this work outside Windows: on Wayland it
    # turns into an empty input region on the surface.
    widget.setAttribute(WAtt.WA_TransparentForMouseEvents, on)
    if not IS_WIN:
        return True
    try:
        import ctypes
        user32 = ctypes.windll.user32
        get = getattr(user32, "GetWindowLongPtrW", None) or user32.GetWindowLongW
        setl = getattr(user32, "SetWindowLongPtrW", None) or user32.SetWindowLongW
        get.restype, get.argtypes = ctypes.c_longlong, [ctypes.c_void_p, ctypes.c_int]
        setl.restype = ctypes.c_longlong
        setl.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_longlong]
        hwnd = ctypes.c_void_p(int(widget.winId()))
        ex = get(hwnd, GWL_EXSTYLE)
        # WS_EX_LAYERED has to stay on: a plain WS_EX_TRANSPARENT window still
        # gets hit-tested by some compositing paths.
        ex = (ex | WS_EX_TRANSPARENT | WS_EX_LAYERED) if on \
            else (ex & ~WS_EX_TRANSPARENT)
        setl(hwnd, GWL_EXSTYLE, ex)
        # A style change is not guaranteed to take effect until the window is
        # told to re-read it. Without this the flag can sit there doing
        # nothing until something else happens to move or resize the window —
        # which reads exactly like "the hotkey did not work".
        user32.SetWindowPos.argtypes = [ctypes.c_void_p, ctypes.c_void_p,
                                        ctypes.c_int, ctypes.c_int,
                                        ctypes.c_int, ctypes.c_int,
                                        ctypes.c_uint]
        SWP_NOMOVE, SWP_NOSIZE, SWP_NOZORDER = 0x0002, 0x0001, 0x0004
        SWP_NOACTIVATE, SWP_FRAMECHANGED = 0x0010, 0x0020
        user32.SetWindowPos(hwnd, None, 0, 0, 0, 0,
                            SWP_NOMOVE | SWP_NOSIZE | SWP_NOZORDER |
                            SWP_NOACTIVATE | SWP_FRAMECHANGED)
        return True
    except Exception:
        return False


# ── Qt enum aliases ────────────────────────────────────────────────────────────
WType  = Qt.WindowType
WAtt   = Qt.WidgetAttribute
MB     = Qt.MouseButton
GC     = Qt.GlobalColor
PS     = Qt.PenStyle
BS     = Qt.BrushStyle
Cap    = Qt.PenCapStyle
Join   = Qt.PenJoinStyle
Ori    = Qt.Orientation
Cursor = Qt.CursorShape
Key    = Qt.Key
RHint  = QPainter.RenderHint
AA     = Qt.AlignmentFlag
CM     = QPainter.CompositionMode

# ── Palette & tool definitions ─────────────────────────────────────────────────
COLORS = [
    ("#FF3B3B", "Red"), ("#FF9F0A", "Orange"), ("#FFD60A", "Yellow"),
    ("#32D74B", "Green"), ("#0A84FF", "Blue"), ("#BF5AF2", "Purple"),
    ("#FFFFFF", "White"), ("#1C1C1E", "Black"),
]

SWATCHES = [
    "#FF3B3B","#FF6B00","#FFD60A","#34C759",
    "#0A84FF","#BF5AF2","#FF375F","#30D158",
    "#FFFFFF","#E5E5EA","#8E8E93","#636366",
    "#3A3A3C","#1C1C1E","#000000","#FF9F0A",
]

TOOLS = [
    ("select",    "↖",    "Select / Move  V"),
    ("pen",       "〜",    "Pen  P"),
    ("line",      "—",    "Line  L"),
    ("arrow",     "→",    "Arrow  A"),
    ("rect",      "▭",    "Rectangle  R"),
    ("circle",    "○",    "Circle  O"),
    ("ruler",     "📏",   "Ruler  U"),
    ("text",      "T",    "Text  T"),
    ("callout",   "①",   "Callout  K"),
    ("steps",     "1▸2",  "Steps  S"),
    ("highlight", "HL",   "Highlight  H"),
    ("blur",      "⊘",    "Blur  Z"),
    ("pixel",     "PX",   "Pixelate  X"),
    ("redact",    "▪",    "Redact  D"),
    ("laser",     "⊙",    "Laser  I"),
]

KEY_TOOL = {
    Key.Key_V: "select", Key.Key_P: "pen",    Key.Key_L: "line",
    Key.Key_A: "arrow",  Key.Key_R: "rect",   Key.Key_O: "circle",
    Key.Key_U: "ruler",  Key.Key_T: "text",   Key.Key_K: "callout",
    Key.Key_S: "steps",  Key.Key_H: "highlight",
    Key.Key_Z: "blur",   Key.Key_X: "pixel",
    Key.Key_D: "redact", Key.Key_I: "laser",
    Key.Key_E: "eraser", Key.Key_J: "ocr",    Key.Key_G: "stamp",
}

DRAG_TOOLS  = {"line","arrow","rect","circle","ruler","highlight","blur","pixel","redact"}
POINT_TOOLS = {"text","callout","steps","stamp"}
PEN_TOOLS   = {"pen", "eraser"}   # freehand stroke tools

# [WIN-FIX] pick the right system emoji font per platform
# ── Helpers ────────────────────────────────────────────────────────────────────
def _norm(p1: QPointF, p2: QPointF) -> QRectF:
    return QRectF(min(p1.x(),p2.x()), min(p1.y(),p2.y()),
                  abs(p2.x()-p1.x()), abs(p2.y()-p1.y()))

def _pen(color: str, width: int) -> QPen:
    return QPen(QColor(color), width, PS.SolidLine, Cap.RoundCap, Join.RoundJoin)

def _with_alpha(hex_color: str, alpha: int) -> str:
    """Return #AARRGGBB string with alpha baked in (alpha 0-255)."""
    c = QColor(hex_color)
    c.setAlpha(alpha)
    return c.name(QColor.NameFormat.HexArgb)

def _snap_45(p1: QPointF, p2: QPointF) -> QPointF:
    """Snap p2 to the nearest 45° direction from p1 (Shift-lock)."""
    dx, dy = p2.x() - p1.x(), p2.y() - p1.y()
    dist = math.hypot(dx, dy)
    if dist < 1:
        return p2
    angle   = math.atan2(dy, dx)
    snapped = round(angle / (math.pi / 4)) * (math.pi / 4)
    return QPointF(p1.x() + dist * math.cos(snapped),
                   p1.y() + dist * math.sin(snapped))

def _contrast(hex_color: str) -> QColor:
    c = QColor(hex_color)
    return QColor("#000") if (0.299*c.red()+0.587*c.green()+0.114*c.blue()) > 128 else QColor("#fff")

def _arrowhead(p1: QPointF, p2: QPointF, size: float) -> QPolygonF:
    dx, dy = p2.x()-p1.x(), p2.y()-p1.y()
    if math.hypot(dx, dy) < 1:
        return QPolygonF()
    a = math.atan2(dy, dx)
    return QPolygonF([
        p2,
        QPointF(p2.x()-size*math.cos(a-math.pi/6), p2.y()-size*math.sin(a-math.pi/6)),
        QPointF(p2.x()-size*math.cos(a+math.pi/6), p2.y()-size*math.sin(a+math.pi/6)),
    ])


def _blur_pixmap(pixmap: QPixmap, radius: int = 18) -> QPixmap:
    """Apply a real Gaussian blur to a QPixmap via Qt's graphics effect."""
    if pixmap.isNull():
        return pixmap
    fx = QGraphicsBlurEffect()
    fx.setBlurRadius(radius)
    fx.setBlurHints(QGraphicsBlurEffect.BlurHint.QualityHint)
    item = QGraphicsPixmapItem(pixmap)
    item.setGraphicsEffect(fx)
    scene = QGraphicsScene()
    scene.addItem(item)
    out = QPixmap(pixmap.size())
    out.fill(QColor(0, 0, 0, 0))
    p = QPainter(out)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    scene.render(p, source=QRectF(item.boundingRect()))
    p.end()
    return out


# ── Shape classes ──────────────────────────────────────────────────────────────
def _dist_to_segment(pt: QPointF, a: QPointF, b: QPointF) -> float:
    dx, dy = b.x() - a.x(), b.y() - a.y()
    length2 = dx * dx + dy * dy
    if length2 == 0:
        return math.hypot(pt.x() - a.x(), pt.y() - a.y())
    t = max(0.0, min(1.0, ((pt.x() - a.x()) * dx + (pt.y() - a.y()) * dy) / length2))
    return math.hypot(pt.x() - (a.x() + t * dx), pt.y() - (a.y() + t * dy))


class Shape:
    def draw(self, p: QPainter): pass
    def move(self, dx: float, dy: float): pass
    def bounding_rect(self) -> QRectF: return QRectF()
    def contains(self, pt: QPointF) -> bool: return self.bounding_rect().contains(pt)

    def hit(self, pt: QPointF, tolerance: float = 6.0) -> bool:
        """Is `pt` on the visible mark (within `tolerance`)? Filled shapes are
        hit anywhere inside; outlines only near the line itself — a long
        diagonal arrow no longer claims every click in its bounding box."""
        return self.bounding_rect().adjusted(-tolerance, -tolerance,
                                             tolerance, tolerance).contains(pt)


class PenShape(Shape):
    def __init__(self, color, width):
        self.color, self.width = color, width
        self.pts: list[QPointF] = []

    def draw(self, p):
        if not self.pts: return
        p.setRenderHint(RHint.Antialiasing)
        p.setPen(_pen(self.color, self.width))
        if len(self.pts) == 1:
            p.drawPoint(self.pts[0])
        elif QColor(self.color).alpha() < 255:
            # One polyline is stroked as one outline, so where segments meet
            # nothing is painted twice. Separate segments each blend their
            # round cap over the last, and a see-through stroke came out as a
            # string of darker beads. Opaque strokes keep the separate
            # segments: they look the same and paint about twice as fast.
            p.drawPolyline(QPolygonF(self.pts))
        else:
            for i in range(1, len(self.pts)):
                p.drawLine(self.pts[i-1], self.pts[i])

    def move(self, dx, dy):
        self.pts = [QPointF(pt.x()+dx, pt.y()+dy) for pt in self.pts]

    def bounding_rect(self):
        if not self.pts: return QRectF()
        xs = [pt.x() for pt in self.pts]; ys = [pt.y() for pt in self.pts]
        return QRectF(min(xs), min(ys), max(xs)-min(xs), max(ys)-min(ys))

    def hit(self, pt, tolerance=6.0):
        reach = self.width / 2 + tolerance
        if not self.bounding_rect().adjusted(-reach, -reach, reach, reach).contains(pt):
            return False
        if len(self.pts) == 1:
            return _dist_to_segment(pt, self.pts[0], self.pts[0]) <= reach
        return any(_dist_to_segment(pt, a, b) <= reach
                   for a, b in zip(self.pts, self.pts[1:]))


class LineShape(Shape):
    def __init__(self, p1, p2, color, width):
        self.p1, self.p2, self.color, self.width = p1, p2, color, width

    def draw(self, p):
        p.setRenderHint(RHint.Antialiasing)
        p.setPen(_pen(self.color, self.width))
        p.drawLine(self.p1, self.p2)

    def move(self, dx, dy):
        self.p1 = QPointF(self.p1.x()+dx, self.p1.y()+dy)
        self.p2 = QPointF(self.p2.x()+dx, self.p2.y()+dy)

    def bounding_rect(self): return _norm(self.p1, self.p2).adjusted(-10,-10,10,10)

    def hit(self, pt, tolerance=6.0):
        return _dist_to_segment(pt, self.p1, self.p2) <= self.width / 2 + tolerance


class ArrowShape(Shape):
    """`heads` 1 or 2. `bend` curves it: how far the middle of the arrow sits
    off the straight line, in px, to its left (negative: right)."""

    def __init__(self, p1, p2, color, width, heads: int = 1, bend: float = 0.0):
        self.p1, self.p2, self.color, self.width = p1, p2, color, width
        self.heads, self.bend = heads, bend

    def _normal(self) -> tuple[float, float]:
        dx, dy = self.p2.x() - self.p1.x(), self.p2.y() - self.p1.y()
        length = math.hypot(dx, dy)
        return (0.0, 0.0) if length < 1 else (-dy / length, dx / length)

    def mid_point(self) -> QPointF:
        """The middle of the arrow as drawn — the handle that bends it."""
        nx, ny = self._normal()
        b = getattr(self, "bend", 0.0)
        return QPointF((self.p1.x() + self.p2.x()) / 2 + nx * b,
                       (self.p1.y() + self.p2.y()) / 2 + ny * b)

    def set_mid(self, pos: QPointF):
        nx, ny = self._normal()
        mx, my = (self.p1.x() + self.p2.x()) / 2, (self.p1.y() + self.p2.y()) / 2
        b = (pos.x() - mx) * nx + (pos.y() - my) * ny
        self.bend = 0.0 if abs(b) < 4 else b        # a little slack snaps straight

    def _ctrl(self) -> QPointF:
        # A quadratic curve passes through half its control point's offset.
        nx, ny = self._normal()
        b = 2 * getattr(self, "bend", 0.0)
        return QPointF((self.p1.x() + self.p2.x()) / 2 + nx * b,
                       (self.p1.y() + self.p2.y()) / 2 + ny * b)

    def draw(self, p):
        # One outline, filled once. Drawn as shaft + filled head + stroked
        # head, every overlap was painted two or three times, so a
        # see-through arrow showed its shaft through the head and a darker
        # ring around it. The union covers exactly the same pixels as before.
        p.setRenderHint(RHint.Antialiasing)
        p.setPen(PS.NoPen)
        p.setBrush(QBrush(QColor(self.color)))
        p.drawPath(self.outline())

    def outline(self) -> QPainterPath:
        heads, bend = getattr(self, "heads", 1), getattr(self, "bend", 0.0)
        key = (self.p1.x(), self.p1.y(), self.p2.x(), self.p2.y(), self.width,
               heads, bend)
        if getattr(self, "_outline_key", None) != key:
            stroker = QPainterPathStroker()
            stroker.setWidth(self.width)
            stroker.setCapStyle(Cap.RoundCap)
            stroker.setJoinStyle(Join.RoundJoin)
            shaft = QPainterPath(self.p1)
            if bend:
                ctrl = self._ctrl()
                shaft.quadTo(ctrl, self.p2)
            else:
                ctrl = None
                shaft.lineTo(self.p2)
            path = stroker.createStroke(shaft)
            size = max(self.width*3.5, 14)
            # A curve's head points along the curve's own end, not the chord.
            polys = [_arrowhead(ctrl or self.p1, self.p2, size)]
            if heads == 2:
                polys.append(_arrowhead(ctrl or self.p2, self.p1, size))
            for poly in polys:
                if poly.isEmpty():
                    continue
                head = QPainterPath()
                head.addPolygon(poly)
                head.closeSubpath()
                path = path.united(head).united(stroker.createStroke(head))
            path.setFillRule(Qt.FillRule.WindingFill)
            self._outline_key, self._outline_path = key, path
        return self._outline_path

    def move(self, dx, dy):
        self.p1 = QPointF(self.p1.x()+dx, self.p1.y()+dy)
        self.p2 = QPointF(self.p2.x()+dx, self.p2.y()+dy)

    def bounding_rect(self):
        box = _norm(self.p1, self.p2).adjusted(-20, -20, 20, 20)
        if getattr(self, "bend", 0.0):
            box = box.united(self.outline().boundingRect().adjusted(-4, -4, 4, 4))
        return box

    def hit(self, pt, tolerance=6.0):
        if getattr(self, "bend", 0.0):
            wide = QPainterPathStroker()
            wide.setWidth(self.width + 2 * tolerance)
            shaft = QPainterPath(self.p1)
            shaft.quadTo(self._ctrl(), self.p2)
            return wide.createStroke(shaft).contains(pt) or self.outline().contains(pt)
        if _dist_to_segment(pt, self.p1, self.p2) <= self.width / 2 + tolerance:
            return True
        return self.outline().contains(pt)


def _paint_filled(p: QPainter, shape, draw):
    """Rectangle/circle with FILL: "tint" puts a light wash inside the
    outline, "solid" fills it in the mark's colour. Fill and outline never
    overlap, so a see-through mark has no darker ring (the arrow lesson)."""
    fill, r = getattr(shape, "fill", "none"), _norm(shape.p1, shape.p2)
    h = shape.width / 2
    p.setRenderHint(RHint.Antialiasing)
    if fill == "solid":
        p.setPen(PS.NoPen)
        p.setBrush(QBrush(QColor(shape.color)))
        draw(r.adjusted(-h, -h, h, h), h)
        return
    if fill == "tint":
        wash = QColor(shape.color)
        wash.setAlpha(max(1, round(wash.alpha() * 0.28)))
        p.setPen(PS.NoPen)
        p.setBrush(QBrush(wash))
        draw(r.adjusted(h, h, -h, -h), 0)
    p.setPen(_pen(shape.color, shape.width))
    p.setBrush(BS.NoBrush)
    draw(r, None)


class RectShape(Shape):
    def __init__(self, p1, p2, color, width, fill: str = "none"):
        self.p1, self.p2, self.color, self.width = p1, p2, color, width
        self.fill = fill

    def draw(self, p):
        def rect(r, radius):
            if radius:
                p.drawRoundedRect(r, radius, radius)   # the round join's corners
            else:
                p.drawRect(r)
        _paint_filled(p, self, rect)

    def move(self, dx, dy):
        self.p1 = QPointF(self.p1.x()+dx, self.p1.y()+dy)
        self.p2 = QPointF(self.p2.x()+dx, self.p2.y()+dy)

    def bounding_rect(self): return _norm(self.p1, self.p2)

    def hit(self, pt, tolerance=6.0):
        r = _norm(self.p1, self.p2)
        if getattr(self, "fill", "none") != "none" and r.contains(pt):
            return True
        c = [r.topLeft(), r.topRight(), r.bottomRight(), r.bottomLeft()]
        reach = self.width / 2 + tolerance
        return any(_dist_to_segment(pt, c[i], c[(i + 1) % 4]) <= reach
                   for i in range(4))


class CircleShape(Shape):
    def __init__(self, p1, p2, color, width, fill: str = "none"):
        self.p1, self.p2, self.color, self.width = p1, p2, color, width
        self.fill = fill

    def draw(self, p):
        _paint_filled(p, self, lambda r, _radius: p.drawEllipse(r))

    def move(self, dx, dy):
        self.p1 = QPointF(self.p1.x()+dx, self.p1.y()+dy)
        self.p2 = QPointF(self.p2.x()+dx, self.p2.y()+dy)

    def bounding_rect(self): return _norm(self.p1, self.p2)

    def hit(self, pt, tolerance=6.0):
        r = _norm(self.p1, self.p2)
        a, b = r.width() / 2, r.height() / 2
        if a < 1 or b < 1:
            return r.adjusted(-tolerance, -tolerance, tolerance, tolerance).contains(pt)
        dx, dy = pt.x() - r.center().x(), pt.y() - r.center().y()
        if getattr(self, "fill", "none") != "none" and \
                (dx / a) ** 2 + (dy / b) ** 2 <= 1:
            return True
        # Distance from the outline along the ray from the centre: the
        # ellipse's radius in that direction against the point's distance.
        theta = math.atan2(dy, dx)
        radius = a * b / math.hypot(b * math.cos(theta), a * math.sin(theta))
        return abs(math.hypot(dx, dy) - radius) <= self.width / 2 + tolerance


class RulerShape(Shape):
    """Measures in real screen pixels: `scale` is the screen's device pixel
    ratio, so at 125 % a 100-logical-pixel line reads "125 px" — the number
    that matches a screenshot or a design file."""

    def __init__(self, p1, p2, color, width, scale: float = 1.0):
        self.p1, self.p2, self.color, self.width = p1, p2, color, width
        self.scale = scale

    def draw(self, p):
        p.setRenderHint(RHint.Antialiasing)
        p.setPen(_pen(self.color, self.width))
        dx, dy = self.p2.x()-self.p1.x(), self.p2.y()-self.p1.y()
        length = math.hypot(dx, dy)
        if length < 1:
            p.drawLine(self.p1, self.p2)
            return
        # Line and end ticks as one path, stroked once — separate lines
        # painted the crossings twice, a dark blob at each end when the
        # colour is see-through.
        nx, ny = -dy/length, dx/length
        tick = 8
        path = QPainterPath(self.p1)
        path.lineTo(self.p2)
        for pt in (self.p1, self.p2):
            path.moveTo(QPointF(pt.x()+nx*tick, pt.y()+ny*tick))
            path.lineTo(QPointF(pt.x()-nx*tick, pt.y()-ny*tick))
        p.setBrush(BS.NoBrush)
        p.drawPath(path)
        label = f"{self.length_px()} px"
        mid = QPointF((self.p1.x()+self.p2.x())/2, (self.p1.y()+self.p2.y())/2)
        font = QFont("Arial", 11, QFont.Weight.Bold)
        p.setFont(font)
        fm = QFontMetrics(font)
        tw, th = fm.horizontalAdvance(label)+10, fm.height()+6
        p.setPen(PS.NoPen); p.setBrush(QBrush(QColor(28,28,30,210)))
        p.drawRoundedRect(QRectF(mid.x()-tw/2, mid.y()-th/2, tw, th), 5, 5)
        p.setPen(QPen(QColor(self.color)))
        p.drawText(QRectF(mid.x()-tw/2, mid.y()-th/2, tw, th), AA.AlignCenter, label)

    def move(self, dx, dy):
        self.p1 = QPointF(self.p1.x()+dx, self.p1.y()+dy)
        self.p2 = QPointF(self.p2.x()+dx, self.p2.y()+dy)

    def bounding_rect(self): return _norm(self.p1, self.p2).adjusted(-30,-30,30,30)

    def hit(self, pt, tolerance=6.0):
        return _dist_to_segment(pt, self.p1, self.p2) <= self.width / 2 + tolerance + 8

    def length_px(self) -> int:
        """Length in real screen pixels."""
        return round(math.hypot(self.p2.x() - self.p1.x(),
                                self.p2.y() - self.p1.y()) * self.scale)


class TextShape(Shape):
    """Text whose top-left corner is `pos`; several lines are fine. `box`
    puts a rounded plate in the contrasting colour behind it, so a label
    stays readable on a busy background."""

    PAD_X, PAD_Y = 8, 4

    def __init__(self, pos, text, color, size, box: bool | str = False):
        self.pos, self.text, self.color, self.size = pos, text, color, size
        self.box = box                  # False, True (plate) or "bubble"
        self.tail: QPointF | None = None    # bubble tail tip, relative to pos

    def tail_point(self) -> QPointF:
        off = self.tail
        if off is None:                 # below the first letters, pointing down
            off = QPointF(18, self.text_rect().height() + self.PAD_Y + 34)
        return QPointF(self.pos.x() + off.x(), self.pos.y() + off.y())

    def bubble_path(self) -> QPainterPath:
        body = self.text_rect().adjusted(-self.PAD_X - 4, -self.PAD_Y - 3,
                                         self.PAD_X + 4, self.PAD_Y + 3)
        path = QPainterPath()
        path.addRoundedRect(body, 12, 12)
        tip = self.tail_point()
        bx = min(max(tip.x(), body.left() + 16), body.right() - 16)
        by = min(max(tip.y(), body.top() + 12), body.bottom() - 12)
        dx, dy = tip.x() - bx, tip.y() - by
        length = math.hypot(dx, dy)
        if length > 1 and not body.contains(tip):
            nx, ny, half = -dy / length, dx / length, 9
            tail = QPainterPath()
            tail.addPolygon(QPolygonF([QPointF(bx + nx * half, by + ny * half), tip,
                                       QPointF(bx - nx * half, by - ny * half)]))
            tail.closeSubpath()
            path = path.united(tail)
        return path

    def font(self) -> QFont:
        return QFont("Arial", self.size, QFont.Weight.Bold)

    def text_rect(self) -> QRectF:
        fm = QFontMetricsF(self.font())
        r = fm.boundingRect(QRectF(0, 0, 1e6, 1e6),
                            int(AA.AlignLeft | AA.AlignTop), self.text or " ")
        return QRectF(self.pos, r.size())

    def draw(self, p):
        p.setRenderHint(RHint.Antialiasing)
        r = self.text_rect()
        if self.box == "bubble":
            plate = _contrast(self.color)
            plate.setAlpha(240)
            p.setPen(QPen(QColor(self.color), 2))
            p.setBrush(QBrush(plate))
            p.drawPath(self.bubble_path())
        elif self.box:
            plate = _contrast(self.color)
            plate.setAlpha(225)
            p.setPen(PS.NoPen)
            p.setBrush(QBrush(plate))
            p.drawRoundedRect(r.adjusted(-self.PAD_X, -self.PAD_Y,
                                         self.PAD_X, self.PAD_Y), 6, 6)
        p.setFont(self.font())
        p.setPen(QPen(QColor(self.color)))
        p.drawText(r, int(AA.AlignLeft | AA.AlignTop), self.text)

    def move(self, dx, dy): self.pos = QPointF(self.pos.x()+dx, self.pos.y()+dy)

    def bounding_rect(self):
        r = self.text_rect()
        if self.box == "bubble":
            return self.bubble_path().boundingRect().adjusted(-2, -2, 2, 2)
        return r.adjusted(-self.PAD_X, -self.PAD_Y, self.PAD_X, self.PAD_Y) \
            if self.box else r


def _marker_radius(size: int) -> int:
    """Callout/step radius from the SIZE slider: 20 pt gives the original 16 px."""
    return max(10, round(size * 0.8))


class CalloutShape(Shape):
    """Filled circle with auto-incrementing number."""
    def __init__(self, pos, number, color, size: int = 20):
        self.pos, self.number, self.color = pos, number, color
        self.r = _marker_radius(size)

    def draw(self, p):
        p.setRenderHint(RHint.Antialiasing)
        r = self.r
        p.setPen(PS.NoPen); p.setBrush(QBrush(QColor(self.color)))
        p.drawEllipse(QRectF(self.pos.x()-r, self.pos.y()-r, r*2, r*2))
        p.setFont(QFont("Arial", r-2, QFont.Weight.Bold))
        p.setPen(QPen(_contrast(self.color)))
        p.drawText(QRectF(self.pos.x()-r, self.pos.y()-r, r*2, r*2), AA.AlignCenter, str(self.number))

    def move(self, dx, dy): self.pos = QPointF(self.pos.x()+dx, self.pos.y()+dy)
    def bounding_rect(self): return QRectF(self.pos.x()-self.r, self.pos.y()-self.r, self.r*2, self.r*2)


class StepShape(Shape):
    """Rounded square with auto-incrementing step number."""
    def __init__(self, pos, number, color, size: int = 20):
        self.pos, self.number, self.color = pos, number, color
        self.r = _marker_radius(size)

    def draw(self, p):
        p.setRenderHint(RHint.Antialiasing)
        r = self.r
        p.setPen(PS.NoPen); p.setBrush(QBrush(QColor(self.color)))
        p.drawRoundedRect(QRectF(self.pos.x()-r, self.pos.y()-r, r*2, r*2), 5, 5)
        p.setFont(QFont("Arial", r-2, QFont.Weight.Bold))
        p.setPen(QPen(_contrast(self.color)))
        p.drawText(QRectF(self.pos.x()-r, self.pos.y()-r, r*2, r*2), AA.AlignCenter, str(self.number))

    def move(self, dx, dy): self.pos = QPointF(self.pos.x()+dx, self.pos.y()+dy)
    def bounding_rect(self): return QRectF(self.pos.x()-self.r, self.pos.y()-self.r, self.r*2, self.r*2)


STAMPS = ("check", "cross", "excl", "quest", "star")


class StampShape(Shape):
    """A ✓ ✗ ! ? or ★ on a filled disc: right, wrong, look here, unclear,
    well done. Vector-drawn, so it never depends on a font having the glyph."""

    def __init__(self, pos, kind, color, size):
        self.pos, self.kind, self.color = pos, kind, color
        self.r = _stamp_radius(size)

    def draw(self, p):
        c, r = self.pos, self.r
        p.setRenderHint(RHint.Antialiasing)
        p.setPen(PS.NoPen)
        p.setBrush(QBrush(QColor(self.color)))
        p.drawEllipse(c, r, r)
        ink = _contrast(self.color)
        ink.setAlpha(255)
        pen = QPen(ink, max(2.0, r * 0.2))
        pen.setCapStyle(Cap.RoundCap)
        pen.setJoinStyle(Join.RoundJoin)
        at = lambda fx, fy: QPointF(c.x() + fx * r, c.y() + fy * r)
        if self.kind == "check":
            p.setPen(pen)
            p.drawPolyline(QPolygonF([at(-0.42, 0.02), at(-0.12, 0.32), at(0.44, -0.3)]))
        elif self.kind == "cross":
            p.setPen(pen)
            p.drawLine(at(-0.33, -0.33), at(0.33, 0.33))
            p.drawLine(at(-0.33, 0.33), at(0.33, -0.33))
        elif self.kind == "excl":
            p.setPen(pen)
            p.drawLine(at(0, -0.48), at(0, 0.1))
            p.setPen(PS.NoPen)
            p.setBrush(QBrush(ink))
            p.drawEllipse(at(0, 0.42), r * 0.12, r * 0.12)
        elif self.kind == "quest":
            f = QFont("Arial", 10, QFont.Weight.Black)
            f.setPixelSize(max(8, round(r * 1.35)))
            p.setFont(f)
            p.setPen(QPen(ink))
            p.drawText(QRectF(c.x() - r, c.y() - r, 2 * r, 2 * r),
                       int(AA.AlignCenter), "?")
        else:                           # star
            pts = []
            for i in range(10):
                a = -math.pi / 2 + i * math.pi / 5
                k = 0.58 if i % 2 == 0 else 0.24
                pts.append(at(k * math.cos(a), k * math.sin(a)))
            p.setPen(PS.NoPen)
            p.setBrush(QBrush(ink))
            p.drawPolygon(QPolygonF(pts))

    def move(self, dx, dy): self.pos = QPointF(self.pos.x()+dx, self.pos.y()+dy)

    def bounding_rect(self):
        return QRectF(self.pos.x()-self.r, self.pos.y()-self.r, 2*self.r, 2*self.r)

    def hit(self, pt, tolerance=6.0):
        return math.hypot(pt.x()-self.pos.x(), pt.y()-self.pos.y()) <= self.r + tolerance


def _stamp_radius(size: int) -> int:
    return round(_marker_radius(size) * 1.15)


class HighlightShape(Shape):
    def __init__(self, p1, p2, color: str = "#FFD60A"):
        self.p1, self.p2, self.color = p1, p2, color

    def draw(self, p):
        c = QColor(self.color)
        c.setAlpha(110)
        p.setPen(PS.NoPen)
        p.setBrush(QBrush(c))
        p.drawRect(_norm(self.p1, self.p2))

    def move(self, dx, dy):
        self.p1 = QPointF(self.p1.x()+dx, self.p1.y()+dy)
        self.p2 = QPointF(self.p2.x()+dx, self.p2.y()+dy)

    def bounding_rect(self): return _norm(self.p1, self.p2)


class BlurShape(Shape):
    """Draws the blurred screen content captured at creation time."""
    def __init__(self, p1, p2, blurred: QPixmap | None = None):
        self.p1, self.p2 = p1, p2
        self.blurred = blurred

    def draw(self, p):
        rect = _norm(self.p1, self.p2)
        if self.blurred and not self.blurred.isNull():
            p.drawPixmap(rect.toRect(), self.blurred)
        else:
            p.setPen(PS.NoPen); p.setBrush(QBrush(QColor(200, 200, 210, 130)))
            p.drawRect(rect)
            p.setPen(QPen(QColor(255,255,255,55), 1))
            step, x = 8, rect.left()
            while x < rect.right() + rect.height():
                x1 = max(x, rect.left());  y1 = rect.top() + max(0.0, rect.left()-x)
                x2 = min(x+rect.height(), rect.right())
                y2 = y1 + (x2-x1)
                p.drawLine(QPointF(x1,y1), QPointF(x2,y2))
                x += step
            p.setPen(QPen(QColor(180,180,200,200), 1, PS.DashLine))
            p.setBrush(BS.NoBrush); p.drawRect(rect)

    def move(self, dx, dy):
        self.p1 = QPointF(self.p1.x()+dx, self.p1.y()+dy)
        self.p2 = QPointF(self.p2.x()+dx, self.p2.y()+dy)

    def bounding_rect(self): return _norm(self.p1, self.p2)


class PixelShape(Shape):
    """A real mosaic of what was underneath: the grab shrunk to one pixel per
    cell and blown back up without smoothing. Cells never go below
    PixelShape.MIN_CELL — small cells over small text can be read back.
    Without a grab (it failed) it falls back to a grey noise block."""

    MIN_CELL = 10

    def __init__(self, p1, p2, mosaic: QPixmap | None = None):
        self.p1, self.p2 = p1, p2
        self.mosaic = mosaic

    def draw(self, p):
        rect = _norm(self.p1, self.p2)
        if self.mosaic is not None and not self.mosaic.isNull():
            p.drawPixmap(rect.toRect(), self.mosaic)
            return
        pz = max(self.MIN_CELL, getattr(self, "size", 12))
        rng = _rng.Random(int(rect.width() * 100 + rect.height()))
        p.setPen(PS.NoPen)
        x = rect.left()
        while x < rect.right():
            y = rect.top()
            while y < rect.bottom():
                g = rng.randint(80, 210)
                p.setBrush(QBrush(QColor(g, g, g, 255)))
                p.drawRect(QRectF(x, y, min(pz, rect.right()-x), min(pz, rect.bottom()-y)))
                y += pz
            x += pz

    def move(self, dx, dy):
        self.p1 = QPointF(self.p1.x()+dx, self.p1.y()+dy)
        self.p2 = QPointF(self.p2.x()+dx, self.p2.y()+dy)

    def bounding_rect(self): return _norm(self.p1, self.p2)


def _mosaic(raw: QPixmap, cell_px: int) -> QPixmap:
    """Pixelate a grab: average each cell (smooth downscale), then enlarge
    with hard edges."""
    w, h = raw.width(), raw.height()
    small = raw.scaled(max(1, round(w / cell_px)), max(1, round(h / cell_px)),
                       Qt.AspectRatioMode.IgnoreAspectRatio,
                       Qt.TransformationMode.SmoothTransformation)
    out = small.scaled(w, h, Qt.AspectRatioMode.IgnoreAspectRatio,
                       Qt.TransformationMode.FastTransformation)
    out.setDevicePixelRatio(1.0)
    return out


class RedactShape(Shape):
    def __init__(self, p1, p2):
        self.p1, self.p2 = p1, p2

    def draw(self, p):
        p.setPen(PS.NoPen); p.setBrush(QBrush(QColor(0,0,0,255)))
        p.drawRect(_norm(self.p1, self.p2))

    def move(self, dx, dy):
        self.p1 = QPointF(self.p1.x()+dx, self.p1.y()+dy)
        self.p2 = QPointF(self.p2.x()+dx, self.p2.y()+dy)

    def bounding_rect(self): return _norm(self.p1, self.p2)


class EraserShape(Shape):
    """Freehand eraser — clears pixels using CompositionMode_Clear."""

    def hit(self, pt, tolerance=6.0):
        return False          # invisible: nothing to select or erase
    def __init__(self, width: int):
        self.pts:  list[QPointF] = []
        self.width = width

    def draw(self, p: QPainter):
        if len(self.pts) < 2:
            return
        p.setRenderHint(RHint.Antialiasing)
        p.setCompositionMode(CM.CompositionMode_Clear)
        p.setPen(QPen(Qt.GlobalColor.transparent, self.width,
                      PS.SolidLine, Cap.RoundCap, Join.RoundJoin))
        for i in range(1, len(self.pts)):
            p.drawLine(self.pts[i - 1], self.pts[i])
        p.setCompositionMode(CM.CompositionMode_SourceOver)

    def move(self, dx, dy):
        self.pts = [QPointF(pt.x() + dx, pt.y() + dy) for pt in self.pts]

    def bounding_rect(self):
        if not self.pts:
            return QRectF()
        xs = [pt.x() for pt in self.pts]
        ys = [pt.y() for pt in self.pts]
        m = self.width / 2
        return QRectF(min(xs) - m, min(ys) - m,
                      max(xs) - min(xs) + self.width,
                      max(ys) - min(ys) + self.width)


# ── Pressed keys (presenter effect) ───────────────────────────────────────────
# Polled with GetAsyncKeyState rather than hooked: nothing runs inside
# Windows' keyboard path (no typing lag anywhere, nothing for antivirus to
# flag), and it only runs while the effect is on.

_VK_NAMES = {0x08: "Backspace", 0x09: "Tab", 0x0D: "Enter", 0x1B: "Esc",
             0x20: "Space", 0x21: "PgUp", 0x22: "PgDn", 0x23: "End",
             0x24: "Home", 0x25: "←", 0x26: "↑", 0x27: "→", 0x28: "↓",
             0x2C: "PrtSc", 0x2D: "Ins", 0x2E: "Del"}
_VK_SPECIAL = {0x08, 0x09, 0x0D, 0x1B, 0x21, 0x22, 0x23, 0x24, 0x25, 0x26,
               0x27, 0x28, 0x2C, 0x2D, 0x2E} | set(range(0x70, 0x88))   # + F1-F24
_VK_WATCH = sorted(_VK_SPECIAL | {0x20} | set(range(0x30, 0x3A)) | set(range(0x41, 0x5B))
                   | set(range(0xBA, 0xC1)) | set(range(0xDB, 0xE0)))


def _vk_label(vk: int) -> str:
    if vk in _VK_NAMES:
        return _VK_NAMES[vk]
    if 0x70 <= vk <= 0x87:
        return f"F{vk - 0x6F}"
    if 0x30 <= vk <= 0x39 or 0x41 <= vk <= 0x5A:
        return chr(vk)
    try:
        import ctypes
        ch = ctypes.windll.user32.MapVirtualKeyW(vk, 2) & 0xFFFF   # VK → char
        return chr(ch).upper() if ch else f"#{vk}"
    except Exception:
        return f"#{vk}"


def keys_pressed(down: set, key_state=None) -> str:
    """The shortcut just pressed ("Ctrl + Shift + S", "Enter"), or "".
    `down` carries the keys already held between calls (updated here);
    `key_state(vk) -> bool` is GetAsyncKeyState, injectable for tests.
    Plain typing — letters, digits, space, with or without Shift — is
    never reported."""
    if key_state is None:
        if not IS_WIN:
            return ""
        import ctypes
        get = ctypes.windll.user32.GetAsyncKeyState
        key_state = lambda vk: bool(get(vk) & 0x8000)
    ctrl, alt = key_state(0x11), key_state(0x12)
    win = key_state(0x5B) or key_state(0x5C)
    shift = key_state(0x10)
    fresh = None
    for vk in _VK_WATCH:
        if key_state(vk):
            if vk not in down:
                down.add(vk)
                fresh = vk
        else:
            down.discard(vk)
    if fresh is None:
        return ""
    if not (ctrl or alt or win) and fresh not in _VK_SPECIAL:
        return ""                                   # typing, not a shortcut
    parts = [n for on, n in ((ctrl, "Ctrl"), (win, "Win"), (alt, "Alt"),
                             (shift, "Shift")) if on]
    return " + ".join(parts + [_vk_label(fresh)])


class HintSwitch(QObject):
    """Settings → General → "Show hints": swallows hover tooltips app-wide
    while it is off."""

    def __init__(self, settings):
        super().__init__()
        self._settings = settings

    def eventFilter(self, obj, event):
        if event.type() != QEvent.Type.ToolTip:
            return False
        if not self._settings.get("show_hints"):
            return True
        # Qt parents a tooltip to the hovered widget, so it inherits that
        # widget's style sheet — and the dock's buttons are all
        # "background:transparent", which Windows paints as a black box.
        # Parent it to the top-level window instead and style it here.
        if isinstance(obj, QWidget) and obj.toolTip() and not obj.isWindow():
            top = obj.window()
            sheet = (f"QToolTip{{background:{DLG_SURFACE};color:{DLG_INK};"
                     f"border:1px solid {DLG_MUTED};padding:5px 7px;font-size:12px;}}")
            # App level: on Windows Qt gives a tooltip no parent at all, so
            # this is the only style sheet that reaches it there. A tooltip
            # with no opaque background of its own comes out black.
            app = QApplication.instance()
            own = app.styleSheet()
            if own != sheet and (not own or own.startswith("QToolTip{")):
                app.setStyleSheet(sheet)
            QToolTip.showText(event.globalPos(), obj.toolTip(), top,
                              QRect(obj.mapTo(top, QPoint(0, 0)), obj.size()))
            return True
        return False


# ── Canvas ─────────────────────────────────────────────────────────────────────
def _global_desktop_rect() -> QRect:
    rect = QRect()
    for scr in QApplication.screens():
        rect = rect.united(scr.geometry())
    return rect


def _blur_region(raw: QPixmap, padded: QRect, target: QRect, radius: int) -> QPixmap:
    """Blur `raw` (a grab of `padded`) and return just the `target` part of it,
    fully opaque.

    The padding is the point. A blur spreads every pixel `radius` wide, and at
    the edge of the grab there is nothing to spread in from — Qt fills it with
    transparency, so the outer band of a blur box used to be only half
    covered and whatever it was hiding stayed readable there. Blurring a
    larger area and cropping keeps real, blurred content all the way to the
    edge; the opaque base underneath catches whatever the padding couldn't
    (a box drawn against the edge of the desktop).
    """
    blurred = _blur_pixmap(raw, radius)
    sx = blurred.width() / max(1, padded.width())
    sy = blurred.height() / max(1, padded.height())
    crop = QRect(round((target.x() - padded.x()) * sx),
                 round((target.y() - padded.y()) * sy),
                 max(1, round(target.width() * sx)),
                 max(1, round(target.height() * sy)))
    part = blurred.copy(crop)
    out = QPixmap(part.size())
    out.fill(QColor(128, 128, 128))
    p = QPainter(out)
    p.drawPixmap(0, 0, part)
    p.end()
    return out


def _snap(shape) -> dict:
    """A shape's state, copied — for undoing a reshape or restyle."""
    out = {}
    for k, v in shape.__dict__.items():
        if k.startswith("_outline"):
            continue
        if isinstance(v, QPointF):
            out[k] = QPointF(v)
        elif k == "pts":
            out[k] = [QPointF(pt) for pt in v]
        else:
            out[k] = v
    return out


def _restore(shape, state: dict):
    for k, v in state.items():
        if isinstance(v, QPointF):
            v = QPointF(v)
        elif k == "pts":
            v = [QPointF(pt) for pt in v]
        setattr(shape, k, v)


def _clone(shape):
    """An independent copy of a shape (pixmaps shared — they never change)."""
    import copy
    twin = copy.copy(shape)
    _restore(twin, _snap(shape))
    for k in [k for k in twin.__dict__ if k.startswith("_outline")]:
        delattr(twin, k)
    return twin


# ── saving marks to a file and opening them again (Ctrl+S / Ctrl+O) ──────────
MARKS_FILTER = "Screen Annotator marks (*.samarks)"
_MARK_TYPES = {c.__name__: c for c in (
    PenShape, LineShape, ArrowShape, RectShape, CircleShape, RulerShape,
    TextShape, CalloutShape, StepShape, StampShape, HighlightShape,
    BlurShape, PixelShape, RedactShape, EraserShape)}


def marks_to_json(shapes) -> dict:
    """Every mark with its attributes. Blur and pixelate keep the picture of
    what was underneath (PNG), so they still hide it when reopened."""
    import base64
    from PySide6.QtCore import QBuffer, QIODevice

    def enc(v):
        if isinstance(v, QPointF):
            return {"pt": [v.x(), v.y()]}
        if isinstance(v, (QPixmap, QImage)):
            buf = QBuffer()
            buf.open(QIODevice.OpenModeFlag.WriteOnly)
            v.save(buf, "PNG")
            return {"png": base64.b64encode(bytes(buf.data())).decode("ascii"),
                    "dpr": v.devicePixelRatio()}
        if isinstance(v, list):
            return [enc(x) for x in v]
        if v is None or isinstance(v, (str, int, float, bool)):
            return v
        raise TypeError(type(v).__name__)

    out = []
    for sh in shapes:
        name = type(sh).__name__
        if name not in _MARK_TYPES:
            continue
        d = {"type": name}
        for k, v in sh.__dict__.items():
            if k.startswith("_") or k in ("fades", "born"):   # fading: not kept
                continue
            try:
                d[k] = enc(v)
            except TypeError:
                continue
        out.append(d)
    return {"app": "Screen Annotator Pro", "format": 1, "marks": out}


def marks_from_json(data: dict) -> list:
    import base64

    def dec(v):
        if isinstance(v, dict):
            if "pt" in v:
                return QPointF(float(v["pt"][0]), float(v["pt"][1]))
            if "png" in v:
                pm = QPixmap()
                pm.loadFromData(base64.b64decode(v["png"]), "PNG")
                pm.setDevicePixelRatio(float(v.get("dpr", 1.0)))
                return pm
            return None
        if isinstance(v, list):
            return [dec(x) for x in v]
        return v

    if not isinstance(data, dict) or data.get("app") != "Screen Annotator Pro":
        raise ValueError("not a Screen Annotator marks file")
    shapes = []
    for d in data.get("marks", []):
        cls = _MARK_TYPES.get(d.get("type"))
        if cls is None:
            continue
        sh = cls.__new__(cls)
        for k, v in d.items():
            if k != "type" and not k.startswith("_"):
                setattr(sh, k, dec(v))
        shapes.append(sh)
    return shapes


LINE_SHAPES = ("LineShape", "ArrowShape", "RulerShape")
BOX_SHAPES = ("RectShape", "CircleShape", "HighlightShape", "RedactShape",
              "BlurShape", "PixelShape")


class Canvas(QWidget):
    # Anything that changes which marks exist: add, undo, redo, clear, delete.
    shapes_changed = Signal()
    # The Select tool's selection changed (the dock shows its style).
    selection_changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(WAtt.WA_TransparentForMouseEvents, False)
        self.setAttribute(WAtt.WA_NoSystemBackground, True)
        self.setAttribute(WAtt.WA_OpaquePaintEvent, False)
        # Enable mouse tracking so laser pointer works without clicking
        self.setMouseTracking(True)

        self.tool       = "pen"
        self.pen_color  = "#FF3B3B"
        self.pen_width  = 4
        self.pen_alpha  = 255   # 0-255; baked into colour when shapes are created
        self.font_size  = 20
        self.text_box   = False       # Text tool: False, True (plate), "bubble"
        self.shape_fill = "none"      # Rectangle/Circle fill
        self.arrow_heads = 1
        self.stamp_kind = "check"
        self.eraser_mode = "shapes"   # "shapes": touch a mark to remove it
                                      # "pixels": rub out part of one
        self.pixel_size = 14          # Pixelate cell, logical px

        self._shapes:      list[Shape] = []
        # Every change is an action, so Clear, Delete and moving a shape undo
        # like drawing one does: ("add", s) · ("clear", [shapes]) ·
        # ("delete", s, index) · ("delete_many", [(s, index), …]) ·
        # ("move", s, dx, dy) · ("edit", s, old_text, new_text)
        self._undo:        list[tuple] = []
        self._redo:        list[tuple] = []
        self._selection:   list[Shape] = []
        self._handle: str | None = None         # handle being dragged
        self._handle_anchor = QPointF()
        self._handle_before: dict | None = None
        self._band: QRectF | None = None        # rubber-band selection
        self._clip: list[Shape] = []
        self._paste_offset = 0
        self._last_restyle = 0.0
        self._drag_last    = QPointF()
        self._move_from    = QPointF()

        self._drawing      = False
        self._start        = QPointF()
        self._cur          = QPointF()
        self._pen_shape:   PenShape | None = None
        self._eraser_shape = None   # filled when tool == "eraser"

        # Offscreen layers the marks are painted into when an eraser stroke
        # exists — keyed by (w, h, dpr), see paint_marks().
        self._layers: dict[tuple, QImage] = {}

        # Laser pointer — tracks mouse position, never commits to _shapes
        self._laser_pos: QPointF | None = None
        # Object eraser: where its ring is, and what one drag has removed
        self._eraser_pos: QPointF | None = None
        self._erased: list[tuple] = []
        # Text being typed on the canvas, and the label it is editing (if any)
        self._editor: "InlineTextEditor | None" = None
        self._editing: TextShape | None = None

        # Fading ink: marks drawn while it is on disappear by themselves
        self.fade_ink = False
        self._fade_timer = QTimer(self)
        self._fade_timer.setInterval(50)
        self._fade_timer.timeout.connect(self._fade_tick)

        # Whiteboard / blackboard: its own pages of marks; the desktop's marks
        # wait aside until you leave the board.
        self.board: str | None = None           # None | "white" | "black"
        self.board_rect = QRectF()
        self._desktop_space: tuple | None = None
        self._pages: list[tuple] = []
        self._page = 0

        # Presenter effects — they follow the real cursor, so they work in
        # click-through mode too, and they are part of what gets recorded.
        self.spotlight = False
        self.halo = False
        self.ripples = False
        self.spot_radius = 140
        self.keys = False
        self._keys_down: set[int] = set()
        self._key_text = ""
        self._key_time = 0.0
        self._fx_pos: QPointF | None = None
        self._ripple_list: list[tuple] = []     # (pos, started)
        self._button_down = False
        self._fx_timer = QTimer(self)
        self._fx_timer.setInterval(16)
        self._fx_timer.timeout.connect(self._fx_tick)

        # Zoom: a still of one screen, magnified around the cursor
        self.zoom_pix: QPixmap | None = None
        self.zoom_rect = QRectF()
        self.zoom_factor = 2.0
        self._zoom_cursor = QPointF()

    def has_marks(self) -> bool:
        return bool(self._shapes)

    # ── selection ──────────────────────────────────────────────────────────
    @property
    def _selected(self):
        return self._selection[0] if self._selection else None

    @_selected.setter
    def _selected(self, shape):
        self._set_selection([shape] if shape is not None else [])

    def _set_selection(self, shapes: list):
        shapes = [sh for sh in shapes if sh is not None]
        if shapes != self._selection:
            self._selection = shapes
            self.update()
            self.selection_changed.emit()

    def select_all(self):
        self._set_selection(list(self._shapes))

    def _handles(self, sh) -> dict:
        name = type(sh).__name__
        if name == "ArrowShape":
            return {"p1": sh.p1, "p2": sh.p2, "mid": sh.mid_point()}
        if name in LINE_SHAPES:
            return {"p1": sh.p1, "p2": sh.p2}
        if name == "TextShape" and sh.box == "bubble":
            return {"tail": sh.tail_point()}
        if name in BOX_SHAPES:
            r = _norm(sh.p1, sh.p2)
            return {"tl": r.topLeft(), "tr": r.topRight(),
                    "bl": r.bottomLeft(), "br": r.bottomRight()}
        return {}

    def _handle_at(self, pos: QPointF) -> str | None:
        if len(self._selection) != 1:
            return None
        for name, pt in self._handles(self._selection[0]).items():
            if abs(pt.x() - pos.x()) <= 8 and abs(pt.y() - pos.y()) <= 8:
                return name
        return None

    def _selection_area(self) -> QRectF:
        area = QRectF()
        for sh in self._selection:
            m = 40 + getattr(sh, "width", 0)
            area = area.united(sh.bounding_rect().adjusted(-m, -m, m, m))
        return area

    def move_selection(self, dx: float, dy: float, record: bool = True):
        if not self._selection or not (dx or dy):
            return
        before = self._selection_area()
        for sh in self._selection:
            sh.move(dx, dy)
        self._update_area(before, self._selection_area())
        if record:
            self._record(("move_many", list(self._selection), dx, dy))

    def restyle_selected(self, *, color: str | None = None, alpha: int | None = None,
                         width: int | None = None, size: int | None = None,
                         fill: str | None = None, heads: int | None = None,
                         box=None, kind: str | None = None) -> bool:
        """Apply the dock's colour / opacity / stroke / size to the selection.
        A slider dragged across many values is one undo step."""
        changes = []
        for sh in self._selection:
            if isinstance(sh, (BlurShape, PixelShape, RedactShape, EraserShape)):
                continue
            before = _snap(sh)
            if color is not None and hasattr(sh, "color"):
                c = QColor(color)
                c.setAlpha(QColor(sh.color).alpha())
                sh.color = c.name(QColor.NameFormat.HexArgb)
            if alpha is not None and hasattr(sh, "color"):
                c = QColor(sh.color)
                c.setAlpha(alpha)
                sh.color = c.name(QColor.NameFormat.HexArgb)
            if width is not None and hasattr(sh, "width"):
                sh.width = width
            if size is not None:
                if isinstance(sh, TextShape):
                    sh.size = size
                elif isinstance(sh, (CalloutShape, StepShape)):
                    sh.r = _marker_radius(size)
                elif isinstance(sh, StampShape):
                    sh.r = _stamp_radius(size)
            if fill is not None and isinstance(sh, (RectShape, CircleShape)):
                sh.fill = fill
            if heads is not None and isinstance(sh, ArrowShape):
                sh.heads = heads
            if box is not None and isinstance(sh, TextShape):
                sh.box = box
            if kind is not None and isinstance(sh, StampShape):
                sh.kind = kind
            after = _snap(sh)
            if after != before:
                changes.append((sh, before, after))
        if not changes:
            return False
        now = time.monotonic()
        last = self._undo[-1] if self._undo else None
        if (last is not None and last[0] == "states" and now - self._last_restyle < 1.0
                and [c[0] for c in last[1]] == [c[0] for c in changes]):
            merged = [(sh, old[1], new[2]) for old, new, sh in
                      zip(last[1], changes, [c[0] for c in changes])]
            self._undo[-1] = ("states", merged)
            self._redo.clear()
            self._changed()
        else:
            self._record(("states", changes))
        self._last_restyle = now
        return True

    def copy_selection(self) -> int:
        self._clip = [_clone(sh) for sh in self._selection]
        self._paste_offset = 0
        return len(self._clip)

    def paste(self) -> int:
        if not self._clip:
            return 0
        self._paste_offset += 20
        pasted = [_clone(sh) for sh in self._clip]
        for sh in pasted:
            sh.move(self._paste_offset, self._paste_offset)
        self._shapes.extend(pasted)
        self._record(("add_many", pasted))
        self._set_selection(pasted)
        return len(pasted)

    def duplicate(self) -> int:
        if not self._selection:
            return 0
        self.copy_selection()
        return self.paste()

    def add_marks(self, shapes: list) -> int:
        """Marks from a saved file, added on top of what's there — one undo
        step takes them all away again."""
        if not shapes:
            return 0
        self.finish_editing()
        self._shapes.extend(shapes)
        self._record(("add_many", list(shapes)))
        self._set_selection([])
        self.update()
        return len(shapes)

    def _eraser_radius(self) -> float:
        if self.eraser_mode == "pixels":
            return max(self.pen_width * 4, 20) / 2
        return max(self.pen_width * 2, 10)

    def wheelEvent(self, e):
        if self.zoom_pix is not None:
            k = 1.25 if e.angleDelta().y() > 0 else 1 / 1.25
            self.zoom_factor = max(self.ZOOM_MIN, min(self.ZOOM_MAX, self.zoom_factor * k))
            self.update(self.loupe_rect().adjusted(-4, -4, 4, 4).toAlignedRect())
            return
        if self.spotlight:                      # the wheel sizes the spotlight
            step = 15 if e.angleDelta().y() > 0 else -15
            self.spot_radius = max(60, min(400, self.spot_radius + step))
            self.update()
            return
        super().wheelEvent(e)

    def mousePressEvent(self, e):
        if self.zoom_pix is not None:           # zoomed: no drawing
            if e.button() == MB.RightButton:
                self.stop_zoom()
            return
        if e.button() != MB.LeftButton: return
        pos = e.position()
        # A click anywhere finishes the text being typed (the canvas never
        # takes focus, so the editor would not notice on its own).
        was_editing = self._editor is not None
        self.finish_editing()
        if was_editing and self.tool == "text":
            return                      # that click was "done", not "new text"
        self._start = self._cur = pos
        self._drawing = True

        if self.tool == "laser":
            self._laser_pos = pos
            self.update(); return

        if self.tool == "select":
            shift = bool(e.modifiers() & Qt.KeyboardModifier.ShiftModifier)
            handle = self._handle_at(pos)
            if handle is not None:              # reshape the selected mark
                sh = self._selection[0]
                self._handle = handle
                self._handle_before = _snap(sh)
                if handle in ("tl", "tr", "bl", "br"):
                    r = _norm(sh.p1, sh.p2)
                    self._handle_anchor = {"tl": r.bottomRight(), "tr": r.bottomLeft(),
                                           "bl": r.topRight(), "br": r.topLeft()}[handle]
                return
            hit = next((sh for sh in reversed(self._shapes) if sh.hit(pos, 6)), None)
            if hit is not None:
                if shift:
                    sel = list(self._selection)
                    sel.remove(hit) if hit in sel else sel.append(hit)
                    self._set_selection(sel)
                elif hit not in self._selection:
                    self._set_selection([hit])
                self._drag_last = self._move_from = pos
            else:                               # empty spot: rubber band
                if not shift:
                    self._set_selection([])
                self._band = QRectF(pos, pos)
            self.update(); return

        if self.tool == "pen":
            self._pen_shape = PenShape(_with_alpha(self.pen_color, self.pen_alpha), self.pen_width)
            self._pen_shape.pts.append(pos); return

        if self.tool == "eraser":
            if self.eraser_mode == "shapes":
                self._erased = []
                self._erase_at(pos)
            else:
                self._eraser_shape = EraserShape(max(self.pen_width * 4, 20))
                self._eraser_shape.pts.append(pos)
            return

        if self.tool in POINT_TOOLS:
            self._place_point(pos)
            self._drawing = False; return

    # ── repainting only what changed ───────────────────────────────────────
    # Every mouse move used to repaint the whole overlay — every monitor, every
    # mark — 24-35 ms a frame on two 4K screens with a few dozen marks, a CPU
    # core pinned while the laser moved. Repainting just the area that changed
    # is ~2 ms however large the desktop is.
    def _update_area(self, *rects: QRectF, margin: float = 4):
        area = QRectF()
        for r in rects:
            if r is not None and not r.isNull():
                area = area.united(r)
        if not area.isNull():
            self.update(area.adjusted(-margin, -margin, margin, margin).toAlignedRect())

    @staticmethod
    def _ring(pos: QPointF | None, r: float) -> QRectF:
        if pos is None:
            return QRectF()
        return QRectF(pos.x() - r, pos.y() - r, 2 * r, 2 * r)

    def _preview_area(self) -> QRectF:
        """Where the drag preview (or the snip rectangle) is drawn now."""
        if not self._drawing:
            return QRectF()
        if self.tool == "ocr":
            return _norm(self._start, self._cur).adjusted(-3, -3, 3, 3)
        preview = self._make_drag(self._start, self._cur) \
            if self.tool in DRAG_TOOLS else None
        if preview is None:
            return QRectF()
        # Arrowheads, stroke width and the ruler's label reach past the ends.
        m = self.pen_width * 4 + 40
        return preview.bounding_rect().adjusted(-m, -m, m, m)

    def mouseMoveEvent(self, e):
        pos = e.position()

        if self.zoom_pix is not None:           # the magnifier follows the cursor
            old = self.loupe_rect()
            self._zoom_cursor = pos
            self.update(old.united(self.loupe_rect()).adjusted(-4, -4, 4, 4).toAlignedRect())
            return

        # Laser tracks freely — no button held needed
        if self.tool == "laser":
            old, self._laser_pos = self._laser_pos, pos
            self._update_area(self._ring(old, 24), self._ring(pos, 24))
            return

        if self.tool == "eraser":           # the eraser's ring follows too
            r = self._eraser_radius() + 3
            old, self._eraser_pos = self._eraser_pos, pos
            if e.buttons() & MB.LeftButton and self.eraser_mode == "shapes":
                self._erase_at(pos)         # repaints everything if it took any
            self._update_area(self._ring(old, r), self._ring(pos, r))

        if not (e.buttons() & MB.LeftButton): return
        before = self._preview_area()
        last = self._cur
        self._cur = pos

        if self.tool == "select" and self._handle is not None:
            sh = self._selection[0]
            before = self._selection_area()
            if self._handle in ("p1", "p2"):
                setattr(sh, self._handle, QPointF(pos))
            elif self._handle == "mid":
                sh.set_mid(pos)
            elif self._handle == "tail":
                sh.tail = QPointF(pos.x() - sh.pos.x(), pos.y() - sh.pos.y())
            else:
                sh.p1, sh.p2 = QPointF(self._handle_anchor), QPointF(pos)
            self._update_area(before, self._selection_area())
            return
        if self.tool == "select" and self._band is not None:
            old = QRectF(self._band)
            self._band = QRectF(self._band.topLeft(), pos)
            self._update_area(old.normalized(), self._band.normalized(), margin=4)
            return
        if self.tool == "select" and self._selection:
            self.move_selection(pos.x() - self._drag_last.x(),
                                pos.y() - self._drag_last.y(), record=False)
            self._drag_last = pos
            return

        if self.tool == "pen" and self._pen_shape:
            self._pen_shape.pts.append(pos)
            w = self._pen_shape.width
            self._update_area(QRectF(last, pos).normalized(), margin=w + 2)
            return

        if self.tool == "eraser" and self._eraser_shape:
            self._eraser_shape.pts.append(pos)
            w = self._eraser_shape.width
            self._update_area(QRectF(last, pos).normalized(), margin=w + 2)
            return

        if self.tool in DRAG_TOOLS or self.tool == "ocr":
            self._update_area(before, self._preview_area())

    def mouseReleaseEvent(self, e):
        if e.button() != MB.LeftButton or not self._drawing: return
        self._drawing = False
        pos = e.position(); self._cur = pos

        if self.tool == "laser":
            return  # laser never commits shapes

        if self.tool == "select":
            if self._handle is not None:
                sh = self._selection[0]
                if _snap(sh) != self._handle_before:
                    self._record(("states", [(sh, self._handle_before, _snap(sh))]))
                self._handle = None
            elif self._band is not None:
                band, self._band = self._band.normalized(), None
                picked = [sh for sh in self._shapes
                          if not isinstance(sh, EraserShape)
                          and band.intersects(sh.bounding_rect())]
                if e.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                    picked = self._selection + [sh for sh in picked
                                                if sh not in self._selection]
                self._set_selection(picked)
                self.update()
            elif self._selection:
                dx = pos.x() - self._move_from.x()
                dy = pos.y() - self._move_from.y()
                if dx or dy:
                    self._record(("move_many", list(self._selection), dx, dy))
            return

        if self.tool == "pen" and self._pen_shape:
            if len(self._pen_shape.pts) > 1:
                self._commit(self._pen_shape)
            self._pen_shape = None
            self.update(); return

        if self.tool == "eraser":
            if self._erased:
                erased, self._erased = self._erased, []
                self._record(("delete_many", erased))
            elif self._eraser_shape:
                if len(self._eraser_shape.pts) > 1:
                    self._commit(self._eraser_shape)
                self._eraser_shape = None
            self.update(); return

        if self.tool == "ocr":
            rect = _norm(self._start, pos)
            if rect.width() > 10 and rect.height() > 10:
                r = rect.toRect()
                # r.x()/r.y() are canvas-local — the overlay covers the union of
                # every monitor and can sit at a negative global position (e.g.
                # a screen placed above/left of the primary), so a canvas-local
                # point is not a global desktop coordinate. Resolve it via
                # mapToGlobal before the overlay hides, or the grab below reads
                # from the wrong monitor (or nothing) on non-trivial layouts.
                global_top_left = self.mapToGlobal(r.topLeft())
                overlay = self.window()
                overlay.hide()                # get overlay out of the way before grab
                QApplication.processEvents()  # flush so overlay is fully hidden
                pixmap = QApplication.primaryScreen().grabWindow(
                    0, global_top_left.x(), global_top_left.y(),
                    max(r.width(), 1), max(r.height(), 1)
                )
                dlg = OcrResultDialog(pixmap)
                dlg.exec()
                if hasattr(overlay, "sync_window"):
                    overlay.sync_window()
                else:
                    overlay.show()
                overlay.raise_()
                overlay.activateWindow()
            else:
                self.update()
            return

        if self.tool in DRAG_TOOLS:
            if self.tool == "blur":
                rect = _norm(self._start, pos)
                if rect.width() > 3 and rect.height() > 3:
                    blurred = self._blurred_behind(
                        rect, int(getattr(self, "blur_radius", 18)))
                    self._commit(BlurShape(self._start, pos, blurred))
            elif self.tool == "pixel":
                rect = _norm(self._start, pos)
                if rect.width() > 3 and rect.height() > 3:
                    self._commit(PixelShape(self._start, pos,
                                            self._pixelated_behind(rect)))
            else:
                s = self._make_drag(self._start, pos)
                if s: self._commit(s)

    def _place_point(self, pos: QPointF):
        col = self._tool_color()
        t = self.tool
        if t == "text":
            # On an existing label: edit it. Anywhere else: new text, typed
            # right there — not in a dialog on another monitor.
            existing = next((s for s in reversed(self._shapes)
                             if isinstance(s, TextShape) and s.hit(pos, 2)), None)
            self.begin_text(pos, existing)
        elif t == "callout":
            self._commit(CalloutShape(pos, self._next_number(CalloutShape), col,
                                      self.font_size))
        elif t == "steps":
            self._commit(StepShape(pos, self._next_number(StepShape), col,
                                   self.font_size))
        elif t == "stamp":
            self._commit(StampShape(pos, self.stamp_kind, col, self.font_size))

    # ── text typed on the canvas ───────────────────────────────────────────
    def begin_text(self, pos: QPointF, shape: "TextShape | None" = None):
        self.finish_editing()
        if shape is not None:
            self._editing = shape
            ed = InlineTextEditor(self, shape.pos, shape.color, shape.size,
                                  shape.box, shape.text)
        else:
            ed = InlineTextEditor(self, pos,
                                  self._tool_color(),
                                  self.font_size, self.text_box)
        ed.committed.connect(self._text_committed)
        ed.cancelled.connect(self._text_cancelled)
        self._editor = ed
        self.update()

    def finish_editing(self):
        """Commit whatever is being typed (clicking elsewhere, switching tool
        or mode all count as done)."""
        if self._editor is not None:
            self._editor.commit()

    def _close_editor(self):
        ed, self._editor = self._editor, None
        self._editing = None
        if ed is not None:
            ed.hide()
            ed.deleteLater()
        self.update()

    def _text_committed(self, text: str):
        ed, shape = self._editor, self._editing
        if ed is None:
            return
        pos, color, size, box = ed.origin, ed.color, ed.size, ed.box
        self._close_editor()
        if shape is not None:
            if not text.strip():
                self._selected = shape
                self.delete_selected()
            elif text != shape.text:
                old = shape.text
                shape.text = text
                self._record(("edit", shape, old, text))
        elif text.strip():
            self._commit(TextShape(pos, text, color, size, box))

    def _text_cancelled(self):
        self._close_editor()

    # ── object eraser ──────────────────────────────────────────────────────
    def _erase_at(self, pos: QPointF):
        """Remove every visible mark the eraser's ring touches. One drag is
        one undo step, however many marks it took."""
        r = self._eraser_radius()
        for i in range(len(self._shapes) - 1, -1, -1):
            shape = self._shapes[i]
            if shape.hit(pos, r):
                del self._shapes[i]
                self._erased.append((shape, i))
        if self._erased:
            if self._selected is not None and self._selected not in self._shapes:
                self._selected = None
            self.update()

    # Tools whose dock row has no opacity slider — they used to inherit
    # whatever opacity another tool was left at, with no way to see why.
    OPAQUE_TOOLS = ("callout", "steps", "stamp", "ruler")

    def _tool_color(self) -> str:
        alpha = 255 if self.tool in self.OPAQUE_TOOLS else self.pen_alpha
        return _with_alpha(self.pen_color, alpha)

    def _next_number(self, cls) -> int:
        """One past the highest number on screen — worked out from the marks
        themselves, so undoing a 3 makes the next one a 3 again, not a 4."""
        return max((s.number for s in self._shapes if isinstance(s, cls)),
                   default=0) + 1

    def _make_drag(self, p1: QPointF, p2: QPointF) -> Shape | None:
        if abs(p2.x()-p1.x()) < 3 and abs(p2.y()-p1.y()) < 3: return None
        col   = self._tool_color()
        t     = self.tool
        shift = bool(QApplication.queryKeyboardModifiers()
                     & Qt.KeyboardModifier.ShiftModifier)
        # Shift-lock: snap lines/arrows/ruler to 45°, rect/circle to square
        if shift:
            if t in {"line", "arrow", "ruler"}:
                p2 = _snap_45(p1, p2)
            elif t in {"rect", "circle"}:
                size = max(abs(p2.x()-p1.x()), abs(p2.y()-p1.y()))
                p2   = QPointF(p1.x() + math.copysign(size, p2.x()-p1.x()),
                                p1.y() + math.copysign(size, p2.y()-p1.y()))
        if t == "line":      return LineShape(p1, p2, col, self.pen_width)
        if t == "arrow":     return ArrowShape(p1, p2, col, self.pen_width, self.arrow_heads)
        if t == "rect":      return RectShape(p1, p2, col, self.pen_width, self.shape_fill)
        if t == "circle":    return CircleShape(p1, p2, col, self.pen_width, self.shape_fill)
        if t == "ruler":
            scr = self.screen()
            scale = scr.devicePixelRatio() if scr is not None else 1.0
            return RulerShape(p1, p2, col, self.pen_width, scale)
        if t == "highlight": return HighlightShape(p1, p2, col)
        if t == "blur":      return BlurShape(p1, p2)
        if t == "pixel":
            s = PixelShape(p1, p2)
            s.size = self.pixel_size
            return s
        if t == "redact":    return RedactShape(p1, p2)
        return None

    def capture_annotated(self, region: QRect | None = None,
                          marks: bool = True) -> QPixmap:
        """Grab the desktop behind the overlay and composite all shapes on top
        — the whole desktop, or just `region` (global coordinates). `marks`
        False leaves them out (the overlay is put away, so they aren't on
        screen either)."""
        overlay = self.window()
        with _ChromeHidden(overlay):
            sr = QApplication.primaryScreen().virtualGeometry()
            bg = QApplication.primaryScreen().grabWindow(
                0, sr.x(), sr.y(), sr.width(), sr.height()
            )

        # grabWindow returns device pixels, and at 125 %/150 % Qt tags the
        # pixmap with that ratio — which QPainter then applies by itself. Our
        # shapes are in logical pixels, so the scale must be applied exactly
        # once: drop the tag and scale explicitly, whatever grabWindow did.
        ratio = bg.devicePixelRatio()
        bg.setDevicePixelRatio(1.0)
        p = QPainter(bg)
        p.setRenderHint(RHint.Antialiasing)
        if ratio != 1.0:
            p.scale(ratio, ratio)
        if marks:
            self.paint_marks(p, bg.width(), bg.height(), selection=False, live=False)
        p.end()
        if region is not None and region.isValid():
            crop = QRect(round((region.x() - sr.x()) * ratio),
                         round((region.y() - sr.y()) * ratio),
                         round(region.width() * ratio),
                         round(region.height() * ratio)).intersected(bg.rect())
            if crop.isValid():
                bg = bg.copy(crop)
        return bg

    # ── history ────────────────────────────────────────────────────────────
    def _commit(self, shape: Shape):
        """Add a shape (undoable)."""
        # Redactions never fade — a blur that disappears would show what it hid.
        if self.fade_ink and not isinstance(
                shape, (BlurShape, PixelShape, RedactShape, EraserShape)):
            shape.fades = True
            shape.born = time.monotonic()
            self._fade_timer.start()
        self._shapes.append(shape)
        self._record(("add", shape))

    # ── fading ink ─────────────────────────────────────────────────────────
    FADE_AFTER = 3.0        # seconds fully visible
    FADE_FOR = 1.0          # seconds to fade out

    def _fade_factor(self, shape, now: float) -> float:
        if not getattr(shape, "fades", False):
            return 1.0
        age = now - shape.born
        if age <= self.FADE_AFTER:
            return 1.0
        return max(0.0, 1.0 - (age - self.FADE_AFTER) / self.FADE_FOR)

    def _fade_tick(self):
        now = time.monotonic()
        fading = [sh for sh in self._shapes if getattr(sh, "fades", False)]
        if not fading:
            self._fade_timer.stop()
            return
        gone = [sh for sh in fading if self._fade_factor(sh, now) <= 0]
        for sh in fading:
            if now - sh.born > self.FADE_AFTER:
                self._update_area(sh.bounding_rect(), margin=40)
        if gone:
            for sh in gone:
                self._shapes.remove(sh)
            # A mark that faded away is not something Ctrl+Z should step over.
            self._undo = [a for a in self._undo if not (a[0] == "add" and a[1] in gone)]
            self._redo = [a for a in self._redo if not (a[0] == "add" and a[1] in gone)]
            self._changed()

    # ── whiteboard / blackboard ────────────────────────────────────────────
    def _space(self) -> tuple:
        return (self._shapes, self._undo, self._redo)

    def _load_space(self, space: tuple):
        self._shapes, self._undo, self._redo = space
        self._selected = None

    def set_board(self, kind: str | None, rect: QRectF | None = None):
        """Show a whiteboard or blackboard over `rect` (one screen), or go back
        to the desktop. Boards have their own pages; switching colour keeps
        them."""
        self.finish_editing()
        if kind == self.board:
            return
        if self.board is None:                   # entering: park the desktop
            self._desktop_space = self._space()
            if not self._pages:
                self._pages = [([], [], [])]
            self._load_space(self._pages[self._page])
        elif kind is None:                        # leaving: put it back
            self._pages[self._page] = self._space()
            self._load_space(self._desktop_space or ([], [], []))
            self._desktop_space = None
        if rect is not None:
            self.board_rect = rect
        self.board = kind
        self._changed()

    def board_page(self, delta: int) -> int:
        """Next / previous page (a new blank one past the last). 1-based."""
        if self.board is None:
            return 0
        self.finish_editing()
        self._pages[self._page] = self._space()
        self._page = max(0, self._page + delta)
        if self._page >= len(self._pages):
            self._pages.append(([], [], []))
            self._page = len(self._pages) - 1
        self._load_space(self._pages[self._page])
        self._changed()
        return self._page + 1

    def _paint_board(self, p: QPainter):
        if self.board is not None and not self.board_rect.isNull():
            p.fillRect(self.board_rect, QColor("#FAFAF7" if self.board == "white"
                                               else "#1E2023"))

    # ── zoom ───────────────────────────────────────────────────────────────
    ZOOM_MIN, ZOOM_MAX = 2.0, 16.0
    LOUPE_R = 110                       # the magnifier's radius

    def start_zoom(self, pix: QPixmap, rect: QRectF, cursor: QPointF):
        self.finish_editing()
        self.zoom_pix, self.zoom_rect = pix, rect
        self.zoom_factor = 4.0
        self._zoom_cursor = cursor
        self.update()

    def stop_zoom(self):
        if self.zoom_pix is None:
            return
        self.zoom_pix = None
        self.update()
        win = self.window()
        if hasattr(win, "sync_window"):
            win.sync_window()

    def loupe_rect(self) -> QRectF:
        """Where the magnifier sits: below-right of the cursor, flipped at the
        edges of the screen it was opened on (Greenshot's feel)."""
        if self.zoom_pix is None:
            return QRectF()
        r, c, d, gap = self.zoom_rect, self._zoom_cursor, 2.0 * self.LOUPE_R, 28
        x = c.x() + gap if c.x() + gap + d <= r.right() else c.x() - gap - d
        y = c.y() + gap if c.y() + gap + d <= r.bottom() else c.y() - gap - d
        return QRectF(x, y, d, d)

    def zoom_source(self) -> QRectF:
        """The part of the still shown in the magnifier, in its pixels —
        centred on the point under the cursor."""
        r = self.zoom_rect
        scale = self.zoom_pix.width() / max(1.0, r.width()) if self.zoom_pix else 1.0
        side = 2.0 * self.LOUPE_R / self.zoom_factor * scale
        cx = (self._zoom_cursor.x() - r.x()) * scale
        cy = (self._zoom_cursor.y() - r.y()) * scale
        return QRectF(cx - side / 2, cy - side / 2, side, side)

    def _paint_zoom(self, p: QPainter) -> bool:
        return False                    # the magnifier paints over the marks

    def _paint_loupe(self, p: QPainter):
        if self.zoom_pix is None:
            return
        box = self.loupe_rect()
        c, f = box.center(), self.zoom_factor
        ring = QPainterPath()
        ring.addEllipse(box)
        p.save()
        p.setRenderHint(RHint.Antialiasing)
        p.setClipPath(ring)
        p.fillRect(box, QColor("#1C1C1E"))
        # Real pixels, not a blur, once they're big enough to count.
        p.setRenderHint(RHint.SmoothPixmapTransform, f < 4)
        p.drawPixmap(box, self.zoom_pix, self.zoom_source())
        # Crosshair through the pixel under the cursor, open in the middle.
        half = max(f / 2, 3.0)
        p.setPen(QPen(QColor(255, 59, 59, 210), 1))
        p.drawLine(QPointF(box.left(), c.y()), QPointF(c.x() - half, c.y()))
        p.drawLine(QPointF(c.x() + half, c.y()), QPointF(box.right(), c.y()))
        p.drawLine(QPointF(c.x(), box.top()), QPointF(c.x(), c.y() - half))
        p.drawLine(QPointF(c.x(), c.y() + half), QPointF(c.x(), box.bottom()))
        p.setPen(QPen(QColor(255, 59, 59, 240), 1.5))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRect(QRectF(c.x() - half, c.y() - half, 2 * half, 2 * half))
        label = f"{f:.1f}".rstrip("0").rstrip(".") + "×"
        p.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
        tag = QRectF(c.x() - 24, box.bottom() - 30, 48, 20)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(0, 0, 0, 150))
        p.drawRoundedRect(tag, 10, 10)
        p.setPen(QColor("#FFFFFF"))
        p.drawText(tag, int(AA.AlignCenter), label)
        p.setClipping(False)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(QColor(0, 0, 0, 120), 5))
        p.drawEllipse(box)
        p.setPen(QPen(QColor("#FFFFFF"), 3))
        p.drawEllipse(box)
        p.restore()

    # ── presenter effects ──────────────────────────────────────────────────
    def effects_on(self) -> bool:
        return self.spotlight or self.halo or self.ripples or self.keys

    # ── pressed keys ───────────────────────────────────────────────────────
    KEY_SHOW_SECONDS = 1.6

    def _key_area(self) -> QRectF:
        scr = QApplication.screenAt(QCursor.pos()) or QApplication.primaryScreen()
        g = scr.geometry()
        tl = QPointF(self.mapFromGlobal(g.topLeft()))
        return QRectF(tl.x() + g.width() / 2 - 300, tl.y() + g.height() - 190, 600, 90)

    def _poll_keys(self):
        """Shortcuts and special keys only — never plain typing, so a
        password typed during a recording never shows up in it."""
        combo = keys_pressed(self._keys_down)
        if combo:
            self._key_text = combo
            self._key_time = time.monotonic()
            self._update_area(self._key_area())
        elif self._key_text and time.monotonic() - self._key_time > self.KEY_SHOW_SECONDS:
            self._key_text = ""
            self._update_area(self._key_area())

    def _paint_keys(self, p: QPainter):
        if not self._key_text:
            return
        age = time.monotonic() - self._key_time
        fade = 1.0 if age < self.KEY_SHOW_SECONDS - 0.4 else \
            max(0.0, (self.KEY_SHOW_SECONDS - age) / 0.4)
        area = self._key_area()
        font = QFont("Segoe UI", 22, QFont.Weight.Bold)
        fm = QFontMetricsF(font)
        w = fm.horizontalAdvance(self._key_text) + 44
        box = QRectF(area.center().x() - w / 2, area.top() + 14, w, 58)
        p.save()
        p.setOpacity(fade)
        p.setPen(PS.NoPen)
        p.setBrush(QColor(20, 20, 22, 215))
        p.drawRoundedRect(box, 12, 12)
        p.setPen(QColor("#FFFFFF"))
        p.setFont(font)
        p.drawText(box, int(AA.AlignCenter), self._key_text)
        p.restore()

    def set_effect(self, name: str, on: bool):
        setattr(self, name, on)
        if self.effects_on() or self._ripple_list:
            self._fx_timer.start()
        else:
            self._fx_timer.stop()
            self._fx_pos = None
        self.update()

    def _fx_area(self, pos: QPointF | None) -> QRectF:
        if pos is None:
            return QRectF()
        r = 30.0
        if self.spotlight:
            r = max(r, self.spot_radius + 6)
        return self._ring(pos, r)

    def _left_button_down(self) -> bool:
        if IS_WIN:
            try:
                import ctypes
                return bool(ctypes.windll.user32.GetAsyncKeyState(0x01) & 0x8000)
            except Exception:
                return False
        return bool(QApplication.mouseButtons() & MB.LeftButton)

    def _fx_tick(self):
        pos = QPointF(self.mapFromGlobal(QCursor.pos()))
        if pos != self._fx_pos:
            old, self._fx_pos = self._fx_pos, pos
            self._update_area(self._fx_area(old), self._fx_area(pos))
        now = time.monotonic()
        if self.keys:
            self._poll_keys()
        if self.ripples:
            # Polled, not hooked: works while clicks go to the app underneath.
            down = self._left_button_down()
            if down and not self._button_down:
                self._ripple_list.append((pos, now))
            self._button_down = down
        for rpos, _t in self._ripple_list:
            self._update_area(self._ring(rpos, 48))
        self._ripple_list = [(rp, t) for rp, t in self._ripple_list if now - t < 0.5]
        if not self.effects_on() and not self._ripple_list:
            self._fx_timer.stop()

    def _paint_effects(self, p: QPainter):
        if self.keys:
            self._paint_keys(p)
        pos = self._fx_pos
        if pos is not None and self.spotlight:
            path = QPainterPath()
            path.setFillRule(Qt.FillRule.OddEvenFill)
            path.addRect(QRectF(self.rect()))
            path.addEllipse(pos, self.spot_radius, self.spot_radius)
            p.fillPath(path, QColor(0, 0, 0, 150))
        if pos is not None and self.halo:
            p.setPen(PS.NoPen)
            p.setBrush(QColor(255, 214, 10, 90))
            p.drawEllipse(pos, 26, 26)
        now = time.monotonic()
        for rpos, t in self._ripple_list:
            k = min(1.0, (now - t) / 0.5)
            p.setBrush(BS.NoBrush)
            p.setPen(QPen(QColor(10, 132, 255, int(220 * (1 - k))), 3))
            p.drawEllipse(rpos, 10 + 34 * k, 10 + 34 * k)

    def _record(self, action: tuple):
        self._undo.append(action)
        self._redo.clear()
        self._changed()

    def _changed(self):
        if any(sh not in self._shapes for sh in self._selection):
            self._set_selection([sh for sh in self._selection if sh in self._shapes])
        self.update()
        self.shapes_changed.emit()

    def undo(self) -> bool:
        if not self._undo:
            return False
        action = self._undo.pop()
        kind, shape = action[0], action[1]
        if kind == "add":
            if shape in self._shapes:
                self._shapes.remove(shape)
        elif kind == "clear":
            self._shapes[:] = shape
        elif kind == "delete":
            self._shapes.insert(min(action[2], len(self._shapes)), shape)
        elif kind == "delete_many":
            for s, i in reversed(shape):
                self._shapes.insert(min(i, len(self._shapes)), s)
        elif kind == "move":
            shape.move(-action[2], -action[3])
        elif kind == "edit":
            shape.text = action[2]
        elif kind == "move_many":
            for sh in shape:
                sh.move(-action[2], -action[3])
        elif kind == "states":
            for sh, before, _after in shape:
                _restore(sh, before)
        elif kind == "add_many":
            for sh in shape:
                if sh in self._shapes:
                    self._shapes.remove(sh)
        self._redo.append(action)
        self._changed()
        return True

    def redo(self) -> bool:
        if not self._redo:
            return False
        action = self._redo.pop()
        kind, shape = action[0], action[1]
        if kind == "add":
            self._shapes.append(shape)
        elif kind == "clear":
            self._shapes.clear()
        elif kind == "delete":
            if shape in self._shapes:
                self._shapes.remove(shape)
        elif kind == "delete_many":
            for s, _i in shape:
                if s in self._shapes:
                    self._shapes.remove(s)
        elif kind == "move":
            shape.move(action[2], action[3])
        elif kind == "edit":
            shape.text = action[3]
        elif kind == "move_many":
            for sh in shape:
                sh.move(action[2], action[3])
        elif kind == "states":
            for sh, _before, after in shape:
                _restore(sh, after)
        elif kind == "add_many":
            self._shapes.extend(shape)
        self._undo.append(action)
        self._changed()
        return True

    def clear(self) -> int:
        """Remove every mark — undoable. Returns how many were removed."""
        if not self._shapes:
            return 0
        before = list(self._shapes)
        self._shapes.clear()
        self._selected = None
        self._record(("clear", before))
        return len(before)

    def undo_clear(self) -> bool:
        """The toast's Undo: only if Clear is still the last thing done, so a
        late click can't undo something drawn since."""
        if self._undo and self._undo[-1][0] == "clear":
            return self.undo()
        return False

    def delete_selected(self) -> bool:
        chosen = [sh for sh in self._selection if sh in self._shapes]
        if not chosen:
            return False
        if len(chosen) == 1:
            s = chosen[0]
            index = self._shapes.index(s)
            self._shapes.remove(s)
            self._set_selection([])
            self._record(("delete", s, index))
            return True
        removed = []
        for i in range(len(self._shapes) - 1, -1, -1):
            if self._shapes[i] in chosen:
                removed.append((self._shapes[i], i))
                del self._shapes[i]
        self._set_selection([])
        self._record(("delete_many", removed))
        return True

    # ── blur ───────────────────────────────────────────────────────────────
    def _blurred_behind(self, rect: QRectF, radius: int) -> QPixmap:
        """The desktop under `rect` (canvas coordinates), blurred edge to edge."""
        target = QRect(self.mapToGlobal(rect.topLeft().toPoint()),
                       rect.size().toSize())
        pad = radius * 2 + 4
        padded = target.adjusted(-pad, -pad, pad, pad)
        desktop = _global_desktop_rect()
        if desktop.isValid():
            padded = padded.intersected(desktop)
        raw = self._grab_behind(padded)
        return _blur_region(raw, padded, target, radius)

    def _pixelated_behind(self, rect: QRectF) -> QPixmap:
        """The desktop under `rect`, as a mosaic of pixel_size cells."""
        target = QRect(self.mapToGlobal(rect.topLeft().toPoint()),
                       rect.size().toSize())
        raw = self._grab_behind(target)
        if raw.isNull() or raw.width() < 1:
            return QPixmap()
        device_cell = max(PixelShape.MIN_CELL, self.pixel_size) \
            * raw.width() / max(1, target.width())
        return _mosaic(raw, round(device_cell))

    def _grab_behind(self, r: QRect) -> QPixmap:
        """Grab the desktop under global rect `r` with the app's own windows
        out of the way. Global, not canvas coordinates: the overlay spans every
        monitor and starts at a negative position when one sits left of or
        above the main screen, so canvas (0, 0) is not desktop (0, 0)."""
        # Same reason as capture_annotated: without hiding the dock, a blur or
        # pixelate region drawn under it would sample the dock itself.
        overlay = self.window()
        with _ChromeHidden(overlay):
            pix = QApplication.primaryScreen().grabWindow(
                0, r.x(), r.y(), max(r.width(), 1), max(r.height(), 1)
            )   # grabWindow with explicit coords works across the virtual desktop
        return pix

    # ── painting ───────────────────────────────────────────────────────────
    def paintEvent(self, e):
        area = e.rect()                 # only this part needs repainting
        p = QPainter(self)
        p.setCompositionMode(CM.CompositionMode_Clear)
        p.fillRect(area, Qt.GlobalColor.transparent)
        p.setCompositionMode(CM.CompositionMode_SourceOver)
        if IS_WIN:
            p.fillRect(area, QColor(0, 0, 0, 1))
        if self._paint_zoom(p):         # the still already has the marks
            self._paint_effects(p)
            p.end()
            return
        self._paint_board(p)
        if not self._has_eraser():
            self.render_annotations(p, area=QRectF(area))
        else:
            # Eraser strokes must only erase marks (see paint_marks), so the
            # marks go into a layer first — one the size of the repainted
            # area, not of the whole desktop.
            dpr = self.devicePixelRatioF()
            layer = QImage(max(1, round(area.width() * dpr)),
                           max(1, round(area.height() * dpr)),
                           QImage.Format.Format_ARGB32_Premultiplied)
            layer.setDevicePixelRatio(dpr)
            layer.fill(0)
            lp = QPainter(layer)
            lp.translate(-area.x(), -area.y())
            self.render_annotations(lp, area=QRectF(area))
            lp.end()
            p.drawImage(area.topLeft(), layer)
        p.end()

    def _has_eraser(self) -> bool:
        return (any(isinstance(s, EraserShape) for s in self._shapes)
                or (self.tool == "eraser" and self._eraser_shape is not None))

    def paint_marks(self, p: QPainter, width_px: int, height_px: int,
                    dpr: float = 1.0, *, selection: bool = True,
                    live: bool = True):
        """render_annotations(), made safe to paint over something.

        An eraser stroke clears pixels. Drawn straight onto a screenshot or a
        video frame it cleared the *desktop* too — a black streak in every
        MP4, a hole in every PNG — and on the overlay itself it wiped out the
        near-invisible fill that makes the window clickable, so clicks fell
        through wherever you had erased. With an eraser present the marks go
        into a layer of their own first; erasing then only ever removes marks.
        `width_px`/`height_px` are the target's size in device pixels.
        """
        if self._paint_zoom(p):
            if live:
                self._paint_effects(p)
            return
        self._paint_board(p)
        if not self._has_eraser():
            self._layers.clear()
            self.render_annotations(p, selection=selection, live=live)
            return
        key = (width_px, height_px, dpr)
        layer = self._layers.get(key)
        if layer is None:
            if len(self._layers) >= 2:          # overlay + one recording size
                self._layers.clear()
            layer = QImage(width_px, height_px,
                           QImage.Format.Format_ARGB32_Premultiplied)
            layer.setDevicePixelRatio(dpr)
            self._layers[key] = layer
        layer.fill(0)
        lp = QPainter(layer)
        lp.setTransform(p.transform())
        self.render_annotations(lp, selection=selection, live=live)
        lp.end()
        p.save()
        p.resetTransform()
        p.drawImage(0, 0, layer)
        p.restore()

    def render_annotations(self, p: QPainter, *, selection: bool = True,
                           live: bool = True, area: QRectF | None = None):
        """Paint every mark onto `p` — committed shapes, the stroke in
        progress, the drag preview, the laser dot.

        The overlay paints itself with this, and the video recorder paints the
        same content onto every captured frame. One code path, so a recording
        can never disagree with what the presenter had on screen. The selection
        outline is the one thing a recording leaves out: it is an editing
        affordance, not an annotation. A still screenshot also leaves out
        everything `live` — the half-drawn stroke and the laser dot.
        """
        p.setRenderHint(RHint.Antialiasing)
        now = time.monotonic()
        for shape in self._shapes:
            if shape is self._editing:          # its editor shows it instead
                continue
            if area is not None and not shape.bounding_rect().adjusted(
                    -60, -60, 60, 60).intersects(area):
                continue                        # nowhere near the repaint
            fade = self._fade_factor(shape, now)
            if fade < 1.0:
                p.save()
                p.setOpacity(fade)
                shape.draw(p)
                p.restore()
            else:
                shape.draw(p)
        self._paint_loupe(p)
        if not live:
            return
        if self.tool == "pen"    and self._pen_shape:    self._pen_shape.draw(p)
        if self.tool == "eraser" and self._eraser_shape: self._eraser_shape.draw(p)
        if self.tool == "eraser" and self._eraser_pos is not None:
            r = self._eraser_radius()
            p.setBrush(QBrush(QColor(255, 255, 255, 40)))
            p.setPen(QPen(QColor(0, 0, 0, 150), 1.5, PS.DashLine))
            p.drawEllipse(self._eraser_pos, r, r)
        if self.tool == "ocr" and self._drawing:
            # Dashed blue selection rectangle while user drags the snip area
            p.setRenderHint(RHint.Antialiasing)
            p.setPen(QPen(QColor("#0A84FF"), 2, PS.DashLine))
            p.setBrush(QBrush(QColor(10, 132, 255, 18)))
            p.drawRect(_norm(self._start, self._cur))
        if self._drawing and self.tool in DRAG_TOOLS:
            preview = self._make_drag(self._start, self._cur)
            if preview: preview.draw(p)
        if selection and self._selection:
            p.setPen(QPen(QColor("#0A84FF"), 1, PS.DashLine))
            p.setBrush(BS.NoBrush)
            for sh in self._selection:
                p.drawRect(sh.bounding_rect().adjusted(-3, -3, 3, 3))
            if len(self._selection) == 1:
                p.setPen(QPen(QColor("#0A84FF"), 1.5))
                p.setBrush(QColor("#FFFFFF"))
                for pt in self._handles(self._selection[0]).values():
                    p.drawRect(QRectF(pt.x() - 4, pt.y() - 4, 8, 8))
        if selection and self._band is not None:
            p.setPen(QPen(QColor("#0A84FF"), 1, PS.DashLine))
            p.setBrush(QColor(10, 132, 255, 25))
            p.drawRect(self._band.normalized())

        self._paint_effects(p)

        # ── Laser pointer ──────────────────────────────────────────────────
        if self.tool == "laser" and self._laser_pos:
            lx, ly = self._laser_pos.x(), self._laser_pos.y()
            # Outer glow rings (largest → smallest)
            for radius, alpha in [(22, 18), (15, 35), (10, 60)]:
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QBrush(QColor(255, 30, 30, alpha)))
                p.drawEllipse(QPointF(lx, ly), radius, radius)
            # Bright white core
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QBrush(QColor(255, 255, 255, 230)))
            p.drawEllipse(QPointF(lx, ly), 4, 4)
            # Hot red ring around core
            p.setPen(QPen(QColor(255, 40, 40, 200), 1.5))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(QPointF(lx, ly), 5, 5)


# ── Slider that doesn't steal scroll-wheel from parent scroll area ────────────
class _Slider(QSlider):
    def wheelEvent(self, e):
        e.ignore()


# ── Dot preview ───────────────────────────────────────────────────────────────
class DotPreview(QWidget):
    def __init__(self):
        super().__init__()
        self.setFixedHeight(22)
        self._size  = 4
        self._color = QColor("#FF3B3B")

    def set_size(self, sz: int, color: QColor):
        self._size = sz; self._color = color; self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(RHint.Antialiasing)
        sz = min(self._size, self.height() - 4)
        cx, cy = self.width() // 2, self.height() // 2
        p.setBrush(QBrush(self._color))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(cx - sz // 2, cy - sz // 2, sz, sz)


class _ChromeHidden:
    """Hide the app's own windows for the duration of a single grab.

    The overlay used to own the dock, so dropping the overlay's opacity took
    the dock with it. The dock is its own window now — the same window that
    the recorder excludes from video — so a screenshot has to hide it
    explicitly or the bar ends up in the picture.

    Opacity rather than hide(): the windows keep their geometry and there is
    no re-layout to flicker through on the way back.
    """

    def __init__(self, overlay):
        self._windows = []
        if overlay is None:
            return
        self._windows.append(overlay)
        toolbar = getattr(overlay, "toolbar", None)
        if toolbar is not None:
            self._windows += [w for w in toolbar.chrome_windows()
                              if w.isVisible()]

    def __enter__(self):
        for w in self._windows:
            w.setWindowOpacity(0.0)
        QApplication.processEvents()
        return self

    def __exit__(self, *_):
        for w in self._windows:
            w.setWindowOpacity(1.0)
        return False


# ── Screenshot result bar ─────────────────────────────────────────────────────
def screenshot_dir(settings=None) -> str:
    """Where Save starts: the folder used last, else Pictures\\Screenshots
    (Windows' own screenshot folder), created if it isn't there yet."""
    chosen = (settings.get("shot_dir") if settings is not None else "") or ""
    if chosen and os.path.isdir(chosen):
        return chosen
    from PySide6.QtCore import QStandardPaths
    pictures = QStandardPaths.writableLocation(
        QStandardPaths.StandardLocation.PicturesLocation) or os.path.expanduser("~")
    folder = os.path.join(pictures, "Screenshots")
    try:
        os.makedirs(folder, exist_ok=True)
    except OSError:
        return pictures
    return folder


class ScreenshotBar(QWidget):
    """Floating panel shown after capture: Copy | Save PNG | Discard

    Its own top-level window, and that is not cosmetic: as a child of the
    overlay it inherited the overlay's click-through state, so in that mode
    every button here was unclickable and there was no way to save the shot.
    Result panels are chrome — they have to stay usable in both modes.
    """
    def __init__(self, pixmap: QPixmap, parent: QWidget):
        super().__init__(None,
                         WType.FramelessWindowHint |
                         WType.WindowStaysOnTopHint |
                         WType.Tool)
        self.setAttribute(WAtt.WA_NoSystemBackground, True)
        self._pixmap = pixmap
        self._overlay = parent
        self._build()
        self.adjustSize()
        # Centered on display 1 in global coordinates — the overlay spans every
        # monitor's combined bounding box, so centering on *that* can land in a
        # gap or a seam on a non-trivial layout.
        _center_on_display1(self)
        self.show()
        self.raise_()
        self.activateWindow()

    def _succeeded(self):
        """The shot went somewhere — a moment the review prompt may follow."""
        settings = getattr(self._overlay, "settings", None)
        if settings is not None:
            note_success(settings)
            ask_for_review_soon(self._overlay)

    def _build(self):
        lo = QVBoxLayout(self)
        lo.setContentsMargins(16, 16, 16, 16)
        lo.setSpacing(10)

        thumb = QLabel()
        scaled = self._pixmap.scaled(480, 270, Qt.AspectRatioMode.KeepAspectRatio,
                                     Qt.TransformationMode.SmoothTransformation)
        thumb.setPixmap(scaled)
        thumb.setAlignment(AA.AlignCenter)
        lo.addWidget(thumb)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)
        for label, fn, primary in [
            ("Copy",     self._copy,  False),
            ("Save PNG", self._save,  True),
            ("Discard",  self.close,  False),
        ]:
            btn = QPushButton(label)
            btn.setFixedHeight(34)
            btn.setCursor(Cursor.PointingHandCursor)
            btn.setStyleSheet(_dlg_button_style(primary))
            btn.clicked.connect(fn)
            btn_row.addWidget(btn)
        lo.addLayout(btn_row)

    def keyPressEvent(self, e):
        if e.key() == Key.Key_Escape:
            self.close()
        else:
            super().keyPressEvent(e)

    def _copy(self):
        QApplication.clipboard().setPixmap(self._pixmap)
        self.close()
        self._succeeded()

    def _save(self):
        from datetime import datetime
        settings = getattr(self._overlay, "settings", None)
        folder = screenshot_dir(settings)
        name = f"Screenshot {datetime.now().strftime('%Y-%m-%d %H%M%S')}.png"
        path, _ = QFileDialog.getSaveFileName(self, "Save Screenshot",
                                              os.path.join(folder, name),
                                              "PNG Images (*.png)")
        saved = False
        if path:
            if not path.lower().endswith(".png"):
                path += ".png"
            saved = self._pixmap.save(path, "PNG")
            if saved and settings is not None:
                settings.set("shot_dir", os.path.dirname(path))  # next time: here
                settings.save()
        self.close()
        if saved:
            self._succeeded()

    def paintEvent(self, _):
        _dlg_frame_paint(self)


# ── Store review prompt ───────────────────────────────────────────────────────
#
# ms-windows-store://review/?ProductId=… opens the Store on this app's review
# dialog. No SDK needed — it is where the Store's own "rate this" button goes.
#
# The rules below exist because a badly-timed review prompt is the fastest way
# to make someone resent an app they otherwise liked:
#   · only right after the app just did its job — a screenshot copied or
#     saved, a recording saved — never on a timer, so never in the middle of
#     a presentation (the old eight-hours-of-use timer could fire mid-talk,
#     and almost nobody ever reached it: 0 ratings in four months)
#   · and only once it has done so a few times, on more than one day
#   · never while recording, never over another dialog
#   · "later" means a fortnight of silence, not the next launch
#   · "don't ask again" is permanent, and it is on the dialog, not buried
#   · Esc means later, never never — dismissing must not be punishing

STORE_ID           = "9NS87MQB29C7"
STORE_REVIEW_URI   = f"ms-windows-store://review/?ProductId={STORE_ID}"
STORE_WEB_URL      = f"https://apps.microsoft.com/detail/{STORE_ID}"
REVIEW_MIN_SUCCESSES = 3        # screenshots / recordings that worked
REVIEW_MIN_DAYS    = 2          # …spread over at least this many days
REVIEW_SNOOZE_DAYS = 14
REVIEW_DELAY_MS    = 1500       # after the result panel closes
USAGE_TICK_SECONDS = 60         # how often usage time is counted up


def note_success(settings: SettingsManager, today: str | None = None):
    """Count one moment the app did what it is for."""
    settings.set("review_successes", int(settings.get("review_successes") or 0) + 1)
    day = today or date.today().isoformat()
    days = [d for d in (settings.get("review_days") or []) if d != day]
    settings.set("review_days", (days + [day])[-30:])
    settings.save()


def review_due(settings: SettingsManager, now: float | None = None) -> bool:
    """Has the app earned asking, and is the answer not already given?"""
    if settings.get("review_state") in ("never", "done"):
        return False
    if (now or time.time()) < float(settings.get("review_after") or 0):
        return False
    return (int(settings.get("review_successes") or 0) >= REVIEW_MIN_SUCCESSES
            and len(settings.get("review_days") or []) >= REVIEW_MIN_DAYS)


def ask_for_review_soon(overlay):
    """Give the moment a beat to settle, then maybe ask."""
    settings = getattr(overlay, "settings", None)
    if settings is None or not review_due(settings):
        return
    QTimer.singleShot(REVIEW_DELAY_MS,
                      lambda: maybe_ask_for_review(settings, overlay))


def open_store_review(owner: QWidget | None = None) -> bool:
    """The Store's own rating dialog over our window where the package allows
    it, otherwise the Store app's review page, otherwise the web listing."""
    if IS_WIN and owner is not None:
        try:
            if platform_win.request_store_rating(int(owner.winId()),
                                                 lambda _rated: None):
                return True
        except Exception:
            pass
    if IS_WIN and QDesktopServices.openUrl(QUrl(STORE_REVIEW_URI)):
        return True
    return QDesktopServices.openUrl(QUrl(STORE_WEB_URL))


class UsageClock(QObject):
    """Counts how long the app has genuinely been in use.

    Not process uptime: this is a tray app that can sit there all day
    untouched, and eight hours of sitting in the tray is not eight hours of
    use. A minute counts when the overlay is on screen or a recording is
    running — otherwise the app is only resident, not being used.
    """

    def __init__(self, overlay, settings: SettingsManager):
        super().__init__(overlay)
        self._overlay = overlay
        self._settings = settings
        self._unsaved = 0
        self._timer = QTimer(self)
        self._timer.setInterval(USAGE_TICK_SECONDS * 1000)
        self._timer.timeout.connect(self._tick)
        self._timer.start()

    @property
    def seconds(self) -> float:
        return float(self._settings.get("usage_seconds") or 0)

    def _in_use(self) -> bool:
        return (getattr(self._overlay, "wanted", self._overlay.isVisible())
                or self._overlay.recording.active)

    def _tick(self):
        if not self._in_use():
            return
        self._settings.set("usage_seconds", self.seconds + USAGE_TICK_SECONDS)
        self._unsaved += 1
        if self._unsaved >= 5:              # don't touch the disk every minute
            self._settings.save()
            self._unsaved = 0

    def flush(self):
        if self._unsaved:
            self._settings.save()
            self._unsaved = 0


def maybe_ask_for_review(settings: SettingsManager, overlay):
    """Ask for a Store review — but only if this is a fair moment to ask."""
    if not IS_WIN:
        return                                    # no Store to review on
    if not review_due(settings):
        return
    # Not while they are in the middle of something: recording, or another
    # dialog or menu already open.
    if overlay.recording.active:
        return
    if QApplication.activeModalWidget() is not None \
            or QApplication.activePopupWidget() is not None:
        return
    settings.save()
    ReviewPrompt(settings, overlay).exec()


class ReviewPrompt(QDialog):
    """Asked once the app has earned it: rate, remind me later, or never."""

    def __init__(self, settings: SettingsManager, parent=None):
        super().__init__(parent,
                         WType.FramelessWindowHint | WType.WindowStaysOnTopHint)
        self.setAttribute(WAtt.WA_TranslucentBackground)
        self.setWindowTitle("Enjoying Screen Annotator Pro?")
        self._settings = settings

        lo = QVBoxLayout(self)
        lo.setContentsMargins(24, 20, 24, 20)
        lo.setSpacing(12)

        title = QLabel("Enjoying Screen Annotator Pro?")
        tf = QFont(DLG_FONT, 13)
        tf.setBold(True)
        title.setFont(tf)
        title.setStyleSheet(f"color:{DLG_INK};background:transparent;")
        lo.addWidget(title)
        lo.addWidget(_dlg_sep())

        body = QLabel(
            "Glad that worked. If Screen Annotator Pro is useful to you, a "
            "rating on the Microsoft Store is the biggest help there is — it "
            "is most of what decides whether other people ever find it.\n\n"
            "It takes about thirty seconds, and this won't ask again "
            "afterwards.")
        body.setWordWrap(True)
        body.setStyleSheet(
            f"color:{DLG_INK};font-family:'{DLG_FONT}';font-size:12px;"
            "background:transparent;")
        lo.addWidget(body)

        row = QHBoxLayout()
        row.setSpacing(8)
        for label, fn, primary in [("Don't ask again", self._never, False),
                                   ("Maybe later",     self._later, False),
                                   ("Write a review",  self._rate,  True)]:
            b = QPushButton(label)
            b.setFixedHeight(34)
            b.setCursor(Cursor.PointingHandCursor)
            b.setStyleSheet(_dlg_button_style(primary))
            b.clicked.connect(fn)
            row.addWidget(b)
        lo.addLayout(row)

        self.setFixedWidth(430)
        self.adjustSize()
        _center_on_display1(self)

    def _rate(self):
        self._finish("done")
        # Owned by the dock rather than this dialog, which is closing — the
        # dock is the one window of ours that is reliably on screen.
        toolbar = getattr(self.parent(), "toolbar", None)
        open_store_review(toolbar if toolbar is not None else self.parent())

    def _later(self):
        self._settings.set("review_after",
                           time.time() + REVIEW_SNOOZE_DAYS * 86400)
        self._finish("later")

    def _never(self):
        self._finish("never")

    def _finish(self, state: str):
        self._settings.set("review_state", state)
        self._settings.save()
        self.accept()

    def keyPressEvent(self, e):
        if e.key() == Key.Key_Escape:
            self._later()
        else:
            super().keyPressEvent(e)

    def paintEvent(self, _):
        _dlg_frame_paint(self)


# ── Screen recording ──────────────────────────────────────────────────────────

def _reveal_in_file_manager(path: str):
    """Open the containing folder with the file selected, where the OS can."""
    folder = os.path.dirname(path)
    try:
        if IS_WIN:
            subprocess.Popen(["explorer", "/select,", os.path.normpath(path)])
            return
        if IS_MAC:
            subprocess.Popen(["open", "-R", path])
            return
        subprocess.Popen(["xdg-open", folder])
    except Exception:
        QDesktopServices.openUrl(QUrl.fromLocalFile(folder))


class NoticeDialog(QDialog):
    """One-message dialog in the app's flat style, with an optional link."""

    def __init__(self, title: str, message: str, parent=None,
                 link: tuple[str, str] | None = None):
        super().__init__(parent,
                         WType.FramelessWindowHint | WType.WindowStaysOnTopHint)
        self.setAttribute(WAtt.WA_TranslucentBackground)
        self.setWindowTitle(title)

        lo = QVBoxLayout(self)
        lo.setContentsMargins(24, 20, 24, 20)
        lo.setSpacing(12)

        t = QLabel(title)
        tf = QFont(DLG_FONT, 13)
        tf.setBold(True)
        t.setFont(tf)
        t.setStyleSheet(f"color:{DLG_INK};background:transparent;")
        lo.addWidget(t)
        lo.addWidget(_dlg_sep())

        body = QLabel(message)
        body.setWordWrap(True)
        body.setStyleSheet(
            f"color:{DLG_INK};font-family:'{DLG_FONT}';font-size:12px;"
            "background:transparent;")
        lo.addWidget(body)

        row = QHBoxLayout()
        row.setSpacing(8)
        if link:
            label, url = link
            lb = QPushButton(label)
            lb.setFixedHeight(34)
            lb.setCursor(Cursor.PointingHandCursor)
            lb.setStyleSheet(_dlg_button_style(primary=False))
            lb.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(url)))
            row.addWidget(lb)
        row.addStretch()
        ok = QPushButton("OK")
        ok.setFixedHeight(34)
        ok.setCursor(Cursor.PointingHandCursor)
        ok.setStyleSheet(_dlg_button_style(primary=True))
        ok.clicked.connect(self.accept)
        row.addWidget(ok)
        lo.addLayout(row)

        self.setFixedWidth(460)
        self.adjustSize()
        _center_on_display1(self)

    def paintEvent(self, _):
        _dlg_frame_paint(self)


class ConfirmDialog(QDialog):
    """Two-button question in the app's flat style. exec() == Accepted means go."""

    def __init__(self, title: str, message: str, confirm: str, parent=None,
                 cancel: str = "Cancel"):
        super().__init__(parent,
                         WType.FramelessWindowHint | WType.WindowStaysOnTopHint)
        self.setAttribute(WAtt.WA_TranslucentBackground)
        self.setWindowTitle(title)

        lo = QVBoxLayout(self)
        lo.setContentsMargins(24, 20, 24, 20)
        lo.setSpacing(12)

        t = QLabel(title)
        tf = QFont(DLG_FONT, 13)
        tf.setBold(True)
        t.setFont(tf)
        t.setStyleSheet(f"color:{DLG_INK};background:transparent;")
        lo.addWidget(t)
        lo.addWidget(_dlg_sep())

        body = QLabel(message)
        body.setWordWrap(True)
        body.setStyleSheet(
            f"color:{DLG_INK};font-family:'{DLG_FONT}';font-size:12px;"
            "background:transparent;")
        lo.addWidget(body)

        row = QHBoxLayout()
        row.setSpacing(8)
        row.addStretch()
        for label, slot, primary in ((cancel, self.reject, False),
                                     (confirm, self.accept, True)):
            b = QPushButton(label)
            b.setFixedHeight(34)
            b.setCursor(Cursor.PointingHandCursor)
            b.setStyleSheet(_dlg_button_style(primary))
            b.clicked.connect(slot)
            row.addWidget(b)
        lo.addLayout(row)

        self.setFixedWidth(430)
        self.adjustSize()
        _center_on_display1(self)

    def paintEvent(self, _):
        _dlg_frame_paint(self)


class Toast(QWidget):
    """A one-line note that fades out by itself, with an optional action —
    "Cleared 12 marks · Undo". Chrome, like the dock: its own top-level
    window, and kept out of screen captures on Windows."""

    SHOW_MS = 5000

    def __init__(self):
        super().__init__(None,
                         WType.FramelessWindowHint |
                         WType.WindowStaysOnTopHint |
                         WType.Tool)
        self.setAttribute(WAtt.WA_ShowWithoutActivating, True)
        self.setAttribute(WAtt.WA_TranslucentBackground, True)
        lo = QHBoxLayout(self)
        lo.setContentsMargins(16, 8, 8, 8)
        lo.setSpacing(12)
        self._label = QLabel()
        self._label.setStyleSheet(
            f"color:{DLG_INK};font-family:'{DLG_FONT}';font-size:12px;"
            "background:transparent;")
        lo.addWidget(self._label)
        self._action = QPushButton()
        self._action.setFixedHeight(28)
        self._action.setCursor(Cursor.PointingHandCursor)
        self._action.clicked.connect(self._run_action)
        lo.addWidget(self._action)
        self._callback = None
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.hide)

    def show_message(self, text: str, action: str = "", callback=None,
                     anchor: QWidget | None = None):
        self._label.setText(text)
        self._label.setStyleSheet(
            f"color:{DLG_INK};font-family:'{DLG_FONT}';font-size:12px;"
            "background:transparent;")
        self._action.setStyleSheet(_dlg_button_style(primary=True))
        self._action.setText(action)
        self._action.setVisible(bool(action))
        self._callback = callback
        self.adjustSize()
        if anchor is not None and anchor.isVisible():
            g = anchor.frameGeometry()
            self.move(g.center().x() - self.width() // 2,
                      g.top() - self.height() - 10)
        else:
            geo = QApplication.primaryScreen().availableGeometry()
            self.move(geo.center().x() - self.width() // 2,
                      geo.bottom() - self.height() - 120)
        self.show()
        self.raise_()
        exclude_from_capture(self, True)
        self._timer.start(self.SHOW_MS)

    def _run_action(self):
        callback, self._callback = self._callback, None
        self.hide()
        if callback:
            callback()

    def paintEvent(self, _):
        _dlg_frame_paint(self)


class WelcomeTips(QWidget):
    """Three steps, once, on a first run: how to draw, how to get your
    clicks back without losing the marks, and where capture and record are.
    The app starts in click-through, so without this a new user can see a
    dock and nothing happening when they click the screen."""

    def __init__(self, overlay):
        super().__init__(None,
                         WType.FramelessWindowHint |
                         WType.WindowStaysOnTopHint |
                         WType.Tool)
        self.setAttribute(WAtt.WA_TranslucentBackground, True)
        self._overlay = overlay
        settings = overlay.settings
        toggle = shortcut_label(settings, "hotkey")
        rec = shortcut_label(settings, "rec_hotkey")
        shot = shortcut_label(settings, "screenshot_hotkey")
        self._pages = [
            ("Draw on anything",
             f"Press {toggle}, or click \u201cDrawing OFF\u201d on the dock, "
             "and draw right on top of whatever is on screen. Every tool has "
             "a one-letter key — P pen, A arrow, T text."),
            ("Keep working — the marks stay",
             f"Press Esc (or {toggle} again): your marks stay on screen and "
             "your mouse goes back to the app underneath. Ctrl+Z undoes "
             "anything, even Clear all."),
            ("Capture and record",
             f"Capture ({shot}) takes a screenshot of an area with your marks; "
             f"Record ({rec}) makes an MP4 with them. Everything else is in "
             "Settings."),
        ]
        self._page = 0
        lo = QVBoxLayout(self)
        lo.setContentsMargins(20, 16, 20, 16)
        lo.setSpacing(8)
        self._step = QLabel()
        self._step.setStyleSheet(f"color:{DLG_MUTED};font-size:10px;")
        self._title = QLabel()
        tf = QFont(DLG_FONT, 12)
        tf.setBold(True)
        self._title.setFont(tf)
        self._title.setStyleSheet(f"color:{DLG_INK};")
        self._body = QLabel()
        self._body.setWordWrap(True)
        self._body.setStyleSheet(f"color:{DLG_INK};font-size:12px;")
        for w in (self._step, self._title, self._body):
            lo.addWidget(w)
        row = QHBoxLayout()
        skip = QPushButton("Skip")
        skip.setFixedHeight(30)
        skip.setCursor(Cursor.PointingHandCursor)
        skip.setStyleSheet(_dlg_button_style(primary=False))
        skip.clicked.connect(self._done)
        self._next = QPushButton()
        self._next.setFixedHeight(30)
        self._next.setCursor(Cursor.PointingHandCursor)
        self._next.setStyleSheet(_dlg_button_style(primary=True))
        self._next.clicked.connect(self._advance)
        row.addWidget(skip)
        row.addStretch()
        row.addWidget(self._next)
        lo.addLayout(row)
        self.setFixedWidth(400)
        self._show_page()

    def _show_page(self):
        title, body = self._pages[self._page]
        self._step.setText(f"{self._page + 1} of {len(self._pages)}")
        self._title.setText(title)
        self._body.setText(body)
        self._next.setText("Done" if self._page == len(self._pages) - 1 else "Next")
        self.adjustSize()
        self._place()

    def _place(self):
        dock = getattr(self._overlay, "toolbar", None)
        if dock is not None and dock.isVisible():
            g = dock.frameGeometry()
            self.move(g.center().x() - self.width() // 2,
                      g.top() - self.height() - 12)
        else:
            _center_on_display1(self)

    def start(self):
        self.show()
        self.raise_()
        exclude_from_capture(self, True)

    def _advance(self):
        if self._page < len(self._pages) - 1:
            self._page += 1
            self._show_page()
        else:
            self._done()

    def _done(self):
        settings = self._overlay.settings
        settings.set("tips_done", True)
        settings.save()
        self.close()

    def paintEvent(self, _):
        _dlg_frame_paint(self)


def maybe_show_welcome(overlay) -> "WelcomeTips | None":
    """First run on this PC, not started at sign-in, not seen before."""
    settings = overlay.settings
    if not getattr(settings, "is_new", False) or settings.get("tips_done") \
            or not overlay.wanted:
        return None
    tips = WelcomeTips(overlay)
    tips.start()
    return tips


class RegionSelector(QWidget):
    """Full-desktop dimmer: drag out the rectangle to record.

    Its own top-level window rather than a mode on the canvas — the canvas is
    busy being a drawing surface, and a recording area is chosen before the
    recorder (and its capture exclusions) exist.
    """

    chosen = Signal(object)          # QRect in global coords, or None

    RECORD_HINT = "Drag the area you want to record   ·   Esc to cancel"
    SHOT_HINT = ("Drag an area to capture   ·   click for this whole screen"
                 "   ·   Enter for all screens   ·   Esc to cancel")

    def __init__(self, hint: str = RECORD_HINT, click_for_screen: bool = False):
        self._hint = hint
        self._click_for_screen = click_for_screen
        super().__init__(None,
                         WType.FramelessWindowHint |
                         WType.WindowStaysOnTopHint |
                         WType.Tool)
        self.setAttribute(WAtt.WA_TranslucentBackground)
        self.setCursor(_cross_cursor())
        self._origin = virtual_desktop_rect().topLeft()
        self.setGeometry(virtual_desktop_rect())
        self._start = None
        self._cur   = None
        self._done  = False

    def choose(self):
        self.show()
        self.raise_()
        self.activateWindow()
        self.setFocus()

    # ── input ─────────────────────────────────────────────────────────────────
    def mousePressEvent(self, e):
        if e.button() == MB.LeftButton:
            self._start = e.position().toPoint()
            self._cur   = self._start
            self.update()

    def mouseMoveEvent(self, e):
        if self._start is not None:
            self._cur = e.position().toPoint()
            self.update()

    def mouseReleaseEvent(self, e):
        if self._start is None:
            return
        r = self._local_rect()
        if r.width() < 16 or r.height() < 16:
            if self._click_for_screen:       # a click: the screen it was on
                scr = (QApplication.screenAt(e.globalPosition().toPoint())
                       or QApplication.primaryScreen())
                self._finish(scr.geometry())
                return
            self._start = self._cur = None   # too small to be deliberate
            self.update()
            return
        self._finish(QRect(r.topLeft() + self._origin, r.size()))

    def keyPressEvent(self, e):
        if e.key() == Key.Key_Escape:
            self._finish(None)
        elif self._click_for_screen and e.key() in (Key.Key_Return, Key.Key_Enter):
            self._finish(virtual_desktop_rect())

    def _finish(self, rect):
        if self._done:
            return
        self._done = True
        self.hide()
        self.chosen.emit(rect)
        self.deleteLater()

    def _local_rect(self) -> QRect:
        if self._start is None or self._cur is None:
            return QRect()
        return QRect(self._start, self._cur).normalized()

    # ── paint ─────────────────────────────────────────────────────────────────
    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(RHint.Antialiasing)
        p.fillRect(self.rect(), QColor(0, 0, 0, 120))

        r = self._local_rect()
        if r.isValid() and r.width() > 1:
            p.setCompositionMode(CM.CompositionMode_Clear)
            p.fillRect(r, GC.transparent)
            p.setCompositionMode(CM.CompositionMode_SourceOver)
            p.setPen(QPen(QColor("#FF3B3B"), 2))
            p.setBrush(BS.NoBrush)
            p.drawRect(r)

            size_lbl = f"{r.width()} × {r.height()}"
            f = QFont(DLG_FONT, 10)
            f.setBold(True)
            p.setFont(f)
            tw = QFontMetrics(f).horizontalAdvance(size_lbl) + 16
            box = QRect(r.x(), max(0, r.y() - 26), tw, 22)
            p.fillRect(box, QColor("#FF3B3B"))
            p.setPen(QColor("#FFFFFF"))
            p.drawText(box, AA.AlignCenter, size_lbl)

        hint = self._hint
        f2 = QFont(DLG_FONT, 12)
        f2.setBold(True)
        p.setFont(f2)
        fm = QFontMetrics(f2)
        scr = QApplication.primaryScreen().availableGeometry()
        cx  = scr.center().x() - self._origin.x()
        box = QRect(cx - fm.horizontalAdvance(hint) // 2 - 18,
                    scr.y() - self._origin.y() + 48,
                    fm.horizontalAdvance(hint) + 36, 40)
        p.fillRect(box, QColor(0, 0, 0, 200))
        p.setPen(QColor("#FFFFFF"))
        p.drawText(box, AA.AlignCenter, hint)
        p.end()


class RecordingHUD(QWidget):
    """The only chrome visible while recording: dot, timer, pause, stop.

    A separate top-level window so it survives the overlay being hidden with
    Esc — you must always be able to stop a recording you started.
    """

    def __init__(self, controller: "RecordingController"):
        super().__init__(None,
                         WType.FramelessWindowHint |
                         WType.WindowStaysOnTopHint |
                         WType.Tool)
        self.setAttribute(WAtt.WA_TranslucentBackground)
        self._ctl     = controller
        self._elapsed = 0.0
        self._blink   = True
        self._drag    = None
        self.setFixedSize(238, 46)

        lo = QHBoxLayout(self)
        lo.setContentsMargins(46, 0, 8, 0)
        lo.setSpacing(6)

        self._time = QLabel("00:00")
        tf = QFont(DLG_FONT, 12)
        tf.setBold(True)
        self._time.setFont(tf)
        self._time.setStyleSheet("color:#FFFFFF;background:transparent;")
        lo.addWidget(self._time)
        lo.addStretch()

        self._pause_btn = self._button("Pause", self._toggle_pause)
        self._stop_btn  = self._button("Stop", controller.stop, danger=True)
        lo.addWidget(self._pause_btn)
        lo.addWidget(self._stop_btn)

        self._blinker = QTimer(self)
        self._blinker.setInterval(600)
        self._blinker.timeout.connect(self._flip)
        self._blinker.start()

    def _button(self, text: str, slot, danger: bool = False) -> QPushButton:
        b = QPushButton(text)
        b.setFixedHeight(28)
        b.setCursor(Cursor.PointingHandCursor)
        bg = "#FF3B3B" if danger else "rgba(255,255,255,0.14)"
        hover = "#FF5C5C" if danger else "rgba(255,255,255,0.26)"
        b.setStyleSheet(
            f"QPushButton{{color:#FFFFFF;background:{bg};border:none;"
            f"font-family:'{DLG_FONT}';font-size:11px;font-weight:700;"
            "padding:0 12px;}"
            f"QPushButton:hover{{background:{hover};}}"
            "QPushButton:disabled{color:rgba(255,255,255,0.35);}")
        b.clicked.connect(slot)
        return b

    # ── state ─────────────────────────────────────────────────────────────────
    def place(self):
        scr = QApplication.screenAt(QCursor.pos()) or QApplication.primaryScreen()
        g = scr.availableGeometry()
        self.move(g.right() - self.width() - 24, g.bottom() - self.height() - 24)

    def set_elapsed(self, seconds: float):
        self._elapsed = seconds
        self._time.setText(format_elapsed(seconds))

    def set_paused(self, paused: bool):
        self._pause_btn.setText("Resume" if paused else "Pause")
        self.update()

    def set_finishing(self):
        self._time.setText("Saving…")
        self._pause_btn.setEnabled(False)
        self._stop_btn.setEnabled(False)
        self._blinker.stop()
        self._blink = False
        self.update()

    def allow_pause(self, on: bool):
        self._pause_btn.setEnabled(on)
        self._pause_btn.setToolTip(
            "" if on else "Pause is unavailable while the microphone is recording")

    def _toggle_pause(self):
        self._ctl.pause(not self._ctl.paused)

    def _flip(self):
        if not self._ctl.paused:
            self._blink = not self._blink
            self.update()

    # ── drag anywhere on the panel ────────────────────────────────────────────
    def mousePressEvent(self, e):
        if e.button() == MB.LeftButton:
            self._drag = e.globalPosition().toPoint() - self.pos()

    def mouseMoveEvent(self, e):
        if self._drag is not None:
            self.move(e.globalPosition().toPoint() - self._drag)

    def mouseReleaseEvent(self, _):
        self._drag = None

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(RHint.Antialiasing)
        p.fillRect(self.rect(), QColor(16, 16, 18, 242))
        p.setPen(QPen(QColor("#FF3B3B"), 4))
        p.setBrush(BS.NoBrush)
        p.drawRect(0, 0, self.width(), self.height())

        # Recording dot — hollow while paused, blinking while rolling
        p.setPen(Qt.PenStyle.NoPen)
        if self._ctl.paused:
            p.setPen(QPen(QColor("#FF9F0A"), 2))
            p.setBrush(BS.NoBrush)
        else:
            p.setBrush(QColor("#FF3B3B") if self._blink else QColor(255, 59, 59, 70))
        p.drawEllipse(QPointF(26, self.height() / 2), 7, 7)
        p.end()


class RecordingBar(QWidget):
    """Shown when a recording lands on disk: play, reveal, save elsewhere, bin."""

    def __init__(self, path: str, duration: float, parent: QWidget):
        # Top-level for the same reason as ScreenshotBar: a child of the
        # overlay is unclickable whenever the overlay is letting clicks through.
        super().__init__(None,
                         WType.FramelessWindowHint |
                         WType.WindowStaysOnTopHint |
                         WType.Tool)
        self.setAttribute(WAtt.WA_NoSystemBackground, True)
        self._overlay = parent
        self._path = path
        self._duration = duration
        self._deleted = False
        self._build()
        self.adjustSize()
        _center_on_display1(self)
        self.show()
        self.raise_()
        self.activateWindow()
        settings = getattr(parent, "settings", None)
        if settings is not None:
            note_success(settings)

    def closeEvent(self, e):
        super().closeEvent(e)
        # Done with the recording, and kept it: a fair moment to ask.
        if not self._deleted:
            ask_for_review_soon(self._overlay)

    def _build(self):
        lo = QVBoxLayout(self)
        lo.setContentsMargins(20, 18, 20, 18)
        lo.setSpacing(10)

        title = QLabel("Recording saved")
        tf = QFont(DLG_FONT, 13)
        tf.setBold(True)
        title.setFont(tf)
        title.setStyleSheet(f"color:{DLG_INK};background:transparent;")
        lo.addWidget(title)
        lo.addWidget(_dlg_sep())

        try:
            mb = os.path.getsize(self._path) / (1024 * 1024)
            size = f"{mb:.1f} MB"
        except OSError:
            size = "—"
        meta = QLabel(f"{os.path.basename(self._path)}\n"
                      f"{format_elapsed(self._duration)}   ·   {size}")
        meta.setStyleSheet(
            f"color:{DLG_MUTED};font-family:'{DLG_FONT}';font-size:11px;"
            "background:transparent;")
        lo.addWidget(meta)

        # Two rows: what you probably want to do with it, then housekeeping.
        # GIF gets its own button rather than living behind "Export…" — it is
        # the format people actually reach for after a screen recording, and
        # burying it meant nobody was offered it at all. Delete sits at the
        # far end from Close, where a slip of the mouse can't reach it.
        for buttons in (
            [("Play",           self._play,     True),
             ("Make GIF",       self._make_gif, True),
             ("Export…",        self._export,   False)],
            [("Delete",         self._delete,   False),
             None,
             ("Show in folder", self._reveal,   False),
             ("Save as…",       self._save_as,  False),
             ("Close",          self.close,     False)],
        ):
            row = QHBoxLayout()
            row.setSpacing(8)
            for spec in buttons:
                if spec is None:
                    row.addStretch()
                    continue
                label, fn, primary = spec
                b = QPushButton(label)
                b.setFixedHeight(34)
                b.setCursor(Cursor.PointingHandCursor)
                b.setStyleSheet(_dlg_button_style(primary))
                b.clicked.connect(fn)
                if fn == self._delete:
                    b.setToolTip("Moves the file to the Recycle Bin" if IS_WIN
                                 else "Moves the file to the Trash")
                row.addWidget(b)
            lo.addLayout(row)

    def _play(self):
        QDesktopServices.openUrl(QUrl.fromLocalFile(self._path))
        self.close()

    def keyPressEvent(self, e):
        if e.key() == Key.Key_Escape:
            self.close()
        else:
            super().keyPressEvent(e)

    def _make_gif(self):
        """Straight to a GIF at sensible defaults — no questions asked.

        The dialog opens on GIF with 720 px / 12 fps already chosen, so this is
        one more click, and every other format is still one panel away.
        """
        dlg = ExportDialog(self._path, self._duration, self._overlay)
        dlg.preselect("gif", width=720, fps=12)
        dlg.exec()

    def _export(self):
        ExportDialog(self._path, self._duration, self._overlay).exec()

    def _reveal(self):
        _reveal_in_file_manager(self._path)
        self.close()

    def _save_as(self):
        target, _ = QFileDialog.getSaveFileName(
            self, "Save Recording",
            os.path.join(os.path.expanduser("~"),
                         os.path.basename(self._path)),
            "MP4 Video (*.mp4)")
        if target:
            if not target.lower().endswith(".mp4"):
                target += ".mp4"
            try:
                shutil.move(self._path, target)
            except OSError as e:
                NoticeDialog("Could not move the file", str(e), self).exec()
                return
        self.close()

    def _delete(self):
        """To the Recycle Bin, not gone: one misclick used to cost the take."""
        from PySide6.QtCore import QFile
        ok, _where = QFile.moveToTrash(self._path)
        if not ok and os.path.exists(self._path):
            if not ConfirmDialog(
                    "Delete the recording for good?",
                    "It couldn't be moved to the Recycle Bin, so deleting it "
                    "can't be undone.", "Delete", self).exec():
                return
            try:
                os.remove(self._path)
            except OSError as e:
                NoticeDialog("Could not delete the file", str(e), self).exec()
                return
            ok = False
        self._deleted = True
        self.close()
        toast = getattr(self._overlay, "toast", None)
        if toast is not None and ok:
            toast.show_message("Recording moved to the Recycle Bin" if IS_WIN
                               else "Recording moved to the Trash",
                               anchor=getattr(self._overlay, "toolbar", None))

    def paintEvent(self, _):
        _dlg_frame_paint(self)


class ExportDialog(QDialog):
    """Convert a finished recording to another format.

    Everything here is a second pass over a file that already exists, which is
    not a limitation so much as the only way GIF can be done well: its palette
    has to be chosen from footage that has already been seen.
    """

    def __init__(self, path: str, duration: float = 0.0, parent=None):
        super().__init__(parent,
                         WType.FramelessWindowHint | WType.WindowStaysOnTopHint)
        self.setAttribute(WAtt.WA_TranslucentBackground)
        self.setWindowTitle("Export recording")
        self._path = path
        self._duration = duration or probe_duration(path)
        self._out = ""
        self._keys = list(EXPORT_FORMATS.keys())

        self._conv = MediaConverter(self)
        self._conv.progress.connect(self._on_progress)
        self._conv.done.connect(self._on_done)
        self._conv.failed.connect(self._on_failed)

        self._build()
        self.setFixedWidth(430)
        self.adjustSize()
        _center_on_display1(self)

    # ── build ─────────────────────────────────────────────────────────────────
    def _build(self):
        lo = QVBoxLayout(self)
        lo.setContentsMargins(24, 20, 24, 20)
        lo.setSpacing(10)

        title = QLabel("Export recording")
        tf = QFont(DLG_FONT, 13)
        tf.setBold(True)
        title.setFont(tf)
        title.setStyleSheet(f"color:{DLG_INK};background:transparent;")
        lo.addWidget(title)
        lo.addWidget(_dlg_sep())

        src = QLabel(f"{os.path.basename(self._path)}   ·   "
                     f"{format_elapsed(self._duration)}")
        src.setStyleSheet(
            f"color:{DLG_MUTED};font-family:'{DLG_FONT}';font-size:11px;"
            "background:transparent;")
        lo.addWidget(src)

        def combo(items):
            c = QComboBox()
            c.addItems(items)
            c.setFixedHeight(30)
            c.setStyleSheet(_dlg_combo_style())
            return c

        row = QHBoxLayout()
        row.setSpacing(8)
        self._fmt = combo([EXPORT_FORMATS[k][0] for k in self._keys])
        self._fmt.currentIndexChanged.connect(self._on_format)
        self._size = combo(["Original size"] +
                           [f"{w} px wide" for w in GIF_WIDTHS if w])
        self._rate = combo([f"{r} fps" for r in GIF_RATES])
        self._rate.setCurrentText("12 fps")
        for w in (self._fmt, self._size, self._rate):
            row.addWidget(w)
        lo.addLayout(row)

        self._note = QLabel()
        self._note.setWordWrap(True)
        self._note.setStyleSheet(
            f"color:{DLG_MUTED};font-size:10px;background:transparent;")
        lo.addWidget(self._note)

        self._bar = QProgressBar()
        self._bar.setFixedHeight(6)
        self._bar.setTextVisible(False)
        self._bar.setStyleSheet(
            f"QProgressBar{{background:{DLG_SURFACE};border:none;}}"
            f"QProgressBar::chunk{{background:{DLG_ACCENT};}}")
        self._bar.hide()
        lo.addWidget(self._bar)

        self._status = QLabel()
        self._status.setWordWrap(True)
        self._status.setStyleSheet(
            f"color:{DLG_INK};font-size:11px;background:transparent;")
        self._status.hide()
        lo.addWidget(self._status)

        btns = QHBoxLayout()
        btns.setSpacing(8)
        btns.addStretch()
        self._cancel_btn = QPushButton("Cancel")
        self._cancel_btn.setFixedHeight(34)
        self._cancel_btn.setCursor(Cursor.PointingHandCursor)
        self._cancel_btn.setStyleSheet(_dlg_button_style(primary=False))
        self._cancel_btn.clicked.connect(self.reject)
        btns.addWidget(self._cancel_btn)

        self._go_btn = QPushButton("Export")
        self._go_btn.setFixedHeight(34)
        self._go_btn.setCursor(Cursor.PointingHandCursor)
        self._go_btn.setStyleSheet(_dlg_button_style(primary=True))
        self._go_btn.clicked.connect(self._start)
        btns.addWidget(self._go_btn)
        lo.addLayout(btns)

        self._fmt.setCurrentIndex(0)
        self._on_format(0)

    def preselect(self, kind: str, width: int = 0, fps: int = 12):
        """Open with a format already chosen."""
        if kind in self._keys:
            self._fmt.setCurrentIndex(self._keys.index(kind))
        if width and width in GIF_WIDTHS:
            self._size.setCurrentIndex([w for w in GIF_WIDTHS].index(width))
        if fps in GIF_RATES:
            self._rate.setCurrentIndex(GIF_RATES.index(fps))
        self._on_format(0)

    # ── state ─────────────────────────────────────────────────────────────────
    def _kind(self) -> str:
        return self._keys[self._fmt.currentIndex()]

    def _width(self) -> int:
        i = self._size.currentIndex()
        return 0 if i == 0 else [w for w in GIF_WIDTHS if w][i - 1]

    def _on_format(self, _i):
        kind = self._kind()
        self._rate.setEnabled(kind == "gif")     # only GIF re-times the frames
        note = EXPORT_FORMATS[kind][2]
        if kind == "gif":
            if self._duration > 30:
                note += ("  This one runs "
                         f"{format_elapsed(self._duration)} — expect a big "
                         "file; 480 px at 10 fps keeps it sane.")
            elif self._width() == 0:
                note += "  Scaling down helps more than anything else here."
        self._note.setText(note)

    def _start(self):
        kind = self._kind()
        dst = export_path(self._path, kind)
        rate = GIF_RATES[self._rate.currentIndex()]
        if not self._conv.start(self._path, dst, kind, fps=rate,
                                width=self._width(), duration=self._duration):
            return
        for w in (self._fmt, self._size, self._rate, self._go_btn):
            w.setEnabled(False)
        self._bar.setRange(0, 100 if self._duration > 0 else 0)  # 0,0 = busy
        self._bar.setValue(0)
        self._bar.show()
        self._status.setText(f"Converting to {EXPORT_FORMATS[kind][0]}…")
        self._status.show()
        self._cancel_btn.setText("Stop")
        self.adjustSize()

    def _on_progress(self, fraction: float):
        if self._duration > 0:
            self._bar.setValue(int(fraction * 100))

    def _on_done(self, path: str):
        self._out = path
        settings = getattr(self.parent(), "settings", None)
        if settings is not None:
            note_success(settings)
        try:
            size = f"{os.path.getsize(path) / (1024 * 1024):.1f} MB"
        except OSError:
            size = "—"
        self._bar.setRange(0, 100)
        self._bar.setValue(100)
        self._status.setText(f"Saved  {os.path.basename(path)}   ·   {size}")
        self._cancel_btn.setText("Close")
        self._go_btn.setText("Show in folder")
        self._go_btn.setEnabled(True)
        try:
            self._go_btn.clicked.disconnect()
        except TypeError:
            pass
        self._go_btn.clicked.connect(self._reveal)
        self.adjustSize()

    def _on_failed(self, message: str):
        self._bar.hide()
        self._status.setText(f"Export failed.\n{message}")
        for w in (self._fmt, self._size, self._rate, self._go_btn):
            w.setEnabled(True)
        self._rate.setEnabled(self._kind() == "gif")
        self._cancel_btn.setText("Close")
        self.adjustSize()

    def _reveal(self):
        if self._out:
            _reveal_in_file_manager(self._out)
        self.accept()

    def reject(self):
        if self._conv.running:
            self._conv.cancel()
        super().reject()

    def paintEvent(self, _):
        _dlg_frame_paint(self)


class Countdown(QWidget):
    """3-2-1 in the middle of what's about to be recorded. It is gone before
    the first frame is taken, so it is never in the video."""

    def __init__(self, rect: QRect, done, seconds: int = 3):
        super().__init__(None, Qt.WindowType.FramelessWindowHint
                         | Qt.WindowType.WindowStaysOnTopHint
                         | Qt.WindowType.Tool
                         | Qt.WindowType.WindowTransparentForInput)
        self.setAttribute(WAtt.WA_TranslucentBackground)
        self.setAttribute(WAtt.WA_ShowWithoutActivating)
        self.setAttribute(WAtt.WA_TransparentForMouseEvents)
        self.n, self._done = seconds, done
        side = 200
        self.setGeometry(rect.center().x() - side // 2,
                         rect.center().y() - side // 2, side, side)
        self._timer = QTimer(self)
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self._tick)

    def start(self):
        self.show()
        self.raise_()
        self._timer.start()

    def cancel(self):
        self._timer.stop()
        self.hide()
        self.deleteLater()

    def _tick(self):
        self.n -= 1
        if self.n > 0:
            self.update()
            return
        self.cancel()
        QTimer.singleShot(150, self._done)   # let the compositor take it away

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(RHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(10, 10, -10, -10)
        p.setPen(PS.NoPen)
        p.setBrush(QColor(20, 20, 22, 205))
        p.drawEllipse(r)
        f = QFont("Segoe UI", 10, QFont.Weight.Bold)
        f.setPixelSize(96)
        p.setFont(f)
        p.setPen(QColor("#FFFFFF"))
        p.drawText(r, int(AA.AlignCenter), str(self.n))
        p.end()


class RecordingController(QObject):
    """Everything the rest of the app needs to know about recording.

    The dock, the tray menu and the global hotkey all call `toggle()`; they
    never touch the recorder, the HUD or ffmpeg directly.
    """

    state_changed = Signal(bool)     # True while a recording is running
    ticked        = Signal(float)    # elapsed seconds

    def __init__(self, overlay: "AnnotationOverlay", settings: SettingsManager):
        super().__init__(overlay)
        self.overlay   = overlay
        self._settings = settings
        self._hud: RecordingHUD | None = None
        self._result_bar = None
        self._duration = 0.0
        self._dock_hidden = False
        self._dock_parked = False
        self._dock_excluded = False    # WDA_EXCLUDEFROMCAPTURE path
        self._dock_excluded_windows: list = []
        self._quit_when_done = False   # Exit was chosen mid-recording

        # Two recorders: the GPU one where this machine can (see
        # HardwareRecorder in video_recorder.py), the CPU one otherwise.
        self._cpu = ScreenRecorder(self)
        self._gpu = HardwareRecorder(self)
        for rec in (self._cpu, self._gpu):
            rec.tick.connect(self._on_tick)
            rec.finishing.connect(self._on_finishing)
            rec.finished.connect(self._on_finished)
            rec.failed.connect(self._on_failed)
        self._gpu.fell_back.connect(self._gpu_fell_back)
        self._gpu_broken = ""           # why the GPU path failed this session
        self._pending: tuple | None = None
        self._countdown: Countdown | None = None
        self.recorder = self._cpu

    # ── state ─────────────────────────────────────────────────────────────────
    @property
    def active(self) -> bool:
        return self.recorder.active

    @property
    def paused(self) -> bool:
        return self.recorder.paused

    def config(self) -> RecordConfig:
        g = self._settings.get
        return RecordConfig(
            fps=int(g("rec_fps")),
            quality=g("rec_quality"),
            audio=bool(g("rec_audio")),
            audio_device=g("rec_audio_dev") or "",
            cursor=bool(g("rec_cursor")),
            area=g("rec_area"),
            out_dir=g("rec_dir") or default_output_dir(),
        )

    # ── start / stop ──────────────────────────────────────────────────────────
    @Slot()
    def toggle(self):
        if self._countdown is not None:     # pressed again while counting in
            self._countdown.cancel()
            self._countdown = None
            return
        self.stop() if self.active else self.start()

    def start(self):
        if self.active:
            return
        if not find_ffmpeg():
            NoticeDialog("Recording needs ffmpeg", FFMPEG_HELP, self.overlay,
                         link=("Download ffmpeg",
                               "https://ffmpeg.org/download.html")).exec()
            return

        cfg = self.config()
        if cfg.area == "region":
            native = pick_region_natively()
            if native is not False:            # the compositor picked, or cancelled
                if native:
                    self._count_in(cfg, native)
                return
            sel = RegionSelector()
            sel.chosen.connect(lambda r: self._count_in(cfg, r) if r else None)
            sel.choose()
            return
        region = screen_under_cursor() if cfg.area == "screen" else None
        self._count_in(cfg, region)

    def _count_in(self, cfg: RecordConfig, region):
        if not self._settings.get("rec_countdown"):
            self._begin(cfg, region)
            return
        where = region if region and region.isValid() else screen_under_cursor()

        def go():
            if self._countdown is not None:
                self._countdown = None
                self._begin(cfg, region)
        self._countdown = Countdown(where, go)
        self._countdown.start()

    def _begin(self, cfg: RecordConfig, region):
        # WDA_EXCLUDEFROMCAPTURE exists on Windows 10 2004+, but it does not
        # reliably keep a window out of Qt's grabWindow() in practice — the
        # dock was landing in recordings anyway. Rather than trust it, the
        # dock always gets moved or hidden before the first frame is grabbed,
        # the same way every other platform already has to.
        rect = region if region and region.isValid() else virtual_desktop_rect()
        self._clear_chrome(rect)
        self.overlay.pin_on_screen(True)

        if self._start_on_gpu(cfg, region):
            self._duration = 0.0
            self.state_changed.emit(True)
            return
        self.recorder = self._cpu
        # The overlay's own ink is still worth excluding where the platform
        # honours it: that lets the recorder draw the shapes itself at full
        # output resolution instead of capturing them pre-resampled.
        ok = self.recorder.start(self.overlay.canvas, self.overlay, cfg, region,
                                 exclude=(self.overlay,))
        if not ok:
            self._teardown_hud()
            self._restore_chrome()
            return
        self._duration = 0.0
        self.state_changed.emit(True)

    def gpu_eligible(self) -> bool:
        return (bool(self._settings.get("rec_hardware")) and not self._gpu_broken
                and gpu_recording_possible(len(QApplication.screens())))

    def _start_on_gpu(self, cfg: RecordConfig, region) -> bool:
        if not self.gpu_eligible():
            return False
        scr = QApplication.primaryScreen()
        g, dpr = scr.geometry(), scr.devicePixelRatio()
        crop = None
        size = (round(g.width() * dpr), round(g.height() * dpr))
        if region is not None and region.isValid() and region != g:
            r = region.intersected(g)
            crop = (round((r.x() - g.x()) * dpr) // 2 * 2,
                    round((r.y() - g.y()) * dpr) // 2 * 2)
            size = (round(r.width() * dpr), round(r.height() * dpr))
        audio = None
        if cfg.audio:
            audio = resolve_audio_device(cfg.audio_device)
            if audio is None:
                return False            # the CPU path explains the missing mic
        self._pending = (cfg, region)
        if not self._gpu.start(cfg, size, crop, audio):
            return False
        self.recorder = self._gpu
        return True

    def _gpu_fell_back(self, reason: str):
        """The GPU path gave up in its first seconds — carry on on the CPU,
        and don't try the GPU again this session."""
        self._gpu_broken = reason or "unavailable"
        cfg, region = self._pending or (self.config(), None)
        self.recorder = self._cpu
        ok = self._cpu.start(self.overlay.canvas, self.overlay, cfg, region,
                             exclude=(self.overlay,))
        if not ok:
            self._teardown_hud()
            self._restore_chrome()
            self.state_changed.emit(False)

    def _clear_chrome(self, rect: QRect):
        """Get the dock out of the recorded area, hiding it if there is no
        room left. There is no HUD in this mode — the dock's own Record cell
        turns red, counts up and stops the recording, so a second timer would
        only be one more thing to keep out of frame."""
        if self._settings.get("rec_keep_dock_live") and can_exclude_from_capture():
            windows = self.overlay.toolbar.chrome_windows()
            excluded = [w for w in windows if exclude_from_capture(w, True)]
            if len(excluded) == len(windows):
                # Every dock window took the flag — leave it exactly where it
                # is and trust the compositor to keep it out of the frame.
                self._dock_excluded_windows = excluded
                self._dock_excluded = True
                return
            # Didn't fully take (the thing this setting is a gamble on, per
            # the module docstring in video_recorder.py) — undo whatever did
            # apply and fall back to the guaranteed-correct path below.
            for w in excluded:
                exclude_from_capture(w, False)
        if self.overlay.toolbar.clear_of(rect):   # global coords now
            self._dock_parked = True
            return
        self.overlay.toolbar.set_chrome_visible(False)
        self._dock_hidden = True
        self._explain_hidden_chrome()

    def _explain_hidden_chrome(self):
        """Said once, ever: the dock is about to vanish and the user needs to
        know how to get the recording to stop."""
        if self._settings.get("rec_chrome_notice_seen"):
            return
        self._settings.set("rec_chrome_notice_seen", True)
        self._settings.save()
        NoticeDialog(
            "The dock hides while recording",
            "This recording covers the whole screen, and on this platform a "
            "screen capture includes every visible window — so the dock would "
            "end up in the video. It comes back the moment you stop.\n\n"
            f"To stop: press {shortcut_label(self._settings, 'rec_hotkey')}, "
            "or use the tray icon → Stop recording.\n\n"
            "Recording an area instead of the whole screen keeps the dock "
            "on screen and out of the frame.",
            self.overlay).exec()

    @Slot()
    def stop(self):
        if not self.active:
            return
        self._duration = self.recorder.elapsed()
        self.recorder.stop()

    def stop_and_quit(self):
        """Exit without losing the take: let ffmpeg finish the file first."""
        self._quit_when_done = True
        self.stop()

    def pause(self, on: bool):
        self.recorder.pause(on)
        if self._hud:
            self._hud.set_paused(self.recorder.paused)

    # ── recorder callbacks ────────────────────────────────────────────────────
    def _on_tick(self, seconds: float):
        if self._hud:
            self._hud.set_elapsed(seconds)
        self.ticked.emit(seconds)

    def _on_finishing(self):
        if self._hud:
            self._hud.set_finishing()
        else:
            self._restore_chrome()      # nothing left to keep out of frame
        self.state_changed.emit(False)

    def _on_finished(self, path: str):
        self._teardown_hud()
        self._restore_chrome()
        if self._quit_when_done:
            QApplication.quit()
            return
        # Held, not dropped: these are parentless top-level windows now, so
        # nothing but this reference keeps them alive — an unassigned one is
        # collected the moment this method returns and the panel never appears.
        self._result_bar = RecordingBar(path, self._duration, self.overlay)

    def _on_failed(self, message: str):
        self._teardown_hud()
        self._restore_chrome()
        self.state_changed.emit(False)
        NoticeDialog("Recording stopped", message, self.overlay).exec()
        if self._quit_when_done:
            QApplication.quit()

    def _restore_chrome(self):
        """Put back only what we took away — the dock may legitimately be
        collapsed to its puck, or the overlay hidden with Esc, and neither
        should be undone by a recording ending. The result panel is a child
        of the overlay, though, so that much has to come back."""
        if self._dock_excluded:
            for w in self._dock_excluded_windows:
                exclude_from_capture(w, False)
            self._dock_excluded_windows = []
            self._dock_excluded = False
        if self._dock_hidden:
            self.overlay.toolbar.set_chrome_visible(True)
            self._dock_hidden = False
        if self._dock_parked:
            self.overlay.toolbar.restore_from_parking()
            self._dock_parked = False
        self.overlay.pin_on_screen(False)

    def _teardown_hud(self):
        if self._hud:
            self._hud.close()
            self._hud.deleteLater()
            self._hud = None


# ── Collapsible tool section ───────────────────────────────────────────────────
class ToolSection(QWidget):
    def __init__(self, title: str, tools: list, toolbar: "Toolbar"):
        super().__init__()
        self.toolbar   = toolbar
        self._btns: dict[str, QPushButton] = {}
        self._expanded = False

        lo = QVBoxLayout(self)
        lo.setContentsMargins(0, 0, 0, 0)
        lo.setSpacing(0)

        self.header = QPushButton(f"  {title}  ›")
        self.header.setFixedHeight(28)
        self.header.setCheckable(True)
        self.header.setCursor(Cursor.PointingHandCursor)
        self.header.setStyleSheet(
            "QPushButton{color:#636366;font-size:10px;font-weight:600;"
            "letter-spacing:1px;background:transparent;border:none;"
            "text-align:left;padding-left:4px;border-radius:6px;}"
            "QPushButton:hover{color:#aeaeb2;background:rgba(255,255,255,0.04);}"
            "QPushButton:checked{color:#e5e5e7;}"
        )
        self.header.clicked.connect(self._toggle)
        lo.addWidget(self.header)

        self.body = QWidget()
        self.body.setVisible(False)
        body_lo = QVBoxLayout(self.body)
        body_lo.setContentsMargins(2, 2, 0, 6)
        body_lo.setSpacing(2)

        for tid, icon, label in tools:
            btn = QPushButton(f"  {icon}   {label}")
            btn.setFixedHeight(30)
            btn.setCheckable(True)
            btn.setCursor(Cursor.PointingHandCursor)
            btn.setStyleSheet(
                "QPushButton{color:#98989d;background:transparent;border-radius:8px;"
                "font-size:12px;text-align:left;padding-left:8px;"
                "border:1.5px solid transparent;}"
                "QPushButton:hover{background:rgba(255,255,255,0.07);color:#e5e5e7;}"
                "QPushButton:checked{background:rgba(10,132,255,0.22);color:#4DA3FF;"
                "border:1.5px solid rgba(10,132,255,0.4);}"
            )
            btn.clicked.connect(lambda _, t=tid: toolbar._activate(t))
            body_lo.addWidget(btn)
            self._btns[tid] = btn

        lo.addWidget(self.body)

    def _toggle(self):
        self._expanded = not self._expanded
        self.body.setVisible(self._expanded)
        self.header.setChecked(self._expanded)
        txt = self.header.text()
        self.header.setText(txt.replace("›", "‹") if self._expanded else txt.replace("‹", "›"))
        self.toolbar.adjustSize()

    def expand(self):
        if not self._expanded:
            self._toggle()

    def check_tool(self, tid: str):
        for k, b in self._btns.items():
            b.setChecked(k == tid)

    def has_tool(self, tid: str) -> bool:
        return tid in self._btns


# ── Dialog chrome tokens ────────────────────────────────────────────────────────
# Same palette as the dock toolbar (dock_toolbar.py) — flat, 2px rules, no radius.
# Same two palettes as dock_toolbar.py's THEMES, duplicated rather than
# imported — annotate.py's dialogs are meant to keep working even if the
# `from dock_toolbar import Toolbar` line gets commented out to revert to
# the old vertical panel (see REDESIGN.md).
_DLG_THEMES = {
    "light": dict(
        ink="#201e1d", ground="#f3f2f2", surface="#eae9e9",
        tint="#ffe0d9", accent="#ec3013", accent_600="#dd2b0f",
        muted="#7d7979",
    ),
    "dark": dict(
        ink="#f3f2f2", ground="#201e1d", surface="#2c2a29",
        tint="#3a1f1a", accent="#ec3013", accent_600="#dd2b0f",
        muted="#9b9797",
    ),
}
_current_dlg_theme = "light"

DLG_INK        = _DLG_THEMES["light"]["ink"]
DLG_GROUND     = _DLG_THEMES["light"]["ground"]
DLG_SURFACE    = _DLG_THEMES["light"]["surface"]
DLG_TINT       = _DLG_THEMES["light"]["tint"]
DLG_ACCENT     = _DLG_THEMES["light"]["accent"]
DLG_ACCENT_600 = _DLG_THEMES["light"]["accent_600"]
DLG_MUTED      = _DLG_THEMES["light"]["muted"]
DLG_FONT       = "Segoe UI Variable"


def _apply_dlg_theme(name: str):
    """Switch the dialog palette (and the dock's, if it's loaded) live.

    Widgets that are already on screen don't repaint themselves just because
    a module constant changed — callers are responsible for rebuilding/
    repainting whatever's currently visible afterward (see
    SettingsDialog._set_theme, which is the only place this is called from
    while something is on screen).
    """
    global DLG_INK, DLG_GROUND, DLG_SURFACE, DLG_TINT
    global DLG_ACCENT, DLG_ACCENT_600, DLG_MUTED, _current_dlg_theme
    t = _DLG_THEMES.get(name, _DLG_THEMES["light"])
    DLG_INK, DLG_GROUND, DLG_SURFACE = t["ink"], t["ground"], t["surface"]
    DLG_TINT, DLG_ACCENT             = t["tint"], t["accent"]
    DLG_ACCENT_600, DLG_MUTED        = t["accent_600"], t["muted"]
    _current_dlg_theme = name if name in _DLG_THEMES else "light"

    try:
        import dock_toolbar
        dock_toolbar.set_theme(_current_dlg_theme)
    except ImportError:
        pass  # dock import commented out (reverted to the old vertical panel)


def _dlg_frame_paint(dlg, painter_cls=QPainter):
    """Flat ground + 2px ink border, square corners — shared by all dialogs."""
    p = painter_cls(dlg)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    w, h = dlg.width(), dlg.height()
    p.fillRect(0, 0, w, h, QColor(DLG_GROUND))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.setPen(QPen(QColor(DLG_INK), 4))   # pen straddles the edge → 2px visible
    p.drawRect(0, 0, w, h)
    p.end()


def _center_on_display1(dlg):
    """Center a dialog on the primary monitor's available geometry.

    The overlay these dialogs are parented to spans every connected screen
    (it's one big window covering the whole virtual desktop), so centering
    on `parent.geometry()` lands the dialog on the *bounding box* of all
    monitors combined — which on an irregular multi-monitor layout can be a
    gap between screens, or straddling the seam where several meet. Always
    landing on display 1 keeps it fully visible and interactive no matter
    how the monitors are arranged.
    """
    geo = QApplication.primaryScreen().availableGeometry()
    dlg.move(
        geo.x() + (geo.width()  - dlg.width())  // 2,
        geo.y() + (geo.height() - dlg.height()) // 2,
    )


def _dlg_sep() -> QFrame:
    f = QFrame()
    f.setFrameShape(QFrame.Shape.HLine)
    f.setFixedHeight(2)
    f.setStyleSheet(f"background:{DLG_INK};border:none;")
    return f


def _dlg_section_lbl(text: str) -> QLabel:
    lbl = QLabel(text.upper())
    f = QFont(DLG_FONT, 8)
    f.setBold(True)
    f.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 0.8)
    lbl.setFont(f)
    lbl.setStyleSheet(f"color:{DLG_MUTED};background:transparent;")
    return lbl


class ShortcutCapture(QLineEdit):
    """Flat, fully stylesheet-controlled stand-in for QKeySequenceEdit.

    QKeySequenceEdit has a long-standing Qt quirk where its displayed text
    doesn't reliably take the color set via stylesheet *or* palette — it can
    look fine once and then go low-contrast (sometimes fully invisible)
    after a later runtime palette change, which is exactly what this app's
    dark-mode toggle does. Forcing the palette by hand didn't hold up across
    a theme switch either, so this sidesteps the whole class: a plain
    QLineEdit reliably respects `color` in a stylesheet, always. It only
    reimplements the one bit of QKeySequenceEdit this app actually uses —
    show a single key(+modifiers) combo, capture the next one on a keypress.

    It holds the combo in the stored format (hotkeys.py), "" for none.
    """
    _IGNORED = {
        Qt.Key.Key_Shift, Qt.Key.Key_Control, Qt.Key.Key_Alt,
        Qt.Key.Key_Meta, Qt.Key.Key_AltGr, Qt.Key.Key_CapsLock,
        Qt.Key.Key_unknown,
    }

    changed = Signal()

    def __init__(self, combo: str, parent=None):
        super().__init__(parent)
        self.setReadOnly(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setPlaceholderText("No shortcut — click here and press keys")
        self._combo = hotkeys.canonical(combo)
        self._refresh()

    def _refresh(self):
        self.setText(hotkeys.display(self._combo))

    def combo(self) -> str:
        return self._combo

    def set_combo(self, combo: str):
        self._combo = hotkeys.canonical(combo)
        self._refresh()
        self.changed.emit()

    def keyPressEvent(self, e):
        key = Qt.Key(e.key())
        if key in self._IGNORED:
            e.accept()
            return
        mods = e.modifiers() & ~Qt.KeyboardModifier.KeypadModifier
        text = QKeySequence(QKeyCombination(mods, key)).toString()
        self.set_combo(hotkeys.canonical(text) or text)
        e.accept()


def shortcut_row(combo: str) -> tuple[QWidget, "ShortcutCapture", QLabel]:
    """A shortcut field, its clear button and the line under it that explains
    what is wrong with it (hidden while nothing is)."""
    box = QWidget()
    outer = QVBoxLayout(box)
    outer.setContentsMargins(0, 0, 0, 0)
    outer.setSpacing(4)
    row = QHBoxLayout()
    row.setSpacing(6)
    field = ShortcutCapture(combo)
    field.setFixedHeight(36)
    field.setStyleSheet(_dlg_input_style("QLineEdit"))
    row.addWidget(field, 1)
    clear = QPushButton("✕")
    clear.setFixedSize(36, 36)
    clear.setCursor(Cursor.PointingHandCursor)
    clear.setToolTip("No shortcut for this")
    clear.setStyleSheet(
        f"QPushButton{{color:{DLG_INK};background:transparent;"
        f"border:2px solid {DLG_INK};font-size:13px;padding:0;}}"
        f"QPushButton:hover{{background:{DLG_SURFACE};}}")
    clear.clicked.connect(lambda: field.set_combo(""))
    row.addWidget(clear)
    outer.addLayout(row)
    error = QLabel()
    error.setWordWrap(True)
    error.setStyleSheet("color:#FF3B3B;font-size:10px;background:transparent;")
    error.hide()
    outer.addWidget(error)
    return box, field, error


def _dlg_input_style(widget_cls: str = "QLineEdit") -> str:
    return (
        f"{widget_cls}{{"
        f"  background:{DLG_GROUND};color:{DLG_INK};"
        f"  border:2px solid {DLG_INK};border-radius:0;"
        f"  padding:0 10px;font-size:13px;font-family:'{DLG_FONT}';}}"
        f"{widget_cls}:focus{{border:2px solid {DLG_ACCENT};}}"
    )


def _dlg_combo_style() -> str:
    return (
        f"QComboBox{{background:{DLG_GROUND};color:{DLG_INK};"
        f"border:2px solid {DLG_INK};border-radius:0;"
        f"padding:0 8px;font-size:12px;font-family:'{DLG_FONT}';}}"
        "QComboBox::drop-down{border:none;}"
        f"QComboBox QAbstractItemView{{background:{DLG_GROUND};color:{DLG_INK};"
        f"selection-background-color:{DLG_TINT};border:2px solid {DLG_INK};}}"
    )


def _dlg_checkbox_style() -> str:
    return (
        f"QCheckBox{{color:{DLG_INK};font-size:12px;spacing:8px;"
        f"font-family:'{DLG_FONT}';}}"
        f"QCheckBox::indicator{{width:16px;height:16px;border-radius:0;"
        f"  border:2px solid {DLG_INK};background:{DLG_GROUND};}}"
        f"QCheckBox::indicator:checked{{background:{DLG_ACCENT};"
        f"  border:2px solid {DLG_ACCENT};}}"
        f"QCheckBox:disabled{{color:{DLG_MUTED};}}"
    )


def _dlg_button_style(primary: bool) -> str:
    if primary:
        return (
            f"QPushButton{{color:#ffffff;background:{DLG_ACCENT};border:none;"
            f"font-family:'{DLG_FONT}';font-size:12px;font-weight:700;padding:0 16px;}}"
            f"QPushButton:hover{{background:{DLG_ACCENT_600};}}"
        )
    return (
        f"QPushButton{{color:{DLG_INK};background:transparent;"
        f"border:2px solid {DLG_INK};font-family:'{DLG_FONT}';font-size:12px;"
        "padding:0 16px;}"
        f"QPushButton:hover{{background:{DLG_SURFACE};}}"
    )


def _dlg_tab_style() -> str:
    """Flat rectangular tabs, matching the rest of the dialog chrome — no
    radius, 2px ink rules. The pane's top border sits under the tab bar's
    bottom border (top:-2px) so the two don't double up into a 4px line."""
    return (
        f"QTabWidget::pane{{background:{DLG_GROUND};"
        f"border:2px solid {DLG_INK};border-top:none;top:-2px;}}"
        "QTabBar{background:transparent;}"
        f"QTabBar::tab{{background:{DLG_SURFACE};color:{DLG_MUTED};"
        f"border:2px solid {DLG_INK};border-bottom:none;"
        f"font-family:'{DLG_FONT}';font-size:11px;font-weight:700;"
        "padding:7px 16px;margin-right:4px;}"
        f"QTabBar::tab:selected{{background:{DLG_GROUND};color:{DLG_INK};}}"
        f"QTabBar::tab:!selected:hover{{color:{DLG_INK};}}"
    )


# ── Text tool input ───────────────────────────────────────────────────────────
class InlineTextEditor(QTextEdit):
    """A label typed right where it goes, in its own font, colour and size.

    Enter finishes, Shift+Enter starts a new line, Esc throws it away, and a
    click anywhere else counts as done. It replaced a dialog that always
    opened in the middle of monitor 1, wherever you had clicked.
    """

    committed = Signal(str)
    cancelled = Signal()

    PAD_X, PAD_Y, BORDER = 8, 4, 1

    def __init__(self, canvas: QWidget, pos: QPointF, color: str, size: int,
                 box: bool, text: str = ""):
        super().__init__(canvas)
        self.origin, self.color, self.size, self.box = QPointF(pos), color, size, box
        self._done = False
        self.setAcceptRichText(False)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setLineWrapMode(QTextEdit.LineWrapMode.NoWrap)
        self.document().setDocumentMargin(0)
        self.setFont(QFont("Arial", size, QFont.Weight.Bold))
        ink = QColor(color)
        if box:
            plate = _contrast(color)
            bg = f"rgba({plate.red()},{plate.green()},{plate.blue()},225)"
        else:
            bg = "transparent"
        self.setStyleSheet(
            f"QTextEdit{{color:rgba({ink.red()},{ink.green()},{ink.blue()},"
            f"{max(ink.alpha(), 60)});background:{bg};"
            f"border:{self.BORDER}px dashed rgba(10,132,255,230);"
            f"padding:{self.PAD_Y}px {self.PAD_X}px;}}")
        self.move(round(pos.x()) - self.PAD_X - self.BORDER,
                  round(pos.y()) - self.PAD_Y - self.BORDER)
        self.setPlainText(text)
        cursor = self.textCursor()
        cursor.movePosition(cursor.MoveOperation.End)
        self.setTextCursor(cursor)
        self.textChanged.connect(self._fit)
        self._fit()
        self.show()
        self.raise_()
        self.setFocus()

    def _fit(self):
        doc = self.document()
        extra_w = 2 * (self.PAD_X + self.BORDER) + 8        # room for the caret
        extra_h = 2 * (self.PAD_Y + self.BORDER)
        self.resize(max(60, int(doc.idealWidth()) + extra_w),
                    int(doc.size().height()) + extra_h)

    def keyPressEvent(self, e):
        if e.key() == Key.Key_Escape:
            self._finish(keep=False)
            return
        if e.key() in (Key.Key_Return, Key.Key_Enter) \
                and not (e.modifiers() & Qt.KeyboardModifier.ShiftModifier):
            self._finish(keep=True)
            return
        super().keyPressEvent(e)

    def focusOutEvent(self, e):
        super().focusOutEvent(e)
        self.commit()

    def commit(self):
        self._finish(keep=True)

    def _finish(self, keep: bool):
        if self._done:
            return
        self._done = True
        if keep:
            self.committed.emit(self.toPlainText())
        else:
            self.cancelled.emit()


# ── Help dialog ───────────────────────────────────────────────────────────────

class HelpDialog(QDialog):
    """Full feature reference — opened from the Settings dialog."""

    _TOOLS = [
        # (icon, name, shortcut, shift_tip)
        ("↖",  "Select / Move",   "V",  "Drag to reposition any shape"),
        ("〜", "Pen",             "P",  "Freehand drawing stroke"),
        ("—",  "Line",            "L",  "Hold Shift → 45° snap"),
        ("→",  "Arrow",           "A",  "Hold Shift → 45° snap"),
        ("▭",  "Rectangle",       "R",  "Hold Shift → perfect square"),
        ("○",  "Circle",          "O",  "Hold Shift → perfect circle"),
        ("↔",  "Ruler",           "U",  "Hold Shift → 45° snap  ·  length in real screen pixels"),
        ("T",  "Text",            "T",  "Click and type  ·  Enter finishes, Shift+Enter adds a line  ·  click a label to edit it"),
        ("①",  "Callout",        "K",  "Auto-numbered filled circles"),
        ("1▸2","Steps",           "S",  "Auto-numbered step squares"),
        ("✓",  "Stamp",           "G",  "Click to place ✓ ✗ ! ? or ★"),
        ("HL", "Highlight",       "H",  "Semi-transparent colour band"),
        ("◻",  "Eraser",          "E",  "Touch a mark to remove it  ·  or switch to Pixels to rub out part of one"),
        ("⊘",  "Blur",            "Z",  "Gaussian blur over a selected region"),
        ("PX", "Pixelate",        "X",  "Turns what's underneath into large blocks"),
        ("▪",  "Black Box",       "D",  "Solid opaque black redaction"),
        ("⊙",  "Laser Pointer",   "I",  "No mark left — OS cursor hidden, red dot only"),
        ("⌗",  "Snip & Read",     "J",  "Drag over text to copy it out, then translate it"),
        ("▢",  "Whiteboard",      "W",  "Board over this screen, white or dark (Settings) · PgDn/PgUp: pages · W or Esc leaves"),
        ("◎",  "Spotlight",       "F",  "Dims everything but the cursor · mouse wheel sizes it"),
        ("⌕",  "Zoom",            "M",  "A magnifier next to the cursor · wheel zooms 2×–16× · Esc leaves"),
    ]

    _TIPS = [
        ("Opacity slider",   "Sets transparency for new shapes — existing ones are not affected."),
        ("Text size slider", "Controls the font size of the Text tool."),
        ("Shift while drawing", "Locks lines / arrows / ruler to nearest 45°.\n"
                                "Locks rectangle / circle to perfect square / circle."),
        ("Eraser size",      "Follows the Width slider."),
        ("Screenshot",       "Hides the overlay, grabs the full desktop (all monitors), "
                             "then shows Copy / Save PNG / Discard."),
        ("Recording",        "Records the screen to MP4 with your marks in it. The "
                             "Record button on the dock turns red and counts up; "
                             "press it again to stop."),
        ("Multi-monitor",    "The overlay covers all connected displays automatically."),
        ("Start on boot",    "Starts Screen Annotator Pro hidden in the tray when "
                             "you sign in to Windows."),
    ]

    def __init__(self, settings: "SettingsManager | None" = None, parent=None):
        super().__init__(parent,
                         WType.FramelessWindowHint | WType.WindowStaysOnTopHint)
        self.setAttribute(WAtt.WA_TranslucentBackground)
        self._settings = settings
        self._build()
        self.adjustSize()
        _center_on_display1(self)

    def _tools(self) -> list:
        return [t for t in self._TOOLS if t[1] != "Snip & Read" or ocr_available()]

    def _shortcuts(self) -> list:
        """Read from the live settings — this list used to be hard-coded and
        had drifted (Esc was described as hiding the overlay)."""
        rows = []
        if self._settings is not None:
            for key, (name, label) in HOTKEY_SETTINGS.items():
                if name == "ocr" and not ocr_available():
                    continue
                rows.append((shortcut_label(self._settings, key),
                             f"{label} — change it in Settings"))
        rows += [
            ("Ctrl + Z",  "Undo — drawing, moving, deleting and Clear all"),
            ("Ctrl + Y",  "Redo"),
            ("C",         "Clear all marks (Ctrl + Z brings them back)"),
            ("Esc",       "Click-through: the marks stay, your clicks go to "
                          "the app underneath"),
            ("Delete",    "Remove the selected marks (Select tool)"),
            ("Ctrl + C / V / D", "Copy, paste, duplicate the selection"),
            ("Ctrl + S / Ctrl + O", "Save the marks to a file / open saved marks"),
            ("Ctrl + A",  "Select everything"),
            ("Arrows",    "Nudge the selection (Shift: 10 px)"),
        ]
        return rows

    # ── Build ──────────────────────────────────────────────────────────────────
    def _build(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 18, 20, 18)
        outer.setSpacing(10)

        # Title row
        title_row = QHBoxLayout()
        title = QLabel("Help & Features")
        tf = QFont(DLG_FONT, 13)
        tf.setBold(True)
        title.setFont(tf)
        title.setStyleSheet(f"color:{DLG_INK};background:transparent;")
        title_row.addWidget(title)
        title_row.addStretch()
        close_btn = QPushButton("✕")
        close_btn.setFixedSize(26, 26)
        close_btn.setCursor(Cursor.PointingHandCursor)
        close_btn.setStyleSheet(
            f"QPushButton{{color:{DLG_INK};background:transparent;border:none;font-size:13px;}}"
            f"QPushButton:hover{{color:{DLG_ACCENT};}}"
        )
        close_btn.clicked.connect(self.accept)
        title_row.addWidget(close_btn)
        outer.addLayout(title_row)
        outer.addWidget(_dlg_sep())

        # Scroll area
        from PySide6.QtWidgets import QScrollArea
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setFixedHeight(460)
        scroll.setStyleSheet(
            "QScrollArea{background:transparent;border:none;}"
            f"QScrollBar:vertical{{background:{DLG_SURFACE};width:8px;border-radius:0;}}"
            f"QScrollBar::handle:vertical{{background:{DLG_MUTED};border-radius:0;min-height:20px;}}"
            "QScrollBar::add-line:vertical,QScrollBar::sub-line:vertical{height:0;}"
        )

        content = QWidget()
        content.setStyleSheet("background:transparent;")
        cl = QVBoxLayout(content)
        cl.setContentsMargins(0, 0, 8, 0)
        cl.setSpacing(0)

        # ── Tools ──────────────────────────────────────────────────────────────
        cl.addWidget(self._section("Tools"))
        for icon, name, key, tip in self._tools():
            cl.addWidget(self._tool_row(icon, name, key, tip))
        cl.addSpacing(10)

        # ── Keyboard shortcuts ─────────────────────────────────────────────────
        cl.addWidget(self._section("Keyboard Shortcuts"))
        for keys, desc in self._shortcuts():
            cl.addWidget(self._shortcut_row(keys, desc))
        cl.addSpacing(10)

        # ── Tips ───────────────────────────────────────────────────────────────
        cl.addWidget(self._section("Tips"))
        for heading, body in self._TIPS:
            cl.addWidget(self._tip_row(heading, body))

        cl.addStretch()
        scroll.setWidget(content)
        outer.addWidget(scroll)

        outer.addWidget(_dlg_sep())

        # Close button
        close2 = QPushButton("Close")
        close2.setFixedHeight(34)
        close2.setCursor(Cursor.PointingHandCursor)
        close2.setStyleSheet(_dlg_button_style(primary=False))
        close2.clicked.connect(self.accept)
        outer.addWidget(close2)

        self.setFixedWidth(420)

    # ── Row builders ───────────────────────────────────────────────────────────
    def _section(self, text: str) -> QLabel:
        lbl = _dlg_section_lbl(text)
        lbl.setStyleSheet(lbl.styleSheet() + "padding:8px 0 4px 0;")
        return lbl

    def _tool_row(self, icon: str, name: str, key: str, tip: str) -> QWidget:
        w  = QWidget()
        lo = QVBoxLayout(w)
        lo.setContentsMargins(4, 3, 4, 3)
        lo.setSpacing(1)

        top = QHBoxLayout()
        icon_lbl = QLabel(icon)
        icon_lbl.setFixedWidth(28)
        icon_lbl.setStyleSheet(f"color:{DLG_ACCENT};font-size:13px;font-weight:600;")
        name_lbl = QLabel(name)
        name_lbl.setStyleSheet(f"color:{DLG_INK};font-size:12px;")
        key_lbl  = QLabel(key)
        key_lbl.setStyleSheet(
            f"color:{DLG_MUTED};font-size:10px;background:{DLG_SURFACE};padding:1px 5px;"
        )
        top.addWidget(icon_lbl)
        top.addWidget(name_lbl)
        top.addStretch()
        top.addWidget(key_lbl)
        lo.addLayout(top)

        tip_lbl = QLabel(tip)
        tip_lbl.setStyleSheet(f"color:{DLG_MUTED};font-size:10px;padding-left:28px;")
        lo.addWidget(tip_lbl)
        return w

    def _shortcut_row(self, keys: str, desc: str) -> QWidget:
        w  = QWidget()
        lo = QHBoxLayout(w)
        lo.setContentsMargins(4, 4, 4, 4)
        keys_lbl = QLabel(keys)
        keys_lbl.setFixedWidth(160)
        keys_lbl.setStyleSheet(
            f"color:{DLG_INK};font-size:11px;background:{DLG_SURFACE};"
            "padding:2px 6px;font-family:Consolas,monospace;"
        )
        desc_lbl = QLabel(desc)
        desc_lbl.setStyleSheet(f"color:{DLG_MUTED};font-size:11px;")
        desc_lbl.setWordWrap(True)
        lo.addWidget(keys_lbl)
        lo.addWidget(desc_lbl, 1)
        return w

    def _tip_row(self, heading: str, body: str) -> QWidget:
        w  = QWidget()
        lo = QVBoxLayout(w)
        lo.setContentsMargins(4, 5, 4, 5)
        lo.setSpacing(2)
        h = QLabel(heading)
        h.setStyleSheet(f"color:{DLG_INK};font-size:11px;font-weight:600;")
        b = QLabel(body)
        b.setStyleSheet(f"color:{DLG_MUTED};font-size:10px;")
        b.setWordWrap(True)
        lo.addWidget(h)
        lo.addWidget(b)
        return w

    def paintEvent(self, _):
        _dlg_frame_paint(self)


# ── Settings dialog ───────────────────────────────────────────────────────────

class _FitTabWidget(QTabWidget):
    """A tab widget as tall as the page on show, not the tallest page.

    QTabWidget sizes itself from every page's size hint (their size policies
    don't enter into it), so the short tabs carried the tall one's empty
    space and the dialog never shrank on a tab switch.
    """

    def _fit(self, full, height):
        pages = [self.widget(i) for i in range(self.count())]
        if not pages or self.currentWidget() is None:
            return full
        tallest = max(w.sizeHint().height() for w in pages)
        spare = tallest - height(self.currentWidget())
        return full.shrunkBy(QMargins(0, 0, 0, max(0, spare)))

    def _page_height(self, w) -> int:
        # Word-wrapped labels make a page's plain size hint a guess at some
        # arbitrary width; ask for the height at the width it really has.
        width = w.width()
        if w.hasHeightForWidth() and width > 0:
            return max(w.heightForWidth(width), w.minimumSizeHint().height())
        return w.sizeHint().height()

    def hasHeightForWidth(self):
        # QStackedLayout answers height-for-width with the tallest page, which
        # would undo the whole point; _page_height() does that job instead.
        return False

    def sizeHint(self):
        return self._fit(super().sizeHint(), self._page_height)

    def minimumSizeHint(self):
        return self._fit(super().minimumSizeHint(),
                         lambda w: w.minimumSizeHint().height())


class SettingsDialog(QDialog):
    def __init__(self, settings: SettingsManager, hotkey_mgr: HotkeyManager,
                 parent=None):
        super().__init__(parent,
                         WType.FramelessWindowHint | WType.WindowStaysOnTopHint)
        self.setAttribute(WAtt.WA_TranslucentBackground)
        self._settings   = settings
        self._hotkey_mgr = hotkey_mgr
        self._build()
        self.adjustSize()
        _center_on_display1(self)

    # ── Build UI ───────────────────────────────────────────────────────────────
    def _build(self):
        lo = QVBoxLayout(self)
        lo.setContentsMargins(24, 20, 24, 20)
        lo.setSpacing(10)

        title = QLabel("Settings")
        tf = QFont(DLG_FONT, 14)
        tf.setBold(True)
        title.setFont(tf)
        title.setStyleSheet(f"color:{DLG_INK};background:transparent;")
        lo.addWidget(title)
        lo.addWidget(_dlg_sep())

        # ── Tabs ───────────────────────────────────────────────────────────────
        # Two tabs rather than one long stack: each one only has to be as tall
        # as its own content, and the dialog resizes to match on every switch
        # (see the currentChanged connection below) instead of always paying
        # for the height of everything combined.
        self._hk_fields = {}
        tabs = _FitTabWidget()
        tabs.setStyleSheet(_dlg_tab_style())
        tabs.addTab(self._build_general_tab(), "General")
        tabs.addTab(self._build_shortcuts_tab(), "Shortcuts")
        tabs.addTab(self._build_recording_tab(), "Recording")
        tabs.currentChanged.connect(lambda i, t=tabs: self._fit_tab(t, i))
        self._fit_tab(tabs, 0)
        lo.addWidget(tabs)

        lo.addSpacing(6)
        lo.addWidget(_dlg_sep())
        lo.addSpacing(4)

        # ── Developer link ─────────────────────────────────────────────────────
        dev_row = QHBoxLayout()
        dev_lbl = QLabel("Developer")
        dev_lbl.setStyleSheet(f"color:{DLG_MUTED};font-size:11px;")
        dev_row.addWidget(dev_lbl)
        dev_row.addStretch()
        dev_btn = QPushButton("celikovic.xyz ↗")
        dev_btn.setCursor(Cursor.PointingHandCursor)
        dev_btn.setStyleSheet(
            f"QPushButton{{color:{DLG_ACCENT};background:transparent;border:none;"
            "font-size:11px;}"
            f"QPushButton:hover{{color:{DLG_ACCENT_600};text-decoration:underline;}}"
        )
        dev_btn.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl("https://celikovic.xyz"))
        )
        dev_row.addWidget(dev_btn)
        lo.addLayout(dev_row)

        notices = _third_party_notices()
        if notices:
            lic_row = QHBoxLayout()
            lic_lbl = QLabel("Built with open-source software")
            lic_lbl.setStyleSheet(f"color:{DLG_MUTED};font-size:11px;")
            lic_row.addWidget(lic_lbl)
            lic_row.addStretch()
            lic_btn = QPushButton("Licenses ↗")
            lic_btn.setCursor(Cursor.PointingHandCursor)
            lic_btn.setStyleSheet(
                f"QPushButton{{color:{DLG_ACCENT};background:transparent;border:none;"
                "font-size:11px;}"
                f"QPushButton:hover{{color:{DLG_ACCENT_600};text-decoration:underline;}}")
            lic_btn.clicked.connect(
                lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(notices)))
            lic_row.addWidget(lic_btn)
            lo.addLayout(lic_row)

        ver_lbl = QLabel(f"Version {VERSION}")
        ver_lbl.setStyleSheet(f"color:{DLG_MUTED};font-size:10px;")
        ver_lbl.setAlignment(AA.AlignRight)
        lo.addWidget(ver_lbl)
        lo.addSpacing(6)

        # ── Buttons ────────────────────────────────────────────────────────────
        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)

        help_btn = QPushButton("Help")
        help_btn.setFixedHeight(34)
        help_btn.setCursor(Cursor.PointingHandCursor)
        help_btn.setStyleSheet(_dlg_button_style(primary=False))
        help_btn.clicked.connect(lambda: HelpDialog(self._settings, self).exec())
        btn_row.addWidget(help_btn)
        btn_row.addStretch()

        for label, slot, primary in [("Cancel", self.reject, False),
                                     ("Save",   self._save,  True)]:
            btn = QPushButton(label)
            btn.setFixedHeight(34)
            btn.setCursor(Cursor.PointingHandCursor)
            btn.setStyleSheet(_dlg_button_style(primary))
            btn.clicked.connect(slot)
            btn_row.addWidget(btn)
        lo.addLayout(btn_row)

    def showEvent(self, e):
        super().showEvent(e)
        # Heights guessed before the first show (fonts, word-wrapped notes)
        # come out a few pixels short and clipped the last row of a tab; fit
        # once more now that everything has been laid out for real.
        QTimer.singleShot(0, self.adjustSize)

    def _fit_tab(self, tabs: QTabWidget, index: int):
        tabs.updateGeometry()
        self.adjustSize()

    def _build_shortcuts_tab(self) -> QWidget:
        """All four global shortcuts on one tab — where a clash between two of
        them, or with another app, can be seen and fixed in one place."""
        page = QWidget()
        lo = QVBoxLayout(page)
        lo.setContentsMargins(0, 12, 0, 2)
        lo.setSpacing(6)

        if not self._hotkey_mgr.available:
            note = QLabel("Global shortcuts aren't available on this desktop "
                          "(Wayland). They still work while the overlay has "
                          "the keyboard, and the tray icon does the rest.")
            note.setWordWrap(True)
            note.setStyleSheet(f"color:{DLG_MUTED};font-size:10px;")
            lo.addWidget(note)

        self._add_shortcut(lo, "hotkey",
                           "Click a box and press the new combination.")
        self._add_shortcut(lo, "visibility_hotkey", "")
        self._add_shortcut(lo, "rec_hotkey", "")
        self._add_shortcut(lo, "screenshot_hotkey", "")
        self._add_shortcut(lo, "zoom_hotkey", "")
        if ocr_available():
            self._add_shortcut(lo, "ocr_hotkey", "")

        reset = QPushButton("Reset shortcuts to the defaults")
        reset.setCursor(Cursor.PointingHandCursor)
        reset.setStyleSheet(
            f"QPushButton{{color:{DLG_ACCENT};background:transparent;border:none;"
            "font-size:11px;text-align:left;padding:0;}"
            f"QPushButton:hover{{color:{DLG_ACCENT_600};text-decoration:underline;}}")
        reset.clicked.connect(self._reset_shortcuts)
        lo.addWidget(reset)
        lo.addSpacing(10)
        hold = QHBoxLayout()
        hold.setSpacing(10)
        hold_lbl = QLabel("Hold a key to draw, let go to click through")
        hold_lbl.setStyleSheet(f"color:{DLG_INK};background:transparent;"
                               f"font-size:12px;font-family:'{DLG_FONT}';")
        self._hold_keys = ["off", "rctrl", "rshift"]
        self._hold_box = QComboBox()
        self._hold_box.addItems(["Off", "Right Ctrl", "Right Shift"])
        cur = self._settings.get("hold_to_draw")
        self._hold_box.setCurrentIndex(self._hold_keys.index(cur)
                                       if cur in self._hold_keys else 0)
        self._hold_box.setFixedHeight(30)
        self._hold_box.setStyleSheet(_dlg_combo_style())
        self._hold_box.setEnabled(IS_WIN)
        hold.addWidget(hold_lbl)
        hold.addWidget(self._hold_box)
        hold.addStretch()
        lo.addLayout(hold)
        lo.addStretch()
        return page

    def _build_general_tab(self) -> QWidget:
        page = QWidget()
        lo = QVBoxLayout(page)
        lo.setContentsMargins(0, 12, 0, 2)
        lo.setSpacing(10)

        # ── Boot ───────────────────────────────────────────────────────────────
        self._boot_status = platform_win.startup_status()
        self._boot_cb = QCheckBox("Start with Windows, hidden in the tray")
        self._boot_cb.setChecked(self._boot_status == "on")
        self._boot_cb.setEnabled(self._boot_status in ("on", "off"))
        self._boot_cb.setStyleSheet(_dlg_checkbox_style())
        lo.addWidget(self._boot_cb)
        if self._boot_status == "blocked":
            why = QLabel(platform_win.BLOCKED_MESSAGE)
            why.setWordWrap(True)
            why.setStyleSheet(f"color:{DLG_MUTED};font-size:10px;")
            lo.addWidget(why)
        lo.addSpacing(6)

        # ── Dock size ──────────────────────────────────────────────────────────
        lo.addWidget(_dlg_section_lbl("Dock size"))
        self._scale_values = [1.0, 0.9, 0.78, 0.7, 0.6]
        self._scale_box = QComboBox()
        self._scale_box.addItems([f"{round(v * 100)} %" for v in self._scale_values])
        current = float(self._settings.get("dock_scale") or 1.0)
        nearest = min(self._scale_values, key=lambda v: abs(v - current))
        self._scale_box.setCurrentText(f"{round(nearest * 100)} %")
        self._scale_box.setFixedHeight(30)
        self._scale_box.setStyleSheet(_dlg_combo_style())
        lo.addWidget(self._scale_box)
        lo.addSpacing(6)

        # ── Hints / presenting ─────────────────────────────────────────────────
        self._hints_cb = QCheckBox("Show a hint when hovering over a button")
        self._hints_cb.setChecked(bool(self._settings.get("show_hints")))
        self._hints_cb.setStyleSheet(_dlg_checkbox_style())
        lo.addWidget(self._hints_cb)
        self._keys_cb = QCheckBox("Show pressed shortcuts on screen")
        self._keys_cb.setChecked(bool(self._settings.get("fx_keys")))
        self._keys_cb.setEnabled(IS_WIN)
        self._keys_cb.setStyleSheet(_dlg_checkbox_style())
        self._keys_cb.setToolTip(
            "Shows shortcuts like Ctrl+S and keys like Enter or the arrows, "
            "big, at the bottom of the screen — and in recordings. Ordinary "
            "typing is never shown, so passwords stay private.")
        lo.addWidget(self._keys_cb)
        lo.addSpacing(6)

        # ── Whiteboard ─────────────────────────────────────────────────────────
        lo.addWidget(_dlg_section_lbl("Whiteboard style  (W)"))
        self._board_box = QComboBox()
        self._board_box.addItems(["White board", "Dark board"])
        self._board_box.setCurrentIndex(1 if self._settings.get("board_style") == "black" else 0)
        self._board_box.setFixedHeight(30)
        self._board_box.setStyleSheet(_dlg_combo_style())
        lo.addWidget(self._board_box)
        lo.addSpacing(6)

        # ── Appearance ─────────────────────────────────────────────────────────
        lo.addWidget(_dlg_section_lbl("Appearance"))
        appearance_row = QHBoxLayout()
        appearance_row.setSpacing(8)
        current_theme = self._settings.get("theme")
        for label, key in [("Light", "light"), ("Dark", "dark")]:
            btn = QPushButton(label)
            btn.setFixedHeight(32)
            btn.setCursor(Cursor.PointingHandCursor)
            btn.setStyleSheet(_dlg_button_style(primary=(key == current_theme)))
            btn.clicked.connect(lambda _c, k=key: self._set_theme(k))
            appearance_row.addWidget(btn)
        lo.addLayout(appearance_row)

        lo.addStretch()
        return page

    def _build_recording_tab(self) -> QWidget:
        page = QWidget()
        lo = QVBoxLayout(page)
        lo.setContentsMargins(0, 12, 0, 2)
        lo.setSpacing(10)
        self._build_recording(lo)
        lo.addStretch()
        return page

    # ── Recording ──────────────────────────────────────────────────────────────
    def _build_recording(self, lo: QVBoxLayout):
        g = self._settings.get
        lo.addWidget(_dlg_section_lbl("Recording"))

        def combo(items: list[str], current: str) -> QComboBox:
            c = QComboBox()
            c.addItems(items)
            c.setCurrentText(current)
            c.setFixedHeight(30)
            c.setMinimumWidth(96)
            c.setStyleSheet(_dlg_combo_style())
            return c

        self._area_keys = ["all", "screen", "region"]
        area_labels = ["All monitors", "Monitor in use", "Pick an area"]
        area_now = area_labels[self._area_keys.index(g("rec_area"))
                               if g("rec_area") in self._area_keys else 0]
        self._rec_area = combo(area_labels, area_now)
        self._rec_area.setToolTip(
            "“Monitor in use” records whichever screen the cursor is on when "
            "you hit Record.")

        self._fps_choices = [15, 24, 30, 60]
        self._rec_fps = combo([f"{f} fps" for f in self._fps_choices],
                              f"{g('rec_fps')} fps")

        self._quality_keys = list(QUALITY_PRESETS.keys())
        q_labels = {"high": "High", "balanced": "Balanced", "small": "Small file"}
        self._rec_quality = combo([q_labels[k] for k in self._quality_keys],
                                  q_labels.get(g("rec_quality"), "Balanced"))
        self._rec_quality.setToolTip(
            "  ·  ".join(f"{q_labels[k]}: {QUALITY_PRESETS[k][2]}"
                         for k in self._quality_keys))

        row = QHBoxLayout()
        row.setSpacing(8)
        for w in (self._rec_area, self._rec_fps, self._rec_quality):
            row.addWidget(w)
        lo.addLayout(row)

        opts = QHBoxLayout()
        opts.setSpacing(16)
        self._rec_cursor_cb = QCheckBox("Show the cursor")
        self._rec_cursor_cb.setChecked(bool(g("rec_cursor")))
        self._rec_audio_cb = QCheckBox("Record the microphone")
        self._rec_audio_cb.setChecked(bool(g("rec_audio")))
        self._rec_countdown_cb = QCheckBox("3-2-1 countdown")
        self._rec_countdown_cb.setChecked(bool(g("rec_countdown")))
        for cb in (self._rec_cursor_cb, self._rec_audio_cb, self._rec_countdown_cb):
            cb.setStyleSheet(_dlg_checkbox_style())
            opts.addWidget(cb)
        opts.addStretch()
        lo.addLayout(opts)

        # Device picking is only offered where ffmpeg can enumerate inputs;
        # elsewhere the system default input is the one sane answer.
        self._rec_dev = None
        devices = list_audio_devices()
        if devices:
            self._rec_dev = combo(devices, g("rec_audio_dev") or devices[0])
            self._rec_dev.setEnabled(self._rec_audio_cb.isChecked())
            self._rec_audio_cb.toggled.connect(self._rec_dev.setEnabled)
            lo.addWidget(self._rec_dev)

        # On by default — see the comment on rec_keep_dock_live in
        # _DEFAULT_SETTINGS.
        self._rec_keep_live_cb = None
        if can_exclude_from_capture():
            self._rec_keep_live_cb = QCheckBox(
                "Keep the dock visible while recording")
            self._rec_keep_live_cb.setChecked(bool(g("rec_keep_dock_live")))
            self._rec_keep_live_cb.setStyleSheet(_dlg_checkbox_style())
            self._rec_keep_live_cb.setToolTip(
                "Asks Windows to leave the dock out of the capture instead of "
                "moving or hiding it, so it stays exactly where it is and "
                "stays usable — hotkeys included. If a finished recording "
                "ever shows the dock anyway, turn this off; recording falls "
                "back to moving/hiding it whenever Windows refuses the "
                "request outright, but a silent partial failure on the "
                "compositor's end is the one thing this can't detect for you.")
            lo.addWidget(self._rec_keep_live_cb)

        self._rec_gpu_cb = None
        if IS_WIN:
            self._rec_gpu_cb = QCheckBox("Record with the graphics chip (beta)")
            self._rec_gpu_cb.setChecked(bool(g("rec_hardware")))
            self._rec_gpu_cb.setStyleSheet(_dlg_checkbox_style())
            self._rec_gpu_cb.setToolTip(
                "Captures and encodes on the GPU — a fraction of the CPU, so "
                "less heat, fan and battery, and smooth 4K. One screen for "
                "now; if this PC can't, recording switches to the normal "
                "recorder by itself. No pause while it's on.")
            lo.addWidget(self._rec_gpu_cb)

        note = QLabel("A screen capture includes every visible window, so "
                      "the dock moves out of the recorded area — or hides, "
                      "if you are recording the whole screen — unless the "
                      "option above is on and takes on this machine."
                      if self._rec_keep_live_cb is not None else
                      "A screen capture includes every visible window, so "
                      "the dock moves out of the recorded area — or hides, "
                      "if you are recording the whole screen.")
        note.setWordWrap(True)
        note.setStyleSheet(
            f"color:{DLG_MUTED};font-size:10px;background:transparent;")
        lo.addWidget(note)

        self._rec_dir = g("rec_dir") or default_output_dir()
        dir_row = QHBoxLayout()
        dir_row.setSpacing(8)
        self._dir_lbl = QLabel(self._elide_dir(self._rec_dir))
        self._dir_lbl.setStyleSheet(
            f"color:{DLG_MUTED};font-size:11px;background:transparent;")
        self._dir_lbl.setToolTip(self._rec_dir)
        dir_row.addWidget(self._dir_lbl)
        dir_row.addStretch()
        change = QPushButton("Change…")
        change.setFixedHeight(28)
        change.setCursor(Cursor.PointingHandCursor)
        change.setStyleSheet(_dlg_button_style(primary=False))
        change.clicked.connect(self._pick_rec_dir)
        dir_row.addWidget(change)
        lo.addLayout(dir_row)

        ver = ffmpeg_version()
        found = bool(find_ffmpeg())
        status = QLabel(
            f"ffmpeg  ·  {ver}" if found and ver else
            "ffmpeg  ·  found" if found else
            "ffmpeg not found — recording is unavailable until it is installed")
        status.setWordWrap(True)
        status.setStyleSheet(
            f"color:{DLG_MUTED if found else '#FF3B3B'};font-size:10px;"
            "background:transparent;")
        lo.addWidget(status)
        lo.addSpacing(6)

    @staticmethod
    def _elide_dir(path: str) -> str:
        home = os.path.expanduser("~")
        shown = path.replace(home, "~", 1) if path.startswith(home) else path
        return f"Saves to  {shown}" if len(shown) < 52 \
            else f"Saves to  …{shown[-48:]}"

    def _pick_rec_dir(self):
        chosen = QFileDialog.getExistingDirectory(
            self, "Where should recordings go?", self._rec_dir)
        if chosen:
            self._rec_dir = chosen
            self._dir_lbl.setText(self._elide_dir(chosen))
            self._dir_lbl.setToolTip(chosen)

    # ── Shortcuts ──────────────────────────────────────────────────────────────
    _FAILURE_TEXT = {
        "taken":   "Another app already uses this combination, so it does "
                   "nothing right now. Pick a different one.",
        "invalid": "This key can't be used as a global shortcut.",
        "failed":  "Windows didn't accept this shortcut. Try a different one.",
    }

    def _add_shortcut(self, lo: QVBoxLayout, key: str, hint: str):
        name, label = HOTKEY_SETTINGS[key]
        lo.addWidget(_dlg_section_lbl(f"{label} shortcut"))
        box, field, error = shortcut_row(self._settings.get(key))
        field.changed.connect(lambda k=key: self._check_shortcuts(k))
        lo.addWidget(box)
        # What went wrong with the combo that is saved right now, if anything.
        why = self._hotkey_mgr.failures().get(name)
        if why in self._FAILURE_TEXT:
            error.setText(self._FAILURE_TEXT[why])
            error.show()
        if hint:
            h = QLabel(hint)
            h.setWordWrap(True)
            h.setStyleSheet(f"color:{DLG_MUTED};font-size:10px;")
            lo.addWidget(h)
        lo.addSpacing(2)
        self._hk_fields[key] = (field, error)

    def _check_shortcuts(self, only: str | None = None) -> bool:
        """Show what is wrong with each shortcut; True if they can all be saved.
        `only` limits the messages to the field just edited (the others keep
        whatever they were showing), the result always covers all of them."""
        users: dict[str, list[str]] = {}
        for key, (field, _error) in self._hk_fields.items():
            if field.combo():
                users.setdefault(hotkeys.canonical(field.combo()), []).append(key)
        ok = True
        for key, (field, error) in self._hk_fields.items():
            combo = field.combo()
            msg = hotkeys.problem(combo)
            others = [k for k in users.get(hotkeys.canonical(combo), []) if k != key]
            if not msg and combo and others:
                # Both fields say so — whichever one you just typed into.
                msg = "Also set for " + ", ".join(
                    f"“{HOTKEY_SETTINGS[k][1]}”" for k in others) + "."
            ok = ok and not msg
            # Other fields keep a "taken by another app" note from when the
            # dialog opened, but a clash message comes and goes with the clash.
            if (only is None or key == only or msg
                    or error.text().startswith("Also set for")):
                error.setText(msg)
                error.setVisible(bool(msg))
        self.adjustSize()
        return ok

    def _reset_shortcuts(self):
        for key, (field, _error) in self._hk_fields.items():
            field.set_combo(_DEFAULT_SETTINGS[key])
        self._check_shortcuts()

    # ── Helpers ────────────────────────────────────────────────────────────────
    def _input_style(self) -> str:
        return _dlg_input_style("QLineEdit")

    def _save(self):
        if not self._check_shortcuts():
            return
        overlay = self.parent()
        for key, (field, _error) in self._hk_fields.items():
            name, _label = HOTKEY_SETTINGS[key]
            combo = field.combo()
            self._settings.set(key, combo)
            self._hotkey_mgr.rebind(name, combo)
        if overlay is not None and hasattr(overlay, "toolbar"):
            overlay.toolbar.set_mode_shortcut(hotkeys.display(self._settings.get("hotkey")))
            overlay.toolbar.set_record_shortcut(
                hotkeys.display(self._settings.get("rec_hotkey")))

        self._settings.set("rec_area", self._area_keys[self._rec_area.currentIndex()])
        self._settings.set("rec_fps", self._fps_choices[self._rec_fps.currentIndex()])
        self._settings.set("rec_quality",
                           self._quality_keys[self._rec_quality.currentIndex()])
        self._settings.set("rec_cursor", self._rec_cursor_cb.isChecked())
        self._settings.set("rec_audio", self._rec_audio_cb.isChecked())
        self._settings.set("rec_countdown", self._rec_countdown_cb.isChecked())
        if self._rec_dev is not None:
            self._settings.set("rec_audio_dev", self._rec_dev.currentText())
        self._settings.set("rec_dir", self._rec_dir)
        if self._rec_keep_live_cb is not None:
            self._settings.set("rec_keep_dock_live",
                               self._rec_keep_live_cb.isChecked())
        if self._rec_gpu_cb is not None:
            self._settings.set("rec_hardware", self._rec_gpu_cb.isChecked())

        self._settings.set("board_style",
                           "black" if self._board_box.currentIndex() == 1 else "white")
        self._settings.set("show_hints", self._hints_cb.isChecked())
        self._settings.set("hold_to_draw", self._hold_keys[self._hold_box.currentIndex()])
        if hasattr(overlay, "apply_hold_to_draw"):
            overlay.apply_hold_to_draw()
        if overlay is not None and hasattr(overlay, "set_effect") \
                and self._keys_cb.isChecked() != bool(self._settings.get("fx_keys")):
            overlay.set_effect("keys", self._keys_cb.isChecked())
        new_scale = self._scale_values[self._scale_box.currentIndex()]
        if abs(new_scale - float(self._settings.get("dock_scale") or 1.0)) > 1e-3 \
                and overlay is not None and hasattr(overlay, "toolbar"):
            overlay.toolbar.apply_scale(new_scale)      # now, not next launch
        self._settings.set("dock_scale", new_scale)
        boot_problem = ""
        want_boot = self._boot_cb.isChecked()
        if self._boot_cb.isEnabled() and want_boot != (self._boot_status == "on"):
            ok, boot_problem = platform_win.set_startup(want_boot)
            if not ok:
                want_boot = not want_boot
        self._settings.set("start_on_boot", want_boot)
        self._settings.save()
        self.accept()

        # Said after the dialog closes, so there is one thing on screen at a time.
        taken = [HOTKEY_SETTINGS[k][1] + " — " + shortcut_label(self._settings, k)
                 for k in self._hk_fields
                 if self._hotkey_mgr.failures().get(HOTKEY_SETTINGS[k][0]) == "taken"]
        if taken:
            NoticeDialog("A shortcut is already taken",
                         "Another app already uses:\n\n  " + "\n  ".join(taken) +
                         "\n\nThose shortcuts won't do anything until you pick "
                         "different ones in Settings.", overlay).exec()
        if boot_problem:
            NoticeDialog("Start with Windows", boot_problem, overlay).exec()

    def _set_theme(self, name: str):
        if name == self._settings.get("theme"):
            return
        self._settings.set("theme", name)
        self._settings.save()
        _apply_dlg_theme(name)

        # The dock is a long-lived sibling widget (this dialog's parent is
        # the overlay, which holds it) — refresh it immediately rather than
        # waiting for the next launch.
        overlay = self.parent()
        if overlay is not None and hasattr(overlay, "toolbar"):
            overlay.toolbar.refresh_theme()

        # Rebuild this dialog's own contents in the new palette. Deferred by
        # one tick so the click that triggered this finishes before the
        # button doing the rebuilding gets torn down.
        QTimer.singleShot(0, self._rebuild_ui)

    def _rebuild_ui(self):
        old_layout = self.layout()
        if old_layout is not None:
            QWidget().setLayout(old_layout)  # detach so it (and its children) can be GC'd
        self._build()
        self.adjustSize()
        self.update()

    def paintEvent(self, _):
        _dlg_frame_paint(self)


# ── Toolbar (vertical floating panel) ─────────────────────────────────────────
# ── OCR + Translation ─────────────────────────────────────────────────────────

# Language name → deep-translator / Google Translate language code
_TRANSLATE_LANGS = {
    "English": "en", "Bosnian": "bs", "German": "de", "French": "fr",
    "Spanish": "es", "Italian": "it", "Portuguese": "pt", "Dutch": "nl",
    "Polish": "pl", "Russian": "ru", "Ukrainian": "uk", "Arabic": "ar",
    "Chinese (Simplified)": "zh-CN", "Chinese (Traditional)": "zh-TW",
    "Japanese": "ja", "Korean": "ko", "Turkish": "tr", "Swedish": "sv",
    "Norwegian": "no", "Danish": "da", "Finnish": "fi", "Czech": "cs",
    "Romanian": "ro", "Hungarian": "hu", "Greek": "el", "Hebrew": "iw",
    "Hindi": "hi", "Thai": "th", "Vietnamese": "vi", "Indonesian": "id",
    "Malay": "ms", "Croatian": "hr", "Slovak": "sk", "Bulgarian": "bg",
    "Serbian": "sr", "Albanian": "sq", "Lithuanian": "lt", "Latvian": "lv",
    "Estonian": "et", "Slovenian": "sl", "Catalan": "ca", "Swahili": "sw",
    "Afrikaans": "af", "Tagalog": "tl", "Georgian": "ka", "Armenian": "hy",
    "Azerbaijani": "az", "Kazakh": "kk", "Uzbek": "uz", "Mongolian": "mn",
}

_ocr_reader      = None            # lazy-loaded EasyOCR Reader (cached after first use)
_ocr_reader_lock = threading.Lock()

def _ocr_model_dir() -> str:
    """Store OCR models in the app data folder, not in the user's home dir."""
    if IS_WIN:
        base = os.environ.get("APPDATA", os.path.expanduser("~"))
    else:
        base = os.path.join(os.path.expanduser("~"), ".config")
    path = os.path.join(base, "ScreenAnnotatorPro", "ocr_models")
    os.makedirs(path, exist_ok=True)
    return path

def _ocr_models_present() -> bool:
    """Return True if the EasyOCR detection + English recognition models exist."""
    d = _ocr_model_dir()
    return (os.path.exists(os.path.join(d, "craft_mlt_25k.pth")) and
            os.path.exists(os.path.join(d, "english_g2.pth")))


def _get_ocr_reader():
    """Build (or return the already-cached) EasyOCR reader.

    The slow part of OCR isn't recognition — it's this ~5-10s model load,
    which used to only start once the user had already drawn a selection
    and was sitting there waiting on it. Thread-safe so the background
    preload kicked off when the OCR tool is selected (see
    _preload_ocr_reader) and an on-demand build from OcrThread can both
    call this without racing each other or building it twice.
    """
    global _ocr_reader
    if _ocr_reader is not None:
        return _ocr_reader
    with _ocr_reader_lock:
        if _ocr_reader is None:
            try:
                import easyocr
            except ImportError:
                # The lite single-file build ships without the OCR stack.
                raise RuntimeError(
                    "Snip & Read is not available in this build.\n\n"
                    "It needs EasyOCR, which is left out of the lite "
                    "executable to keep it small. Use the full build, or run "
                    "from source with:  pip install easyocr deep-translator"
                ) from None
            _ocr_reader = easyocr.Reader(
                ["en"],
                gpu=False,
                verbose=False,
                model_storage_directory=_ocr_model_dir(),
            )
    return _ocr_reader


class OcrPreloadThread(QThread):
    """Warms up the EasyOCR reader as soon as the OCR tool is selected, so
    the model is usually already loaded by the time a selection is drawn."""
    def run(self):
        try:
            _get_ocr_reader()
        except Exception:
            pass  # not fatal here — OcrThread surfaces any real error when used


_ocr_preload_thread = None

def _preload_ocr_reader():
    global _ocr_preload_thread
    if ocr_win.available():
        return                      # Windows' engine starts in milliseconds
    if _ocr_reader is not None or _ocr_preload_thread is not None:
        return
    _ocr_preload_thread = OcrPreloadThread()
    _ocr_preload_thread.start()


class OcrThread(QThread):
    """Reads the snip off the GUI thread: Windows' own OCR where it is
    available (ocr_win.py), EasyOCR otherwise (Linux, from source)."""
    status   = Signal(str)   # progress updates for the dialog label
    finished = Signal(str)
    error    = Signal(str)

    def __init__(self, image: QImage, language: str = ""):
        super().__init__()
        # A QImage, not a QPixmap: pixmaps belong to the GUI thread.
        self._image = image
        self._language = language

    def run(self):
        try:
            if ocr_win.available():
                self.status.emit("Reading text…")
                text = ocr_win.recognize(self._image, self._language)
            else:
                text = self._easyocr()
            self.finished.emit(text or "(no text detected)")
        except Exception as exc:
            self.error.emit(str(exc))

    def _easyocr(self) -> str:
        import numpy as np
        img = self._image.convertToFormat(QImage.Format.Format_RGB888)
        w, h, stride = img.width(), img.height(), img.bytesPerLine()
        raw = np.frombuffer(bytes(img.constBits()),
                            dtype=np.uint8).reshape(h, stride)
        rgb = raw[:, :w * 3].reshape(h, w, 3)
        if _ocr_reader is None:
            self.status.emit("Downloading OCR model (~150 MB) — first use only…"
                             if not _ocr_models_present() else "Loading OCR engine…")
        reader = _get_ocr_reader()
        self.status.emit("Reading text…")
        return "\n".join(r[1] for r in reader.readtext(rgb)).strip()


TRANSLATE_URL = "https://translate.google.com/?sl=auto&tl={lang}&text={text}&op=translate"
TRANSLATE_URL_MAX = 5000      # longer links get cut off; paste instead


def translate_url(text: str, lang_code: str) -> str | None:
    """Google Translate with the text filled in, or None when the text is too
    long to travel in a link."""
    from urllib.parse import quote
    url = TRANSLATE_URL.format(lang=quote(lang_code), text=quote(text))
    return url if len(url) <= TRANSLATE_URL_MAX else None


class OcrResultDialog(QDialog):
    """The recognised text, editable, with Copy — and a one-click hand-off to
    Google Translate.

    Translation used to be done in-app by deep-translator, which scrapes
    Google's web endpoint: rate-limited, CAPTCHA-blocked on some networks,
    and it sometimes returned Google's error page as the "translation". The
    browser does the same job reliably, and it is honest about where the
    text goes.
    """

    def __init__(self, pixmap: QPixmap, parent=None):
        super().__init__(parent,
                         WType.Window |
                         WType.WindowStaysOnTopHint |
                         WType.WindowCloseButtonHint |
                         WType.WindowMinimizeButtonHint |
                         WType.WindowMaximizeButtonHint)
        self.setWindowTitle("Snip & Read — Screen Annotator Pro")
        self.setStyleSheet(
            f"QDialog{{background:{DLG_GROUND};}}"
            f"QLabel{{color:{DLG_INK};background:transparent;font-family:'{DLG_FONT}';}}"
        )
        self._image      = pixmap.toImage()
        self._ocr_thread = None
        self._languages  = ocr_win.languages() if ocr_win.available() else []
        self._build()
        self.resize(520, 420)
        _center_on_display1(self)
        self._start_ocr()

    # ── Build UI ───────────────────────────────────────────────────────────────
    def _build(self):
        lo = QVBoxLayout(self)
        lo.setContentsMargins(20, 18, 20, 18)
        lo.setSpacing(10)

        top = QHBoxLayout()
        self._status = QLabel("Reading text…")
        self._status.setStyleSheet(f"color:{DLG_MUTED};font-size:10px;")
        top.addWidget(self._status, 1)
        # Which language to read as — only worth offering when there is a
        # choice (each installed Windows language brings its own recognizer).
        self._read_as = None
        if len(self._languages) > 1:
            lbl = QLabel("Read as")
            lbl.setStyleSheet(f"color:{DLG_MUTED};font-size:11px;")
            top.addWidget(lbl)
            self._read_as = QComboBox()
            for tag, name in self._languages:
                self._read_as.addItem(name, tag)
            default = ocr_win.default_language()
            idx = self._read_as.findData(default)
            if idx >= 0:
                self._read_as.setCurrentIndex(idx)
            self._read_as.setFixedHeight(28)
            self._read_as.setStyleSheet(_dlg_combo_style())
            self._read_as.currentIndexChanged.connect(lambda _i: self._start_ocr())
            top.addWidget(self._read_as)
        lo.addLayout(top)

        # Editable: fixing one misread letter before copying beats retyping.
        self._ocr_box = QTextEdit()
        self._ocr_box.setMinimumHeight(120)
        self._ocr_box.setPlaceholderText("Recognized text will appear here…")
        self._ocr_box.setStyleSheet(self._box_style())
        lo.addWidget(self._ocr_box, 1)

        copy_ocr = QPushButton("Copy text")
        copy_ocr.setFixedHeight(32)
        copy_ocr.setCursor(Cursor.PointingHandCursor)
        copy_ocr.setStyleSheet(_dlg_button_style(primary=True))
        copy_ocr.clicked.connect(
            lambda: self._copy_and_flash(copy_ocr, self._ocr_box.toPlainText()))
        lo.addWidget(copy_ocr)

        lo.addWidget(_dlg_sep())

        lang_row = QHBoxLayout()
        lang_lbl = QLabel("Translate to")
        lang_lbl.setStyleSheet(f"color:{DLG_MUTED};font-size:12px;")
        self._lang_box = QComboBox()
        self._lang_box.addItems(list(_TRANSLATE_LANGS.keys()))
        self._lang_box.setCurrentText("English")
        self._lang_box.setFixedHeight(30)
        self._lang_box.setStyleSheet(_dlg_combo_style())
        go_btn = QPushButton("Open in Google Translate ↗")
        go_btn.setFixedHeight(30)
        go_btn.setCursor(Cursor.PointingHandCursor)
        go_btn.setStyleSheet(_dlg_button_style(primary=False))
        go_btn.clicked.connect(self._translate)
        lang_row.addWidget(lang_lbl)
        lang_row.addWidget(self._lang_box, 1)
        lang_row.addWidget(go_btn)
        lo.addLayout(lang_row)

        note = QLabel("Reading happens on this PC. Translating opens your "
                      "browser and sends the text to Google.")
        note.setWordWrap(True)
        note.setStyleSheet(f"color:{DLG_MUTED};font-size:10px;")
        lo.addWidget(note)

    def _copy_and_flash(self, btn: QPushButton, text: str):
        QApplication.clipboard().setText(text)
        original = btn.text()
        btn.setText("Copied")
        btn.setEnabled(False)
        QTimer.singleShot(1500, lambda: (btn.setText(original), btn.setEnabled(True)))

    # ── OCR ────────────────────────────────────────────────────────────────────
    def _start_ocr(self):
        if self._ocr_thread is not None and self._ocr_thread.isRunning():
            self._ocr_thread.wait(5000)
        language = self._read_as.currentData() if self._read_as else ""
        self._status.setText("Reading text…")
        self._ocr_thread = OcrThread(self._image, language or "")
        self._ocr_thread.status.connect(self._status.setText)
        self._ocr_thread.finished.connect(self._on_ocr_done)
        self._ocr_thread.error.connect(self._on_ocr_error)
        self._ocr_thread.start()

    def _on_ocr_done(self, text: str):
        self._ocr_box.setPlainText(text)
        self._status.setText("Text recognized — edit it here if a letter is off")
        overlay = self.parent()
        settings = getattr(overlay, "settings", None)
        if settings is not None and text and text != "(no text detected)":
            note_success(settings)

    def _on_ocr_error(self, msg: str):
        self._ocr_box.setPlainText(msg)
        self._status.setText("Could not read text")

    # ── Translation ────────────────────────────────────────────────────────────
    def _translate(self):
        text = self._ocr_box.toPlainText().strip()
        if not text:
            return
        lang = _TRANSLATE_LANGS.get(self._lang_box.currentText(), "en")
        url = translate_url(text, lang)
        if url is None:
            # Too long for a link: hand it over through the clipboard.
            QApplication.clipboard().setText(text)
            url = TRANSLATE_URL.format(lang=lang, text="")
            self._status.setText("Too long for a link — the text is on your "
                                 "clipboard; paste it into Google Translate.")
        QDesktopServices.openUrl(QUrl(url))

    # ── Style helpers ──────────────────────────────────────────────────────────
    def _box_style(self) -> str:
        return (
            f"QTextEdit{{background:{DLG_SURFACE};color:{DLG_INK};"
            f"border:2px solid {DLG_INK};border-radius:0;"
            f"padding:6px;font-size:12px;font-family:'{DLG_FONT}';}}"
        )


TOOL_GROUPS = [
    ("✏️ Draw", [
        ("select",    "↖",  "Select / Move"),
        ("pen",       "〜", "Pen"),
        ("line",      "—",  "Line"),
        ("arrow",     "→",  "Arrow"),
        ("rect",      "▭",  "Rectangle"),
        ("circle",    "○",  "Circle"),
        ("ruler",     "📏", "Ruler"),
        ("laser",     "⊙",  "Laser  I"),
        ("eraser",    "◻",  "Eraser  E"),
    ]),
    ("🏷 Annotate", [
        ("text",      "T",   "Text"),
        ("callout",   "①",  "Callout"),
        ("steps",     "1▸2", "Steps"),
        ("stamp",     "✓",   "Stamp"),
        ("highlight", "HL",  "Highlight"),
    ]),
    ("🔒 Redact", [
        ("blur",   "⊘",  "Blur"),
        ("pixel",  "PX", "Pixelate"),
        ("redact", "▪",  "Black Box"),
    ]),
    ("🔍 OCR", [
        ("ocr", "🔍", "Snip & Read"),
    ]),
]

class Toolbar(QWidget):
    def __init__(self, canvas: Canvas, overlay: QWidget,
                 settings_mgr: SettingsManager, hotkey_mgr: HotkeyManager):
        super().__init__(overlay)
        self.canvas        = canvas
        self.overlay       = overlay
        self._settings_mgr = settings_mgr
        self._hotkey_mgr   = hotkey_mgr
        self._drag_pos         = None
        self._active_color_btn = None
        self._tool_btns: dict[str, QPushButton] = {}
        self._build()
        self._position()

    def _build(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(12, 14, 12, 14)
        outer.setSpacing(2)

        # ── Drag handle — always visible, outside the scroll area ────────────
        drag_lbl = QLabel("· · ·  Screen Annotator Pro  · · ·")
        drag_lbl.setAlignment(AA.AlignCenter)
        drag_lbl.setStyleSheet("color:#3a3a3c;font-size:10px;font-weight:600;letter-spacing:0.5px;")
        drag_lbl.setCursor(Cursor.SizeAllCursor)
        outer.addWidget(drag_lbl)
        outer.addWidget(self._hsep())
        outer.addSpacing(4)

        # ── Scrollable content ────────────────────────────────────────────────
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self._scroll.setStyleSheet(
            "QScrollArea{background:transparent;border:none;}"
            "QScrollBar:vertical{background:transparent;width:4px;margin:0;}"
            "QScrollBar::handle:vertical{background:rgba(255,255,255,0.18);"
            "border-radius:2px;min-height:20px;}"
            "QScrollBar::add-line:vertical,QScrollBar::sub-line:vertical{height:0;}"
            "QScrollBar::add-page:vertical,QScrollBar::sub-page:vertical{background:none;}"
        )
        self._scroll.viewport().setStyleSheet("background:transparent;")

        content = QWidget()
        content.setStyleSheet("background:transparent;")
        lo = QVBoxLayout(content)
        lo.setContentsMargins(0, 0, 4, 0)
        lo.setSpacing(2)

        # ── Collapsible tool sections ─────────────────────────────────────────
        self._sections: list[ToolSection] = []
        self._all_btns: dict[str, ToolSection] = {}

        for title, tools in TOOL_GROUPS:
            sec = ToolSection(title, tools, self)
            self._sections.append(sec)
            for tid, _, _ in tools:
                self._all_btns[tid] = sec
            lo.addWidget(sec)

        lo.addSpacing(4)
        lo.addWidget(self._hsep())
        lo.addSpacing(6)

        # ── Color swatches (4×4 grid) ─────────────────────────────────────────
        col_lbl = QLabel("Color")
        col_lbl.setStyleSheet("color:#48484a;font-size:9px;font-weight:600;letter-spacing:1px;")
        lo.addWidget(col_lbl)
        lo.addSpacing(3)

        swatch_w = QWidget()
        sg = QGridLayout(swatch_w)
        sg.setSpacing(4); sg.setContentsMargins(0, 0, 0, 0)
        self._active_swatch = None

        for i, hex_c in enumerate(SWATCHES):
            btn = QPushButton()
            btn.setFixedSize(22, 22)
            btn.setCursor(Cursor.PointingHandCursor)
            btn.setToolTip(hex_c)
            btn.setStyleSheet(
                f"QPushButton{{background:{hex_c};border-radius:5px;"
                f"border:2px solid transparent;}}"
                f"QPushButton:hover{{border:2px solid rgba(255,255,255,0.7);}}"
            )
            btn.clicked.connect(lambda _, c=hex_c, b=btn: self._set_swatch(c, b))
            sg.addWidget(btn, i // 4, i % 4)
            if hex_c == "#FF3B3B":
                self._active_swatch = btn
                self._ring_swatch(btn, True)

        lo.addWidget(swatch_w)

        # ── Opacity ───────────────────────────────────────────────────────────
        op_row = QHBoxLayout()
        op_lbl = QLabel("Opacity")
        op_lbl.setStyleSheet("color:#48484a;font-size:9px;font-weight:600;letter-spacing:1px;")
        self._op_val = QLabel("100%")
        self._op_val.setStyleSheet("color:#636366;font-size:9px;")
        self._op_val.setAlignment(AA.AlignRight | AA.AlignVCenter)
        op_row.addWidget(op_lbl); op_row.addStretch(); op_row.addWidget(self._op_val)
        lo.addLayout(op_row)

        op_slider = _Slider(Ori.Horizontal)
        op_slider.setRange(10, 100); op_slider.setValue(100)
        op_slider.setStyleSheet(
            "QSlider::groove:horizontal{height:4px;background:#3a3a3c;border-radius:2px;}"
            "QSlider::handle:horizontal{width:13px;height:13px;background:#e5e5e7;"
            "border-radius:7px;margin:-5px 0;}"
            "QSlider::sub-page:horizontal{background:#0A84FF;border-radius:2px;}"
        )
        op_slider.valueChanged.connect(lambda v: (
            setattr(self.canvas, "pen_alpha", int(v * 255 / 100)),
            self._op_val.setText(f"{v}%"),
        ))
        lo.addWidget(op_slider)
        lo.addSpacing(4)

        custom_col = QPushButton("⊕  Custom color…")
        custom_col.setFixedHeight(28)
        custom_col.setCursor(Cursor.PointingHandCursor)
        custom_col.setStyleSheet(
            "QPushButton{color:#636366;background:transparent;border-radius:8px;"
            "font-size:11px;border:1px dashed #3a3a3c;}"
            "QPushButton:hover{color:#aeaeb2;border:1px dashed #636366;}"
        )
        custom_col.clicked.connect(self._pick_custom)
        lo.addWidget(custom_col)

        lo.addSpacing(6)
        lo.addWidget(self._hsep())
        lo.addSpacing(4)

        # ── Stroke size ───────────────────────────────────────────────────────
        size_row = QHBoxLayout()
        size_lbl = QLabel("Stroke")
        size_lbl.setStyleSheet("color:#48484a;font-size:9px;font-weight:600;letter-spacing:1px;")
        self._size_val = QLabel("4")
        self._size_val.setStyleSheet("color:#636366;font-size:9px;")
        self._size_val.setAlignment(AA.AlignRight | AA.AlignVCenter)
        size_row.addWidget(size_lbl); size_row.addStretch(); size_row.addWidget(self._size_val)
        lo.addLayout(size_row)
        lo.addSpacing(3)

        self._dot = DotPreview()
        lo.addWidget(self._dot)

        slider = _Slider(Ori.Horizontal)
        slider.setRange(1, 30); slider.setValue(4)
        slider.setStyleSheet(
            "QSlider::groove:horizontal{height:4px;background:#3a3a3c;border-radius:2px;}"
            "QSlider::handle:horizontal{width:13px;height:13px;background:#e5e5e7;"
            "border-radius:7px;margin:-5px 0;}"
            "QSlider::sub-page:horizontal{background:#0A84FF;border-radius:2px;}"
        )
        slider.valueChanged.connect(lambda v: (
            setattr(self.canvas, "pen_width", v),
            self._size_val.setText(str(v)),
            self._dot.set_size(v, QColor(self.canvas.pen_color))
        ))
        lo.addWidget(slider)

        lo.addSpacing(4)

        # ── Text size ─────────────────────────────────────────────────────────
        ts_row = QHBoxLayout()
        ts_lbl = QLabel("Text size")
        ts_lbl.setStyleSheet("color:#48484a;font-size:9px;font-weight:600;letter-spacing:1px;")
        self._ts_val = QLabel("20")
        self._ts_val.setStyleSheet("color:#636366;font-size:9px;")
        self._ts_val.setAlignment(AA.AlignRight | AA.AlignVCenter)
        ts_row.addWidget(ts_lbl); ts_row.addStretch(); ts_row.addWidget(self._ts_val)
        lo.addLayout(ts_row)

        ts_slider = _Slider(Ori.Horizontal)
        ts_slider.setRange(8, 72); ts_slider.setValue(20)
        ts_slider.setStyleSheet(
            "QSlider::groove:horizontal{height:4px;background:#3a3a3c;border-radius:2px;}"
            "QSlider::handle:horizontal{width:13px;height:13px;background:#e5e5e7;"
            "border-radius:7px;margin:-5px 0;}"
            "QSlider::sub-page:horizontal{background:#0A84FF;border-radius:2px;}"
        )
        ts_slider.valueChanged.connect(lambda v: (
            setattr(self.canvas, "font_size", v),
            self._ts_val.setText(str(v)),
        ))
        lo.addWidget(ts_slider)

        lo.addSpacing(6)
        lo.addWidget(self._hsep())
        lo.addSpacing(4)

        # ── Actions ───────────────────────────────────────────────────────────
        shot_btn = QPushButton("  📷  Screenshot")
        shot_btn.setFixedHeight(32)
        shot_btn.setCursor(Cursor.PointingHandCursor)
        shot_btn.setStyleSheet(
            "QPushButton{color:#32D74B;background:rgba(50,215,75,0.1);"
            "border:1px solid rgba(50,215,75,0.3);border-radius:8px;"
            "font-size:13px;text-align:left;}"
            "QPushButton:hover{background:rgba(50,215,75,0.2);"
            "border:1px solid rgba(50,215,75,0.6);}"
        )
        shot_btn.clicked.connect(self._take_screenshot)
        lo.addWidget(shot_btn)

        pause_btn = QPushButton("  ⏸   Pause")
        pause_btn.setFixedHeight(32)
        pause_btn.setCursor(Cursor.PointingHandCursor)
        pause_btn.setToolTip("Hide overlay — resume from system tray or Ctrl+Shift+A")
        pause_btn.setStyleSheet(
            "QPushButton{color:#0A84FF;background:rgba(10,132,255,0.1);"
            "border:1px solid rgba(10,132,255,0.3);border-radius:8px;"
            "font-size:13px;text-align:left;}"
            "QPushButton:hover{background:rgba(10,132,255,0.2);"
            "border:1px solid rgba(10,132,255,0.6);}"
        )
        pause_btn.clicked.connect(self.overlay.toggle)
        lo.addWidget(pause_btn)

        lo.addSpacing(4)
        lo.addWidget(self._hsep())
        lo.addSpacing(4)

        settings_btn = QPushButton("  ⚙   Settings")
        settings_btn.setFixedHeight(30)
        settings_btn.setCursor(Cursor.PointingHandCursor)
        settings_btn.setStyleSheet(
            "QPushButton{color:#636366;background:transparent;border-radius:8px;"
            "font-size:12px;text-align:left;border:none;}"
            "QPushButton:hover{color:#aeaeb2;background:rgba(255,255,255,0.05);}"
        )
        settings_btn.clicked.connect(self._open_settings)
        lo.addWidget(settings_btn)

        for icon, label, fn, danger in [
            ("↩", "Undo",      self.canvas.undo,  False),
            ("↪", "Redo",      self.canvas.redo,  False),
            ("🗑", "Clear all", self.canvas.clear, False),
            ("✕", "Exit",      QApplication.quit, True),
        ]:
            color = "#FF453A" if danger else "#aeaeb2"
            hover = "rgba(255,69,58,0.12)" if danger else "rgba(255,255,255,0.06)"
            btn = QPushButton(f"  {icon}  {label}")
            btn.setFixedHeight(30)
            btn.setCursor(Cursor.PointingHandCursor)
            btn.setStyleSheet(
                f"QPushButton{{color:{color};background:transparent;border-radius:8px;"
                f"font-size:12px;text-align:left;border:none;}}"
                f"QPushButton:hover{{background:{hover};}}"
            )
            btn.clicked.connect(fn)
            lo.addWidget(btn)

        lo.addStretch()
        self._scroll.setWidget(content)
        outer.addWidget(self._scroll)

        self.setFixedWidth(220)
        self.setAttribute(WAtt.WA_OpaquePaintEvent, False)
        self.setStyleSheet("QPushButton,QLabel,QSlider,QWidget{background:transparent;}")
        if not IS_WIN:
            shadow = QGraphicsDropShadowEffect(self)
            shadow.setBlurRadius(32); shadow.setOffset(4, 5)
            shadow.setColor(QColor(0, 0, 0, 200))
            self.setGraphicsEffect(shadow)

    # ── Helpers ────────────────────────────────────────────────────────────────
    def _hsep(self):
        f = QFrame(); f.setFrameShape(QFrame.Shape.HLine); f.setFixedHeight(1)
        f.setStyleSheet("background:rgba(255,255,255,0.06);margin:0;")
        return f

    def _activate(self, tid: str):
        self.canvas.tool = tid
        if tid != "laser":
            self.canvas._laser_pos = None
            self.canvas.update()
        # Laser → blank cursor (only the red dot shows); select → arrow; all else → crosshair
        if tid == "laser":
            self.canvas.setCursor(Qt.CursorShape.BlankCursor)
        elif tid == "select":
            self.canvas.setCursor(Qt.CursorShape.ArrowCursor)
        elif tid == "ocr":
            self.canvas.setCursor(Qt.CursorShape.CrossCursor)
        else:
            self.canvas.setCursor(_cross_cursor())
        for sec in self._sections:
            sec.check_tool(tid)
        sec = self._all_btns.get(tid)
        if sec: sec.expand()

    def _set_swatch(self, hex_c: str, btn: QPushButton):
        self.canvas.pen_color = hex_c
        if self._active_swatch: self._ring_swatch(self._active_swatch, False)
        self._active_swatch = btn
        self._ring_swatch(btn, True)
        self._dot.set_size(self.canvas.pen_width, QColor(hex_c))

    def _ring_swatch(self, btn: QPushButton, on: bool):
        c = btn.toolTip()
        border = "white" if on else "transparent"
        btn.setStyleSheet(
            f"QPushButton{{background:{c};border-radius:5px;border:2.5px solid {border};}}"
            f"QPushButton:hover{{border:2.5px solid rgba(255,255,255,0.7);}}"
        )

    def _take_screenshot(self):
        pixmap = self.canvas.capture_annotated()
        self._shot_bar = ScreenshotBar(pixmap, self.overlay)

    def _pick_custom(self):
        color = QColorDialog.getColor(QColor(self.canvas.pen_color), self, "Custom Color")
        if color.isValid():
            self.canvas.pen_color = color.name()
            if self._active_swatch: self._ring_swatch(self._active_swatch, False)
            self._active_swatch = None
            self._dot.set_size(self.canvas.pen_width, color)

    def _open_settings(self):
        dlg = SettingsDialog(self._settings_mgr, self._hotkey_mgr, self.overlay)
        dlg.exec()

    def _position(self):
        screen_h = QApplication.primaryScreen().availableGeometry().height()
        self._scroll.setMaximumHeight(screen_h - 120)
        self.adjustSize()
        margin = 40 if IS_WIN else 20
        self.move(margin, margin)

    def paintEvent(self, _):
        from PySide6.QtGui import QPainterPath
        p = QPainter(self)
        p.setRenderHint(RHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(QColor(16, 16, 18, 247)))
        path = QPainterPath()
        path.addRoundedRect(0, 0, self.width(), self.height(), 14, 14)
        p.drawPath(path)
        if IS_WIN:
            p.setPen(QPen(QColor(70, 70, 75, 220), 1))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(QRectF(0.5, 0.5, self.width()-1, self.height()-1), 14, 14)
        p.end()

    def mousePressEvent(self, e):
        if e.button() == MB.LeftButton:
            self._drag_pos = e.position().toPoint()

    def mouseMoveEvent(self, e):
        if e.buttons() & MB.LeftButton and self._drag_pos:
            self.move(self.mapToParent(e.position().toPoint() - self._drag_pos))

    def mouseReleaseEvent(self, e):
        self._drag_pos = None


from dock_toolbar import Toolbar   # noqa: E402 — horizontal dock


# ── Overlay window ─────────────────────────────────────────────────────────────
class AnnotationOverlay(QWidget):
    RELEASE_AFTER_MS = 15_000

    def __init__(self, settings_mgr: SettingsManager, hotkey_mgr: HotkeyManager):
        super().__init__(None,
                         WType.WindowStaysOnTopHint |
                         WType.FramelessWindowHint  |
                         WType.Tool)
        self.setAttribute(WAtt.WA_TranslucentBackground)
        self.setAttribute(WAtt.WA_NoSystemBackground)

        self.settings = settings_mgr
        self._hotkeys = hotkey_mgr
        self._passthrough = False
        # Whether the user wants the overlay up at all — the visibility
        # shortcut and the tray put it away. The window itself is only on
        # screen while it has something to do; see sync_window().
        self._wanted = False
        self._pinned = False          # held on screen while a recording runs
        # Hiding a window keeps its buffer; letting go of the native window
        # frees it. Done after a while hidden, so quick toggles stay instant.
        self._release_timer = QTimer(self)
        self._release_timer.setSingleShot(True)
        self._release_timer.setInterval(self.RELEASE_AFTER_MS)
        self._release_timer.timeout.connect(self._release_window)
        self.canvas  = Canvas(self)
        tb = settings_mgr.get("text_box")
        self.canvas.text_box = "bubble" if tb == "bubble" else bool(tb)
        self.canvas.shape_fill = settings_mgr.get("shape_fill") or "none"
        self.canvas.arrow_heads = 2 if settings_mgr.get("arrow_heads") == 2 else 1
        kind = settings_mgr.get("stamp_kind")
        self.canvas.stamp_kind = kind if kind in STAMPS else "check"
        self._held, self._hold_prev = False, 0
        self._hold_timer = QTimer(self)
        self._hold_timer.setInterval(30)
        self._hold_timer.timeout.connect(self._poll_hold)
        self.apply_hold_to_draw()
        self.canvas.eraser_mode = ("pixels" if settings_mgr.get("eraser_mode") == "pixels"
                                   else "shapes")
        self.canvas.fade_ink = bool(settings_mgr.get("fade_ink"))
        self.toolbar = Toolbar(self.canvas, self, settings_mgr, hotkey_mgr)
        self.canvas.setCursor(_cross_cursor())
        self.toolbar.set_mode_shortcut(hotkeys.display(settings_mgr.get("hotkey")))
        self.toolbar.set_record_shortcut(hotkeys.display(settings_mgr.get("rec_hotkey")))
        self.recording = RecordingController(self, settings_mgr)
        self.usage = UsageClock(self, settings_mgr)
        self.toast = Toast()
        self.recording.state_changed.connect(self.toolbar.set_recording)
        self.recording.ticked.connect(self.toolbar.set_record_elapsed)
        self.canvas.shapes_changed.connect(self.sync_window)
        for fx in ("halo", "ripples", "keys"):
            if settings_mgr.get(f"fx_{fx}"):
                self.canvas.set_effect(fx, True)

        # Cover all monitors and react to any display configuration change
        self._fit_to_screens()
        _app = QApplication.instance()
        _app.primaryScreenChanged.connect(self._on_screen_change)
        _app.screenAdded.connect(self._on_screen_change)
        _app.screenRemoved.connect(self._on_screen_change)
        for _s in _app.screens():
            _s.geometryChanged.connect(self._on_screen_change)
            _s.logicalDotsPerInchChanged.connect(self._on_dpi_change)

        # Started at sign-in (Run key --minimized, or the Store package's
        # startup task): stay in the tray until asked.
        if not platform_win.launched_at_startup():
            self._wanted = True
            # The dock is its own window now, so it has to be shown explicitly
            # — and it honours the collapsed-to-a-puck state while doing it.
            self.toolbar.set_chrome_visible(True)
            self.toolbar.raise_chrome()
            # Start out of the way. The app appearing should never be the
            # reason you cannot click something.
            self.set_passthrough(True)
        self.sync_window()

    # ── On screen or not ───────────────────────────────────────────────────────
    @property
    def wanted(self) -> bool:
        return self._wanted

    def sync_window(self):
        """Show the window only while it has a job: drawing mode, marks to
        display, or a recording in progress.

        An empty overlay in click-through mode shows nothing and takes no
        clicks, but a full-desktop, always-on-top transparent window still
        holds a buffer the size of every monitor (a second one on Windows)
        and the compositor blends it over everything on every frame — which
        also stops full-screen games and video from bypassing composition.
        """
        needed = self._wanted and (not self._passthrough
                                   or self.canvas.has_marks() or self._pinned
                                   or self.canvas.board is not None
                                   or self.canvas.effects_on()
                                   or self.canvas.zoom_pix is not None)
        if needed:
            self._release_timer.stop()
        if needed and not self.isVisible():
            self.show()
            # A re-created native window starts without the click-through
            # style, so put the current mode back on it every time.
            _set_click_through(self, self._passthrough)
            self.toolbar.raise_chrome()
        elif not needed and self.isVisible():
            self.hide()
            self._release_timer.start()

    def _release_window(self):
        """Free the full-desktop buffer (and on Windows the layered-window
        surface) of an overlay that has been off screen for a while. The next
        show() creates a fresh native window."""
        if not self.isVisible() and not self._pinned:
            self.destroy(True, True)

    def pin_on_screen(self, on: bool):
        """Keep the window up for a recording, so the capture exclusion is set
        on a window that is actually on screen, as it always was before."""
        self._pinned = on
        self.sync_window()

    # ── Draw ⇄ click-through ───────────────────────────────────────────────────
    @property
    def passthrough(self) -> bool:
        return self._passthrough

    def set_passthrough(self, on: bool):
        """Click-through: marks stay on screen, input goes to what is beneath."""
        if on == self._passthrough:
            return
        self._passthrough = on
        _set_click_through(self, on)
        self.canvas.setAttribute(WAtt.WA_TransparentForMouseEvents, on)
        self.toolbar.set_mode(on)
        if not on:
            self._wanted = True
            self.sync_window()
            self.raise_()
            self.activateWindow()
            self.canvas.setFocus()
            # …and then put the dock back on top of it, or the overlay we just
            # raised swallows every click aimed at a tool.
            self.toolbar.raise_chrome()
        else:
            # Nothing is being pointed at any more; drop the laser dot rather
            # than leaving it frozen mid-screen, and finish any typing.
            self.canvas.finish_editing()
            self.canvas._laser_pos = None
            self.canvas._eraser_pos = None
            self.canvas.update()
            self.sync_window()

    @Slot()
    def toggle_passthrough(self):
        if not self._wanted:              # put away entirely: bring it back armed
            self._wanted = True
            self.toolbar.set_chrome_visible(True)
            self.set_passthrough(False)
            self.sync_window()
            self.toolbar.raise_chrome()
            return
        self.set_passthrough(not self._passthrough)

    # ── Display configuration helpers ──────────────────────────────────────────
    def _fit_to_screens(self):
        """Resize the overlay to cover every connected monitor."""
        from PySide6.QtCore import QRect
        rect = QRect()
        for scr in QApplication.screens():
            rect = rect.united(scr.geometry())
        if rect.isEmpty():
            rect = QApplication.primaryScreen().virtualGeometry()
        self.setGeometry(rect)
        self.canvas.setGeometry(0, 0, rect.width(), rect.height())

    def _on_screen_change(self, *_):
        """Monitor added / removed or geometry changed — refit overlay."""
        # Reconnect DPI signal for any newly added screen
        for scr in QApplication.screens():
            try:
                scr.geometryChanged.disconnect(self._on_screen_change)
                scr.logicalDotsPerInchChanged.disconnect(self._on_dpi_change)
            except RuntimeError:
                pass
            scr.geometryChanged.connect(self._on_screen_change)
            scr.logicalDotsPerInchChanged.connect(self._on_dpi_change)
        self._fit_to_screens()

    def resizeEvent(self, e):
        """Keep the canvas filling the window.

        On Windows the overlay sizes itself to the desktop and is never
        touched again, so _fit_to_screens() was the only path that mattered.
        A Wayland compositor sizes windows itself — Hyprland will happily tile
        this one — and without this the drawing surface keeps its old size
        while the window changes underneath it, which puts every click at the
        wrong coordinates.
        """
        super().resizeEvent(e)
        self.canvas.setGeometry(0, 0, self.width(), self.height())

    def _on_dpi_change(self, *_):
        """DPI changed at runtime (user changed Windows display scale).
        Invalidate the cursor so it's rebuilt at the new pixel density."""
        global _CROSS_CURSOR
        _CROSS_CURSOR = None
        self._fit_to_screens()
        if self.canvas.tool not in {"laser", "select"}:
            self.canvas.setCursor(_cross_cursor())

    def paintEvent(self, _):
        p = QPainter(self)
        p.setCompositionMode(CM.CompositionMode_Clear)
        p.fillRect(self.rect(), QColor(0, 0, 0, 0))
        p.setCompositionMode(CM.CompositionMode_SourceOver)
        if IS_WIN:
            p.fillRect(self.rect(), QColor(0, 0, 0, 1))
        p.end()

    @Slot()
    def activate_ocr(self):
        if not ocr_available():
            return
        if not self._wanted:
            self._wanted = True
            self.toolbar.set_chrome_visible(True)
        self.set_passthrough(False)       # you cannot drag a snip through it
        self.sync_window()
        self.toolbar._activate("ocr")

    @Slot()
    def toggle_recording(self):
        self.recording.toggle()

    # ── marks to a file and back ──────────────────────────────────────────────
    @Slot()
    def save_marks(self):
        shapes = list(self.canvas._shapes)
        if not shapes:
            self.toast.show_message("Nothing to save yet — draw something first",
                                    anchor=self.toolbar)
            return
        folder = self.settings.get("marks_dir") or str(Path.home() / "Documents")
        start = str(Path(folder) / time.strftime("annotations_%Y%m%d_%H%M%S.samarks"))
        path, _ = QFileDialog.getSaveFileName(self, "Save annotations", start, MARKS_FILTER)
        if not path:
            return
        if not path.lower().endswith(".samarks"):
            path += ".samarks"
        try:
            Path(path).write_text(json.dumps(marks_to_json(shapes)), encoding="utf-8")
        except OSError as exc:
            self.toast.show_message(f"Couldn't save the file: {exc.strerror or exc}",
                                    anchor=self.toolbar)
            return
        self.settings.set("marks_dir", str(Path(path).parent))
        self.settings.save()
        self.toast.show_message(f"Saved {len(shapes)} marks — Ctrl+O opens them again",
                                anchor=self.toolbar)

    @Slot()
    def open_marks(self):
        folder = self.settings.get("marks_dir") or str(Path.home() / "Documents")
        path, _ = QFileDialog.getOpenFileName(self, "Open annotations", folder, MARKS_FILTER)
        if not path:
            return
        try:
            shapes = marks_from_json(json.loads(Path(path).read_text(encoding="utf-8")))
        except (OSError, ValueError):
            self.toast.show_message("That file couldn't be opened as annotations",
                                    anchor=self.toolbar)
            return
        self.settings.set("marks_dir", str(Path(path).parent))
        self.settings.save()
        self._wanted = True
        self.canvas.add_marks(shapes)
        self.sync_window()
        self.toast.show_message(f"Opened {len(shapes)} marks — Ctrl+Z takes them away",
                                anchor=self.toolbar)

    # ── hold a key to draw ────────────────────────────────────────────────────
    HOLD_KEYS = {"rctrl": 0xA3, "rshift": 0xA1}     # VK_RCONTROL, VK_RSHIFT

    def apply_hold_to_draw(self):
        if IS_WIN and self.settings.get("hold_to_draw") in self.HOLD_KEYS:
            self._hold_timer.start()
        else:
            self._hold_timer.stop()
            self._held = False

    def _poll_hold(self, key_state=None):
        """Held: drawing. Let go: click-through again, and the app you were
        in gets the keyboard back."""
        vk = self.HOLD_KEYS.get(self.settings.get("hold_to_draw"))
        if vk is None:
            return
        user32 = None
        if IS_WIN:
            import ctypes
            user32 = ctypes.windll.user32
        if key_state is None:
            key_state = lambda v: bool(user32.GetAsyncKeyState(v) & 0x8000)
        down = key_state(vk)
        if down and not self._held and self._passthrough and self._wanted:
            self._held = True
            self._hold_prev = user32.GetForegroundWindow() if user32 else 0
            self.set_passthrough(False)
        elif not down and self._held:
            self._held = False
            self.set_passthrough(True)
            if user32 and self._hold_prev:
                user32.SetForegroundWindow(self._hold_prev)

    @Slot()
    def take_screenshot(self):
        """Pick an area (or click for a whole screen), then Copy / Save."""
        if getattr(self, "_selector", None) is not None:
            return                                  # already picking
        self.canvas.finish_editing()
        sel = RegionSelector(RegionSelector.SHOT_HINT, click_for_screen=True)
        self._selector = sel

        def chosen(rect):
            self._selector = None
            if rect is not None:
                # Give the compositor a moment to take the dimmer off screen.
                QTimer.singleShot(120, lambda: self._shoot(rect))
        sel.chosen.connect(chosen)
        sel.choose()

    def _shoot(self, rect: QRect):
        # What you see is what you get: marks only while they are on screen.
        pixmap = self.canvas.capture_annotated(rect, marks=self._wanted)
        self._shot_bar = ScreenshotBar(pixmap, self)

    @Slot()
    def toggle(self):
        self._wanted = not self._wanted
        self.toolbar.set_chrome_visible(self._wanted)
        self.sync_window()
        if self._wanted:
            if self.isVisible():
                self.raise_()
                self.activateWindow()
            self.toolbar.raise_chrome()

    # ── Whiteboard / presenter effects ─────────────────────────────────────────
    @Slot()
    def cycle_board(self):
        """Open the board (white or dark, as chosen in Settings) on the screen
        under the cursor — or close it. One key, one click."""
        if self.canvas.board is not None:
            self.leave_board()
            return
        style = "black" if self.settings.get("board_style") == "black" else "white"
        scr = QApplication.screenAt(QCursor.pos()) or QApplication.primaryScreen()
        g = scr.geometry()
        rect = QRectF(QPointF(self.canvas.mapFromGlobal(g.topLeft())), QSizeF(g.size()))
        if not self._wanted:
            self._wanted = True
            self.toolbar.set_chrome_visible(True)
        self.set_passthrough(False)              # a board is for drawing on
        self.canvas.set_board(style, rect)
        self.sync_window()
        # The dock comes onto the board, so every tool is right there.
        self.toolbar.move_onto(scr.availableGeometry())
        self.toolbar.raise_chrome()
        self.toast.show_message(
            f"{'Whiteboard' if style == 'white' else 'Dark board'} · page "
            f"{self.canvas._page + 1} of {len(self.canvas._pages)} — "
            "PgDn new page · W or Esc to leave", anchor=self.toolbar)

    def leave_board(self):
        self.canvas.set_board(None)
        self.toolbar.move_back()
        self.sync_window()

    @Slot()
    def toggle_zoom(self):
        """Magnify the screen under the cursor (a still, marks included);
        again, or Esc, to leave."""
        if self.canvas.zoom_pix is not None:
            self.canvas.stop_zoom()
            self.sync_window()
            return
        scr = QApplication.screenAt(QCursor.pos()) or QApplication.primaryScreen()
        g = scr.geometry()
        pix = self.canvas.capture_annotated(g, marks=self._wanted)
        rect = QRectF(QPointF(self.canvas.mapFromGlobal(g.topLeft())), QSizeF(g.size()))
        if not self._wanted:
            self._wanted = True
            self.toolbar.set_chrome_visible(True)
        self.set_passthrough(False)
        self.canvas.start_zoom(pix, rect, QPointF(self.canvas.mapFromGlobal(QCursor.pos())))
        self.sync_window()
        self.toast.show_message("Magnifier — mouse wheel zooms · "
                                "Esc to leave", anchor=self.toolbar)

    def turn_page(self, delta: int):
        page = self.canvas.board_page(delta)
        if page:
            self.toast.show_message(f"Page {page} of {len(self.canvas._pages)}",
                                    anchor=self.toolbar)

    def set_effect(self, name: str, on: bool):
        self.canvas.set_effect(name, on)
        if name in ("halo", "ripples", "keys"):
            self.settings.set(f"fx_{name}", on)
            self.settings.save()
        self.sync_window()

    # ── Destructive actions, made recoverable ──────────────────────────────────
    def clear_marks(self):
        """Clear all — undoable, and it says so, with a button to prove it."""
        n = self.canvas.clear()
        if n:
            self.toast.show_message(
                f"Cleared {n} mark{'s' if n != 1 else ''}", "Undo",
                self.canvas.undo_clear, anchor=self.toolbar)

    @Slot()
    def request_exit(self):
        """Exit, but not by accident: a running recording is finished and saved
        first, and marks on screen (which are not saved anywhere) are asked
        about."""
        if self.recording.active:
            if ConfirmDialog("A recording is running",
                             "Stop it and save the file, then exit?",
                             "Stop, save and exit", self).exec():
                self.recording.stop_and_quit()
            return
        n = len(self.canvas._shapes)
        if n and not ConfirmDialog(
                "Exit Screen Annotator Pro?",
                f"The {n} mark{'s' if n != 1 else ''} on screen will be gone — "
                "they aren't saved anywhere.", "Exit", self).exec():
            return
        QApplication.quit()

    def changeEvent(self, e):
        super().changeEvent(e)
        # Clicking the canvas activates the overlay, and on Windows that lifts
        # it to the front of the always-on-top band — back over the dock. So
        # the dock has to be put back on top every time this window is
        # activated, not just when draw mode is armed. Without this the dock
        # works for exactly one click and then goes dead.
        if e.type() == QEvent.Type.ActivationChange and self.isActiveWindow():
            if hasattr(self, "toolbar"):
                self.toolbar.raise_chrome()

    def keyPressEvent(self, e):
        k = e.key()
        KM = Qt.KeyboardModifier
        mods = e.modifiers() & ~KM.KeypadModifier
        ctrl = bool(mods & KM.ControlModifier)
        chord = bool(mods & (KM.ControlModifier | KM.AltModifier | KM.MetaModifier))

        # A shortcut the system couldn't register globally (Wayland, or taken
        # by another app) still works while the overlay has the keyboard. One
        # that is registered never gets here: Windows takes the key, and on X11
        # the global listener has already fired, so it must not fire twice —
        # which is what the old hard-coded Ctrl+Shift+R here used to do.
        try:
            pressed = QKeySequence(QKeyCombination(mods, Qt.Key(k))).toString()
        except ValueError:
            pressed = ""
        name = self._hotkeys.local_match(pressed) if pressed else None
        if name:
            self._hotkeys.trigger(name)
            return

        if k in (Key.Key_Escape, Key.Key_M) and self.canvas.zoom_pix is not None \
                and not chord:
            self.toggle_zoom()                   # Esc leaves the zoom first
        elif k == Key.Key_M and not chord:
            self.toggle_zoom()
        elif k == Key.Key_Escape and self.canvas.board is not None:
            self.leave_board()                   # first Esc leaves the board
        elif k == Key.Key_Escape:
            # Esc means "stop taking my clicks", not "disappear" — the marks
            # stay up and the dock stays reachable.
            self.set_passthrough(True)
        elif k == Key.Key_W and not chord:
            self.cycle_board()
        elif k == Key.Key_F and not chord:
            self.set_effect("spotlight", not self.canvas.spotlight)
        elif k in (Key.Key_PageDown, Key.Key_PageUp) and self.canvas.board:
            self.turn_page(1 if k == Key.Key_PageDown else -1)
        elif ctrl and k == Key.Key_S:
            self.save_marks()
        elif ctrl and k == Key.Key_O:
            self.open_marks()
        elif ctrl and k in (Key.Key_C, Key.Key_V, Key.Key_D, Key.Key_A):
            cv = self.canvas
            if k == Key.Key_C:
                cv.copy_selection()
            else:
                if cv.tool != "select":         # pasted / selected marks show
                    self.toolbar._activate("select")
                {Key.Key_V: cv.paste, Key.Key_D: cv.duplicate,
                 Key.Key_A: cv.select_all}[k]()
        elif k in (Key.Key_Left, Key.Key_Right, Key.Key_Up, Key.Key_Down) \
                and self.canvas._selection and not ctrl:
            step = 10 if mods & KM.ShiftModifier else 1
            dx = {Key.Key_Left: -step, Key.Key_Right: step}.get(k, 0)
            dy = {Key.Key_Up: -step, Key.Key_Down: step}.get(k, 0)
            self.canvas.move_selection(dx, dy)
        elif k == Key.Key_Z and ctrl:
            self.canvas.undo()
        elif k == Key.Key_Y and ctrl:
            self.canvas.redo()
        elif k == Key.Key_C and not chord:
            self.clear_marks()
        elif k == Key.Key_Delete:
            self.canvas.delete_selected()
        elif k in KEY_TOOL and not chord:
            # Bare letters only: Ctrl+S out of habit is not "switch to Steps".
            self.toolbar._activate(KEY_TOOL[k])


# ── Global hotkey bootstrap ────────────────────────────────────────────────────
def _start_hotkeys(overlay: AnnotationOverlay, hotkey_mgr: HotkeyManager,
                   settings: SettingsManager):
    """Bind every configured shortcut. Callbacks are queued onto the GUI
    thread — pynput calls them from its own thread."""
    from PySide6.QtCore import QMetaObject, Qt as _Qt

    def invoker(slot: str):
        return lambda: QMetaObject.invokeMethod(
            overlay, slot, _Qt.ConnectionType.QueuedConnection)

    slots = {"toggle": "toggle_passthrough", "visibility": "toggle",
             "ocr": "activate_ocr", "record": "toggle_recording",
             "screenshot": "take_screenshot", "zoom": "toggle_zoom"}
    for key, (name, _label) in HOTKEY_SETTINGS.items():
        if name == "ocr" and not ocr_available():
            continue
        hotkey_mgr.bind(name, settings.get(key), invoker(slots[name]))


def _report_taken_hotkeys(tray: QSystemTrayIcon, hotkey_mgr: HotkeyManager,
                          settings: SettingsManager):
    """Say once, at launch, if another app got to a shortcut first — the old
    behavior was a shortcut that silently did nothing."""
    taken = [f"{shortcut_label(settings, key)} ({label})"
             for key, (name, label) in HOTKEY_SETTINGS.items()
             if hotkey_mgr.failures().get(name) == "taken"]
    if taken and QSystemTrayIcon.supportsMessages():
        tray.showMessage(
            "A shortcut is already taken",
            "Another app already uses " + ", ".join(taken) +
            ". Pick a different one in Settings.",
            QSystemTrayIcon.MessageIcon.Warning, 10000)


def _convert_recording(overlay) -> None:
    """Export an older recording — the result panel is long gone by then."""
    start = overlay.recording.config().out_dir
    path, _ = QFileDialog.getOpenFileName(
        overlay, "Choose a recording to convert", start,
        "Video (*.mp4 *.mkv *.webm *.mov);;All files (*)")
    if path:
        ExportDialog(path, 0.0, overlay).exec()


# ── System tray ────────────────────────────────────────────────────────────────
def _setup_tray(overlay: AnnotationOverlay) -> QSystemTrayIcon:
    ico_path = _resource(os.path.join('icons', 'tray.ico'))
    if os.path.exists(ico_path):
        tray_icon = QIcon(ico_path)
    else:
        # fallback: small blue dot (icons not generated yet)
        pix = QPixmap(16, 16)
        pix.fill(QColor(0, 0, 0, 0))
        p = QPainter(pix)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setBrush(QColor("#0A84FF"))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(1, 1, 14, 14)
        p.end()
        tray_icon = QIcon(pix)

    tray = QSystemTrayIcon(tray_icon)
    tray.setToolTip("Screen Annotator Pro — click to show/hide")

    menu = QMenu()
    menu.setStyleSheet(
        "QMenu{background:#1c1c1e;color:#e5e5e7;border:1px solid #3a3a3c;border-radius:8px;}"
        "QMenu::item{padding:6px 20px;}"
        "QMenu::item:selected{background:#0A84FF;border-radius:4px;}"
    )
    show_action = menu.addAction("Show / Hide")
    show_action.triggered.connect(overlay.toggle)

    rec_action = menu.addAction("Start recording")
    rec_action.triggered.connect(overlay.recording.toggle)
    overlay.recording.state_changed.connect(
        lambda on: rec_action.setText("Stop recording" if on
                                      else "Start recording"))

    save_marks_action = menu.addAction("Save annotations…")
    save_marks_action.triggered.connect(overlay.save_marks)
    open_marks_action = menu.addAction("Open annotations…")
    open_marks_action.triggered.connect(overlay.open_marks)
    conv_action = menu.addAction("Convert a recording…")
    conv_action.triggered.connect(lambda: _convert_recording(overlay))

    menu.addSeparator()
    quit_action = menu.addAction("Exit")
    quit_action.triggered.connect(overlay.request_exit)

    tray.setContextMenu(menu)
    tray.activated.connect(
        lambda reason: overlay.toggle()
        if reason == QSystemTrayIcon.ActivationReason.Trigger else None
    )
    tray.show()
    return tray


# ── Entry point ────────────────────────────────────────────────────────────────
def _self_test(overlay, settings_mgr, hotkey_mgr) -> int:
    """`--self-test`: CI launches the *finished* build with this, after the
    spec has stripped everything it thinks is unused. Build every window,
    touch ffmpeg and the Windows integration, then exit — a module or DLL the
    spec dropped by mistake fails here, not on a customer's machine.
    Writes self-test.log to the working directory; the exit code is the verdict."""
    import hashlib
    import traceback
    lines, ok = [f"Screen Annotator Pro {VERSION} self-test"], True

    def check(name, fn):
        nonlocal ok
        try:
            lines.append(f"ok    {name}: {fn()}")
        except Exception:
            ok = False
            lines.append(f"FAIL  {name}\n{traceback.format_exc()}")

    check("ffmpeg", lambda: find_ffmpeg() and ffmpeg_version() or 1 / 0)
    check("hashlib", lambda: hashlib.sha256(b"x").hexdigest()[:12])
    check("packaged", platform_win.is_packaged)
    check("startup", platform_win.startup_status)
    check("hotkeys", lambda: f"{hotkey_mgr.available} {hotkey_mgr.failures()}")
    check("ocr", ocr_available)

    def read_text():
        # Proves the frozen build carries every WinRT module OCR needs.
        if not ocr_win.available():
            return f"windows ocr not available ({ocr_win.languages()})"
        img = QImage(520, 90, QImage.Format.Format_RGB32)
        img.fill(QColor("white"))
        p = QPainter(img)
        p.setPen(QColor("black"))
        p.setFont(QFont("Arial", 28))
        p.drawText(12, 60, "Self test 2026")
        p.end()
        if img.pixelColor(img.width() // 2, img.height() // 2) == QColor("white") \
                and all(img.pixelColor(x, 45).lightness() > 200
                        for x in range(0, 520, 4)):
            raise RuntimeError("couldn't draw the test text (no fonts found)")
        text = ocr_win.recognize(img, "")
        if "2026" not in text:
            raise RuntimeError(f"read {text!r}")
        return repr(text)
    check("windows ocr read", read_text)
    check("settings dialog", lambda: SettingsDialog(settings_mgr, hotkey_mgr,
                                                    overlay).close())
    check("help dialog", lambda: HelpDialog(settings_mgr, overlay).close())
    check("screenshot", lambda: overlay.canvas.capture_annotated().size())
    check("notices", _third_party_notices)
    try:
        with open("self-test.log", "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
    except OSError:
        pass
    print("\n".join(lines))
    return 0 if ok else 1


def main():
    self_test = "--self-test" in sys.argv
    if self_test:
        os.environ["QT_QPA_PLATFORM"] = "offscreen"
        if IS_WIN:
            # Offscreen Qt on Windows finds no fonts unless told where they
            # are, and the OCR check below needs to draw text.
            os.environ.setdefault("QT_QPA_FONTDIR", os.path.join(
                os.environ.get("WINDIR", r"C:\Windows"), "Fonts"))
    # PassThrough: accept fractional scale factors (125 %, 150 %, etc.) on
    # every platform — not just Windows.  Must be called before QApplication().
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )

    app = QApplication(sys.argv)
    app.setApplicationName("Screen Annotator Pro")
    app.setQuitOnLastWindowClosed(False)

    # The icon assets are generated, not committed (see create_icons.py),
    # so a fresh checkout run from source has none yet. Render them once,
    # silently, rather than making the user run a script by hand before the
    # app looks right — a packaged build ships them already and skips this.
    ico_path = _resource(os.path.join('icons', 'annotate.ico'))
    if not os.path.exists(ico_path) and not hasattr(sys, '_MEIPASS'):
        try:
            import create_icons
            create_icons.main(quiet=True)
        except Exception:
            pass  # best effort — worst case the app runs with default icons

    # App-wide icon — every window (Settings, Help, the OCR result window's
    # real title bar, Alt-Tab/taskbar entries) picks this up unless it sets
    # its own. The system tray icon is set separately in _setup_tray().
    if os.path.exists(ico_path):
        app.setWindowIcon(QIcon(ico_path))

    settings_mgr = SettingsManager()
    _apply_dlg_theme(settings_mgr.get("theme"))
    # Must happen before the dock is constructed — every widget on it reads
    # these sizes as it is built.
    import dock_toolbar
    dock_toolbar.set_dock_scale(settings_mgr.get("dock_scale"))

    # Touch ffmpeg once, in the background, before anyone presses Record.
    # The bundled binary is ~146 MB and the first spawn of it on a fresh
    # machine pays for an antivirus scan — several seconds of it, on whatever
    # thread asked. Paying that here means Record starts promptly instead of
    # freezing the overlay at exactly the wrong moment.
    threading.Thread(target=ffmpeg_version, daemon=True,
                     name="ffmpeg-warmup").start()
    hotkey_mgr   = HotkeyManager()
    overlay      = AnnotationOverlay(settings_mgr, hotkey_mgr)
    tray         = _setup_tray(overlay)
    _start_hotkeys(overlay, hotkey_mgr, settings_mgr)
    _report_taken_hotkeys(tray, hotkey_mgr, settings_mgr)

    # Safety net: catches any exit path that isn't already covered by the
    # dock's own save-on-drag/-collapse/-expand calls.
    app.aboutToQuit.connect(overlay.toolbar._save_dock_state)
    app.aboutToQuit.connect(overlay.usage.flush)
    app.aboutToQuit.connect(hotkey_mgr.stop)
    hints = HintSwitch(settings_mgr)            # Settings → General → hints
    app.installEventFilter(hints)

    if self_test:
        code = _self_test(overlay, settings_mgr, hotkey_mgr)
        hotkey_mgr.stop()
        sys.exit(code)
    # Held here: a parentless window with no reference is collected at once.
    overlay._welcome = None
    QTimer.singleShot(900, lambda: setattr(overlay, "_welcome",
                                           maybe_show_welcome(overlay)))
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
