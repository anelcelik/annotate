#!/usr/bin/env python3
"""
dock_toolbar.py — horizontal dock toolbar for Screen Annotator Pro
==================================================================

Drop-in replacement for the vertical `Toolbar` panel in annotate.py.

Same public API, so nothing else has to change:

    Toolbar(canvas, overlay, settings_mgr, hotkey_mgr)   # QWidget child of overlay
    toolbar._activate(tool_id)                           # called by key handler + OCR hotkey

WIRING (one line in annotate.py)
--------------------------------
Put this immediately BEFORE `class AnnotationOverlay(QWidget):` (around line 2252).
It rebinds the name `Toolbar`, so the old class stays in the file untouched and you
can flip back by commenting the line out:

    from dock_toolbar import Toolbar        # noqa: E402  — horizontal dock

You can also delete the old `Toolbar`, `ToolSection`, `DotPreview` and `TOOL_GROUPS`
once you're happy with this one.

OPTIONAL (two one-line edits, only if you want the Blur/Pixelate sliders to do
something — without them the sliders are shown but ignored):

  1. in `_blur_pixmap(pixmap, radius=18)` the call site becomes
         blurred = _blur_pixmap(raw, getattr(self, "blur_radius", 18))
     inside Canvas.mouseReleaseEvent.

  2. in `PixelShape.draw`, replace `pz = 12` with
         pz = getattr(self, "size", 12)
     and in `Canvas._make_drag`, `if t == "pixel":` becomes
         s = PixelShape(p1, p2); s.size = getattr(self, "pixel_size", 12); return s

WHAT CHANGED VS THE OLD PANEL
-----------------------------
* One horizontal dock at the bottom of the screen instead of a 940px column.
* 17 tools as icons on one line, grouped Draw / Annotate / Redact / Read by 2px rules.
* Shortcut key printed in the corner of each tool instead of a text label.
* Second row shows ONLY the properties the active tool uses.
* One stroked icon set — no emoji (they render differently on every Windows build).
* Undo / Redo / Clear sit in a tinted cell behind a rule; Exit is the only red fill.
* Flat: zero corner radius, 2px rules, ink on a light ground.
"""

from PyQt6.QtWidgets import (
    QWidget, QPushButton, QHBoxLayout, QVBoxLayout, QLabel, QSlider,
    QFrame, QApplication, QColorDialog, QSizePolicy,
)
from PyQt6.QtCore import Qt, QRect, QRectF, QPointF, QPoint, QSize
from PyQt6.QtGui import (
    QPainter, QPen, QColor, QBrush, QFont, QPainterPath, QPolygonF, QCursor,
)

# ── Tokens ────────────────────────────────────────────────────────────────────
# Two palettes, swapped live by set_theme(). Everything below reads these as
# plain module globals — paintEvent-based widgets (ToolButton, ActionButton,
# Toolbar's own chrome, …) pick the change up on their next repaint for free;
# the handful of things baked into a setStyleSheet() string at build time
# (DockSlider, the props row background, the custom-colour "+" button) get
# rebuilt explicitly by Toolbar.refresh_theme().
THEMES = {
    "light": dict(
        ink="#201e1d", ground="#f3f2f2", surface="#eae9e9",
        tint="#ffe0d9", accent="#ec3013", accent_600="#dd2b0f",
        muted="#7d7979", hover=QColor(32, 30, 29, 20),
    ),
    "dark": dict(
        ink="#f3f2f2", ground="#201e1d", surface="#2c2a29",
        tint="#3a1f1a", accent="#ec3013", accent_600="#dd2b0f",
        muted="#9b9797", hover=QColor(243, 242, 242, 25),
    ),
}
_current_theme = "light"


def set_theme(name: str):
    """Switch the module-level color tokens to the named palette."""
    global INK, GROUND, SURFACE, TINT, ACCENT, ACCENT_600, MUTED, HOVER
    global _current_theme
    t = THEMES.get(name, THEMES["light"])
    INK, GROUND, SURFACE  = t["ink"], t["ground"], t["surface"]
    TINT, ACCENT           = t["tint"], t["accent"]
    ACCENT_600, MUTED      = t["accent_600"], t["muted"]
    HOVER                  = t["hover"]
    _current_theme = name if name in THEMES else "light"


def current_theme() -> str:
    return _current_theme


INK        = THEMES["light"]["ink"]
GROUND     = THEMES["light"]["ground"]
SURFACE    = THEMES["light"]["surface"]
TINT       = THEMES["light"]["tint"]
ACCENT     = THEMES["light"]["accent"]
ACCENT_600 = THEMES["light"]["accent_600"]
MUTED      = THEMES["light"]["muted"]
HOVER      = THEMES["light"]["hover"]

# ── Dock size ─────────────────────────────────────────────────────────────────
# Every measurement on the dock derives from one factor, so the whole thing
# scales as a unit instead of drifting out of proportion. 1.0 is the original
# size; the default is smaller because the dock is wide, and on a laptop or a
# VM that cannot drop its display scaling it ran off the edge. 0.78 measures
# as 17 % narrower than the original dock — the factor and the result differ
# because the rules between cells cannot go below 1 px, and because the dock
# has gained a minimise button since.
DOCK_SCALE = 0.78


def _s(n: float) -> int:
    """Scale a pixel measurement."""
    return max(1, round(n * DOCK_SCALE))


def _fs(pt: float) -> int:
    """Scale a font point size, with a floor where text stops being legible."""
    return max(6, round(pt * DOCK_SCALE))


CELL   = 48       # tool button width   ) recomputed by set_dock_scale();
ROW1   = 56       # tool row height     ) the values here are the 1.0 sizes
ROW2   = 52       # property row height )
RULE   = 2


def set_dock_scale(scale: float):
    """Resize the whole dock. Call before building the Toolbar."""
    global DOCK_SCALE, CELL, ROW1, ROW2, RULE
    DOCK_SCALE = max(0.6, min(1.25, float(scale or 1.0)))
    CELL, ROW1, ROW2 = _s(48), _s(56), _s(52)
    RULE = max(1, _s(2))


set_dock_scale(DOCK_SCALE)

FONT = "Segoe UI Variable"  # Archivo isn't bundled; this ships with Windows 11

# ── Tool table ────────────────────────────────────────────────────────────────
# (id, label, shortcut, [properties], tip)
DOCK_TOOLS = [
    # Draw
    ("select",    "Select",        "V", [],                                 "Drag any existing shape. Delete removes it."),
    ("pen",       "Pen",           "P", ["color", "stroke", "opacity"],     ""),
    ("line",      "Line",          "L", ["color", "stroke", "opacity"],     "Hold Shift to snap to 45°."),
    ("arrow",     "Arrow",         "A", ["color", "stroke", "opacity"],     "Hold Shift to snap to 45°."),
    ("rect",      "Rectangle",     "R", ["color", "stroke", "opacity"],     "Hold Shift for a perfect square."),
    ("circle",    "Circle",        "O", ["color", "stroke", "opacity"],     "Hold Shift for a perfect circle."),
    ("ruler",     "Ruler",         "U", ["color", "stroke"],                "Measures in pixels as you drag."),
    ("eraser",    "Eraser",        "E", ["stroke"],                         "Erase width is four times the stroke."),
    ("laser",     "Laser pointer", "I", ["color"],                          "Leaves no marks. Hides the OS cursor."),
    # Annotate
    ("text",      "Text",          "T", ["color", "size", "opacity"],       "Click to place, then type."),
    ("callout",   "Callout",       "K", ["color", "size"],                  "Numbers itself. Resets on Clear."),
    ("steps",     "Steps",         "S", ["color", "size"],                  "Numbers itself. Resets on Clear."),
    ("highlight", "Highlight",     "H", ["color", "stroke", "opacity"],     ""),
    # Redact
    ("blur",      "Blur",          "Z", ["blur"],                           "Drag a region to blur it."),
    ("pixel",     "Pixelate",      "X", ["pixel"],                          "Drag a region to pixelate it."),
    ("redact",    "Black box",     "D", [],                                 "Drag a region to cover it completely."),
    # Read
    ("ocr",       "Snip & Read",   "J", [],                                 "Drag over text to extract and translate it."),
]

GROUPS = [
    ["select", "pen", "line", "arrow", "rect", "circle", "ruler", "eraser", "laser"],
    ["text", "callout", "steps", "highlight"],
    ["blur", "pixel", "redact"],
    ["ocr"],
]

TOOL_META = {t[0]: t for t in DOCK_TOOLS}

# Six swatches on the dock; the rest stay behind the custom-colour button.
DOCK_SWATCHES = ["#FF3B3B", "#FF9F0A", "#0A84FF", "#32D74B", "#1C1C1E", "#FFFFFF"]


# ── Icon painting ─────────────────────────────────────────────────────────────
def _paint_icon(p: QPainter, tid: str, size: float, color: QColor):
    """Draw a 24x24 stroked icon, already translated so (0,0) is its top-left."""
    p.save()
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    s = size / 24.0
    p.scale(s, s)
    pen = QPen(color, 2.0, Qt.PenStyle.SolidLine,
               Qt.PenCapStyle.SquareCap, Qt.PenJoinStyle.MiterJoin)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)

    def line(x1, y1, x2, y2):
        p.drawLine(QPointF(x1, y1), QPointF(x2, y2))

    if tid == "select":
        poly = QPolygonF([QPointF(5, 3), QPointF(19, 11), QPointF(12, 13),
                          QPointF(9.5, 20)])
        p.setBrush(QBrush(color))
        p.drawPolygon(poly)

    elif tid == "pen":
        p.drawPolyline(QPolygonF([QPointF(3, 21), QPointF(4, 17),
                                  QPointF(17, 4), QPointF(20, 7),
                                  QPointF(7, 20), QPointF(3, 21)]))
        line(15, 6, 18, 9)

    elif tid == "line":
        line(4, 20, 20, 4)

    elif tid == "arrow":
        line(5, 19, 19, 5)
        p.drawPolyline(QPolygonF([QPointF(9, 5), QPointF(19, 5), QPointF(19, 15)]))

    elif tid == "rect":
        p.drawRect(QRectF(3, 5, 18, 14))

    elif tid == "circle":
        p.drawEllipse(QRectF(3, 3, 18, 18))

    elif tid == "ruler":
        p.save()
        p.translate(12, 12)
        p.rotate(-45)
        p.drawRect(QRectF(-11, -4.5, 22, 9))
        for x in (-5.5, 0, 5.5):
            line(x, -4.5, x, -1)
        p.restore()

    elif tid == "eraser":
        p.drawPolyline(QPolygonF([QPointF(7, 20), QPointF(3, 16), QPointF(13, 6),
                                  QPointF(19, 12), QPointF(11, 20), QPointF(7, 20)]))
        line(3, 21.5, 21, 21.5)

    elif tid == "laser":
        p.setBrush(QBrush(color))
        p.drawEllipse(QPointF(12, 12), 3.0, 3.0)
        p.setBrush(Qt.BrushStyle.NoBrush)
        dashed = QPen(color, 2.0)
        dashed.setDashPattern([2, 2])
        p.setPen(dashed)
        p.drawEllipse(QPointF(12, 12), 8.0, 8.0)
        p.setPen(pen)

    elif tid == "text":
        p.drawPolyline(QPolygonF([QPointF(4, 7), QPointF(4, 4), QPointF(20, 4),
                                  QPointF(20, 7)]))
        line(12, 4, 12, 20)
        line(9, 20, 15, 20)

    elif tid == "callout":
        p.drawEllipse(QRectF(3, 3, 18, 18))
        p.drawPolyline(QPolygonF([QPointF(10.5, 9.5), QPointF(12.5, 8),
                                  QPointF(12.5, 16)]))

    elif tid == "steps":
        p.drawRect(QRectF(3, 3, 8, 8))
        p.drawRect(QRectF(13, 13, 8, 8))

    elif tid == "highlight":
        p.drawPolyline(QPolygonF([QPointF(9, 11), QPointF(3, 17), QPointF(3, 20),
                                  QPointF(12, 20), QPointF(15, 17)]))
        p.drawPolygon(QPolygonF([QPointF(22, 12), QPointF(15.5, 5.5),
                                 QPointF(8.5, 12.5), QPointF(15, 19)]))

    elif tid == "blur":
        p.drawEllipse(QPointF(9, 12), 6.0, 6.0)
        dashed = QPen(color, 2.0)
        dashed.setDashPattern([2, 2])
        p.setPen(dashed)
        p.drawEllipse(QPointF(15, 12), 6.0, 6.0)
        p.setPen(pen)

    elif tid == "pixel":
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(color))
        for x, y in ((3, 3), (15, 3), (9, 9), (3, 15), (15, 15)):
            p.drawRect(QRectF(x, y, 6, 6))

    elif tid == "redact":
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(color))
        p.drawRect(QRectF(3, 7, 18, 10))

    elif tid == "ocr":
        p.drawPolyline(QPolygonF([QPointF(3, 7), QPointF(3, 4), QPointF(7, 4)]))
        p.drawPolyline(QPolygonF([QPointF(17, 4), QPointF(21, 4), QPointF(21, 7)]))
        p.drawPolyline(QPolygonF([QPointF(21, 17), QPointF(21, 20), QPointF(17, 20)]))
        p.drawPolyline(QPolygonF([QPointF(7, 20), QPointF(3, 20), QPointF(3, 17)]))
        line(7, 10, 17, 10)
        line(7, 14, 13, 14)

    # ── action icons ──────────────────────────────────────────────────────────
    elif tid == "undo":
        p.drawPolyline(QPolygonF([QPointF(9, 14), QPointF(4, 9), QPointF(9, 4)]))
        path = QPainterPath(QPointF(4, 9))
        path.lineTo(14.5, 9)
        path.arcTo(QRectF(9, 9, 11, 11), 90, -180)
        path.lineTo(10, 20)
        p.drawPath(path)

    elif tid == "redo":
        p.drawPolyline(QPolygonF([QPointF(15, 14), QPointF(20, 9), QPointF(15, 4)]))
        path = QPainterPath(QPointF(20, 9))
        path.lineTo(9.5, 9)
        path.arcTo(QRectF(4, 9, 11, 11), 90, 180)
        path.lineTo(14, 20)
        p.drawPath(path)

    elif tid == "clear":
        line(3, 6, 21, 6)
        p.drawPolyline(QPolygonF([QPointF(8, 6), QPointF(8, 4), QPointF(16, 4),
                                  QPointF(16, 6)]))
        p.drawPolyline(QPolygonF([QPointF(6, 6), QPointF(7, 20), QPointF(17, 20),
                                  QPointF(18, 6)]))

    elif tid == "camera":
        p.drawPolyline(QPolygonF([QPointF(3, 7), QPointF(7, 7), QPointF(9, 4),
                                  QPointF(15, 4), QPointF(17, 7), QPointF(21, 7),
                                  QPointF(21, 20), QPointF(3, 20), QPointF(3, 7)]))
        p.drawEllipse(QPointF(12, 13), 4.0, 4.0)

    elif tid == "settings":
        p.drawEllipse(QPointF(12, 12), 3.2, 3.2)
        for x1, y1, x2, y2 in ((12, 2, 12, 5), (12, 19, 12, 22), (2, 12, 5, 12),
                               (19, 12, 22, 12), (4.9, 4.9, 7, 7), (17, 17, 19.1, 19.1),
                               (19.1, 4.9, 17, 7), (7, 17, 4.9, 19.1)):
            line(x1, y1, x2, y2)

    elif tid == "pause":
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(color))
        p.drawRect(QRectF(6, 5, 4, 14))
        p.drawRect(QRectF(14, 5, 4, 14))

    elif tid == "close":
        pen.setWidthF(2.4)
        p.setPen(pen)
        line(5, 5, 19, 19)
        line(19, 5, 5, 19)

    elif tid == "record":
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(color))
        p.drawEllipse(QPointF(12, 12), 7.0, 7.0)

    elif tid == "stop":
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(color))
        p.drawRect(QRectF(6, 6, 12, 12))

    elif tid == "collapse":
        # Chevron over a bar: "fold this down into the puck".
        p.drawPolyline(QPolygonF([QPointF(6, 8), QPointF(12, 14), QPointF(18, 8)]))
        line(6, 18, 18, 18)

    elif tid == "grip":
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(color))
        for cy in (5, 12, 19):
            for cx in (8, 16):
                p.drawEllipse(QPointF(cx, cy), 1.6, 1.6)

    p.restore()


# ── Buttons ───────────────────────────────────────────────────────────────────
class ToolButton(QPushButton):
    """48x56 icon cell. Active = accent tint + 4px accent bar, never a colour swap."""

    def __init__(self, tid: str, key: str, tooltip: str, parent=None):
        super().__init__(parent)
        self.tid = tid
        self.key = key
        self.show_key = True
        self.setCheckable(True)
        self.setFixedSize(CELL, ROW1)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip(tooltip)
        self.setFlat(True)
        self.setStyleSheet("border:none;background:transparent;")

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()

        if self.isChecked():
            p.fillRect(0, 0, w, h, QColor(TINT))
            p.fillRect(0, h - 4, w, 4, QColor(ACCENT))
        elif self.underMouse():
            p.fillRect(0, 0, w, h, HOVER)

        p.save()
        ic = _s(20)
        p.translate((w - ic) / 2, (h - ic) / 2 - 1)
        _paint_icon(p, self.tid, ic, QColor(INK))
        p.restore()

        if self.show_key and self.key:
            f = QFont(FONT, _fs(7))
            f.setBold(True)
            p.setFont(f)
            p.setPen(QPen(QColor(MUTED)))
            p.drawText(QRectF(0, h - _s(17), w - _s(5), _s(12)),
                       Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                       self.key)
        p.end()

    def enterEvent(self, e):
        self.update(); super().enterEvent(e)

    def leaveEvent(self, e):
        self.update(); super().leaveEvent(e)


class ActionButton(QPushButton):
    """Icon-only action cell — undo / redo / clear / settings / pause / exit."""

    def __init__(self, tid: str, tooltip: str, danger=False, width=CELL, parent=None):
        super().__init__(parent)
        self.tid = tid
        self.danger = danger
        self.setFixedSize(width, ROW1)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip(tooltip)
        self.setFlat(True)
        self.setStyleSheet("border:none;background:transparent;")

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        if self.danger:
            p.fillRect(0, 0, w, h,
                       QColor(ACCENT_600 if self.underMouse() else ACCENT))
            fg = QColor("#ffffff")
        else:
            if self.underMouse():
                p.fillRect(0, 0, w, h, HOVER)
            fg = QColor("#444141")
        p.save()
        ic = _s(19)
        p.translate((w - ic) / 2, (h - ic) / 2)
        _paint_icon(p, self.tid, ic, fg)
        p.restore()
        p.end()

    def enterEvent(self, e):
        self.update(); super().enterEvent(e)

    def leaveEvent(self, e):
        self.update(); super().leaveEvent(e)


class CaptureButton(QPushButton):
    """Icon + flush-left label — the only labelled control on the tool row."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(_s(118), ROW1)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip("Screenshot — hides the overlay, grabs every monitor")
        self.setFlat(True)
        self.setStyleSheet("border:none;background:transparent;")

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        if self.underMouse():
            p.fillRect(0, 0, w, h, HOVER)
        p.save()
        ic = _s(19)
        p.translate(_s(14), (h - ic) / 2)
        _paint_icon(p, "camera", ic, QColor(INK))
        p.restore()
        f = QFont(FONT, _fs(9))
        f.setBold(True)
        p.setFont(f)
        p.setPen(QPen(QColor(INK)))
        p.drawText(QRectF(_s(41), 0, w - _s(41), h),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   "Capture")
        p.end()

    def enterEvent(self, e):
        self.update(); super().enterEvent(e)

    def leaveEvent(self, e):
        self.update(); super().leaveEvent(e)


class ModeButton(QPushButton):
    """Draw ⇄ click-through, and the dock's most important control.

    It shows the state rather than the action: what you need at a glance is
    "is this thing eating my clicks right now", not what the button will do.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(_s(140), ROW1)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFlat(True)
        self.setStyleSheet("border:none;background:transparent;")
        self._passthrough = False
        self._shortcut = "Ctrl+Shift+A"
        self._sync_tip()

    def set_passthrough(self, on: bool):
        self._passthrough = on
        self._sync_tip()
        self.update()

    def set_shortcut_label(self, text: str):
        self._shortcut = text or "—"
        self._sync_tip()

    def _sync_tip(self):
        self.setToolTip(
            f"Click-through — your clicks go to the app underneath. "
            f"{self._shortcut} to draw again."
            if self._passthrough else
            f"Drawing — the overlay has the mouse. {self._shortcut} to use "
            f"your computer normally.")

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        if self._passthrough:
            if self.underMouse():
                p.fillRect(0, 0, w, h, HOVER)
            ink, icon, label = QColor(MUTED), "select", "Click-through"
        else:
            p.fillRect(0, 0, w, h, QColor(ACCENT))
            ink, icon, label = QColor("#FFFFFF"), "pen", "Drawing"
        p.save()
        ic = _s(18)
        p.translate(_s(12), (h - ic) / 2)
        _paint_icon(p, icon, ic, ink)
        p.restore()
        f = QFont(FONT, _fs(9))
        f.setBold(True)
        p.setFont(f)
        p.setPen(QPen(ink))
        p.drawText(QRectF(_s(38), 0, w - _s(38), h),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   label)
        p.end()

    def enterEvent(self, e):
        self.update(); super().enterEvent(e)

    def leaveEvent(self, e):
        self.update(); super().leaveEvent(e)


class RecordButton(QPushButton):
    """Twin of CaptureButton for video: red dot + "Record", and while rolling,
    a solid red cell counting up. It is the same control either way — one
    place to look, whatever state the app is in."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(_s(132), ROW1)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFlat(True)
        self.setStyleSheet("border:none;background:transparent;")
        self._recording = False
        self._elapsed   = "00:00"
        self._sync_tip()

    def set_recording(self, on: bool):
        self._recording = on
        self._elapsed = "00:00"
        self._sync_tip()
        self.update()

    def set_elapsed(self, text: str):
        if self._recording and text != self._elapsed:
            self._elapsed = text
            self.update()

    def _sync_tip(self):
        self.setToolTip("Stop recording — Ctrl+Shift+R" if self._recording
                        else "Record the screen with your annotations — "
                             "Ctrl+Shift+R")

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        if self._recording:
            p.fillRect(0, 0, w, h, QColor("#FF3B3B"))
            ink, icon, label = QColor("#FFFFFF"), "stop", self._elapsed
        else:
            if self.underMouse():
                p.fillRect(0, 0, w, h, HOVER)
            ink, icon, label = QColor(INK), "record", "Record"
        p.save()
        ic = _s(19)
        p.translate(_s(14), (h - ic) / 2)
        _paint_icon(p, icon, ic, QColor("#FF3B3B") if not self._recording else ink)
        p.restore()
        f = QFont(FONT, _fs(9))
        f.setBold(True)
        p.setFont(f)
        p.setPen(QPen(ink))
        p.drawText(QRectF(_s(41), 0, w - _s(41), h),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   label)
        p.end()

    def enterEvent(self, e):
        self.update(); super().enterEvent(e)

    def leaveEvent(self, e):
        self.update(); super().leaveEvent(e)


class Swatch(QPushButton):
    def __init__(self, hex_c: str, parent=None):
        super().__init__(parent)
        self.hex_c = hex_c
        self.active = False
        self.setFixedSize(_s(22), _s(22))
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip(hex_c)
        self.setFlat(True)
        self.setStyleSheet("border:none;background:transparent;")

    def paintEvent(self, _):
        p = QPainter(self)
        p.fillRect(2, 2, 18, 18, QColor(self.hex_c))
        p.setBrush(Qt.BrushStyle.NoBrush)
        if self.active:
            p.setPen(QPen(QColor(INK), 2))
            p.drawRect(1, 1, 20, 20)
        else:
            p.setPen(QPen(QColor(32, 30, 29, 90), 1))
            p.drawRect(2, 2, 18, 18)
        p.end()


class DockSlider(QSlider):
    """Flat slider — square handle, accent fill, no scroll-wheel hijack."""

    def __init__(self, lo, hi, val, parent=None):
        super().__init__(Qt.Orientation.Horizontal, parent)
        self.setRange(lo, hi)
        self.setValue(val)
        self.setFixedWidth(_s(104))
        self.setStyleSheet(
            "QSlider{background:transparent;}"
            "QSlider::groove:horizontal{height:2px;background:#9b9797;}"
            f"QSlider::sub-page:horizontal{{background:{ACCENT};}}"
            f"QSlider::handle:horizontal{{width:8px;height:16px;background:{INK};margin:-7px 0;}}"
        )

    def wheelEvent(self, e):
        e.ignore()


def _vrule() -> QFrame:
    f = QFrame()
    f.setFrameShape(QFrame.Shape.VLine)
    f.setFixedWidth(RULE)
    f.setStyleSheet(f"background:{INK};border:none;")
    return f


def _label(text: str, size=7, bold=True, color=MUTED) -> QLabel:
    l = QLabel(text)
    f = QFont(FONT, _fs(size))
    f.setBold(bold)
    f.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 0.8)
    l.setFont(f)
    l.setStyleSheet(f"color:{color};background:transparent;")
    return l


def _center_of(widget) -> QPoint:
    """A widget's center, using plain floor-division halves.

    Deliberately NOT widget.geometry().center() — QRect.center() uses Qt's
    inclusive-rect convention (right edge = x + w - 1), which for an even
    width/height is off by one from `top_left = center - QPoint(w//2,
    h//2)` (used everywhere the dock/puck's anchor gets turned back into a
    position). Mixing the two was quietly drifting the anchor by a pixel on
    every single collapse/expand round trip.
    """
    return widget.pos() + QPoint(widget.width() // 2, widget.height() // 2)


# ── Collapsed indicator ──────────────────────────────────────────────────────
class CollapsedIndicator(QWidget):
    """Stands in for the full dock while it's collapsed — the tool puck.

    The same cell the active tool renders as inside the dock (tint fill,
    accent bar, key glyph), sized up into one big draggable target. A click
    that doesn't move the cursor expands back to the full dock; dragging
    moves the puck around instead.
    """
    @staticmethod
    def size_now():
        return (_s(56), _s(56))

    def __init__(self, toolbar: "Toolbar"):
        # Its own top-level window, like the dock — see Toolbar.__init__.
        super().__init__(None,
                         Qt.WindowType.FramelessWindowHint |
                         Qt.WindowType.WindowStaysOnTopHint |
                         Qt.WindowType.Tool)
        self.toolbar   = toolbar
        self._tid      = "pen"
        self._key      = "P"
        self._drag_pos = None
        self._dragged  = False
        self.setFixedSize(*self.size_now())
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, False)

    def set_tool(self, tid: str):
        meta = TOOL_META.get(tid)
        self._tid = tid
        self._key = meta[2] if meta else ""
        self.update()

    def show_at(self, pos: QPoint):
        self.move(pos)
        self.show()
        self.raise_()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        p.fillRect(0, 0, w, h, QColor(TINT))
        p.fillRect(0, h - 4, w, 4, QColor(ACCENT))
        p.save()
        ic = _s(22)
        p.translate((w - ic) / 2, (h - ic) / 2 - 1)
        _paint_icon(p, self._tid, ic, QColor(INK))
        p.restore()
        if self._key:
            f = QFont(FONT, _fs(7))
            f.setBold(True)
            p.setFont(f)
            p.setPen(QPen(QColor(MUTED)))
            p.drawText(QRectF(0, h - _s(17), w - _s(5), _s(12)),
                       Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                       self._key)
        p.end()

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = e.pos()
            self._dragged  = False

    def mouseMoveEvent(self, e):
        if self._drag_pos and e.buttons() & Qt.MouseButton.LeftButton:
            if (e.pos() - self._drag_pos).manhattanLength() > 3:
                self._dragged = True
                self.move(self.mapToParent(e.pos() - self._drag_pos))

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            if self._dragged:
                self.toolbar._anchor = _center_of(self)
                self.toolbar._save_dock_state()
            else:
                self.toolbar._expand()
            self._drag_pos = None
            self._dragged  = False


# ── The dock ──────────────────────────────────────────────────────────────────
class Toolbar(QWidget):
    """Horizontal dock. Same constructor and _activate() as the old panel."""

    def __init__(self, canvas, overlay, settings_mgr, hotkey_mgr):
        # A top-level window rather than a child of the overlay, and that is
        # load-bearing: click-through mode is an OS-level flag on the overlay's
        # window, and it applies to every child. If the dock were still a child
        # it would go dead the moment you switched to click-through, leaving no
        # way back. Its own window keeps it clickable in both modes.
        super().__init__(None,
                         Qt.WindowType.FramelessWindowHint |
                         Qt.WindowType.WindowStaysOnTopHint |
                         Qt.WindowType.Tool)
        self.canvas        = canvas
        self.overlay       = overlay
        self._settings_mgr = settings_mgr
        self._hotkey_mgr   = hotkey_mgr

        self._drag_pos   = None
        self._tool_btns  = {}
        self._swatches   = []
        self._active_tid = "pen"
        self._collapsed  = False
        self._indicator  = None
        # _activate() runs during construction; nothing may reach back into
        # the overlay until this dock is fully built.
        self._built      = False
        # The one stable "where the user put it" reference point — the
        # center the dock (or, collapsed, the puck) is kept centered on.
        # None means "never customized, use the default resting spot".
        # Set *only* by an explicit drag of the grip or the puck, never
        # recomputed as a side effect of a tool switch resizing the dock.
        self._anchor: QPoint | None = None
        # Where the dock was before a recording moved it out of frame.
        self._parked_from: QPoint | None = None

        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, False)
        self._build()
        self._activate("pen")
        self._restore_position()
        self._built = True

    # ── build ─────────────────────────────────────────────────────────────────
    def _build(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(RULE, RULE, RULE, RULE)
        outer.setSpacing(0)

        # ── row 1: grip · tools · actions ─────────────────────────────────────
        row1 = QHBoxLayout()
        row1.setContentsMargins(0, 0, 0, 0)
        row1.setSpacing(0)

        self._grip = QWidget()
        self._grip.setFixedSize(_s(34), ROW1)
        self._grip.setCursor(Qt.CursorShape.SizeAllCursor)
        self._grip.setToolTip("Drag to move the dock  ·  double-click to collapse")
        self._grip.paintEvent = self._paint_grip
        row1.addWidget(self._grip)
        row1.addWidget(_vrule())

        for gi, group in enumerate(GROUPS):
            for tid in group:
                _, label, key, _props, _tip = TOOL_META[tid]
                btn = ToolButton(tid, key, f"{label} — {key}")
                btn.clicked.connect(lambda _c, t=tid: self._activate(t))
                self._tool_btns[tid] = btn
                row1.addWidget(btn)
            row1.addWidget(_vrule())

        # history cell — tinted, set apart from the tools
        hist = QWidget()
        self._hist = hist
        hist.setStyleSheet(f"background:{SURFACE};")
        hl = QHBoxLayout(hist)
        hl.setContentsMargins(0, 0, 0, 0)
        hl.setSpacing(0)
        for tid, tip, fn in (
            ("undo",  "Undo — Ctrl+Z", self.canvas.undo),
            ("redo",  "Redo — Ctrl+Y", self.canvas.redo),
            ("clear", "Clear all — C", self.canvas.clear),
        ):
            b = ActionButton(tid, tip)
            b.clicked.connect(fn)
            hl.addWidget(b)
        row1.addWidget(hist)
        row1.addWidget(_vrule())

        # Over here rather than at the far left: putting it before the tools
        # shifted every tool 80 px right and broke the muscle memory for where
        # each one lives.
        self._mode_btn = ModeButton()
        self._mode_btn.clicked.connect(self._toggle_mode)
        row1.addWidget(self._mode_btn)
        row1.addWidget(_vrule())

        cap = CaptureButton()
        cap.clicked.connect(self._take_screenshot)
        row1.addWidget(cap)

        self._rec_btn = RecordButton()
        self._rec_btn.clicked.connect(self._toggle_recording)
        row1.addWidget(self._rec_btn)

        st = ActionButton("settings", "Settings")
        st.clicked.connect(self._open_settings)
        row1.addWidget(st)

        pz = ActionButton("pause", "Pause — hide the overlay, resume from the tray")
        pz.clicked.connect(self.overlay.toggle)
        row1.addWidget(pz)

        # Collapsing used to be double-click-the-dotted-grip and nothing else:
        # the least discoverable control on the dock, and the scaling made it
        # smaller still. One click, full-height target. The double-click on the
        # grip still works for anyone who had learned it.
        mn = ActionButton("collapse", "Minimise to the puck — or double-click the grip")
        mn.clicked.connect(self._collapse)
        row1.addWidget(mn)

        row1.addWidget(_vrule())
        ex = ActionButton("close", "Exit", danger=True)
        ex.clicked.connect(QApplication.quit)
        row1.addWidget(ex)

        w1 = QWidget()
        w1.setLayout(row1)
        w1.setFixedHeight(ROW1)
        outer.addWidget(w1)

        # ── rule between the rows ─────────────────────────────────────────────
        hr = QFrame()
        hr.setFixedHeight(RULE)
        hr.setStyleSheet(f"background:{INK};border:none;")
        outer.addWidget(hr)

        # ── row 2: contextual properties ──────────────────────────────────────
        self._props = QWidget()
        self._props.setFixedHeight(ROW2)
        self._props.setStyleSheet(f"background:{SURFACE};")
        self._props_lo = QHBoxLayout(self._props)
        self._props_lo.setContentsMargins(0, 0, 0, 0)
        self._props_lo.setSpacing(0)
        outer.addWidget(self._props)

        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)

    def _paint_grip(self, _):
        p = QPainter(self._grip)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        gi = _s(20)
        p.translate((self._grip.width() - _s(14)) / 2,
                    (self._grip.height() - gi) / 2)
        _paint_icon(p, "grip", gi, QColor("#9b9797"))
        p.end()

    # ── contextual property row ───────────────────────────────────────────────
    def _clear_props(self):
        while self._props_lo.count():
            item = self._props_lo.takeAt(0)
            w = item.widget()
            if w:
                w.setParent(None)
                w.deleteLater()

    def _cell(self, *widgets) -> QWidget:
        cell = QWidget()
        cell.setStyleSheet("background:transparent;")
        lo = QHBoxLayout(cell)
        lo.setContentsMargins(16, 0, 16, 0)
        lo.setSpacing(10)
        for w in widgets:
            lo.addWidget(w)
        return cell

    def _build_props(self, tid: str):
        self._clear_props()
        _, label, key, props, tip = TOOL_META[tid]

        # name + key, flush left
        name_box = QWidget()
        name_box.setFixedWidth(_s(168))
        name_box.setStyleSheet("background:transparent;")
        nb = QVBoxLayout(name_box)
        nb.setContentsMargins(16, 0, 16, 0)
        nb.setSpacing(0)
        nl = QLabel(label)
        nf = QFont(FONT, _fs(10))
        nf.setBold(True)
        nl.setFont(nf)
        nl.setStyleSheet(f"color:{INK};background:transparent;")
        nb.addStretch()
        nb.addWidget(nl)
        nb.addWidget(_label(f"KEY {key}"))
        nb.addStretch()
        self._props_lo.addWidget(name_box)
        self._props_lo.addWidget(_vrule())

        if "color" in props:
            sw_box = QWidget()
            sw_box.setStyleSheet("background:transparent;")
            sl = QHBoxLayout(sw_box)
            sl.setContentsMargins(0, 0, 0, 0)
            sl.setSpacing(4)
            self._swatches = []
            for hex_c in DOCK_SWATCHES:
                s = Swatch(hex_c)
                s.active = (hex_c.lower() == str(self.canvas.pen_color).lower())
                s.clicked.connect(lambda _c, h=hex_c: self._set_color(h))
                self._swatches.append(s)
                sl.addWidget(s)
            custom = QPushButton("+")
            custom.setFixedSize(_s(22), _s(22))
            custom.setCursor(Qt.CursorShape.PointingHandCursor)
            custom.setToolTip("Custom colour…")
            custom.setStyleSheet(
                "QPushButton{border:1px dashed rgba(32,30,29,0.5);background:transparent;"
                f"color:{MUTED};font-size:12px;}}"
                f"QPushButton:hover{{border:1px dashed {INK};color:{INK};}}"
            )
            custom.clicked.connect(self._pick_custom)
            sl.addWidget(custom)
            self._props_lo.addWidget(self._cell(_label("COLOR"), sw_box))
            self._props_lo.addWidget(_vrule())

        if "stroke" in props:
            cap = {"eraser": "WIDTH", "highlight": "HEIGHT"}.get(tid, "STROKE")
            val = _label(f"{self.canvas.pen_width} px", size=8, color=INK)
            val.setFixedWidth(_s(38))
            sld = DockSlider(1, 30, int(self.canvas.pen_width))
            sld.valueChanged.connect(
                lambda v, l=val: (setattr(self.canvas, "pen_width", v),
                                  l.setText(f"{v} px")))
            self._props_lo.addWidget(self._cell(_label(cap), sld, val))
            self._props_lo.addWidget(_vrule())

        if "size" in props:
            val = _label(f"{self.canvas.font_size} pt", size=8, color=INK)
            val.setFixedWidth(_s(38))
            sld = DockSlider(8, 72, int(self.canvas.font_size))
            sld.valueChanged.connect(
                lambda v, l=val: (setattr(self.canvas, "font_size", v),
                                  l.setText(f"{v} pt")))
            self._props_lo.addWidget(self._cell(_label("SIZE"), sld, val))
            self._props_lo.addWidget(_vrule())

        if "opacity" in props:
            pct = int(round(self.canvas.pen_alpha * 100 / 255))
            val = _label(f"{pct}%", size=8, color=INK)
            val.setFixedWidth(_s(38))
            sld = DockSlider(10, 100, pct)
            sld.valueChanged.connect(
                lambda v, l=val: (setattr(self.canvas, "pen_alpha", int(v * 255 / 100)),
                                  l.setText(f"{v}%")))
            self._props_lo.addWidget(self._cell(_label("OPACITY"), sld, val))
            self._props_lo.addWidget(_vrule())

        if "blur" in props:
            cur = int(getattr(self.canvas, "blur_radius", 18))
            val = _label(f"{cur} px", size=8, color=INK)
            val.setFixedWidth(_s(38))
            sld = DockSlider(4, 40, cur)
            sld.valueChanged.connect(
                lambda v, l=val: (setattr(self.canvas, "blur_radius", v),
                                  l.setText(f"{v} px")))
            self._props_lo.addWidget(self._cell(_label("RADIUS"), sld, val))
            self._props_lo.addWidget(_vrule())

        if "pixel" in props:
            cur = int(getattr(self.canvas, "pixel_size", 12))
            val = _label(f"{cur} px", size=8, color=INK)
            val.setFixedWidth(_s(38))
            sld = DockSlider(4, 40, cur)
            sld.valueChanged.connect(
                lambda v, l=val: (setattr(self.canvas, "pixel_size", v),
                                  l.setText(f"{v} px")))
            self._props_lo.addWidget(self._cell(_label("CELL"), sld, val))
            self._props_lo.addWidget(_vrule())

        tip_lbl = _label(tip, size=8, bold=False)
        self._props_lo.addWidget(self._cell(tip_lbl))
        self._props_lo.addStretch()

        # Different tools show different property widgets, so the dock's
        # width changes on every switch. Once the user has put it somewhere
        # on purpose, re-center on the *stable* anchor point (set only by an
        # explicit drag — never recomputed from the dock's own current
        # geometry, which would drift a little further every single tool
        # switch and, worse, made collapsing land the puck in a different
        # spot depending on which tool happened to be active).
        self.adjustSize()
        if self._anchor is not None:
            self.move(self._anchor.x() - self.width()  // 2,
                      self._anchor.y() - self.height() // 2)
            self._clamp_to_screen()
        else:
            self._position()

    def _set_color(self, hex_c: str):
        self.canvas.pen_color = hex_c
        for s in self._swatches:
            s.active = (s.hex_c.lower() == hex_c.lower())
            s.update()

    def _pick_custom(self):
        color = QColorDialog.getColor(QColor(self.canvas.pen_color), self, "Custom Color")
        if color.isValid():
            self.canvas.pen_color = color.name()
            for s in self._swatches:
                s.active = False
                s.update()

    # ── theme ──────────────────────────────────────────────────────────────────
    def refresh_theme(self):
        """Re-apply the current palette to everything a stylesheet baked at
        build time (sliders, the tinted cells) — the icon buttons and the
        dock's own chrome read the tokens live in their paintEvent, so a
        plain repaint is enough for those."""
        self._hist.setStyleSheet(f"background:{SURFACE};")
        self._props.setStyleSheet(f"background:{SURFACE};")
        self._build_props(self._active_tid)
        self.update()

    # ── public API (unchanged) ────────────────────────────────────────────────
    def _activate(self, tid: str):
        if tid not in TOOL_META:
            return
        # Reaching for a tool means you want to draw with it — being dropped
        # into click-through and having the first stroke land in the app
        # underneath would be worse than useless.
        if self._built:
            self.overlay.set_passthrough(False)
        self._active_tid = tid
        self.canvas.tool = tid

        if tid != "laser":
            self.canvas._laser_pos = None
            self.canvas.update()

        import annotate as A
        if tid == "laser":
            self.canvas.setCursor(Qt.CursorShape.BlankCursor)
        elif tid == "select":
            self.canvas.setCursor(Qt.CursorShape.ArrowCursor)
        elif tid == "ocr":
            self.canvas.setCursor(Qt.CursorShape.CrossCursor)
            # Start warming up the (slow, ~5-10s) OCR model now, on the
            # assumption the user is about to draw a selection — instead of
            # only starting the load once they've already drawn it and are
            # waiting on the result.
            A._preload_ocr_reader()
        else:
            self.canvas.setCursor(A._cross_cursor())

        for k, b in self._tool_btns.items():
            b.setChecked(k == tid)
        self._build_props(tid)

        # Shortcut keys still work while collapsed — keep the indicator in sync.
        if self._collapsed and self._indicator is not None:
            self._indicator.set_tool(tid)

    # ── actions ───────────────────────────────────────────────────────────────
    def clear_of(self, rect: QRect | None = None) -> bool:
        """Move the dock so it sits outside `rect` (overlay-local coordinates).

        Used while recording on platforms that cannot keep a visible window
        out of a screen capture: if the recorded area leaves room elsewhere on
        the desktop, the dock goes there and stays usable. Returns False when
        the recording covers everything and there is nowhere to put it.
        """
        target = self._indicator if self._collapsed else self
        if target is None or rect is None:
            return False
        bounds = QRect()
        for scr in QApplication.screens():
            bounds = bounds.united(scr.geometry())
        w, h = target.width(), target.height()
        x = max(bounds.left(), min(target.x(), bounds.right() - w))
        y = max(bounds.top(),  min(target.y(), bounds.bottom() - h))
        for pos in (QPoint(x, rect.bottom() + 8),        # below the recording
                    QPoint(x, rect.top() - h - 8),       # above it
                    QPoint(rect.right() + 8, y),         # beside it
                    QPoint(rect.left() - w - 8, y)):
            landed = QRect(pos, target.size())
            if bounds.contains(landed) and not landed.intersects(rect):
                self._parked_from = target.pos()
                target.move(pos)
                target.raise_()
                return True
        return False

    def restore_from_parking(self):
        """Put the dock back where the user had it. Deliberately does not go
        through the drag path, so the anchor the user chose is never rewritten
        by a recording."""
        if self._parked_from is None:
            return
        target = self._indicator if self._collapsed else self
        if target is not None:
            target.move(self._parked_from)
        self._parked_from = None

    def set_mode(self, passthrough: bool):
        self._mode_btn.set_passthrough(passthrough)

    def set_mode_shortcut(self, text: str):
        self._mode_btn.set_shortcut_label(text)

    def _toggle_mode(self):
        self.overlay.toggle_passthrough()

    def chrome_windows(self) -> list:
        """The dock's own top-level windows. The recorder needs these to hide
        them from the capture on Windows — they are no longer children of the
        overlay, so excluding the overlay no longer covers them."""
        return [w for w in (self, self._indicator) if w is not None]

    def set_chrome_visible(self, visible: bool):
        """Hide or restore whatever the dock currently is — the full bar, or
        the puck when collapsed. Used while recording on capture paths that
        cannot leave our own windows out of the frame."""
        target = self._indicator if self._collapsed else self
        if target is None:
            return
        target.setVisible(visible)
        if visible:
            target.raise_()

    def set_recording(self, on: bool):
        self._rec_btn.set_recording(on)

    def set_record_elapsed(self, seconds: float):
        from video_recorder import format_elapsed
        self._rec_btn.set_elapsed(format_elapsed(seconds))

    def _toggle_recording(self):
        # The controller is built after this dock, so reach for it at click
        # time rather than holding a reference from __init__.
        self.overlay.recording.toggle()

    def _take_screenshot(self):
        import annotate as A
        pixmap = self.canvas.capture_annotated()
        A.ScreenshotBar(pixmap, self.overlay)

    def _open_settings(self):
        import annotate as A
        dlg = A.SettingsDialog(self._settings_mgr, self._hotkey_mgr, self.overlay)
        dlg.exec()

    # ── placement ─────────────────────────────────────────────────────────────
    def _position(self):
        self.adjustSize()
        geo = QApplication.primaryScreen().availableGeometry()
        x = max(12, (geo.width() - self.width()) // 2)
        y = max(12, geo.height() - self.height() - 28)
        self.move(x, y)

    def _restore_position(self):
        """Put the dock back wherever it was left — collapsed or not —
        instead of always resetting to the default resting spot. Called
        once, at startup. The saved (dock_x, dock_y) is the anchor
        *center*, not a top-left corner — same thing _save_dock_state()
        writes and everything else in this class reads."""
        x = self._settings_mgr.get("dock_x")
        y = self._settings_mgr.get("dock_y")
        if x is None or y is None:
            self._position()
            return

        self._anchor = QPoint(x, y)
        if self._settings_mgr.get("dock_collapsed"):
            # Give the hidden full dock a sane starting size/position first
            # (its own _build_props/adjustSize calls need *something* to
            # work from), then show only the puck, centered on the anchor.
            self._position()
            if self._indicator is None:
                self._indicator = CollapsedIndicator(self)
            self._indicator.set_tool(self._active_tid)
            w, h = CollapsedIndicator.size_now()
            geo = self._screen_geometry()
            px = max(geo.left(), min(self._anchor.x() - w // 2, geo.right()  - w))
            py = max(geo.top(),  min(self._anchor.y() - h // 2, geo.bottom() - h))
            self._indicator.show_at(QPoint(px, py))
            self._collapsed = True
            self.hide()
        else:
            self.move(self._anchor.x() - self.width()  // 2,
                      self._anchor.y() - self.height() // 2)
            self._clamp_to_screen()

    def _save_dock_state(self):
        """Persist the anchor — the one stable point the dock (or, if
        collapsed, the puck) is centered on — so it comes back in the same
        place next launch."""
        if self._anchor is None:
            return
        self._settings_mgr.set("dock_collapsed", self._collapsed)
        self._settings_mgr.set("dock_x", self._anchor.x())
        self._settings_mgr.set("dock_y", self._anchor.y())
        self._settings_mgr.save()

    # ── chrome ────────────────────────────────────────────────────────────────
    def paintEvent(self, _):
        p = QPainter(self)
        w, h = self.width(), self.height()
        p.fillRect(0, 0, w, h, QColor(GROUND))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(QColor(INK), RULE * 2))   # pen straddles the edge → 2px visible
        p.drawRect(0, 0, w, h)
        p.end()

    # ── drag: only from the grip ──────────────────────────────────────────────
    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            local = self._grip.mapFrom(self, e.pos())
            if self._grip.rect().contains(local):
                self._drag_pos = e.pos()
            else:
                self._drag_pos = None

    def mouseMoveEvent(self, e):
        if e.buttons() & Qt.MouseButton.LeftButton and self._drag_pos:
            self.move(self.mapToParent(e.pos() - self._drag_pos))

    def mouseReleaseEvent(self, e):
        if self._drag_pos is not None:
            self._anchor = _center_of(self)
            self._save_dock_state()
        self._drag_pos = None

    def mouseDoubleClickEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            local = self._grip.mapFrom(self, e.pos())
            if self._grip.rect().contains(local):
                self._collapse()

    # ── collapse / expand ─────────────────────────────────────────────────────
    def _screen_geometry(self):
        # Now that the dock is its own window its position *is* global, so the
        # comparisons in _clamp_to_screen() finally mean what they always read
        # as. (They were only correct before because the overlay happens to sit
        # at the virtual desktop's origin.)
        screen = QApplication.screenAt(_center_of(self))
        return (screen or QApplication.primaryScreen()).availableGeometry()

    def _clamp_to_screen(self):
        geo = self._screen_geometry()
        x = max(geo.left(),  min(self.x(), geo.right()  - self.width()))
        y = max(geo.top(),   min(self.y(), geo.bottom() - self.height()))
        self.move(x, y)

    def _collapse(self):
        if self._collapsed:
            return
        self._collapsed = True
        if self._indicator is None:
            self._indicator = CollapsedIndicator(self)
        self._indicator.set_tool(self._active_tid)

        # Centered on the stable anchor, not on the dock's current x/width —
        # the dock's width (and so its "current position") varies by which
        # tool's property row is showing, so deriving from it would land
        # the puck somewhere different depending on the active tool.
        if self._anchor is None:
            self._anchor = _center_of(self)

        geo = self._screen_geometry()
        w, h = CollapsedIndicator.size_now()
        x = max(geo.left(), min(self._anchor.x() - w // 2, geo.right()  - w))
        y = max(geo.top(),  min(self._anchor.y() - h // 2, geo.bottom() - h))
        self._indicator.show_at(QPoint(x, y))

        self.hide()
        self._save_dock_state()

    def _expand(self):
        if not self._collapsed:
            return
        self._collapsed = False
        ind = self._indicator
        if ind is not None:
            self._anchor = _center_of(ind)  # the puck may have been dragged
            self.move(self._anchor.x() - self.width()  // 2,
                      self._anchor.y() - self.height() // 2)
            ind.hide()
        self.show()
        self.raise_()
        self._clamp_to_screen()
        self._save_dock_state()
