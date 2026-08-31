#!/usr/bin/env python3
"""
Generate Microsoft Store screenshots for Screen Annotator Pro.
Renders a realistic IDE background + actual annotation shapes + toolbar.
Output: screenshots/  (1920×1080 PNG, one per scenario)

Run: python3 create_screenshots.py
"""
import sys, math
from pathlib import Path
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import Qt, QPointF, QRectF, QRect
from PyQt6.QtGui import (
    QPainter, QPen, QColor, QBrush, QPixmap, QFont,
    QPainterPath, QLinearGradient, QFontMetrics, QPolygonF,
)

OUT = Path(__file__).parent / "screenshots"
W, H = 1920, 1080


# ── Palette (matches app colours) ─────────────────────────────────────────────
RED    = QColor("#FF3B3B")
BLUE   = QColor("#0A84FF")
GREEN  = QColor("#32D74B")
YELLOW = QColor("#FFD60A")
WHITE  = QColor("#FFFFFF")
DARK   = QColor(16, 16, 18)
PANEL  = QColor(28, 28, 30)
BORDER = QColor(58, 58, 60)

TOOLBAR_W = 220
TOOLBAR_BG = QColor(16, 16, 18, 247)


# ── Helpers ────────────────────────────────────────────────────────────────────

def new_canvas() -> QPixmap:
    pix = QPixmap(W, H)
    pix.fill(QColor(0, 0, 0))
    return pix


def draw_ide_background(p: QPainter):
    """Realistic dark IDE / code editor background."""
    # Editor background
    p.fillRect(0, 0, W, H, QColor(30, 30, 30))

    # Top menu bar
    p.fillRect(0, 0, W, 30, QColor(40, 40, 40))
    for i, label in enumerate(["File", "Edit", "View", "Run", "Terminal", "Help"]):
        x = 70 + i * 60
        p.setPen(QPen(QColor(200, 200, 200)))
        p.setFont(QFont("Segoe UI", 9))
        p.drawText(x, 20, label)
    # Window title
    p.setFont(QFont("Segoe UI", 9))
    p.setPen(QPen(QColor(160, 160, 160)))
    p.drawText(QRect(0, 0, W, 30), Qt.AlignmentFlag.AlignCenter,
               "annotate.py — Screen Annotator Pro")

    # Tab bar
    tab_y = 30
    p.fillRect(0, tab_y, W, 36, QColor(37, 37, 38))
    for i, (label, active) in enumerate([
        ("annotate.py", True), ("create_icons.py", False), ("README.md", False)
    ]):
        x = i * 160
        bg = QColor(30, 30, 30) if active else QColor(37, 37, 38)
        p.fillRect(x, tab_y, 158, 36, bg)
        p.setPen(QPen(QColor(220, 220, 220) if active else QColor(120, 120, 120)))
        p.setFont(QFont("Segoe UI", 9))
        p.drawText(QRect(x + 12, tab_y, 140, 36), Qt.AlignmentFlag.AlignVCenter, label)
        if active:
            p.fillRect(x, tab_y + 33, 158, 3, BLUE)

    # Activity bar (left strip)
    p.fillRect(0, 66, 48, H - 66, QColor(50, 50, 50))
    for i, icon in enumerate(["⎇", "⊡", "⚙", "◫"]):
        p.setFont(QFont("Segoe UI", 14))
        p.setPen(QPen(QColor(150, 150, 150)))
        p.drawText(QRect(0, 66 + i * 52, 48, 52), Qt.AlignmentFlag.AlignCenter, icon)

    # File explorer panel
    exp_w = 240
    p.fillRect(48, 66, exp_w, H - 66, QColor(37, 37, 38))
    p.setPen(QPen(QColor(80, 80, 80)))
    p.drawLine(48 + exp_w, 66, 48 + exp_w, H)
    p.setFont(QFont("Segoe UI", 8))
    p.setPen(QPen(QColor(180, 180, 180)))
    p.drawText(QRect(58, 66, exp_w, 28), Qt.AlignmentFlag.AlignVCenter, "  EXPLORER")

    files = [
        (0, "▾ screen-annotator-pro"),
        (1, "▾ installer"),
        (2, "annotate.wxs"),
        (2, "AppxManifest.xml"),
        (2, "License.rtf"),
        (1, "annotate.py"),
        (1, "annotate.spec"),
        (1, "create_icons.py"),
        (1, "requirements.txt"),
        (1, "README.md"),
        (1, "infosMS.md"),
    ]
    y = 100
    for indent, name in files:
        is_py  = name.endswith(".py")
        is_sel = name == "annotate.py"
        if is_sel:
            p.fillRect(48, y - 2, exp_w, 22, QColor(50, 90, 130, 60))
        col = BLUE if is_sel else (QColor(220, 180, 80) if is_py else QColor(170, 170, 170))
        p.setPen(QPen(col))
        p.setFont(QFont("Segoe UI", 9))
        p.drawText(QRect(58 + indent * 14, y, exp_w - indent * 14, 20),
                   Qt.AlignmentFlag.AlignVCenter, name)
        y += 22

    # Code editor area
    code_x = 48 + exp_w + 1
    p.fillRect(code_x, 66, W - code_x, H - 66, QColor(30, 30, 30))

    # Line number gutter
    gutter = 52
    p.fillRect(code_x, 66, gutter, H - 66, QColor(30, 30, 30))

    lines = [
        ("1",  ""),
        ("2",  "#!/usr/bin/env python3"),
        ("3",  '"""'),
        ("4",  "Screen Annotator Pro  (PyQt6)"),
        ("5",  "Draw on your screen like a whiteboard."),
        ("6",  '"""'),
        ("7",  ""),
        ("8",  "import sys, os, json, math, platform"),
        ("9",  "from pathlib import Path"),
        ("10", "from PyQt6.QtWidgets import ("),
        ("11", "    QApplication, QWidget, QVBoxLayout,"),
        ("12", "    QPushButton, QSlider, QLabel,"),
        ("13", ")"),
        ("14", "from PyQt6.QtCore import Qt, QPointF, QRectF"),
        ("15", "from PyQt6.QtGui import ("),
        ("16", "    QPainter, QPen, QColor, QFont, QBrush,"),
        ("17", "    QPainterPath, QPixmap, QCursor,"),
        ("18", ")"),
        ("19", ""),
        ("20", "VERSION = \"1.1.0\""),
        ("21", ""),
        ("22", "class Canvas(QWidget):"),
        ("23", '    """Transparent drawing surface."""'),
        ("24", "    def __init__(self, parent=None):"),
        ("25", "        super().__init__(parent)"),
        ("26", "        self.tool      = \"pen\""),
        ("27", "        self.pen_color = \"#FF3B3B\""),
        ("28", "        self.pen_width = 4"),
        ("29", "        self.pen_alpha = 255"),
        ("30", "        self._shapes   = []"),
        ("31", "        self._redo_stack = []"),
        ("32", ""),
        ("33", "    def _commit(self, shape):"),
        ("34", "        self._shapes.append(shape)"),
        ("35", "        self._redo_stack.clear()"),
        ("36", "        self.update()"),
        ("37", ""),
        ("38", "    def undo(self):"),
        ("39", "        if self._shapes:"),
        ("40", "            self._redo_stack.append(self._shapes.pop())"),
        ("41", "            self.update()"),
    ]
    y = 80
    for num, code in lines:
        # Line number
        p.setFont(QFont("Consolas", 10))
        p.setPen(QPen(QColor(75, 75, 75)))
        p.drawText(QRect(code_x, y, gutter - 6, 20),
                   Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, num)
        # Code with basic syntax colouring
        if code.startswith("#") or code.startswith('"""') or code.startswith("Draw") or code.startswith("Screen"):
            col = QColor(106, 153, 85)
        elif "class " in code or "def " in code or code.strip().startswith("import") or code.strip().startswith("from") or "return" in code:
            col = QColor(86, 156, 214)
        elif '"' in code or "'" in code:
            col = QColor(206, 145, 120)
        elif "=" in code and "==" not in code:
            col = QColor(156, 220, 254)
        else:
            col = QColor(212, 212, 212)
        p.setPen(QPen(col))
        p.setFont(QFont("Consolas", 10))
        p.drawText(code_x + gutter + 8, y + 14, code)
        y += 22

    # Status bar
    p.fillRect(0, H - 28, W, 28, BLUE)
    p.setFont(QFont("Segoe UI", 9))
    p.setPen(QPen(WHITE))
    p.drawText(QRect(8, H - 28, 400, 28), Qt.AlignmentFlag.AlignVCenter,
               "  main ●  Python 3.11  UTF-8  Screen Annotator Pro")


def draw_toolbar(p: QPainter, x: int = 40, y: int = 40):
    """Draw a representation of the app toolbar."""
    tw, th = TOOLBAR_W, 620
    # Background rounded rect
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    path = QPainterPath()
    path.addRoundedRect(QRectF(x, y, tw, th), 14, 14)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QBrush(TOOLBAR_BG))
    p.drawPath(path)
    p.setPen(QPen(BORDER, 1))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawPath(path)

    def sep(sy):
        p.setPen(QPen(QColor(255, 255, 255, 15), 1))
        p.drawLine(x + 10, sy, x + tw - 10, sy)

    def lbl(lx, ly, text, col=QColor(72, 72, 74), size=9):
        p.setFont(QFont("Segoe UI", size))
        p.setPen(QPen(col))
        p.drawText(lx, ly, text)

    def btn(bx, by, bw, bh, text, col=QColor(150, 150, 155), active=False):
        if active:
            bp = QPainterPath()
            bp.addRoundedRect(QRectF(bx, by, bw, bh), 8, 8)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QBrush(QColor(10, 132, 255, 50)))
            p.drawPath(bp)
            col = BLUE
        p.setFont(QFont("Segoe UI", 10))
        p.setPen(QPen(col))
        p.drawText(QRect(int(bx), int(by), int(bw), int(bh)),
                   Qt.AlignmentFlag.AlignVCenter, f"  {text}")

    cy = y + 14
    # Drag handle
    lbl(x + 14, cy + 12, "· · ·  Screen Annotator Pro  · · ·", QColor(58, 58, 60), 8)
    cy += 22
    sep(cy); cy += 8

    # Tool sections
    for section, tools in [
        ("✏️ Draw", [("↖", "Select", False), ("〜", "Pen", True), ("—", "Line", False),
                    ("→", "Arrow", False), ("▭", "Rectangle", False), ("○", "Circle", False),
                    ("📏", "Ruler", False), ("◻", "Eraser", False), ("⊙", "Laser", False)]),
        ("🏷 Annotate", [("T", "Text", False), ("①", "Callout", False), ("1▸2", "Steps", False), ("HL", "Highlight", False)]),
        ("🔒 Redact",   [("⊘", "Blur", False), ("PX", "Pixelate", False), ("▪", "Black Box", False)]),
    ]:
        p.setFont(QFont("Segoe UI", 9, QFont.Weight.DemiBold))
        p.setPen(QPen(QColor(174, 174, 178)))
        p.drawText(x + 10, cy + 14, section + "  ‹")
        cy += 22
        for icon, name, active in tools:
            btn(x + 6, cy, tw - 12, 26, f"{icon}   {name}", active=active)
            cy += 27
        cy += 4

    sep(cy); cy += 8

    # Color swatches
    lbl(x + 10, cy + 10, "Color", QColor(72, 72, 74), 8)
    cy += 16
    swatches = ["#FF3B3B","#FF9F0A","#FFD60A","#34C759",
                "#0A84FF","#BF5AF2","#FFFFFF","#1C1C1E",
                "#FF6B00","#30D158","#64D2FF","#FFD60A"]
    for i, c in enumerate(swatches):
        sx = x + 12 + (i % 4) * 26
        sy2 = cy + (i // 4) * 26
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(QColor(c)))
        pp2 = QPainterPath(); pp2.addRoundedRect(QRectF(sx, sy2, 20, 20), 5, 5)
        p.drawPath(pp2)
        if c == "#FF3B3B":
            p.setPen(QPen(WHITE, 2)); p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawPath(pp2)
    cy += 58

    sep(cy); cy += 6

    # Action buttons
    for icon, label, col in [
        ("📷", "Screenshot", "#32D74B"),
        ("⏸",  "Pause",      "#0A84FF"),
        ("⚙",  "Settings",   "#636366"),
        ("↩",  "Undo",       "#aeaeb2"),
        ("↪",  "Redo",       "#aeaeb2"),
        ("🗑", "Clear all",  "#aeaeb2"),
        ("✕",  "Exit",       "#FF453A"),
    ]:
        p.setFont(QFont("Segoe UI", 11))
        p.setPen(QPen(QColor(col)))
        p.drawText(QRect(x + 10, cy, tw - 16, 28), Qt.AlignmentFlag.AlignVCenter,
                   f"  {icon}  {label}")
        cy += 29


def arrow(p: QPainter, x1, y1, x2, y2, color: QColor, width=3):
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setPen(QPen(color, width, Qt.PenStyle.SolidLine,
                  Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
    p.drawLine(QPointF(x1, y1), QPointF(x2, y2))
    ah = width * 6
    angle = math.atan2(y2 - y1, x2 - x1)
    spread = math.pi / 5.5
    p.setPen(Qt.PenStyle.NoPen); p.setBrush(QBrush(color))
    p.drawPolygon(QPolygonF([
        QPointF(x2, y2),
        QPointF(x2 - ah * math.cos(angle - spread), y2 - ah * math.sin(angle - spread)),
        QPointF(x2 - ah * math.cos(angle + spread), y2 - ah * math.sin(angle + spread)),
    ]))


def callout(p: QPainter, cx, cy, n, color: QColor, r=18):
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setPen(Qt.PenStyle.NoPen); p.setBrush(QBrush(color))
    p.drawEllipse(QPointF(cx, cy), r, r)
    p.setPen(QPen(WHITE)); p.setFont(QFont("Arial", r - 4, QFont.Weight.Bold))
    p.drawText(QRect(int(cx - r), int(cy - r), int(r * 2), int(r * 2)),
               Qt.AlignmentFlag.AlignCenter, str(n))


def highlight(p: QPainter, x, y, w, h, color: QColor):
    c = QColor(color); c.setAlpha(90)
    p.setPen(Qt.PenStyle.NoPen); p.setBrush(QBrush(c))
    p.drawRect(QRectF(x, y, w, h))


def rect_shape(p: QPainter, x, y, w, h, color: QColor, lw=2):
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setPen(QPen(color, lw)); p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawRect(QRectF(x, y, w, h))


def text_label(p: QPainter, x, y, text, color: QColor, size=14):
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setFont(QFont("Arial", size, QFont.Weight.Bold))
    p.setPen(QPen(color))
    p.drawText(QPointF(x, y), text)


def blur_box(p: QPainter, x, y, w, h):
    """Simulate a blur region."""
    p.setPen(Qt.PenStyle.NoPen)
    step = 8
    import random; rng = random.Random(42)
    xi = x
    while xi < x + w:
        yi = y
        while yi < y + h:
            g = rng.randint(60, 160)
            p.setBrush(QBrush(QColor(g, g, g + 20, 210)))
            p.drawRect(QRectF(xi, yi, min(step, x + w - xi), min(step, y + h - yi)))
            yi += step
        xi += step
    p.setPen(QPen(QColor(150, 150, 180, 180), 1, Qt.PenStyle.DashLine))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawRect(QRectF(x, y, w, h))


# ── Screenshots ────────────────────────────────────────────────────────────────

def screenshot_1_overview():
    """General overview — toolbar + multiple annotation types on IDE background."""
    pix = new_canvas()
    p = QPainter(pix)
    draw_ide_background(p)
    draw_toolbar(p, 40, 40)

    # Highlight a line of code
    highlight(p, 340, 506, 580, 22, YELLOW)

    # Arrow pointing at VERSION line
    arrow(p, 620, 430, 560, 509, RED, 3)
    text_label(p, 628, 428, "Important!", RED, 13)

    # Callout on a function
    callout(p, 780, 600, 1, BLUE)
    callout(p, 900, 690, 2, BLUE)
    callout(p, 820, 780, 3, BLUE)

    # Rect around import block
    rect_shape(p, 335, 172, 550, 178, GREEN, 2)
    arrow(p, 900, 200, 895, 173, GREEN, 2)
    text_label(p, 905, 198, "Dependencies", GREEN, 12)

    # Free pen scribble underline
    p.setPen(QPen(RED, 3, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
    pts = [(340 + i * 4, 526 + (2 if i % 4 < 2 else -1)) for i in range(60)]
    for i in range(1, len(pts)):
        p.drawLine(QPointF(*pts[i-1]), QPointF(*pts[i]))

    p.end()
    return pix


def screenshot_2_redaction():
    """Redaction tools — blur and black box over sensitive data."""
    pix = new_canvas()
    p = QPainter(pix)
    draw_ide_background(p)
    draw_toolbar(p, 40, 40)

    # Blur box over some lines
    blur_box(p, 335, 392, 480, 44)
    blur_box(p, 335, 458, 280, 22)

    # Black box over a variable value
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QBrush(QColor(0, 0, 0, 255)))
    p.drawRect(QRectF(335, 504, 360, 22))

    # Labels pointing at the redactions
    arrow(p, 870, 360, 700, 405, QColor("#FF9F0A"), 3)
    text_label(p, 876, 358, "Gaussian blur", QColor("#FF9F0A"), 13)

    arrow(p, 870, 510, 697, 514, QColor("#BF5AF2"), 3)
    text_label(p, 876, 508, "Redact", QColor("#BF5AF2"), 13)

    p.end()
    return pix


def screenshot_3_callouts():
    """Step-by-step callouts and highlights for a tutorial."""
    pix = new_canvas()
    p = QPainter(pix)
    draw_ide_background(p)
    draw_toolbar(p, 40, 40)

    steps = [
        (580, 194, "Import PyQt6"),
        (660, 458, "Set version"),
        (700, 546, "Define Canvas"),
        (750, 634, "Add _commit()"),
        (780, 722, "Implement undo"),
    ]
    for i, (cx, cy, label) in enumerate(steps):
        callout(p, cx, cy, i + 1, BLUE)
        text_label(p, cx + 26, cy + 5, label, BLUE, 12)

    # Highlight the class definition line
    highlight(p, 335, 546, 420, 22, GREEN)

    # Big rect around the whole Canvas class block
    rect_shape(p, 332, 544, 700, 286, GREEN, 2)
    text_label(p, 1042, 560, "Canvas class", GREEN, 13)

    p.end()
    return pix


def screenshot_4_drawing():
    """Drawing tools in action — pen, lines, arrows, circle, ruler."""
    pix = new_canvas()
    p = QPainter(pix)
    draw_ide_background(p)
    draw_toolbar(p, 40, 40)

    # Freehand pen strokes
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setPen(QPen(RED, 4, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
    import math as m
    pts = [(700 + 120 * m.cos(t * 0.3), 350 + 80 * m.sin(t * 0.5))
           for t in range(80)]
    for i in range(1, len(pts)):
        p.drawLine(QPointF(*pts[i-1]), QPointF(*pts[i]))

    # Line + arrow
    p.setPen(QPen(BLUE, 3))
    p.drawLine(QPointF(850, 300), QPointF(1100, 450))
    arrow(p, 1100, 450, 1250, 550, BLUE, 3)

    # Rectangle
    rect_shape(p, 900, 580, 280, 160, QColor("#BF5AF2"), 3)

    # Circle
    p.setPen(QPen(YELLOW, 3)); p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawEllipse(QPointF(1450, 400), 120, 80)

    # Ruler line with label
    p.setPen(QPen(GREEN, 2))
    p.drawLine(QPointF(1050, 750), QPointF(1450, 750))
    p.drawLine(QPointF(1050, 740), QPointF(1050, 760))
    p.drawLine(QPointF(1450, 740), QPointF(1450, 760))
    p.setFont(QFont("Arial", 11, QFont.Weight.Bold))
    p.setPen(Qt.PenStyle.NoPen); p.setBrush(QBrush(QColor(28, 28, 30, 210)))
    p.drawRoundedRect(QRectF(1215, 738, 72, 24), 5, 5)
    p.setPen(QPen(GREEN))
    p.drawText(QRect(1215, 738, 72, 24), Qt.AlignmentFlag.AlignCenter, "400 px")

    # Highlight
    highlight(p, 700, 650, 300, 26, YELLOW)

    p.end()
    return pix


def screenshot_5_settings():
    """Settings dialog open over the IDE."""
    pix = new_canvas()
    p = QPainter(pix)
    draw_ide_background(p)
    draw_toolbar(p, 40, 40)

    # Dim overlay
    p.fillRect(0, 0, W, H, QColor(0, 0, 0, 80))

    # Settings dialog
    dw, dh = 380, 340
    dx = (W - dw) // 2
    dy = (H - dh) // 2

    dp = QPainterPath()
    dp.addRoundedRect(QRectF(dx, dy, dw, dh), 14, 14)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QBrush(QColor(16, 16, 18, 252)))
    p.drawPath(dp)
    p.setPen(QPen(BORDER, 1)); p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawPath(dp)

    # Title
    p.setFont(QFont("Segoe UI", 15, QFont.Weight.Bold))
    p.setPen(QPen(QColor(229, 229, 231)))
    p.drawText(QRect(dx + 20, dy + 18, dw - 40, 30), Qt.AlignmentFlag.AlignVCenter, "Settings")

    # Separator
    p.setPen(QPen(QColor(255, 255, 255, 15)))
    p.drawLine(dx + 10, dy + 52, dx + dw - 10, dy + 52)

    # Hotkey section
    p.setFont(QFont("Segoe UI", 8))
    p.setPen(QPen(QColor(99, 99, 102)))
    p.drawText(dx + 20, dy + 72, "ACTIVATION SHORTCUT")

    hkp = QPainterPath()
    hkp.addRoundedRect(QRectF(dx + 20, dy + 82, dw - 40, 36), 8, 8)
    p.setPen(QPen(BLUE, 1.5)); p.setBrush(QBrush(QColor(255, 255, 255, 12)))
    p.drawPath(hkp)
    p.setFont(QFont("Segoe UI", 12))
    p.setPen(QPen(QColor(229, 229, 231)))
    p.drawText(QRect(dx + 30, dy + 82, dw - 60, 36), Qt.AlignmentFlag.AlignVCenter,
               "Ctrl + Shift + A")

    p.setFont(QFont("Segoe UI", 8))
    p.setPen(QPen(QColor(72, 72, 74)))
    p.drawText(dx + 20, dy + 130, "Click the box and press a new key combination.")

    # Boot checkbox
    cbx, cby = dx + 20, dy + 152
    cbp = QPainterPath(); cbp.addRoundedRect(QRectF(cbx, cby, 18, 18), 5, 5)
    p.setPen(Qt.PenStyle.NoPen); p.setBrush(QBrush(BLUE)); p.drawPath(cbp)
    p.setFont(QFont("Segoe UI", 11)); p.setPen(QPen(QColor(174, 174, 178)))
    p.drawText(cbx + 26, cby + 14, "Start on boot  (Windows only)")

    # Separator
    p.setPen(QPen(QColor(255, 255, 255, 15)))
    p.drawLine(dx + 10, dy + 186, dx + dw - 10, dy + 186)

    # Developer row
    p.setFont(QFont("Segoe UI", 10))
    p.setPen(QPen(QColor(72, 72, 74)))
    p.drawText(dx + 20, dy + 212, "Developer")
    p.setPen(QPen(BLUE))
    p.drawText(dx + dw - 110, dy + 212, "celikovic.xyz ↗")

    # Version
    p.setFont(QFont("Segoe UI", 9))
    p.setPen(QPen(QColor(58, 58, 60)))
    p.drawText(QRect(dx, dy + 220, dw - 16, 20), Qt.AlignmentFlag.AlignRight, "Version 1.1.0")

    # Buttons
    # Help button
    hp = QPainterPath(); hp.addRoundedRect(QRectF(dx + 20, dy + 284, 80, 34), 8, 8)
    p.setPen(QPen(BORDER)); p.setBrush(Qt.BrushStyle.NoBrush); p.drawPath(hp)
    p.setFont(QFont("Segoe UI", 11)); p.setPen(QPen(QColor(99, 99, 102)))
    p.drawText(QRect(dx + 20, dy + 284, 80, 34), Qt.AlignmentFlag.AlignCenter, "?  Help")

    # Cancel
    cp2 = QPainterPath(); cp2.addRoundedRect(QRectF(dx + dw - 176, dy + 284, 80, 34), 8, 8)
    p.setPen(QPen(BORDER)); p.setBrush(QBrush(QColor(255, 255, 255, 15))); p.drawPath(cp2)
    p.setPen(QPen(QColor(152, 152, 157)))
    p.drawText(QRect(dx + dw - 176, dy + 284, 80, 34), Qt.AlignmentFlag.AlignCenter, "Cancel")

    # Save
    sp = QPainterPath(); sp.addRoundedRect(QRectF(dx + dw - 90, dy + 284, 70, 34), 8, 8)
    p.setPen(Qt.PenStyle.NoPen); p.setBrush(QBrush(BLUE)); p.drawPath(sp)
    p.setFont(QFont("Segoe UI", 11, QFont.Weight.DemiBold)); p.setPen(QPen(WHITE))
    p.drawText(QRect(dx + dw - 90, dy + 284, 70, 34), Qt.AlignmentFlag.AlignCenter, "Save")

    p.end()
    return pix


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    app = QApplication(sys.argv)
    OUT.mkdir(exist_ok=True)

    scenarios = [
        ("01_overview.png",   screenshot_1_overview,  "Overview — annotations on code"),
        ("02_redaction.png",  screenshot_2_redaction, "Blur & black box redaction"),
        ("03_callouts.png",   screenshot_3_callouts,  "Step-by-step callouts"),
        ("04_drawing.png",    screenshot_4_drawing,   "Drawing tools"),
        ("05_settings.png",   screenshot_5_settings,  "Settings dialog"),
    ]

    print("Generating Store screenshots…")
    for filename, fn, desc in scenarios:
        pix = fn()
        path = OUT / filename
        pix.save(str(path), "PNG")
        print(f"  ✓  {filename}  —  {desc}")

    print(f"\nAll screenshots → {OUT}/")


if __name__ == "__main__":
    main()
