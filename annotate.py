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

import sys, os, json, math, random as _rng, threading, platform
from pathlib import Path
from PyQt6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QPushButton, QSlider, QLabel, QColorDialog, QGraphicsDropShadowEffect,
    QGraphicsBlurEffect, QGraphicsScene, QGraphicsPixmapItem,
    QInputDialog, QFrame, QSystemTrayIcon, QMenu, QFileDialog,
    QDialog, QCheckBox, QKeySequenceEdit, QTextEdit, QComboBox, QScrollArea,
)
from PyQt6.QtCore import Qt, QPointF, QRectF, QUrl, QThread, QTimer, pyqtSignal, pyqtSlot
from PyQt6.QtGui import (
    QPainter, QPen, QColor, QFont, QBrush,
    QPolygonF, QPainterPath, QFontMetrics, QPixmap, QCursor, QIcon,
    QKeySequence, QDesktopServices,
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
VERSION = "2.2.7"

# ── Platform detection ─────────────────────────────────────────────────────────
IS_WIN = platform.system() == "Windows"
IS_MAC = platform.system() == "Darwin"

# ── Settings ───────────────────────────────────────────────────────────────────
_DEFAULT_SETTINGS: dict = {
    "hotkey":        "<ctrl>+<shift>+a",
    "ocr_hotkey":   "<ctrl>+t",
    "start_on_boot": False,
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
    def __init__(self):
        self._listener   = None
        self._cb         = None
        self._hotkey     = ""
        self._ocr_cb     = None
        self._ocr_hotkey = ""

    def start(self, pynput_str: str, callback):
        self._cb = callback; self._hotkey = pynput_str
        self._restart()

    def update(self, pynput_str: str):
        self._hotkey = pynput_str
        self._restart()

    def start_ocr(self, pynput_str: str, callback):
        self._ocr_cb = callback; self._ocr_hotkey = pynput_str
        self._restart()

    def update_ocr(self, pynput_str: str):
        self._ocr_hotkey = pynput_str
        self._restart()

    def _restart(self):
        if self._listener:
            try: self._listener.stop()
            except Exception: pass
            self._listener = None
        on_wayland = (os.environ.get("WAYLAND_DISPLAY") or
                      os.environ.get("XDG_SESSION_TYPE", "").lower() == "wayland")
        if on_wayland:
            return
        mapping = {}
        if self._hotkey     and self._cb:     mapping[self._hotkey]     = self._cb
        if self._ocr_hotkey and self._ocr_cb: mapping[self._ocr_hotkey] = self._ocr_cb
        if not mapping:
            return
        try:
            from pynput import keyboard as kb
            self._listener = kb.GlobalHotKeys(mapping)
            self._listener.daemon = True
            self._listener.start()
        except (ImportError, Exception):
            pass

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
        pz = 12
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
                pixmap = self._grab_behind(rect)
                dlg = OcrResultDialog(pixmap, self.window())
                dlg.exec()
            self.update(); return

        if self.tool in DRAG_TOOLS:
            if self.tool == "blur":
                rect = _norm(self._start, pos)
                if rect.width() > 3 and rect.height() > 3:
                    raw = self._grab_behind(rect)
                    blurred = _blur_pixmap(raw)
                    self._commit(BlurShape(self._start, pos, blurred))
            else:
                s = self._make_drag(self._start, pos)
                if s: self._commit(s)

    def _place_point(self, pos: QPointF):
        col = _with_alpha(self.pen_color, self.pen_alpha)
        t = self.tool
        if t == "text":
            text, ok = QInputDialog.getText(self, "Add Text", "Text:")
            if ok and text:
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
        if t == "pixel":     return PixelShape(p1, p2)
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
        if self._selected:
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

        p.end()


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
        self.move((parent.width() - self.width()) // 2,
                  (parent.height() - self.height()) // 2)
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
        for icon, label, fn, color in [
            ("📋", "Copy",     self._copy, "#0A84FF"),
            ("💾", "Save PNG", self._save, "#32D74B"),
            ("✕",  "Discard",  self.close, "#FF453A"),
        ]:
            btn = QPushButton(f"  {icon}  {label}")
            btn.setFixedHeight(36)
            btn.setCursor(Cursor.PointingHandCursor)
            btn.setStyleSheet(
                f"QPushButton{{color:{color};background:rgba(255,255,255,0.06);"
                f"border:1px solid rgba(255,255,255,0.12);border-radius:8px;"
                f"font-size:13px;padding:0 12px;}}"
                f"QPushButton:hover{{background:rgba(255,255,255,0.13);"
                f"border:1px solid {color};}}"
            )
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
        ("📏", "Ruler",           "U",  "Hold Shift → 45° snap  ·  shows pixel length"),
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
        if parent:
            self.move(
                parent.x() + (parent.width()  - self.width())  // 2,
                parent.y() + (parent.height() - self.height()) // 2,
            )

    # ── Build ──────────────────────────────────────────────────────────────────
    def _build(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 18, 20, 18)
        outer.setSpacing(10)

        # Title row
        title_row = QHBoxLayout()
        title = QLabel("Help & Features")
        title.setStyleSheet("color:#e5e5e7;font-size:15px;font-weight:700;")
        title_row.addWidget(title)
        title_row.addStretch()
        close_btn = QPushButton("✕")
        close_btn.setFixedSize(26, 26)
        close_btn.setCursor(Cursor.PointingHandCursor)
        close_btn.setStyleSheet(
            "QPushButton{color:#636366;background:transparent;border:none;font-size:14px;}"
            "QPushButton:hover{color:#FF453A;}"
        )
        close_btn.clicked.connect(self.accept)
        title_row.addWidget(close_btn)
        outer.addLayout(title_row)
        outer.addWidget(self._hsep())

        # Scroll area
        from PyQt6.QtWidgets import QScrollArea
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setFixedHeight(460)
        scroll.setStyleSheet(
            "QScrollArea{background:transparent;border:none;}"
            "QScrollBar:vertical{background:#1c1c1e;width:6px;border-radius:3px;}"
            "QScrollBar::handle:vertical{background:#3a3a3c;border-radius:3px;min-height:20px;}"
            "QScrollBar::add-line:vertical,QScrollBar::sub-line:vertical{height:0;}"
        )

        content = QWidget()
        content.setStyleSheet("background:transparent;")
        cl = QVBoxLayout(content)
        cl.setContentsMargins(0, 0, 8, 0)
        cl.setSpacing(0)

        # ── Tools ──────────────────────────────────────────────────────────────
        cl.addWidget(self._section("🛠  Tools"))
        for icon, name, key, tip in self._TOOLS:
            cl.addWidget(self._tool_row(icon, name, key, tip))
        cl.addSpacing(10)

        # ── Keyboard shortcuts ─────────────────────────────────────────────────
        cl.addWidget(self._section("⌨️  Keyboard Shortcuts"))
        for keys, desc in self._SHORTCUTS:
            cl.addWidget(self._shortcut_row(keys, desc))
        cl.addSpacing(10)

        # ── Tips ───────────────────────────────────────────────────────────────
        cl.addWidget(self._section("💡  Tips"))
        for heading, body in self._TIPS:
            cl.addWidget(self._tip_row(heading, body))

        cl.addStretch()
        scroll.setWidget(content)
        outer.addWidget(scroll)

        outer.addWidget(self._hsep())

        # Close button
        close2 = QPushButton("Close")
        close2.setFixedHeight(34)
        close2.setCursor(Cursor.PointingHandCursor)
        close2.setStyleSheet(
            "QPushButton{color:#98989d;background:rgba(255,255,255,0.06);"
            "border:1px solid rgba(255,255,255,0.12);border-radius:8px;font-size:13px;}"
            "QPushButton:hover{background:rgba(255,255,255,0.10);}"
        )
        close2.clicked.connect(self.accept)
        outer.addWidget(close2)

        self.setFixedWidth(420)

    # ── Row builders ───────────────────────────────────────────────────────────
    def _section(self, text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setStyleSheet(
            "color:#aeaeb2;font-size:11px;font-weight:700;letter-spacing:0.5px;"
            "padding:8px 0 4px 0;"
        )
        return lbl

    def _tool_row(self, icon: str, name: str, key: str, tip: str) -> QWidget:
        w  = QWidget()
        lo = QVBoxLayout(w)
        lo.setContentsMargins(4, 3, 4, 3)
        lo.setSpacing(1)

        top = QHBoxLayout()
        icon_lbl = QLabel(icon)
        icon_lbl.setFixedWidth(28)
        icon_lbl.setStyleSheet("color:#0A84FF;font-size:13px;font-weight:600;")
        name_lbl = QLabel(name)
        name_lbl.setStyleSheet("color:#e5e5e7;font-size:12px;")
        key_lbl  = QLabel(key)
        key_lbl.setStyleSheet(
            "color:#636366;font-size:10px;background:rgba(255,255,255,0.07);"
            "border-radius:4px;padding:1px 5px;"
        )
        top.addWidget(icon_lbl)
        top.addWidget(name_lbl)
        top.addStretch()
        top.addWidget(key_lbl)
        lo.addLayout(top)

        tip_lbl = QLabel(tip)
        tip_lbl.setStyleSheet("color:#48484a;font-size:10px;padding-left:28px;")
        lo.addWidget(tip_lbl)
        return w

    def _shortcut_row(self, keys: str, desc: str) -> QWidget:
        w  = QWidget()
        lo = QHBoxLayout(w)
        lo.setContentsMargins(4, 4, 4, 4)
        keys_lbl = QLabel(keys)
        keys_lbl.setFixedWidth(160)
        keys_lbl.setStyleSheet(
            "color:#e5e5e7;font-size:11px;background:rgba(255,255,255,0.07);"
            "border-radius:4px;padding:2px 6px;font-family:monospace;"
        )
        desc_lbl = QLabel(desc)
        desc_lbl.setStyleSheet("color:#636366;font-size:11px;")
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
        h.setStyleSheet("color:#aeaeb2;font-size:11px;font-weight:600;")
        b = QLabel(body)
        b.setStyleSheet("color:#636366;font-size:10px;")
        b.setWordWrap(True)
        lo.addWidget(h)
        lo.addWidget(b)
        return w

    def _hsep(self) -> QFrame:
        f = QFrame()
        f.setFrameShape(QFrame.Shape.HLine)
        f.setFixedHeight(1)
        f.setStyleSheet("background:rgba(255,255,255,0.06);margin:0;")
        return f

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(QColor(16, 16, 18, 252)))
        path = QPainterPath()
        path.addRoundedRect(0, 0, self.width(), self.height(), 14, 14)
        p.drawPath(path)
        if IS_WIN:
            p.setPen(QPen(QColor(70, 70, 75, 220), 1))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(
                QRectF(0.5, 0.5, self.width() - 1, self.height() - 1), 14, 14
            )
        p.end()


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
        if parent:
            self.move(
                parent.x() + (parent.width()  - self.width())  // 2,
                parent.y() + (parent.height() - self.height()) // 2,
            )

    # ── Build UI ───────────────────────────────────────────────────────────────
    def _build(self):
        lo = QVBoxLayout(self)
        lo.setContentsMargins(24, 22, 24, 22)
        lo.setSpacing(10)

        title = QLabel("Settings")
        title.setStyleSheet("color:#e5e5e7;font-size:16px;font-weight:700;")
        lo.addWidget(title)
        lo.addWidget(self._sep())

        # ── Hotkey ─────────────────────────────────────────────────────────────
        lo.addWidget(self._section_lbl("ACTIVATION SHORTCUT"))

        self._hk_edit = QKeySequenceEdit(
            QKeySequence(_pynput_to_ks(self._settings.get("hotkey")))
        )
        self._hk_edit.setMaximumSequenceLength(1)
        self._hk_edit.setFixedHeight(36)
        self._hk_edit.setStyleSheet(
            "QKeySequenceEdit{"
            "  background:rgba(255,255,255,0.07);color:#e5e5e7;"
            "  border:1px solid rgba(255,255,255,0.12);border-radius:8px;"
            "  padding:0 10px;font-size:13px;}"
            "QKeySequenceEdit:focus{border:1px solid #0A84FF;}"
        )
        lo.addWidget(self._hk_edit)

        hint = QLabel("Click the box and press a new key combination.")
        hint.setStyleSheet("color:#48484a;font-size:10px;")
        lo.addWidget(hint)
        lo.addSpacing(6)

        # ── OCR shortcut ───────────────────────────────────────────────────────
        lo.addWidget(self._section_lbl("OCR SHORTCUT  (Snip & Read)"))

        self._ocr_hk_edit = QKeySequenceEdit(
            QKeySequence(_pynput_to_ks(self._settings.get("ocr_hotkey")))
        )
        self._ocr_hk_edit.setMaximumSequenceLength(1)
        self._ocr_hk_edit.setFixedHeight(36)
        self._ocr_hk_edit.setStyleSheet(
            "QKeySequenceEdit{"
            "  background:rgba(255,255,255,0.07);color:#e5e5e7;"
            "  border:1px solid rgba(255,255,255,0.12);border-radius:8px;"
            "  padding:0 10px;font-size:13px;}"
            "QKeySequenceEdit:focus{border:1px solid #0A84FF;}"
        )
        lo.addWidget(self._ocr_hk_edit)
        lo.addSpacing(6)

        # ── Boot ───────────────────────────────────────────────────────────────
        self._boot_cb = QCheckBox("Start on boot  (Windows only)")
        self._boot_cb.setChecked(_is_startup_enabled())
        self._boot_cb.setEnabled(IS_WIN)
        self._boot_cb.setStyleSheet(
            "QCheckBox{color:#aeaeb2;font-size:13px;spacing:8px;}"
            "QCheckBox::indicator{width:18px;height:18px;border-radius:5px;"
            "  border:1.5px solid rgba(255,255,255,0.18);"
            "  background:rgba(255,255,255,0.05);}"
            "QCheckBox::indicator:checked{background:#0A84FF;"
            "  border:1.5px solid #0A84FF;}"
            "QCheckBox:disabled{color:#48484a;}"
        )
        lo.addWidget(self._boot_cb)

        lo.addSpacing(6)
        lo.addWidget(self._sep())
        lo.addSpacing(4)

        # ── Developer link ─────────────────────────────────────────────────────
        dev_row = QHBoxLayout()
        dev_lbl = QLabel("Developer")
        dev_lbl.setStyleSheet("color:#48484a;font-size:11px;")
        dev_row.addWidget(dev_lbl)
        dev_row.addStretch()
        dev_btn = QPushButton("celikovic.xyz ↗")
        dev_btn.setCursor(Cursor.PointingHandCursor)
        dev_btn.setStyleSheet(
            "QPushButton{color:#0A84FF;background:transparent;border:none;"
            "font-size:11px;}"
            "QPushButton:hover{color:#4DA3FF;text-decoration:underline;}"
        )
        dev_btn.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl("https://celikovic.xyz"))
        )
        dev_row.addWidget(dev_btn)
        lo.addLayout(dev_row)

        ver_lbl = QLabel(f"Version {VERSION}")
        ver_lbl.setStyleSheet("color:#3a3a3c;font-size:10px;")
        ver_lbl.setAlignment(AA.AlignRight)
        lo.addWidget(ver_lbl)
        lo.addSpacing(6)

        # ── Buttons ────────────────────────────────────────────────────────────
        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)

        help_btn = QPushButton("?  Help")
        help_btn.setFixedHeight(34)
        help_btn.setCursor(Cursor.PointingHandCursor)
        help_btn.setStyleSheet(
            "QPushButton{color:#636366;background:transparent;border:1px solid #3a3a3c;"
            "border-radius:8px;font-size:13px;}"
            "QPushButton:hover{color:#aeaeb2;border:1px solid #636366;}"
        )
        help_btn.clicked.connect(lambda: HelpDialog(self).exec())
        btn_row.addWidget(help_btn)
        btn_row.addStretch()

        for label, slot, primary in [("Cancel", self.reject, False),
                                     ("Save",   self._save,  True)]:
            btn = QPushButton(label)
            btn.setFixedHeight(34)
            btn.setCursor(Cursor.PointingHandCursor)
            if primary:
                btn.setStyleSheet(
                    "QPushButton{color:#fff;background:#0A84FF;border:none;"
                    "border-radius:8px;font-size:13px;font-weight:600;}"
                    "QPushButton:hover{background:#1A94FF;}"
                )
            else:
                btn.setStyleSheet(
                    "QPushButton{color:#98989d;background:rgba(255,255,255,0.06);"
                    "border:1px solid rgba(255,255,255,0.12);border-radius:8px;"
                    "font-size:13px;}"
                    "QPushButton:hover{background:rgba(255,255,255,0.10);}"
                )
            btn.clicked.connect(slot)
            btn_row.addWidget(btn)
        lo.addLayout(btn_row)

    # ── Helpers ────────────────────────────────────────────────────────────────
    def _sep(self):
        f = QFrame()
        f.setFrameShape(QFrame.Shape.HLine)
        f.setFixedHeight(1)
        f.setStyleSheet("background:rgba(255,255,255,0.06);margin:0;")
        return f

    def _section_lbl(self, text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setStyleSheet(
            "color:#636366;font-size:10px;font-weight:600;letter-spacing:1px;"
        )
        return lbl

    def _save(self):
        ks = self._hk_edit.keySequence().toString()
        if ks:
            new_hotkey = _ks_to_pynput(ks)
            self._settings.set("hotkey", new_hotkey)
            self._hotkey_mgr.update(new_hotkey)
        ocr_ks = self._ocr_hk_edit.keySequence().toString()
        if ocr_ks:
            new_ocr = _ks_to_pynput(ocr_ks)
            self._settings.set("ocr_hotkey", new_ocr)
            self._hotkey_mgr.update_ocr(new_ocr)
        self._settings.set("start_on_boot", self._boot_cb.isChecked())
        _set_startup(self._boot_cb.isChecked())
        self._settings.save()
        self.accept()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(QColor(16, 16, 18, 252)))
        path = QPainterPath()
        path.addRoundedRect(0, 0, self.width(), self.height(), 14, 14)
        p.drawPath(path)
        if IS_WIN:
            p.setPen(QPen(QColor(70, 70, 75, 220), 1))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(
                QRectF(0.5, 0.5, self.width() - 1, self.height() - 1), 14, 14
            )
        p.end()


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

_ocr_reader = None   # lazy-loaded EasyOCR Reader (cached after first use)

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


class OcrThread(QThread):
    """Runs EasyOCR in a background thread so the UI stays responsive."""
    status   = pyqtSignal(str)   # progress updates for the dialog label
    finished = pyqtSignal(str)
    error    = pyqtSignal(str)

    def __init__(self, pixmap: QPixmap):
        super().__init__()
        self._pixmap = pixmap

    def run(self):
        global _ocr_reader
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
                import easyocr
                if not _ocr_models_present():
                    self.status.emit(
                        "Downloading OCR model (~150 MB) — first use only…"
                    )
                else:
                    self.status.emit("Loading OCR engine…")
                _ocr_reader = easyocr.Reader(
                    ["en"],
                    gpu=False,
                    verbose=False,
                    model_storage_directory=_ocr_model_dir(),
                )

            self.status.emit("Reading text…")
            results = _ocr_reader.readtext(np.array(img))
            text    = "\n".join(r[1] for r in results).strip()
            self.finished.emit(text or "(no text detected)")

        except Exception as exc:
            self.error.emit(str(exc))


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
            "QDialog{background:#101012;}"
            "QLabel{color:#e5e5e7;}"
            "QTextEdit{background:#1c1c1e;color:#e5e5e7;"
            " border:1px solid #3a3a3c;border-radius:8px;padding:6px;font-size:12px;}"
            "QScrollBar:vertical{background:#1c1c1e;width:6px;}"
            "QScrollBar::handle:vertical{background:#3a3a3c;border-radius:3px;}"
        )
        self._pixmap       = pixmap
        self._ocr_thread   = None
        self._trans_thread = None
        self._build()
        self.resize(520, 480)
        if parent:
            self.move(
                parent.x() + (parent.width()  - self.width())  // 2,
                parent.y() + (parent.height() - self.height()) // 2,
            )
        self._start_ocr()

    # ── Build UI ───────────────────────────────────────────────────────────────
    def _build(self):
        lo = QVBoxLayout(self)
        lo.setContentsMargins(20, 18, 20, 18)
        lo.setSpacing(10)

        # Status
        self._status = QLabel("Reading text…")
        self._status.setStyleSheet("color:#636366;font-size:10px;")
        lo.addWidget(self._status)

        # OCR text box — grows with window
        self._ocr_box = QTextEdit()
        self._ocr_box.setReadOnly(True)
        self._ocr_box.setMinimumHeight(80)
        self._ocr_box.setPlaceholderText("Recognized text will appear here…")
        self._ocr_box.setStyleSheet(self._box_style())
        lo.addWidget(self._ocr_box, 1)

        # Copy text button
        copy_ocr = QPushButton("📋  Copy text")
        copy_ocr.setFixedHeight(30)
        copy_ocr.setCursor(Cursor.PointingHandCursor)
        copy_ocr.setStyleSheet(self._ghost_btn())
        copy_ocr.clicked.connect(
            lambda: self._copy_and_flash(copy_ocr, self._ocr_box.toPlainText())
        )
        lo.addWidget(copy_ocr)

        lo.addWidget(self._sep())

        # Translate row
        lang_row = QHBoxLayout()
        lang_lbl = QLabel("Translate to")
        lang_lbl.setStyleSheet("color:#98989d;font-size:12px;")
        self._lang_box = QComboBox()
        self._lang_box.addItems(list(_TRANSLATE_LANGS.keys()))
        self._lang_box.setCurrentText("English")
        self._lang_box.setFixedHeight(30)
        self._lang_box.setStyleSheet(
            "QComboBox{background:rgba(255,255,255,0.07);color:#e5e5e7;"
            "border:1px solid rgba(255,255,255,0.12);border-radius:8px;"
            "padding:0 8px;font-size:12px;}"
            "QComboBox::drop-down{border:none;}"
            "QComboBox QAbstractItemView{background:#1c1c1e;color:#e5e5e7;"
            "selection-background-color:#0A84FF;border:1px solid #3a3a3c;}"
        )
        go_btn = QPushButton("Translate →")
        go_btn.setFixedHeight(30)
        go_btn.setCursor(Cursor.PointingHandCursor)
        go_btn.setStyleSheet(
            "QPushButton{color:#fff;background:#0A84FF;border:none;"
            "border-radius:8px;font-size:12px;font-weight:600;padding:0 12px;}"
            "QPushButton:hover{background:#1A94FF;}"
        )
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
        copy_tr = QPushButton("📋  Copy translation")
        copy_tr.setFixedHeight(30)
        copy_tr.setCursor(Cursor.PointingHandCursor)
        copy_tr.setStyleSheet(self._ghost_btn())
        copy_tr.clicked.connect(
            lambda: self._copy_and_flash(copy_tr, self._trans_box.toPlainText())
        )
        lo.addWidget(copy_tr)

    def _copy_and_flash(self, btn: QPushButton, text: str):
        QApplication.clipboard().setText(text)
        original = btn.text()
        btn.setText("✅  Copied!")
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
        self._status.setText("✓  Text recognized")

    def _on_ocr_error(self, msg: str):
        self._ocr_box.setPlainText(msg)
        self._status.setText("⚠  Could not read text")

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
            "QTextEdit{background:rgba(255,255,255,0.06);color:#e5e5e7;"
            "border:1px solid rgba(255,255,255,0.10);border-radius:8px;"
            "padding:6px;font-size:12px;}"
        )

    def _ghost_btn(self) -> str:
        return (
            "QPushButton{color:#98989d;background:rgba(255,255,255,0.06);"
            "border:1px solid rgba(255,255,255,0.12);border-radius:8px;"
            "font-size:12px;}"
            "QPushButton:hover{background:rgba(255,255,255,0.10);color:#e5e5e7;}"
        )

    def _sep(self) -> QFrame:
        f = QFrame(); f.setFrameShape(QFrame.Shape.HLine); f.setFixedHeight(1)
        f.setStyleSheet("background:rgba(255,255,255,0.06);margin:0;")
        return f


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


# ── Overlay window ─────────────────────────────────────────────────────────────
class AnnotationOverlay(QWidget):
    def __init__(self, settings_mgr: SettingsManager, hotkey_mgr: HotkeyManager):
        super().__init__(None,
                         WType.WindowStaysOnTopHint |
                         WType.FramelessWindowHint  |
                         WType.Tool)
        self.setAttribute(WAtt.WA_TranslucentBackground)
        self.setAttribute(WAtt.WA_NoSystemBackground)

        self.canvas  = Canvas(self)
        self.toolbar = Toolbar(self.canvas, self, settings_mgr, hotkey_mgr)
        self.canvas.setCursor(_cross_cursor())

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
        self.toolbar._activate("ocr")

    @pyqtSlot()
    def toggle(self):
        if self.isVisible():
            self.hide()
        else:
            self.show()
            self.raise_()
            self.activateWindow()

    def changeEvent(self, e):
        super().changeEvent(e)

    def keyPressEvent(self, e):
        k = e.key()
        mods = e.modifiers()
        if k == Key.Key_Escape:
            self.hide()
        elif k == Key.Key_C and not (mods & Qt.KeyboardModifier.ControlModifier):
            self.canvas.clear()
        elif k == Key.Key_Z and mods & Qt.KeyboardModifier.ControlModifier:
            self.canvas.undo()
        elif k == Key.Key_Y and mods & Qt.KeyboardModifier.ControlModifier:
            self.canvas.redo()
        elif k == Key.Key_Delete and self.canvas._selected:
            self.canvas._shapes.remove(self.canvas._selected)
            self.canvas._selected = None
            self.canvas.update()
        elif k in KEY_TOOL:
            self.toolbar._activate(KEY_TOOL[k])


# ── Global hotkey bootstrap ────────────────────────────────────────────────────
def _start_hotkey(overlay: AnnotationOverlay, hotkey_mgr: HotkeyManager,
                  hotkey: str):
    from PyQt6.QtCore import QMetaObject, Qt as _Qt
    def on_activate():
        QMetaObject.invokeMethod(overlay, "toggle",
                                 _Qt.ConnectionType.QueuedConnection)
    hotkey_mgr.start(hotkey, on_activate)


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

    settings_mgr = SettingsManager()
    hotkey_mgr   = HotkeyManager()
    overlay      = AnnotationOverlay(settings_mgr, hotkey_mgr)
    tray         = _setup_tray(overlay)
    _start_hotkey(overlay, hotkey_mgr, settings_mgr.get("hotkey"))

    from PyQt6.QtCore import QMetaObject, Qt as _Qt
    def _on_ocr():
        QMetaObject.invokeMethod(overlay, "activate_ocr",
                                 _Qt.ConnectionType.QueuedConnection)
    hotkey_mgr.start_ocr(settings_mgr.get("ocr_hotkey"), _on_ocr)

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
