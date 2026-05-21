#!/usr/bin/env python3
"""
Screen Annotation Tool  (PyQt6)
================================
Fullscreen transparent overlay — draw on your screen like a whiteboard.

Tools: Select, Pen, Line, Arrow, Rectangle, Circle, Ruler,
       Text, Callout, Steps, Highlight, Emoji, Bubble,
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

import sys, math, random as _rng, threading, platform
from PyQt6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QPushButton, QSlider, QLabel, QColorDialog, QGraphicsDropShadowEffect,
    QGraphicsBlurEffect, QGraphicsScene, QGraphicsPixmapItem,
    QInputDialog, QFrame, QSystemTrayIcon, QMenu, QFileDialog,
)
from PyQt6.QtCore import Qt, QPointF, QRectF, pyqtSlot
from PyQt6.QtGui import (
    QPainter, QPen, QColor, QFont, QBrush,
    QPolygonF, QPainterPath, QFontMetrics, QPixmap,
)

# ── Platform detection ─────────────────────────────────────────────────────────
IS_WIN = platform.system() == "Windows"
IS_MAC = platform.system() == "Darwin"

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

EMOJIS = ["⭐","✅","❌","⚠️","💡","🔥","👆","👇","👉","👈",
          "🔴","🟡","🟢","🔵","📌","🎯","🔍","💬"]

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
}

DRAG_TOOLS  = {"line","arrow","rect","circle","ruler","highlight","blur","pixel","redact"}
POINT_TOOLS = {"text","callout","steps"}

# [WIN-FIX] pick the right system emoji font per platform
EMOJI_FONT = "Segoe UI Emoji" if IS_WIN else ("Apple Color Emoji" if IS_MAC else "Noto Color Emoji")


# ── Helpers ────────────────────────────────────────────────────────────────────
def _norm(p1: QPointF, p2: QPointF) -> QRectF:
    return QRectF(min(p1.x(),p2.x()), min(p1.y(),p2.y()),
                  abs(p2.x()-p1.x()), abs(p2.y()-p1.y()))

def _pen(color: str, width: int) -> QPen:
    return QPen(QColor(color), width, PS.SolidLine, Cap.RoundCap, Join.RoundJoin)

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


class EmojiShape(Shape):
    def __init__(self, pos, emoji, size):
        self.pos, self.emoji, self.size = pos, emoji, size

    def draw(self, p):
        p.setFont(QFont(EMOJI_FONT, self.size))
        p.setPen(QPen(QColor("#000")))
        p.drawText(self.pos, self.emoji)

    def move(self, dx, dy): self.pos = QPointF(self.pos.x()+dx, self.pos.y()+dy)
    def bounding_rect(self): return QRectF(self.pos.x(), self.pos.y()-self.size, self.size*1.2, self.size*1.2)


class BubbleShape(Shape):
    def __init__(self, pos, text, color, font_size):
        self.pos, self.text, self.color, self.font_size = pos, text, color, font_size

    def draw(self, p):
        p.setRenderHint(RHint.Antialiasing)
        font = QFont("Arial", self.font_size)
        p.setFont(font)
        fm = QFontMetrics(font)
        tw, th = fm.horizontalAdvance(self.text), fm.height()
        pad, tail = 10, 12
        bx, by = self.pos.x(), self.pos.y() - th - pad*2 - tail
        bw, bh = tw + pad*2, th + pad*2
        path = QPainterPath()
        path.addRoundedRect(QRectF(bx, by, bw, bh), 8, 8)
        path.addPolygon(QPolygonF([QPointF(bx+16, by+bh), self.pos, QPointF(bx+32, by+bh)]))
        p.setPen(PS.NoPen); p.setBrush(QBrush(QColor(self.color)))
        p.drawPath(path)
        p.setPen(QPen(_contrast(self.color)))
        p.drawText(QRectF(bx+pad, by+pad, tw, th), AA.AlignLeft, self.text)

    def move(self, dx, dy): self.pos = QPointF(self.pos.x()+dx, self.pos.y()+dy)
    def bounding_rect(self): return QRectF(self.pos.x()-5, self.pos.y()-80, 200, 80)


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
        self.font_size  = 20

        self._shapes:    list[Shape] = []
        self._selected:  Shape | None = None
        self._drag_last  = QPointF()

        self._drawing    = False
        self._start      = QPointF()
        self._cur        = QPointF()
        self._pen_shape: PenShape | None = None

        self._callout_n  = 1
        self._step_n     = 1

        # Laser pointer — tracks mouse position, never commits to _shapes
        self._laser_pos: QPointF | None = None

    def mousePressEvent(self, e):
        print(f"[PRESS] btn={e.button()} tool={self.tool} pos={e.pos()} overlay_active={self.window().isActiveWindow()}")
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
            self._pen_shape = PenShape(self.pen_color, self.pen_width)
            self._pen_shape.pts.append(pos); return

        if self.tool in POINT_TOOLS:
            self._place_point(pos)
            self._drawing = False; return

    def mouseMoveEvent(self, e):
        pos = QPointF(e.pos())
        if not hasattr(self, '_move_count'): self._move_count = 0
        self._move_count += 1
        if self._move_count % 20 == 1:
            print(f"[MOVE]  tool={self.tool} drawing={self._drawing} pos={e.pos()}")

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

        if self.tool in DRAG_TOOLS:
            self.update()

    def mouseReleaseEvent(self, e):
        print(f"[RELEASE] btn={e.button()} tool={self.tool} drawing={self._drawing}")
        if e.button() != MB.LeftButton or not self._drawing: return
        self._drawing = False
        pos = QPointF(e.pos()); self._cur = pos

        if self.tool == "laser":
            return  # laser never commits shapes

        if self.tool == "pen" and self._pen_shape:
            if len(self._pen_shape.pts) > 1:
                self._shapes.append(self._pen_shape)
            self._pen_shape = None
            self.update(); return

        if self.tool in DRAG_TOOLS:
            if self.tool == "blur":
                rect = _norm(self._start, pos)
                if rect.width() > 3 and rect.height() > 3:
                    raw = self._grab_behind(rect)
                    blurred = _blur_pixmap(raw)
                    self._shapes.append(BlurShape(self._start, pos, blurred))
            else:
                s = self._make_drag(self._start, pos)
                if s: self._shapes.append(s)
            self.update()

    def _place_point(self, pos: QPointF):
        t = self.tool
        if t == "text":
            text, ok = QInputDialog.getText(self, "Add Text", "Text:")
            if ok and text:
                self._shapes.append(TextShape(pos, text, self.pen_color, self.font_size))
        elif t == "callout":
            self._shapes.append(CalloutShape(pos, self._callout_n, self.pen_color))
            self._callout_n += 1
        elif t == "steps":
            self._shapes.append(StepShape(pos, self._step_n, self.pen_color))
            self._step_n += 1
        self.update()

    def _make_drag(self, p1: QPointF, p2: QPointF) -> Shape | None:
        if abs(p2.x()-p1.x()) < 3 and abs(p2.y()-p1.y()) < 3: return None
        t = self.tool
        if t == "line":      return LineShape(p1, p2, self.pen_color, self.pen_width)
        if t == "arrow":     return ArrowShape(p1, p2, self.pen_color, self.pen_width)
        if t == "rect":      return RectShape(p1, p2, self.pen_color, self.pen_width)
        if t == "circle":    return CircleShape(p1, p2, self.pen_color, self.pen_width)
        if t == "ruler":     return RulerShape(p1, p2, self.pen_color, self.pen_width)
        if t == "highlight": return HighlightShape(p1, p2, self.pen_color)
        if t == "blur":      return BlurShape(p1, p2)
        if t == "pixel":     return PixelShape(p1, p2)
        if t == "redact":    return RedactShape(p1, p2)
        return None

    def capture_annotated(self) -> QPixmap:
        """Grab the desktop behind the overlay and composite all shapes on top."""
        overlay = self.window()
        overlay.setWindowOpacity(0.0)
        QApplication.processEvents()
        bg = QApplication.primaryScreen().grabWindow(0)
        overlay.setWindowOpacity(1.0)
        p = QPainter(bg)
        p.setRenderHint(RHint.Antialiasing)
        for shape in self._shapes:
            shape.draw(p)
        p.end()
        return bg

    def undo(self):
        if self._shapes: self._shapes.pop(); self.update()

    def clear(self):
        self._shapes.clear()
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
        )
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
        if self.tool == "pen" and self._pen_shape: self._pen_shape.draw(p)
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


# ── Toolbar (vertical floating panel) ─────────────────────────────────────────
TOOL_GROUPS = [
    ("✏️ Draw", [
        ("select",    "↖",  "Select / Move"),
        ("pen",       "〜", "Pen"),
        ("line",      "—",  "Line"),
        ("arrow",     "→",  "Arrow"),
        ("rect",      "▭",  "Rectangle"),
        ("circle",    "○",  "Circle"),
        ("ruler",     "📏", "Ruler"),
        ("laser",     "⊙",  "Laser  I"),        # ← laser pointer
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
]

class Toolbar(QWidget):
    def __init__(self, canvas: Canvas, overlay: QWidget):
        super().__init__(overlay)
        self.canvas  = canvas
        self.overlay = overlay
        self._drag_pos         = None
        self._active_color_btn = None
        self._tool_btns: dict[str, QPushButton] = {}
        self._build()
        self._position()

    def _build(self):
        lo = QVBoxLayout(self)
        lo.setContentsMargins(12, 14, 12, 14)
        lo.setSpacing(2)

        # ── Drag handle ───────────────────────────────────────────────────────
        drag_lbl = QLabel("⠿  Annotation Tool")
        drag_lbl.setAlignment(AA.AlignCenter)
        drag_lbl.setStyleSheet("color:#48484a;font-size:11px;font-weight:600;")
        drag_lbl.setCursor(Cursor.SizeAllCursor)
        lo.addWidget(drag_lbl)
        lo.addWidget(self._hsep())
        lo.addSpacing(4)

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

        slider = QSlider(Ori.Horizontal)
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

        for icon, label, fn, danger in [
            ("↩", "Undo",      self.canvas.undo,  False),
            ("🗑", "Clear all", self.canvas.clear, False),
            ("✕", "Exit",      QApplication.quit, True),
        ]:
            color = "#FF453A" if danger else "#aeaeb2"
            hover = "rgba(255,69,58,0.12)" if danger else "rgba(255,255,255,0.06)"
            btn = QPushButton(f"  {icon}  {label}")
            btn.setFixedHeight(32)
            btn.setCursor(Cursor.PointingHandCursor)
            btn.setStyleSheet(
                f"QPushButton{{color:{color};background:transparent;border-radius:8px;"
                f"font-size:13px;text-align:left;border:none;}}"
                f"QPushButton:hover{{background:{hover};}}"
            )
            btn.clicked.connect(fn)
            lo.addWidget(btn)

        self.setFixedWidth(200)
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
        # Clear laser dot when switching away from laser tool
        if tid != "laser":
            self.canvas._laser_pos = None
            self.canvas.update()
        for sec in self._sections:
            sec.check_tool(tid)
        sec = self._all_btns.get(tid)
        if sec: sec.expand()
        print(f"[TOOL]  switched to '{tid}'")

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

    def _position(self):
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
    def __init__(self):
        super().__init__(None,
                         WType.WindowStaysOnTopHint |
                         WType.FramelessWindowHint  |
                         WType.Tool)
        self.setAttribute(WAtt.WA_TranslucentBackground)
        self.setAttribute(WAtt.WA_NoSystemBackground)

        screen = QApplication.primaryScreen().geometry()
        self.setGeometry(screen)

        self.canvas = Canvas(self)
        self.canvas.setGeometry(0, 0, screen.width(), screen.height())
        self.toolbar = Toolbar(self.canvas, self)

        self.show()
        self.raise_()
        self.activateWindow()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setCompositionMode(CM.CompositionMode_Clear)
        p.fillRect(self.rect(), QColor(0, 0, 0, 0))
        p.setCompositionMode(CM.CompositionMode_SourceOver)
        if IS_WIN:
            p.fillRect(self.rect(), QColor(0, 0, 0, 1))
        p.end()

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
        from PyQt6.QtCore import QEvent
        if e.type() == QEvent.Type.ActivationChange:
            print(f"[OVERLAY] ActivationChange → isActiveWindow={self.isActiveWindow()}")

    def keyPressEvent(self, e):
        k = e.key()
        mods = e.modifiers()
        if k == Key.Key_Escape:
            self.hide()
        elif k == Key.Key_C and not (mods & Qt.KeyboardModifier.ControlModifier):
            self.canvas.clear()
        elif k == Key.Key_Z and mods & Qt.KeyboardModifier.ControlModifier:
            self.canvas.undo()
        elif k == Key.Key_Delete and self.canvas._selected:
            self.canvas._shapes.remove(self.canvas._selected)
            self.canvas._selected = None
            self.canvas.update()
        elif k in KEY_TOOL:
            self.toolbar._activate(KEY_TOOL[k])


# ── Global hotkey (Ctrl+Shift+A) ───────────────────────────────────────────────
def _start_hotkey(overlay: AnnotationOverlay):
    import os
    on_wayland = (
        os.environ.get("WAYLAND_DISPLAY") or
        os.environ.get("XDG_SESSION_TYPE", "").lower() == "wayland"
    )
    if on_wayland:
        print("Warning: Wayland detected - global hotkey (Ctrl+Shift+A) not available.")
        print("   Use the tray icon or run with QT_QPA_PLATFORM=xcb for X11 mode.")
        return

    try:
        from pynput import keyboard as kb
    except ImportError:
        print("Tip: pip install pynput  to enable Ctrl+Shift+A toggle hotkey")
        return

    from PyQt6.QtCore import QMetaObject, Qt as _Qt

    def on_activate():
        QMetaObject.invokeMethod(overlay, "toggle",
                                 _Qt.ConnectionType.QueuedConnection)

    try:
        listener = kb.GlobalHotKeys({"<ctrl>+<shift>+a": on_activate})
        listener.daemon = True
        listener.start()
        print("Hotkey active: Ctrl+Shift+A to show/hide")
    except Exception as ex:
        print(f"Warning: Could not register hotkey: {ex}")


# ── System tray ────────────────────────────────────────────────────────────────
def _setup_tray(overlay: AnnotationOverlay) -> QSystemTrayIcon:
    from PyQt6.QtGui import QPixmap, QIcon, QColor
    pix = QPixmap(16, 16)
    pix.fill(QColor(0, 0, 0, 0))
    from PyQt6.QtGui import QPainter as _P
    p = _P(pix)
    p.setRenderHint(_P.RenderHint.Antialiasing)
    p.setBrush(QColor("#0A84FF"))
    p.setPen(Qt.PenStyle.NoPen)
    p.drawEllipse(1, 1, 14, 14)
    p.end()

    tray = QSystemTrayIcon(QIcon(pix))
    tray.setToolTip("Annotation Tool  —  click to show/hide")

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
    if IS_WIN:
        QApplication.setHighDpiScaleFactorRoundingPolicy(
            Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
        )

    app = QApplication(sys.argv)
    app.setApplicationName("Screen Annotator")
    app.setQuitOnLastWindowClosed(False)
    overlay = AnnotationOverlay()
    tray = _setup_tray(overlay)
    _start_hotkey(overlay)

    plat = f"Windows {platform.release()}" if IS_WIN else platform.system()
    print("-" * 55)
    print(f"  Screen Annotation Tool  --  PyQt6  [{plat}]")
    print("-" * 55)
    print("  Toggle     : Ctrl+Shift+A  (show / hide)")
    print("  Tools      : toolbar buttons or key shortcuts")
    print("  Laser      : I key  (no marks left on canvas)")
    print("  Undo       : Ctrl+Z  |  Clear: C")
    print("  Hide       : Esc")
    print("  Exit       : X button in toolbar")
    print("-" * 55)
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
