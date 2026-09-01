#!/usr/bin/env python3
"""
Screen Annotation Tool  (PyQt6)
================================
Fullscreen transparent overlay — draw on your screen like a whiteboard.

Tools: Select, Pen, Line, Arrow, Rectangle, Circle, Ruler,
       Text, Callout, Steps, Highlight, Eraser,
       Blur, Pixelate, Redact, Laser Pointer

Install:  pip install PyQt6
Run:      python annotate.py
Exit:     Esc or ✕ in toolbar

Windows notes
─────────────
• Requires Windows 10/11 with Desktop Window Manager (DWM) enabled for
  transparent compositing.  Works in both light and dark mode.
• Global hotkey (Ctrl+Shift+A) requires:  pip install pynput
• High-DPI monitors are handled automatically.
"""

import sys, os, json, math, random as _rng, shutil, subprocess, threading, platform
from pathlib import Path
from PyQt6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QPushButton, QSlider, QLabel, QColorDialog, QGraphicsDropShadowEffect,
    QGraphicsBlurEffect, QGraphicsScene, QGraphicsPixmapItem,
    QFrame, QSystemTrayIcon, QMenu, QFileDialog,
    QDialog, QCheckBox, QTextEdit, QComboBox, QScrollArea, QProgressBar,
    QLineEdit,
)
from PyQt6.QtCore import (
    Qt, QObject, QPoint, QPointF, QRect, QRectF, QUrl, QThread, QTimer,
    QKeyCombination,
    pyqtSignal, pyqtSlot,
)
from PyQt6.QtGui import (
    QPainter, QPen, QColor, QFont, QBrush,
    QPolygonF, QPainterPath, QFontMetrics, QPixmap, QCursor, QIcon,
    QKeySequence, QDesktopServices,
)

from video_recorder import (
    FFMPEG_HELP, QUALITY_PRESETS, RecordConfig, ScreenRecorder,
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
VERSION = "4.0.0"

# ── Platform detection ─────────────────────────────────────────────────────────
IS_WIN = platform.system() == "Windows"
IS_MAC = platform.system() == "Darwin"

# ── Settings ───────────────────────────────────────────────────────────────────
_DEFAULT_SETTINGS: dict = {
    # Switches drawing on and off — the one you reach for constantly.
    "hotkey":         "<ctrl>+<shift>+a",
    # Takes the overlay off the screen entirely, marks and all.
    "visibility_hotkey": "<ctrl>+<shift>+h",
    "ocr_hotkey":    "<ctrl>+t",
    "start_on_boot":  False,
    "theme":          "light",
    # Where you last put the dock (or the collapsed puck) — None means
    # "never moved, use the default resting spot".
    # 1.0 is the original dock size; smaller fits a dock that runs off the
    # edge on a small or unscalable display.
    "dock_scale":     0.80,
    "dock_collapsed": False,
    "dock_x":         None,
    "dock_y":         None,
    # ── Recording ──────────────────────────────────────────────────────────
    "rec_hotkey":     "<ctrl>+<shift>+r",
    "rec_fps":        30,
    "rec_quality":    "balanced",      # high | balanced | small
    "rec_area":       "all",           # all | screen | region
    "rec_cursor":     True,
    "rec_audio":      False,
    "rec_audio_dev":  "",              # "" = system default input
    "rec_dir":        "",              # "" = Videos/ScreenAnnotatorPro
    "rec_chrome_notice_seen": False,   # the "dock hides while recording" note
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
        self._load()

    def _load(self):
        if self._path.exists():
            try:
                saved = json.loads(self._path.read_text(encoding="utf-8"))
                self._data = {**_DEFAULT_SETTINGS, **saved}
            except Exception:
                pass

    def save(self):
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps(self._data, indent=2), encoding="utf-8")

    def get(self, key):
        return self._data.get(key, _DEFAULT_SETTINGS.get(key))

    def set(self, key, value):
        self._data[key] = value


# ── Hotkey format helpers ──────────────────────────────────────────────────────

def _pynput_to_ks(s: str) -> str:
    """'<ctrl>+<shift>+a' → 'Ctrl+Shift+A' for QKeySequence."""
    out = []
    for p in s.split("+"):
        p = p.strip()
        if p == "<ctrl>":    out.append("Ctrl")
        elif p == "<shift>": out.append("Shift")
        elif p == "<alt>":   out.append("Alt")
        elif p == "<cmd>":   out.append("Meta")
        else:                out.append(p.upper())
    return "+".join(out)

def _ks_to_pynput(s: str) -> str:
    """'Ctrl+Shift+A' → '<ctrl>+<shift>+a' for pynput."""
    out = []
    for p in s.split("+"):
        p = p.strip()
        low = p.lower()
        if low == "ctrl":    out.append("<ctrl>")
        elif low == "shift": out.append("<shift>")
        elif low == "alt":   out.append("<alt>")
        elif low == "meta":  out.append("<cmd>")
        else:                out.append(low)
    return "+".join(out)


# ── Boot-startup helpers (Windows registry) ───────────────────────────────────

def _startup_exe() -> str:
    return sys.executable if getattr(sys, "frozen", False) else os.path.abspath(__file__)

def _set_startup(enable: bool):
    if not IS_WIN:
        return
    try:
        import winreg
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Run",
            0, winreg.KEY_SET_VALUE | winreg.KEY_READ,
        )
        if enable:
            winreg.SetValueEx(key, "ScreenAnnotatorPro", 0,
                              winreg.REG_SZ, f'"{_startup_exe()}" --minimized')
        else:
            try:
                winreg.DeleteValue(key, "ScreenAnnotatorPro")
            except FileNotFoundError:
                pass
        winreg.CloseKey(key)
    except Exception as e:
        pass  # registry write failed — non-fatal

def _is_startup_enabled() -> bool:
    if not IS_WIN:
        return False
    try:
        import winreg
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                             r"Software\Microsoft\Windows\CurrentVersion\Run")
        winreg.QueryValueEx(key, "ScreenAnnotatorPro")
        winreg.CloseKey(key)
        return True
    except (FileNotFoundError, OSError):
        return False


# ── Hotkey manager ─────────────────────────────────────────────────────────────

class HotkeyManager:
    """Global hotkeys, kept as one named table.

    pynput can only hold one listener at a time, so every binding lives in
    `_binds` and any change rebuilds the single listener from all of them.
    """

    def __init__(self):
        self._listener = None
        self._binds: dict[str, tuple[str, object]] = {}   # name → (combo, cb)

    def bind(self, name: str, pynput_str: str, callback):
        self._binds[name] = (pynput_str, callback)
        self._restart()

    def rebind(self, name: str, pynput_str: str):
        if name in self._binds:
            self._binds[name] = (pynput_str, self._binds[name][1])
            self._restart()

    # Named wrappers — the call sites read better than bind("ocr", …) would.
    def start(self, pynput_str: str, callback):
        self.bind("toggle", pynput_str, callback)

    def update(self, pynput_str: str):
        self.rebind("toggle", pynput_str)

    def start_ocr(self, pynput_str: str, callback):
        self.bind("ocr", pynput_str, callback)

    def update_ocr(self, pynput_str: str):
        self.rebind("ocr", pynput_str)

    def start_visibility(self, pynput_str: str, callback):
        self.bind("visibility", pynput_str, callback)

    def update_visibility(self, pynput_str: str):
        self.rebind("visibility", pynput_str)

    def start_rec(self, pynput_str: str, callback):
        self.bind("record", pynput_str, callback)

    def update_rec(self, pynput_str: str):
        self.rebind("record", pynput_str)

    def _restart(self):
        if self._listener:
            try: self._listener.stop()
            except Exception: pass
            self._listener = None
        on_wayland = (os.environ.get("WAYLAND_DISPLAY") or
                      os.environ.get("XDG_SESSION_TYPE", "").lower() == "wayland")
        if on_wayland:
            return
        mapping = {combo: cb for combo, cb in self._binds.values() if combo and cb}
        if not mapping:
            return
        try:
            from pynput import keyboard as kb
            self._listener = kb.GlobalHotKeys(mapping)
            self._listener.daemon = True
            self._listener.start()
        except (ImportError, Exception):
            pass

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
    Key.Key_E: "eraser", Key.Key_J: "ocr",
}

DRAG_TOOLS  = {"line","arrow","rect","circle","ruler","highlight","blur","pixel","redact"}
POINT_TOOLS = {"text","callout","steps"}
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
class Shape:
    def draw(self, p: QPainter): pass
    def move(self, dx: float, dy: float): pass
    def bounding_rect(self) -> QRectF: return QRectF()
    def contains(self, pt: QPointF) -> bool: return self.bounding_rect().contains(pt)


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
        else:
            for i in range(1, len(self.pts)):
                p.drawLine(self.pts[i-1], self.pts[i])

    def move(self, dx, dy):
        self.pts = [QPointF(pt.x()+dx, pt.y()+dy) for pt in self.pts]

    def bounding_rect(self):
        if not self.pts: return QRectF()
        xs = [pt.x() for pt in self.pts]; ys = [pt.y() for pt in self.pts]
        return QRectF(min(xs), min(ys), max(xs)-min(xs), max(ys)-min(ys))


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


class ArrowShape(Shape):
    def __init__(self, p1, p2, color, width):
        self.p1, self.p2, self.color, self.width = p1, p2, color, width

    def draw(self, p):
        p.setRenderHint(RHint.Antialiasing)
        p.setPen(_pen(self.color, self.width))
        p.setBrush(QBrush(QColor(self.color)))
        p.drawLine(self.p1, self.p2)
        poly = _arrowhead(self.p1, self.p2, max(self.width*3.5, 14))
        if not poly.isEmpty(): p.drawPolygon(poly)

    def move(self, dx, dy):
        self.p1 = QPointF(self.p1.x()+dx, self.p1.y()+dy)
        self.p2 = QPointF(self.p2.x()+dx, self.p2.y()+dy)

    def bounding_rect(self): return _norm(self.p1, self.p2).adjusted(-20,-20,20,20)


class RectShape(Shape):
    def __init__(self, p1, p2, color, width):
        self.p1, self.p2, self.color, self.width = p1, p2, color, width

    def draw(self, p):
        p.setRenderHint(RHint.Antialiasing)
        p.setPen(_pen(self.color, self.width))
        p.setBrush(BS.NoBrush)
        p.drawRect(_norm(self.p1, self.p2))

    def move(self, dx, dy):
        self.p1 = QPointF(self.p1.x()+dx, self.p1.y()+dy)
        self.p2 = QPointF(self.p2.x()+dx, self.p2.y()+dy)

    def bounding_rect(self): return _norm(self.p1, self.p2)


class CircleShape(Shape):
    def __init__(self, p1, p2, color, width):
        self.p1, self.p2, self.color, self.width = p1, p2, color, width

    def draw(self, p):
        p.setRenderHint(RHint.Antialiasing)
        p.setPen(_pen(self.color, self.width))
        p.setBrush(BS.NoBrush)
        p.drawEllipse(_norm(self.p1, self.p2))

    def move(self, dx, dy):
        self.p1 = QPointF(self.p1.x()+dx, self.p1.y()+dy)
        self.p2 = QPointF(self.p2.x()+dx, self.p2.y()+dy)

    def bounding_rect(self): return _norm(self.p1, self.p2)


class RulerShape(Shape):
    def __init__(self, p1, p2, color, width):
        self.p1, self.p2, self.color, self.width = p1, p2, color, width

    def draw(self, p):
        p.setRenderHint(RHint.Antialiasing)
        p.setPen(_pen(self.color, self.width))
        p.drawLine(self.p1, self.p2)
        dx, dy = self.p2.x()-self.p1.x(), self.p2.y()-self.p1.y()
        length = math.hypot(dx, dy)
        if length < 1: return
        nx, ny = -dy/length, dx/length
        tick = 8
        for pt in (self.p1, self.p2):
            p.drawLine(QPointF(pt.x()+nx*tick, pt.y()+ny*tick),
                       QPointF(pt.x()-nx*tick, pt.y()-ny*tick))
        label = f"{round(length)} px"
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


class TextShape(Shape):
    def __init__(self, pos, text, color, size):
        self.pos, self.text, self.color, self.size = pos, text, color, size

    def draw(self, p):
        p.setRenderHint(RHint.Antialiasing)
        p.setFont(QFont("Arial", self.size, QFont.Weight.Bold))
        p.setPen(QPen(QColor(self.color)))
        p.drawText(self.pos, self.text)

    def move(self, dx, dy): self.pos = QPointF(self.pos.x()+dx, self.pos.y()+dy)

    def bounding_rect(self):
        fm = QFontMetrics(QFont("Arial", self.size))
        return QRectF(self.pos.x(), self.pos.y()-fm.height(),
                      fm.horizontalAdvance(self.text)+4, fm.height()+4)


class CalloutShape(Shape):
    """Filled circle with auto-incrementing number."""
    def __init__(self, pos, number, color):
        self.pos, self.number, self.color, self.r = pos, number, color, 16

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
    def __init__(self, pos, number, color):
        self.pos, self.number, self.color, self.r = pos, number, color, 16

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
    def __init__(self, p1, p2):
        self.p1, self.p2 = p1, p2

    def draw(self, p):
        rect = _norm(self.p1, self.p2)
        pz = getattr(self, "size", 12)
        rng = _rng.Random(int(rect.left()*100 + rect.top()))
        p.setPen(PS.NoPen)
        x = rect.left()
        while x < rect.right():
            y = rect.top()
            while y < rect.bottom():
                g = rng.randint(80, 210)
                p.setBrush(QBrush(QColor(g, g, g, 220)))
                p.drawRect(QRectF(x, y, min(pz, rect.right()-x), min(pz, rect.bottom()-y)))
                y += pz
            x += pz
        p.setPen(QPen(QColor(150,150,150,180), 1, PS.DashLine))
        p.setBrush(BS.NoBrush); p.drawRect(rect)

    def move(self, dx, dy):
        self.p1 = QPointF(self.p1.x()+dx, self.p1.y()+dy)
        self.p2 = QPointF(self.p2.x()+dx, self.p2.y()+dy)

    def bounding_rect(self): return _norm(self.p1, self.p2)


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


# ── Canvas ─────────────────────────────────────────────────────────────────────
class Canvas(QWidget):
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

        self._shapes:      list[Shape] = []
        self._redo_stack:  list[Shape] = []
        self._selected:    Shape | None = None
        self._drag_last    = QPointF()

        self._drawing      = False
        self._start        = QPointF()
        self._cur          = QPointF()
        self._pen_shape:   PenShape | None = None
        self._eraser_shape = None   # filled when tool == "eraser"

        self._callout_n  = 1
        self._step_n     = 1

        # Laser pointer — tracks mouse position, never commits to _shapes
        self._laser_pos: QPointF | None = None

    def mousePressEvent(self, e):
        if e.button() != MB.LeftButton: return
        pos = QPointF(e.pos())
        self._start = self._cur = pos
        self._drawing = True

        if self.tool == "laser":
            self._laser_pos = pos
            self.update(); return

        if self.tool == "select":
            self._selected = None
            for s in reversed(self._shapes):
                if s.contains(pos):
                    self._selected = s
                    self._drag_last = pos
                    break
            self.update(); return

        if self.tool == "pen":
            self._pen_shape = PenShape(_with_alpha(self.pen_color, self.pen_alpha), self.pen_width)
            self._pen_shape.pts.append(pos); return

        if self.tool == "eraser":
            self._eraser_shape = EraserShape(max(self.pen_width * 4, 20))
            self._eraser_shape.pts.append(pos); return

        if self.tool in POINT_TOOLS:
            self._place_point(pos)
            self._drawing = False; return

    def mouseMoveEvent(self, e):
        pos = QPointF(e.pos())

        # Laser tracks freely — no button held needed
        if self.tool == "laser":
            self._laser_pos = pos
            self.update(); return

        if not (e.buttons() & MB.LeftButton): return
        self._cur = pos

        if self.tool == "select" and self._selected:
            self._selected.move(pos.x()-self._drag_last.x(), pos.y()-self._drag_last.y())
            self._drag_last = pos
            self.update(); return

        if self.tool == "pen" and self._pen_shape:
            self._pen_shape.pts.append(pos)
            self.update(); return

        if self.tool == "eraser" and self._eraser_shape:
            self._eraser_shape.pts.append(pos)
            self.update(); return

        if self.tool in DRAG_TOOLS or self.tool == "ocr":
            self.update()

    def mouseReleaseEvent(self, e):
        if e.button() != MB.LeftButton or not self._drawing: return
        self._drawing = False
        pos = QPointF(e.pos()); self._cur = pos

        if self.tool == "laser":
            return  # laser never commits shapes

        if self.tool == "pen" and self._pen_shape:
            if len(self._pen_shape.pts) > 1:
                self._commit(self._pen_shape)
            self._pen_shape = None
            self.update(); return

        if self.tool == "eraser" and self._eraser_shape:
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
                    raw = self._grab_behind(rect)
                    blurred = _blur_pixmap(raw, getattr(self, "blur_radius", 18))
                    self._commit(BlurShape(self._start, pos, blurred))
            else:
                s = self._make_drag(self._start, pos)
                if s: self._commit(s)

    def _place_point(self, pos: QPointF):
        col = _with_alpha(self.pen_color, self.pen_alpha)
        t = self.tool
        if t == "text":
            dlg = TextInputDialog(self.window())
            if dlg.exec() == QDialog.DialogCode.Accepted:
                text = dlg.text()
                if text:
                    self._commit(TextShape(pos, text, col, self.font_size))
        elif t == "callout":
            self._commit(CalloutShape(pos, self._callout_n, col))
            self._callout_n += 1
        elif t == "steps":
            self._commit(StepShape(pos, self._step_n, col))
            self._step_n += 1

    def _make_drag(self, p1: QPointF, p2: QPointF) -> Shape | None:
        if abs(p2.x()-p1.x()) < 3 and abs(p2.y()-p1.y()) < 3: return None
        col   = _with_alpha(self.pen_color, self.pen_alpha)
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
        if t == "arrow":     return ArrowShape(p1, p2, col, self.pen_width)
        if t == "rect":      return RectShape(p1, p2, col, self.pen_width)
        if t == "circle":    return CircleShape(p1, p2, col, self.pen_width)
        if t == "ruler":     return RulerShape(p1, p2, col, self.pen_width)
        if t == "highlight": return HighlightShape(p1, p2, col)
        if t == "blur":      return BlurShape(p1, p2)
        if t == "pixel":
            s = PixelShape(p1, p2)
            s.size = getattr(self, "pixel_size", 12)
            return s
        if t == "redact":    return RedactShape(p1, p2)
        return None

    def capture_annotated(self) -> QPixmap:
        """Grab the desktop behind the overlay and composite all shapes on top."""
        overlay = self.window()
        overlay.setWindowOpacity(0.0)
        QApplication.processEvents()
        sr = QApplication.primaryScreen().virtualGeometry()
        bg = QApplication.primaryScreen().grabWindow(
            0, sr.x(), sr.y(), sr.width(), sr.height()
        )
        overlay.setWindowOpacity(1.0)

        p = QPainter(bg)
        p.setRenderHint(RHint.Antialiasing)
        # grabWindow returns a pixmap at physical resolution (DPR ≥ 1).
        # Our shapes are stored in logical pixels (canvas coordinates).
        # Scaling the painter by DPR maps logical → physical so annotations
        # align perfectly with the screenshot at 125 %, 150 %, 200 %, 400 % etc.
        ratio = bg.devicePixelRatio()
        if ratio != 1.0:
            p.scale(ratio, ratio)
        for shape in self._shapes:
            shape.draw(p)
        p.end()
        return bg

    def _commit(self, shape: Shape):
        """Append a shape and clear the redo stack."""
        self._shapes.append(shape)
        self._redo_stack.clear()
        self.update()

    def undo(self):
        if self._shapes:
            self._redo_stack.append(self._shapes.pop())
            self.update()

    def redo(self):
        if self._redo_stack:
            self._shapes.append(self._redo_stack.pop())
            self.update()

    def clear(self):
        self._shapes.clear()
        self._redo_stack.clear()
        self._callout_n = self._step_n = 1
        self._selected = None
        self.update()

    def _grab_behind(self, rect: QRectF) -> QPixmap:
        overlay = self.window()
        overlay.setWindowOpacity(0.0)
        QApplication.processEvents()
        r = rect.toRect()
        pix = QApplication.primaryScreen().grabWindow(
            0, r.x(), r.y(), max(r.width(), 1), max(r.height(), 1)
        )   # grabWindow with explicit coords works across the virtual desktop
        overlay.setWindowOpacity(1.0)
        return pix

    def paintEvent(self, _):
        p = QPainter(self)
        p.setCompositionMode(CM.CompositionMode_Clear)
        p.fillRect(self.rect(), Qt.GlobalColor.transparent)
        p.setCompositionMode(CM.CompositionMode_SourceOver)
        if IS_WIN:
            p.fillRect(self.rect(), QColor(0, 0, 0, 1))
        self.render_annotations(p)
        p.end()

    def render_annotations(self, p: QPainter, *, selection: bool = True):
        """Paint every mark onto `p` — committed shapes, the stroke in
        progress, the drag preview, the laser dot.

        The overlay paints itself with this, and the video recorder paints the
        same content onto every captured frame. One code path, so a recording
        can never disagree with what the presenter had on screen. The selection
        outline is the one thing a recording leaves out: it is an editing
        affordance, not an annotation.
        """
        p.setRenderHint(RHint.Antialiasing)
        for shape in self._shapes: shape.draw(p)
        if self.tool == "pen"    and self._pen_shape:    self._pen_shape.draw(p)
        if self.tool == "eraser" and self._eraser_shape: self._eraser_shape.draw(p)
        if self.tool == "ocr" and self._drawing:
            # Dashed blue selection rectangle while user drags the snip area
            p.setRenderHint(RHint.Antialiasing)
            p.setPen(QPen(QColor("#0A84FF"), 2, PS.DashLine))
            p.setBrush(QBrush(QColor(10, 132, 255, 18)))
            p.drawRect(_norm(self._start, self._cur))
        if self._drawing and self.tool in DRAG_TOOLS:
            preview = self._make_drag(self._start, self._cur)
            if preview: preview.draw(p)
        if selection and self._selected:
            p.setPen(QPen(QColor("#0A84FF"), 1, PS.DashLine))
            p.setBrush(BS.NoBrush)
            p.drawRect(self._selected.bounding_rect().adjusted(-3,-3,3,3))

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


# ── Screenshot result bar ─────────────────────────────────────────────────────
class ScreenshotBar(QWidget):
    """Floating panel shown after capture: Copy | Save PNG | Discard"""
    def __init__(self, pixmap: QPixmap, parent: QWidget):
        super().__init__(parent)
        self.setAttribute(WAtt.WA_NoSystemBackground, True)
        self._pixmap = pixmap
        self._build()
        self.adjustSize()
        # Centering on parent (the overlay, which spans every monitor's
        # combined bounding box) can land this in a gap or seam on a
        # non-trivial layout — same bug Settings/Help had. This widget is a
        # child, not a top-level window, so `move()` is parent-local: convert
        # display 1's global center into the overlay's local coordinates.
        geo = QApplication.primaryScreen().availableGeometry()
        local_center = parent.mapFromGlobal(geo.center())
        self.move(local_center.x() - self.width()  // 2,
                  local_center.y() - self.height() // 2)
        self.show()
        self.raise_()

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

    def _copy(self):
        QApplication.clipboard().setPixmap(self._pixmap)
        self.close()

    def _save(self):
        from datetime import datetime
        import os
        default = os.path.expanduser(
            f"~/annotation_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
        )
        path, _ = QFileDialog.getSaveFileName(self, "Save Screenshot", default,
                                              "PNG Images (*.png)")
        if path:
            if not path.lower().endswith(".png"):
                path += ".png"
            self._pixmap.save(path, "PNG")
        self.close()

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


class RegionSelector(QWidget):
    """Full-desktop dimmer: drag out the rectangle to record.

    Its own top-level window rather than a mode on the canvas — the canvas is
    busy being a drawing surface, and a recording area is chosen before the
    recorder (and its capture exclusions) exist.
    """

    chosen = pyqtSignal(object)          # QRect in global coords, or None

    def __init__(self):
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
            self._start = self._cur = None   # too small to be deliberate
            self.update()
            return
        self._finish(QRect(r.topLeft() + self._origin, r.size()))

    def keyPressEvent(self, e):
        if e.key() == Key.Key_Escape:
            self._finish(None)

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

        hint = "Drag the area you want to record   ·   Esc to cancel"
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
        super().__init__(parent)
        self.setAttribute(WAtt.WA_NoSystemBackground, True)
        self._path = path
        self._duration = duration
        self._build()
        self.adjustSize()
        geo = QApplication.primaryScreen().availableGeometry()
        local = parent.mapFromGlobal(geo.center())
        self.move(local.x() - self.width() // 2, local.y() - self.height() // 2)
        self.show()
        self.raise_()

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

        row = QHBoxLayout()
        row.setSpacing(8)
        for label, fn, primary in [
            ("Play",           self._play,   True),
            ("Export…",        self._export, False),
            ("Show in folder", self._reveal, False),
            ("Save as…",       self._save_as, False),
            ("Delete",         self._delete, False),
        ]:
            b = QPushButton(label)
            b.setFixedHeight(34)
            b.setCursor(Cursor.PointingHandCursor)
            b.setStyleSheet(_dlg_button_style(primary))
            b.clicked.connect(fn)
            row.addWidget(b)
        lo.addLayout(row)

    def _play(self):
        QDesktopServices.openUrl(QUrl.fromLocalFile(self._path))
        self.close()

    def _export(self):
        ExportDialog(self._path, self._duration, self.parent()).exec()

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
        try:
            os.remove(self._path)
        except OSError:
            pass
        self.close()

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


class RecordingController(QObject):
    """Everything the rest of the app needs to know about recording.

    The dock, the tray menu and the global hotkey all call `toggle()`; they
    never touch the recorder, the HUD or ffmpeg directly.
    """

    state_changed = pyqtSignal(bool)     # True while a recording is running
    ticked        = pyqtSignal(float)    # elapsed seconds

    def __init__(self, overlay: "AnnotationOverlay", settings: SettingsManager):
        super().__init__(overlay)
        self.overlay   = overlay
        self._settings = settings
        self._hud: RecordingHUD | None = None
        self._duration = 0.0
        self._dock_hidden = False
        self._dock_parked = False

        self.recorder = ScreenRecorder(self)
        self.recorder.tick.connect(self._on_tick)
        self.recorder.finishing.connect(self._on_finishing)
        self.recorder.finished.connect(self._on_finished)
        self.recorder.failed.connect(self._on_failed)

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
    @pyqtSlot()
    def toggle(self):
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
                    self._begin(cfg, native)
                return
            sel = RegionSelector()
            sel.chosen.connect(lambda r: self._begin(cfg, r) if r else None)
            sel.choose()
            return
        region = screen_under_cursor() if cfg.area == "screen" else None
        self._begin(cfg, region)

    def _begin(self, cfg: RecordConfig, region):
        # On Windows the app's own windows are excluded from the capture, so
        # the dock and the HUD can stay exactly where they are. Everywhere
        # else, anything on screen lands in the file — so the chrome has to get
        # out of the frame *before* the first one is grabbed.
        in_frame = not can_exclude_from_capture()
        rect = region if region and region.isValid() else virtual_desktop_rect()

        # The dock is a separate top-level window since click-through landed,
        # so excluding the overlay no longer covers it.
        exclude = [self.overlay] + self.overlay.toolbar.chrome_windows()
        if in_frame:
            self._clear_chrome(rect)
        else:
            hud = RecordingHUD(self)
            hud.place()
            hud.allow_pause(not cfg.audio)
            hud.show()
            hud.raise_()
            self._hud = hud
            exclude.append(hud)

        ok = self.recorder.start(self.overlay.canvas, self.overlay, cfg, region,
                                 exclude=tuple(exclude))
        if not ok:
            self._teardown_hud()
            self._restore_chrome()
            return
        self._duration = 0.0
        self.state_changed.emit(True)

    def _clear_chrome(self, rect: QRect):
        """Get the dock out of the recorded area, hiding it if there is no
        room left. There is no HUD in this mode — the dock's own Record cell
        turns red, counts up and stops the recording, so a second timer would
        only be one more thing to keep out of frame."""
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
            "To stop: press Ctrl+Shift+R, or use the tray icon → Stop "
            "recording.\n\n"
            "Recording an area instead of the whole screen keeps the dock "
            "on screen and out of the frame.",
            self.overlay).exec()

    @pyqtSlot()
    def stop(self):
        if not self.active:
            return
        self._duration = self.recorder.elapsed()
        self.recorder.stop()

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
        RecordingBar(path, self._duration, self.overlay)

    def _on_failed(self, message: str):
        self._teardown_hud()
        self._restore_chrome()
        self.state_changed.emit(False)
        NoticeDialog("Recording stopped", message, self.overlay).exec()

    def _restore_chrome(self):
        """Put back only what we took away — the dock may legitimately be
        collapsed to its puck, or the overlay hidden with Esc, and neither
        should be undone by a recording ending. The result panel is a child
        of the overlay, though, so that much has to come back."""
        if self._dock_hidden:
            self.overlay.toolbar.set_chrome_visible(True)
            self._dock_hidden = False
        if self._dock_parked:
            self.overlay.toolbar.restore_from_parking()
            self._dock_parked = False
        if not self.overlay.isVisible():
            self.overlay.show()
            self.overlay.raise_()

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
    show a single key(+modifiers) combo, capture the next one on a
    keypress — and exposes it the same way (`.keySequence()`), so nothing
    else about SettingsDialog needs to change.
    """
    _IGNORED = {
        Qt.Key.Key_Shift, Qt.Key.Key_Control, Qt.Key.Key_Alt,
        Qt.Key.Key_Meta, Qt.Key.Key_AltGr, Qt.Key.Key_CapsLock,
        Qt.Key.Key_unknown,
    }

    def __init__(self, initial: QKeySequence, parent=None):
        super().__init__(parent)
        self.setReadOnly(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._seq = initial
        self._refresh()

    def _refresh(self):
        self.setText(self._seq.toString())

    def keySequence(self) -> QKeySequence:
        return self._seq

    def keyPressEvent(self, e):
        key = Qt.Key(e.key())
        if key in self._IGNORED:
            e.accept()
            return
        self._seq = QKeySequence(QKeyCombination(e.modifiers(), key))
        self._refresh()
        e.accept()


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


# ── Text tool input ───────────────────────────────────────────────────────────
class TextInputDialog(QDialog):
    """Flat replacement for QInputDialog.getText() — the native version was
    the one popup still in the old grey/rounded style. Same shape as the
    other dialogs: ground/ink chrome, square corners, centered on display 1."""

    def __init__(self, parent=None):
        super().__init__(parent,
                         WType.FramelessWindowHint | WType.WindowStaysOnTopHint)
        self.setAttribute(WAtt.WA_TranslucentBackground)
        self._build()
        self.setFixedWidth(320)
        self.adjustSize()
        _center_on_display1(self)

    def _build(self):
        lo = QVBoxLayout(self)
        lo.setContentsMargins(20, 18, 20, 18)
        lo.setSpacing(10)

        title = QLabel("Add Text")
        f = QFont(DLG_FONT, 13)
        f.setBold(True)
        title.setFont(f)
        title.setStyleSheet(f"color:{DLG_INK};background:transparent;")
        lo.addWidget(title)
        lo.addWidget(_dlg_sep())

        self._edit = QLineEdit()
        self._edit.setFixedHeight(36)
        self._edit.setStyleSheet(_dlg_input_style())
        self._edit.returnPressed.connect(self.accept)
        lo.addWidget(self._edit)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)
        btn_row.addStretch()
        for label, slot, primary in [("Cancel", self.reject, False),
                                     ("Add",    self.accept, True)]:
            btn = QPushButton(label)
            btn.setFixedHeight(34)
            btn.setCursor(Cursor.PointingHandCursor)
            btn.setStyleSheet(_dlg_button_style(primary))
            btn.clicked.connect(slot)
            btn_row.addWidget(btn)
        lo.addLayout(btn_row)

    def showEvent(self, e):
        super().showEvent(e)
        self._edit.setFocus()

    def text(self) -> str:
        return self._edit.text()

    def paintEvent(self, _):
        _dlg_frame_paint(self)


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
        ("↔",  "Ruler",           "U",  "Hold Shift → 45° snap  ·  shows pixel length"),
        ("T",  "Text",            "T",  "Click to place  ·  size set by Text size slider"),
        ("①",  "Callout",        "K",  "Auto-numbered filled circles"),
        ("1▸2","Steps",           "S",  "Auto-numbered step squares"),
        ("HL", "Highlight",       "H",  "Semi-transparent colour band"),
        ("◻",  "Eraser",          "E",  "Freehand erase  ·  width = stroke × 4"),
        ("⊘",  "Blur",            "Z",  "Gaussian blur over a selected region"),
        ("PX", "Pixelate",        "X",  "Mosaic / pixel-art redaction"),
        ("▪",  "Black Box",       "D",  "Solid opaque black redaction"),
        ("⊙",  "Laser Pointer",   "I",  "No mark left — OS cursor hidden, red dot only"),
    ]

    _SHORTCUTS = [
        ("Ctrl + Z",       "Undo last shape"),
        ("Ctrl + Y",       "Redo (restore undone shape)"),
        ("C",              "Clear all shapes"),
        ("Esc",            "Hide overlay (stays in tray)"),
        ("Delete",         "Remove selected shape (Select tool)"),
        ("Ctrl + Shift + A","Toggle overlay (default hotkey — customisable in Settings)"),
    ]

    _TIPS = [
        ("Opacity slider",   "Sets transparency for new shapes — existing ones are not affected."),
        ("Text size slider", "Controls the font size of the Text tool."),
        ("Shift while drawing", "Locks lines / arrows / ruler to nearest 45°.\n"
                                "Locks rectangle / circle to perfect square / circle."),
        ("Eraser width",     "Follows the Stroke slider × 4 so it's always usable at any scale."),
        ("Screenshot",       "Hides the overlay, grabs the full desktop (all monitors), "
                             "then shows Copy / Save PNG / Discard."),
        ("Multi-monitor",    "The overlay covers all connected displays automatically."),
        ("Start on boot",    "Writes to the Windows registry Run key.  "
                             "The app starts hidden in the tray (--minimized flag)."),
    ]

    def __init__(self, parent=None):
        super().__init__(parent,
                         WType.FramelessWindowHint | WType.WindowStaysOnTopHint)
        self.setAttribute(WAtt.WA_TranslucentBackground)
        self._build()
        self.adjustSize()
        _center_on_display1(self)

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
        from PyQt6.QtWidgets import QScrollArea
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
        for icon, name, key, tip in self._TOOLS:
            cl.addWidget(self._tool_row(icon, name, key, tip))
        cl.addSpacing(10)

        # ── Keyboard shortcuts ─────────────────────────────────────────────────
        cl.addWidget(self._section("Keyboard Shortcuts"))
        for keys, desc in self._SHORTCUTS:
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

        # ── Hotkey ─────────────────────────────────────────────────────────────
        lo.addWidget(_dlg_section_lbl("Draw / click-through shortcut"))

        self._hk_edit = ShortcutCapture(
            QKeySequence(_pynput_to_ks(self._settings.get("hotkey")))
        )
        self._hk_edit.setFixedHeight(36)
        self._hk_edit.setStyleSheet(self._input_style())
        lo.addWidget(self._hk_edit)

        hint = QLabel("Switches between drawing on the screen and using your "
                      "computer normally. Click the box and press a new key "
                      "combination.")
        hint.setWordWrap(True)
        hint.setStyleSheet(f"color:{DLG_MUTED};font-size:10px;")
        lo.addWidget(hint)
        lo.addSpacing(6)

        # ── Show / hide ────────────────────────────────────────────────────────
        lo.addWidget(_dlg_section_lbl("Show / hide the overlay"))

        self._vis_hk_edit = ShortcutCapture(
            QKeySequence(_pynput_to_ks(self._settings.get("visibility_hotkey")))
        )
        self._vis_hk_edit.setFixedHeight(36)
        self._vis_hk_edit.setStyleSheet(self._input_style())
        lo.addWidget(self._vis_hk_edit)

        hint2 = QLabel("Takes the overlay off the screen entirely, marks and "
                       "all. The tray icon does the same.")
        hint2.setWordWrap(True)
        hint2.setStyleSheet(f"color:{DLG_MUTED};font-size:10px;")
        lo.addWidget(hint2)
        lo.addSpacing(6)

        # ── OCR shortcut ───────────────────────────────────────────────────────
        lo.addWidget(_dlg_section_lbl("OCR shortcut  (Snip & Read)"))

        self._ocr_hk_edit = ShortcutCapture(
            QKeySequence(_pynput_to_ks(self._settings.get("ocr_hotkey")))
        )
        self._ocr_hk_edit.setFixedHeight(36)
        self._ocr_hk_edit.setStyleSheet(self._input_style())
        lo.addWidget(self._ocr_hk_edit)
        lo.addSpacing(6)

        self._build_recording(lo)

        # ── Boot ───────────────────────────────────────────────────────────────
        self._boot_cb = QCheckBox("Start on boot  (Windows only)")
        self._boot_cb.setChecked(_is_startup_enabled())
        self._boot_cb.setEnabled(IS_WIN)
        self._boot_cb.setStyleSheet(_dlg_checkbox_style())
        lo.addWidget(self._boot_cb)
        lo.addSpacing(6)

        # ── Dock size ──────────────────────────────────────────────────────────
        lo.addWidget(_dlg_section_lbl("Dock size"))
        self._scale_values = [1.0, 0.9, 0.8, 0.7, 0.6]
        self._scale_box = QComboBox()
        self._scale_box.addItems([f"{int(v * 100)} %" for v in self._scale_values])
        current = float(self._settings.get("dock_scale") or 1.0)
        nearest = min(self._scale_values, key=lambda v: abs(v - current))
        self._scale_box.setCurrentText(f"{int(nearest * 100)} %")
        self._scale_box.setFixedHeight(30)
        self._scale_box.setStyleSheet(_dlg_combo_style())
        lo.addWidget(self._scale_box)
        scale_hint = QLabel("Applies next time the app starts.")
        scale_hint.setStyleSheet(f"color:{DLG_MUTED};font-size:10px;")
        lo.addWidget(scale_hint)
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
        help_btn.clicked.connect(lambda: HelpDialog(self).exec())
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
        for cb in (self._rec_cursor_cb, self._rec_audio_cb):
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

        if not can_exclude_from_capture():
            note = QLabel("On this platform a screen capture includes every "
                          "visible window, so the dock moves out of the "
                          "recorded area — or hides, if you are recording the "
                          "whole screen.")
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

        self._rec_hk_edit = ShortcutCapture(
            QKeySequence(_pynput_to_ks(g("rec_hotkey")))
        )
        self._rec_hk_edit.setFixedHeight(36)
        self._rec_hk_edit.setStyleSheet(self._input_style())
        lo.addWidget(self._rec_hk_edit)

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

    # ── Helpers ────────────────────────────────────────────────────────────────
    def _input_style(self) -> str:
        return _dlg_input_style("QLineEdit")

    def _save(self):
        ks = self._hk_edit.keySequence().toString()
        if ks:
            new_hotkey = _ks_to_pynput(ks)
            self._settings.set("hotkey", new_hotkey)
            self._hotkey_mgr.update(new_hotkey)
            overlay = self.parent()
            if overlay is not None and hasattr(overlay, "toolbar"):
                overlay.toolbar.set_mode_shortcut(ks)

        vis_ks = self._vis_hk_edit.keySequence().toString()
        if vis_ks:
            new_vis = _ks_to_pynput(vis_ks)
            self._settings.set("visibility_hotkey", new_vis)
            self._hotkey_mgr.update_visibility(new_vis)
        ocr_ks = self._ocr_hk_edit.keySequence().toString()
        if ocr_ks:
            new_ocr = _ks_to_pynput(ocr_ks)
            self._settings.set("ocr_hotkey", new_ocr)
            self._hotkey_mgr.update_ocr(new_ocr)
        rec_ks = self._rec_hk_edit.keySequence().toString()
        if rec_ks:
            new_rec = _ks_to_pynput(rec_ks)
            self._settings.set("rec_hotkey", new_rec)
            self._hotkey_mgr.update_rec(new_rec)

        self._settings.set("rec_area", self._area_keys[self._rec_area.currentIndex()])
        self._settings.set("rec_fps", self._fps_choices[self._rec_fps.currentIndex()])
        self._settings.set("rec_quality",
                           self._quality_keys[self._rec_quality.currentIndex()])
        self._settings.set("rec_cursor", self._rec_cursor_cb.isChecked())
        self._settings.set("rec_audio", self._rec_audio_cb.isChecked())
        if self._rec_dev is not None:
            self._settings.set("rec_audio_dev", self._rec_dev.currentText())
        self._settings.set("rec_dir", self._rec_dir)

        self._settings.set("dock_scale",
                           self._scale_values[self._scale_box.currentIndex()])
        self._settings.set("start_on_boot", self._boot_cb.isChecked())
        _set_startup(self._boot_cb.isChecked())
        self._settings.save()
        self.accept()

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
    if _ocr_reader is not None or _ocr_preload_thread is not None:
        return
    _ocr_preload_thread = OcrPreloadThread()
    _ocr_preload_thread.start()


class OcrThread(QThread):
    """Runs EasyOCR in a background thread so the UI stays responsive."""
    status   = pyqtSignal(str)   # progress updates for the dialog label
    finished = pyqtSignal(str)
    error    = pyqtSignal(str)

    def __init__(self, pixmap: QPixmap):
        super().__init__()
        self._pixmap = pixmap

    def run(self):
        try:
            import io
            import numpy as np
            from PIL import Image
            from PyQt6.QtCore import QByteArray, QBuffer, QIODeviceBase

            # QPixmap → PIL Image
            ba  = QByteArray()
            buf = QBuffer(ba)
            buf.open(QIODeviceBase.OpenModeFlag.WriteOnly)
            self._pixmap.save(buf, "PNG")
            buf.close()
            img = Image.open(io.BytesIO(bytes(ba))).convert("RGB")

            if _ocr_reader is None:
                if not _ocr_models_present():
                    self.status.emit(
                        "Downloading OCR model (~150 MB) — first use only…"
                    )
                else:
                    self.status.emit("Loading OCR engine…")
            reader = _get_ocr_reader()

            self.status.emit("Reading text…")
            results = reader.readtext(np.array(img))
            text    = "\n".join(r[1] for r in results).strip()
            self.finished.emit(text or "(no text detected)")

        except Exception as exc:
            self.error.emit(str(exc))


def _looks_like_error_page(text: str) -> bool:
    """deep-translator hits Google's translate endpoint directly (no API
    key). When Google rate-limits or blocks that — or a network in between
    does, e.g. a corporate proxy — it doesn't always raise; sometimes it just
    hands back Google's raw HTML error page as if it were the translation.
    Catch the obvious cases so that never gets shown to the user as a
    result."""
    t = text.strip().lower()
    return (
        "<html" in t or "<!doctype html" in t
        or "that's an error" in t or "that's all we know" in t
        or t.startswith("error 500") or t.startswith("error 429")
    )


class TranslateThread(QThread):
    """Calls Google Translate via deep-translator in a background thread."""
    finished = pyqtSignal(str)
    error    = pyqtSignal(str)

    def __init__(self, text: str, lang_code: str):
        super().__init__()
        self._text = text
        self._lang = lang_code

    def run(self):
        try:
            from deep_translator import GoogleTranslator
            result = GoogleTranslator(source="auto", target=self._lang).translate(self._text)
            if result and _looks_like_error_page(result):
                self.error.emit(
                    "Translation service returned an error page instead of a "
                    "result — likely a temporary block or rate limit from "
                    "Google, or a network/proxy filtering the request. Wait "
                    "a moment and try again."
                )
                return
            self.finished.emit(result or "(empty result)")
        except ImportError:
            self.error.emit(
                "Missing dependency: deep-translator\n\n"
                "Install with:\n  pip install deep-translator"
            )
        except Exception as exc:
            self.error.emit(str(exc))


class OcrResultDialog(QDialog):
    """Popup showing OCR text + optional translation with copy buttons."""

    def __init__(self, pixmap: QPixmap, parent=None):
        super().__init__(parent,
                         WType.Window |
                         WType.WindowStaysOnTopHint |
                         WType.WindowCloseButtonHint |
                         WType.WindowMinimizeButtonHint |
                         WType.WindowMaximizeButtonHint)
        self.setWindowTitle("OCR & Translate — Screen Annotator Pro")
        self.setStyleSheet(
            f"QDialog{{background:{DLG_GROUND};}}"
            f"QLabel{{color:{DLG_INK};background:transparent;font-family:'{DLG_FONT}';}}"
        )
        self._pixmap       = pixmap
        self._ocr_thread   = None
        self._trans_thread = None
        self._build()
        self.resize(520, 480)
        _center_on_display1(self)
        self._start_ocr()

    # ── Build UI ───────────────────────────────────────────────────────────────
    def _build(self):
        lo = QVBoxLayout(self)
        lo.setContentsMargins(20, 18, 20, 18)
        lo.setSpacing(10)

        # Status
        self._status = QLabel("Reading text…")
        self._status.setStyleSheet(f"color:{DLG_MUTED};font-size:10px;")
        lo.addWidget(self._status)

        # OCR text box — grows with window
        self._ocr_box = QTextEdit()
        self._ocr_box.setReadOnly(True)
        self._ocr_box.setMinimumHeight(80)
        self._ocr_box.setPlaceholderText("Recognized text will appear here…")
        self._ocr_box.setStyleSheet(self._box_style())
        lo.addWidget(self._ocr_box, 1)

        # Copy text button
        copy_ocr = QPushButton("Copy text")
        copy_ocr.setFixedHeight(30)
        copy_ocr.setCursor(Cursor.PointingHandCursor)
        copy_ocr.setStyleSheet(_dlg_button_style(primary=False))
        copy_ocr.clicked.connect(
            lambda: self._copy_and_flash(copy_ocr, self._ocr_box.toPlainText())
        )
        lo.addWidget(copy_ocr)

        lo.addWidget(_dlg_sep())

        # Translate row
        lang_row = QHBoxLayout()
        lang_lbl = QLabel("Translate to")
        lang_lbl.setStyleSheet(f"color:{DLG_MUTED};font-size:12px;")
        self._lang_box = QComboBox()
        self._lang_box.addItems(list(_TRANSLATE_LANGS.keys()))
        self._lang_box.setCurrentText("English")
        self._lang_box.setFixedHeight(30)
        self._lang_box.setStyleSheet(_dlg_combo_style())
        go_btn = QPushButton("Translate")
        go_btn.setFixedHeight(30)
        go_btn.setCursor(Cursor.PointingHandCursor)
        go_btn.setStyleSheet(_dlg_button_style(primary=True))
        go_btn.clicked.connect(self._start_translate)
        lang_row.addWidget(lang_lbl)
        lang_row.addWidget(self._lang_box, 1)
        lang_row.addWidget(go_btn)
        lo.addLayout(lang_row)

        # Translation text box — grows with window
        self._trans_box = QTextEdit()
        self._trans_box.setReadOnly(True)
        self._trans_box.setMinimumHeight(80)
        self._trans_box.setPlaceholderText("Translation will appear here…")
        self._trans_box.setStyleSheet(self._box_style())
        lo.addWidget(self._trans_box, 1)

        # Copy translation button
        copy_tr = QPushButton("Copy translation")
        copy_tr.setFixedHeight(30)
        copy_tr.setCursor(Cursor.PointingHandCursor)
        copy_tr.setStyleSheet(_dlg_button_style(primary=False))
        copy_tr.clicked.connect(
            lambda: self._copy_and_flash(copy_tr, self._trans_box.toPlainText())
        )
        lo.addWidget(copy_tr)

    def _copy_and_flash(self, btn: QPushButton, text: str):
        QApplication.clipboard().setText(text)
        original = btn.text()
        btn.setText("Copied")
        btn.setEnabled(False)
        QTimer.singleShot(1500, lambda: (btn.setText(original), btn.setEnabled(True)))

    # ── OCR ────────────────────────────────────────────────────────────────────
    def _start_ocr(self):
        if not _ocr_models_present():
            self._status.setText(
                "First use: downloading OCR model (~150 MB)…  Please wait."
            )
        self._ocr_thread = OcrThread(self._pixmap)
        self._ocr_thread.status.connect(self._status.setText)
        self._ocr_thread.finished.connect(self._on_ocr_done)
        self._ocr_thread.error.connect(self._on_ocr_error)
        self._ocr_thread.start()

    def _on_ocr_done(self, text: str):
        self._ocr_box.setPlainText(text)
        self._status.setText("Text recognized")

    def _on_ocr_error(self, msg: str):
        self._ocr_box.setPlainText(msg)
        self._status.setText("Could not read text")

    # ── Translation ────────────────────────────────────────────────────────────
    def _start_translate(self):
        text = self._ocr_box.toPlainText().strip()
        if not text:
            return
        lang = _TRANSLATE_LANGS.get(self._lang_box.currentText(), "en")
        self._trans_box.setPlainText("Translating…")
        self._trans_thread = TranslateThread(text, lang)
        self._trans_thread.finished.connect(self._trans_box.setPlainText)
        self._trans_thread.error.connect(self._trans_box.setPlainText)
        self._trans_thread.start()

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
        ScreenshotBar(pixmap, self.overlay)

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
        from PyQt6.QtGui import QPainterPath
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
            self._drag_pos = e.pos()

    def mouseMoveEvent(self, e):
        if e.buttons() & MB.LeftButton and self._drag_pos:
            self.move(self.mapToParent(e.pos() - self._drag_pos))

    def mouseReleaseEvent(self, e):
        self._drag_pos = None


from dock_toolbar import Toolbar   # noqa: E402 — horizontal dock


# ── Overlay window ─────────────────────────────────────────────────────────────
class AnnotationOverlay(QWidget):
    def __init__(self, settings_mgr: SettingsManager, hotkey_mgr: HotkeyManager):
        super().__init__(None,
                         WType.WindowStaysOnTopHint |
                         WType.FramelessWindowHint  |
                         WType.Tool)
        self.setAttribute(WAtt.WA_TranslucentBackground)
        self.setAttribute(WAtt.WA_NoSystemBackground)

        self._passthrough = False
        self.canvas  = Canvas(self)
        self.toolbar = Toolbar(self.canvas, self, settings_mgr, hotkey_mgr)
        self.canvas.setCursor(_cross_cursor())
        self.toolbar.set_mode_shortcut(_pynput_to_ks(settings_mgr.get("hotkey")))
        self.recording = RecordingController(self, settings_mgr)
        self.recording.state_changed.connect(self.toolbar.set_recording)
        self.recording.ticked.connect(self.toolbar.set_record_elapsed)

        # Cover all monitors and react to any display configuration change
        self._fit_to_screens()
        _app = QApplication.instance()
        _app.primaryScreenChanged.connect(self._on_screen_change)
        _app.screenAdded.connect(self._on_screen_change)
        _app.screenRemoved.connect(self._on_screen_change)
        for _s in _app.screens():
            _s.geometryChanged.connect(self._on_screen_change)
            _s.logicalDotsPerInchChanged.connect(self._on_dpi_change)

        if "--minimized" not in sys.argv:
            self.show()
            self.raise_()
            self.activateWindow()
            # The dock is its own window now, so it has to be shown explicitly
            # — and it honours the collapsed-to-a-puck state while doing it.
            self.toolbar.set_chrome_visible(True)
            # Start out of the way. The app appearing should never be the
            # reason you cannot click something.
            self.set_passthrough(True)

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
            self.show()
            self.raise_()
            self.activateWindow()
            self.canvas.setFocus()
        else:
            # Nothing is being pointed at any more; drop the laser dot rather
            # than leaving it frozen mid-screen.
            self.canvas._laser_pos = None
            self.canvas.update()

    @pyqtSlot()
    def toggle_passthrough(self):
        if not self.isVisible():          # hidden entirely: bring it back armed
            self.show()
            self.toolbar.set_chrome_visible(True)
            self.set_passthrough(False)
            return
        self.set_passthrough(not self._passthrough)

    # ── Display configuration helpers ──────────────────────────────────────────
    def _fit_to_screens(self):
        """Resize the overlay to cover every connected monitor."""
        from PyQt6.QtCore import QRect
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

    @pyqtSlot()
    def activate_ocr(self):
        if not self.isVisible():
            self.show(); self.raise_()
            self.toolbar.set_chrome_visible(True)
        self.set_passthrough(False)       # you cannot drag a snip through it
        self.toolbar._activate("ocr")

    @pyqtSlot()
    def toggle_recording(self):
        self.recording.toggle()

    @pyqtSlot()
    def toggle(self):
        if self.isVisible():
            self.hide()
            self.toolbar.set_chrome_visible(False)
        else:
            self.show()
            self.raise_()
            self.activateWindow()
            self.toolbar.set_chrome_visible(True)

    def changeEvent(self, e):
        super().changeEvent(e)

    def keyPressEvent(self, e):
        k = e.key()
        mods = e.modifiers()
        if k == Key.Key_Escape:
            # Esc means "stop taking my clicks", not "disappear" — the marks
            # stay up and the dock stays reachable.
            self.set_passthrough(True)
        elif k == Key.Key_C and not (mods & Qt.KeyboardModifier.ControlModifier):
            self.canvas.clear()
        elif k == Key.Key_Z and mods & Qt.KeyboardModifier.ControlModifier:
            self.canvas.undo()
        elif k == Key.Key_Y and mods & Qt.KeyboardModifier.ControlModifier:
            self.canvas.redo()
        elif (k == Key.Key_R and mods & Qt.KeyboardModifier.ControlModifier
              and mods & Qt.KeyboardModifier.ShiftModifier):
            self.recording.toggle()
        elif k == Key.Key_Delete and self.canvas._selected:
            self.canvas._shapes.remove(self.canvas._selected)
            self.canvas._selected = None
            self.canvas.update()
        elif k in KEY_TOOL:
            self.toolbar._activate(KEY_TOOL[k])


# ── Global hotkey bootstrap ────────────────────────────────────────────────────
def _start_hotkey(overlay: AnnotationOverlay, hotkey_mgr: HotkeyManager,
                  hotkey: str, visibility_hotkey: str):
    from PyQt6.QtCore import QMetaObject, Qt as _Qt

    def on_mode():
        QMetaObject.invokeMethod(overlay, "toggle_passthrough",
                                 _Qt.ConnectionType.QueuedConnection)
    hotkey_mgr.start(hotkey, on_mode)

    def on_visibility():
        QMetaObject.invokeMethod(overlay, "toggle",
                                 _Qt.ConnectionType.QueuedConnection)
    hotkey_mgr.start_visibility(visibility_hotkey, on_visibility)


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

    conv_action = menu.addAction("Convert a recording…")
    conv_action.triggered.connect(lambda: _convert_recording(overlay))

    menu.addSeparator()
    quit_action = menu.addAction("Exit")
    quit_action.triggered.connect(QApplication.quit)

    tray.setContextMenu(menu)
    tray.activated.connect(
        lambda reason: overlay.toggle()
        if reason == QSystemTrayIcon.ActivationReason.Trigger else None
    )
    tray.show()
    return tray


# ── Entry point ────────────────────────────────────────────────────────────────
def main():
    # PassThrough: accept fractional scale factors (125 %, 150 %, etc.) on
    # every platform — not just Windows.  Must be called before QApplication().
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )

    app = QApplication(sys.argv)
    app.setApplicationName("Screen Annotator Pro")
    app.setQuitOnLastWindowClosed(False)

    # App-wide icon — every window (Settings, Help, the OCR result window's
    # real title bar, Alt-Tab/taskbar entries) picks this up unless it sets
    # its own. The system tray icon is set separately in _setup_tray().
    ico_path = _resource(os.path.join('icons', 'annotate.ico'))
    if os.path.exists(ico_path):
        app.setWindowIcon(QIcon(ico_path))

    settings_mgr = SettingsManager()
    _apply_dlg_theme(settings_mgr.get("theme"))
    # Must happen before the dock is constructed — every widget on it reads
    # these sizes as it is built.
    import dock_toolbar
    dock_toolbar.set_dock_scale(settings_mgr.get("dock_scale"))
    hotkey_mgr   = HotkeyManager()
    overlay      = AnnotationOverlay(settings_mgr, hotkey_mgr)
    tray         = _setup_tray(overlay)
    _start_hotkey(overlay, hotkey_mgr, settings_mgr.get("hotkey"),
                  settings_mgr.get("visibility_hotkey"))

    # Safety net: catches any exit path that isn't already covered by the
    # dock's own save-on-drag/-collapse/-expand calls.
    app.aboutToQuit.connect(overlay.toolbar._save_dock_state)

    from PyQt6.QtCore import QMetaObject, Qt as _Qt
    def _on_ocr():
        QMetaObject.invokeMethod(overlay, "activate_ocr",
                                 _Qt.ConnectionType.QueuedConnection)
    hotkey_mgr.start_ocr(settings_mgr.get("ocr_hotkey"), _on_ocr)

    def _on_record():
        QMetaObject.invokeMethod(overlay, "toggle_recording",
                                 _Qt.ConnectionType.QueuedConnection)
    hotkey_mgr.start_rec(settings_mgr.get("rec_hotkey"), _on_record)

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
