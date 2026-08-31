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
from PyQt6.QtCore import Qt, QRectF, QPointF, QSize
from PyQt6.QtGui import (
    QPainter, QPen, QColor, QBrush, QFont, QPainterPath, QPolygonF, QCursor,
)

# ── Tokens ────────────────────────────────────────────────────────────────────
INK        = "#201e1d"
GROUND     = "#f3f2f2"
SURFACE    = "#eae9e9"
TINT       = "#ffe0d9"    # accent-200 — active tool fill
ACCENT     = "#ec3013"
ACCENT_600 = "#dd2b0f"
MUTED      = "#7d7979"
HOVER      = QColor(32, 30, 29, 20)

CELL   = 48       # tool button width
ROW1   = 56       # tool row height
ROW2   = 52       # property row height
RULE   = 2

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
        p.translate((w - 20) / 2, (h - 20) / 2 - 1)
        _paint_icon(p, self.tid, 20, QColor(INK))
        p.restore()

        if self.show_key and self.key:
            f = QFont(FONT, 7)
            f.setBold(True)
            p.setFont(f)
            p.setPen(QPen(QColor(MUTED)))
            p.drawText(QRectF(0, h - 17, w - 5, 12),
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
        p.translate((w - 19) / 2, (h - 19) / 2)
        _paint_icon(p, self.tid, 19, fg)
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
        self.setFixedSize(118, ROW1)
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
        p.translate(14, (h - 19) / 2)
        _paint_icon(p, "camera", 19, QColor(INK))
        p.restore()
        f = QFont(FONT, 9)
        f.setBold(True)
        p.setFont(f)
        p.setPen(QPen(QColor(INK)))
        p.drawText(QRectF(41, 0, w - 41, h),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   "Capture")
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
        self.setFixedSize(22, 22)
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
        self.setFixedWidth(104)
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
    f = QFont(FONT, size)
    f.setBold(bold)
    f.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 0.8)
    l.setFont(f)
    l.setStyleSheet(f"color:{color};background:transparent;")
    return l


# ── The dock ──────────────────────────────────────────────────────────────────
class Toolbar(QWidget):
    """Horizontal dock. Same constructor and _activate() as the old panel."""

    def __init__(self, canvas, overlay, settings_mgr, hotkey_mgr):
        super().__init__(overlay)
        self.canvas        = canvas
        self.overlay       = overlay
        self._settings_mgr = settings_mgr
        self._hotkey_mgr   = hotkey_mgr

        self._drag_pos   = None
        self._tool_btns  = {}
        self._swatches   = []
        self._active_tid = "pen"

        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, False)
        self._build()
        self._activate("pen")
        self._position()

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
        self._grip.setFixedSize(34, ROW1)
        self._grip.setCursor(Qt.CursorShape.SizeAllCursor)
        self._grip.setToolTip("Drag to move the dock")
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

        cap = CaptureButton()
        cap.clicked.connect(self._take_screenshot)
        row1.addWidget(cap)

        st = ActionButton("settings", "Settings")
        st.clicked.connect(self._open_settings)
        row1.addWidget(st)

        pz = ActionButton("pause", "Pause — hide the overlay, resume from the tray")
        pz.clicked.connect(self.overlay.toggle)
        row1.addWidget(pz)

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
        p.translate((self._grip.width() - 14) / 2, (self._grip.height() - 20) / 2)
        _paint_icon(p, "grip", 20, QColor("#9b9797"))
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
        name_box.setFixedWidth(168)
        name_box.setStyleSheet("background:transparent;")
        nb = QVBoxLayout(name_box)
        nb.setContentsMargins(16, 0, 16, 0)
        nb.setSpacing(0)
        nl = QLabel(label)
        nf = QFont(FONT, 10)
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
            custom.setFixedSize(22, 22)
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
            val.setFixedWidth(38)
            sld = DockSlider(1, 30, int(self.canvas.pen_width))
            sld.valueChanged.connect(
                lambda v, l=val: (setattr(self.canvas, "pen_width", v),
                                  l.setText(f"{v} px")))
            self._props_lo.addWidget(self._cell(_label(cap), sld, val))
            self._props_lo.addWidget(_vrule())

        if "size" in props:
            val = _label(f"{self.canvas.font_size} pt", size=8, color=INK)
            val.setFixedWidth(38)
            sld = DockSlider(8, 72, int(self.canvas.font_size))
            sld.valueChanged.connect(
                lambda v, l=val: (setattr(self.canvas, "font_size", v),
                                  l.setText(f"{v} pt")))
            self._props_lo.addWidget(self._cell(_label("SIZE"), sld, val))
            self._props_lo.addWidget(_vrule())

        if "opacity" in props:
            pct = int(round(self.canvas.pen_alpha * 100 / 255))
            val = _label(f"{pct}%", size=8, color=INK)
            val.setFixedWidth(38)
            sld = DockSlider(10, 100, pct)
            sld.valueChanged.connect(
                lambda v, l=val: (setattr(self.canvas, "pen_alpha", int(v * 255 / 100)),
                                  l.setText(f"{v}%")))
            self._props_lo.addWidget(self._cell(_label("OPACITY"), sld, val))
            self._props_lo.addWidget(_vrule())

        if "blur" in props:
            cur = int(getattr(self.canvas, "blur_radius", 18))
            val = _label(f"{cur} px", size=8, color=INK)
            val.setFixedWidth(38)
            sld = DockSlider(4, 40, cur)
            sld.valueChanged.connect(
                lambda v, l=val: (setattr(self.canvas, "blur_radius", v),
                                  l.setText(f"{v} px")))
            self._props_lo.addWidget(self._cell(_label("RADIUS"), sld, val))
            self._props_lo.addWidget(_vrule())

        if "pixel" in props:
            cur = int(getattr(self.canvas, "pixel_size", 12))
            val = _label(f"{cur} px", size=8, color=INK)
            val.setFixedWidth(38)
            sld = DockSlider(4, 40, cur)
            sld.valueChanged.connect(
                lambda v, l=val: (setattr(self.canvas, "pixel_size", v),
                                  l.setText(f"{v} px")))
            self._props_lo.addWidget(self._cell(_label("CELL"), sld, val))
            self._props_lo.addWidget(_vrule())

        tip_lbl = _label(tip, size=8, bold=False)
        self._props_lo.addWidget(self._cell(tip_lbl))
        self._props_lo.addStretch()

        self.adjustSize()
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

    # ── public API (unchanged) ────────────────────────────────────────────────
    def _activate(self, tid: str):
        if tid not in TOOL_META:
            return
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
        else:
            self.canvas.setCursor(A._cross_cursor())

        for k, b in self._tool_btns.items():
            b.setChecked(k == tid)
        self._build_props(tid)

    # ── actions ───────────────────────────────────────────────────────────────
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
        self._drag_pos = None
