#!/usr/bin/env python3
"""
Generate every Microsoft Store icon asset for Screen Annotate.

Output layout (icons/):
  Square44x44Logo.scale-NNN.png
  Square71x71Logo.scale-NNN.png
  Square150x150Logo.scale-NNN.png
  Square310x310Logo.scale-NNN.png
  Wide310x150Logo.scale-NNN.png
  StoreLogo.scale-NNN.png
  SplashScreen.scale-NNN.png
  BadgeLogo.scale-NNN.png
  annotate.ico  (16/24/32/48/256 multi-size)

Run:
  python create_icons.py
"""

import sys, math, io
sys.stdout.reconfigure(encoding='utf-8')
from pathlib import Path

from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import Qt, QRectF, QPointF, QByteArray, QBuffer, QIODeviceBase
from PyQt6.QtGui import (
    QPainter, QPen, QColor, QBrush, QPixmap,
    QPainterPath, QPolygonF, QLinearGradient, QRadialGradient, QFont,
    QFontMetrics,
)

HERE = Path(__file__).parent
OUT  = HERE / "icons"

# ── Microsoft Store asset spec ─────────────────────────────────────────────────
# (name_stem, base_w, base_h, [(scale_label, multiplier), ...])
ASSETS = [
    # Square icons — all five scales required by the Store
    ("Square44x44Logo",   44,  44,  [("100", 1.00), ("125", 1.25), ("150", 1.50), ("200", 2.00), ("400", 4.00)]),
    ("Square71x71Logo",   71,  71,  [("100", 1.00), ("125", 1.25), ("150", 1.50), ("200", 2.00), ("400", 4.00)]),
    ("Square150x150Logo", 150, 150, [("100", 1.00), ("125", 1.25), ("150", 1.50), ("200", 2.00), ("400", 4.00)]),
    ("Square310x310Logo", 310, 310, [("100", 1.00), ("125", 1.25), ("150", 1.50), ("200", 2.00), ("400", 4.00)]),
    # Wide tile
    ("Wide310x150Logo",   310, 150, [("100", 1.00), ("125", 1.25), ("150", 1.50), ("200", 2.00), ("400", 4.00)]),
    # Store listing logo
    ("StoreLogo",          50,  50,  [("100", 1.00), ("125", 1.25), ("150", 1.50), ("200", 2.00), ("400", 4.00)]),
    # Splash screen — valid scales are 100/125/150/200 only (400 is NOT in the MS spec)
    ("SplashScreen",      620, 300, [("100", 1.00), ("125", 1.25), ("150", 1.50), ("200", 2.00)]),
    # BadgeLogo deliberately omitted — not referenced in AppxManifest and not used
    # by a Win32 full-trust app (no lock-screen badge support).
]

ICO_SIZES = [16, 24, 32, 48, 256]

# ── Colour palette ─────────────────────────────────────────────────────────────
BG_TOP    = QColor(22,  22,  28)
BG_BOT    = QColor(10,  10,  14)
BLUE      = QColor(10,  132, 255)
BLUE_DARK = QColor(0,   98,  210)
PEN_LIGHT = QColor(238, 240, 252)
PEN_MID   = QColor(185, 190, 210)
PEN_DARK  = QColor(175, 180, 200)
COLLAR    = QColor(85,  93,  115)
WHITE     = QColor(255, 255, 255)


# ── Drawing helpers ────────────────────────────────────────────────────────────

def _bg_gradient(w: float, h: float) -> QLinearGradient:
    g = QLinearGradient(QPointF(0, 0), QPointF(0, h))
    g.setColorAt(0.0, BG_TOP)
    g.setColorAt(1.0, BG_BOT)
    return g


def _draw_pen(p: QPainter, cx: float, cy: float, pen_size: float, angle_deg: float = -40):
    """Draw a detailed pen centred at (cx, cy) rotated by angle_deg."""
    p.save()
    p.translate(cx, cy)
    p.rotate(angle_deg)

    pw = pen_size * 0.16
    ph = pen_size * 0.50
    body_h   = ph * 0.72
    collar_h = ph * 0.08
    tip_h    = ph * 0.20
    top_y    = -ph * 0.50

    # Body
    body_grad = QLinearGradient(-pw / 2, 0, pw / 2, 0)
    body_grad.setColorAt(0.0,  PEN_MID)
    body_grad.setColorAt(0.45, PEN_LIGHT)
    body_grad.setColorAt(1.0,  PEN_DARK)
    body_path = QPainterPath()
    body_path.addRoundedRect(QRectF(-pw / 2, top_y, pw, body_h), pw * 0.38, pw * 0.38)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QBrush(body_grad))
    p.drawPath(body_path)

    # Collar
    collar_y = top_y + body_h
    p.setBrush(QBrush(COLLAR))
    p.drawRect(QRectF(-pw / 2, collar_y, pw, collar_h))

    # Tapered tip (blue)
    tip_y = collar_y + collar_h
    p.setBrush(QBrush(BLUE))
    p.drawPolygon(QPolygonF([
        QPointF(-pw * 0.43, tip_y),
        QPointF( pw * 0.43, tip_y),
        QPointF( pw * 0.06, tip_y + tip_h * 0.65),
        QPointF(-pw * 0.06, tip_y + tip_h * 0.65),
    ]))

    # Sharp point
    sharp_y = tip_y + tip_h * 0.65
    p.setBrush(QBrush(BLUE_DARK))
    p.drawPolygon(QPolygonF([
        QPointF(-pw * 0.06, sharp_y),
        QPointF( pw * 0.06, sharp_y),
        QPointF(0,          sharp_y + tip_h * 0.35),
    ]))

    p.restore()


def _draw_arrow(p: QPainter, x1: float, y1: float, x2: float, y2: float, stroke: float):
    """Draw an annotation arrow from (x1,y1) to (x2,y2)."""
    p.setPen(QPen(BLUE, stroke, Qt.PenStyle.SolidLine,
                  Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
    p.drawLine(QPointF(x1, y1), QPointF(x2, y2))
    ah     = stroke * 2.0        # was 5.0 — kept arrowhead proportional to stroke
    angle  = math.atan2(y2 - y1, x2 - x1)
    spread = math.pi / 5.5
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QBrush(BLUE))
    p.drawPolygon(QPolygonF([
        QPointF(x2, y2),
        QPointF(x2 - ah * math.cos(angle - spread), y2 - ah * math.sin(angle - spread)),
        QPointF(x2 - ah * math.cos(angle + spread), y2 - ah * math.sin(angle + spread)),
    ]))


# ── Square icon (works for any square size) ────────────────────────────────────

def draw_square(size: int) -> QPixmap:
    pix = QPixmap(size, size)
    pix.fill(QColor(0, 0, 0, 0))
    p = QPainter(pix)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    s = float(size)

    # Background
    bg = QPainterPath()
    bg.addRoundedRect(QRectF(0, 0, s, s), s * 0.20, s * 0.20)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QBrush(_bg_gradient(s, s)))
    p.drawPath(bg)

    # Pen — centred slightly upper-left
    _draw_pen(p, s * 0.38, s * 0.38, s, -40)

    # Short annotation arrow starting at the pen tip (pen tip ≈ 0.54, 0.57 in world coords)
    if size >= 24:
        _draw_arrow(p, s * 0.54, s * 0.57, s * 0.73, s * 0.73, max(1.5, s * 0.038))

    p.end()
    return pix


# ── Wide tile (310×150 base) ───────────────────────────────────────────────────

def draw_wide(w: int, h: int) -> QPixmap:
    pix = QPixmap(w, h)
    pix.fill(QColor(0, 0, 0, 0))
    p = QPainter(pix)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    fw, fh = float(w), float(h)

    # Background (no rounded corners — tiles go edge-to-edge)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QBrush(_bg_gradient(fw, fh)))
    p.drawRect(QRectF(0, 0, fw, fh))

    # Pen on the left third, vertically centred
    pen_area = fh * 0.80
    _draw_pen(p, fw * 0.22, fh * 0.50, pen_area, -40)

    # Divider line
    div_x = fw * 0.40
    p.setPen(QPen(QColor(255, 255, 255, 18), max(1.0, fh * 0.006)))
    p.drawLine(QPointF(div_x, fh * 0.18), QPointF(div_x, fh * 0.82))
    p.setPen(Qt.PenStyle.NoPen)

    # Text area
    text_x = fw * 0.44
    text_w = fw * 0.53

    def _fit(txt, max_w, px, bold=False):
        f = QFont("Segoe UI")
        f.setBold(bold)
        f.setPixelSize(max(6, px))
        while QFontMetrics(f).horizontalAdvance(txt) > max_w and f.pixelSize() > 6:
            f.setPixelSize(f.pixelSize() - 1)
        return f

    # "SCREEN" small dim label
    lbl_font = _fit("SCREEN", text_w, int(fh * 0.13))
    lbl_font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, max(1.0, fh * 0.012))
    p.setFont(lbl_font)
    p.setPen(QPen(QColor(90, 100, 135)))
    p.drawText(QRectF(text_x, fh * 0.10, text_w, fh * 0.28),
               Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, "SCREEN")

    # "Annotator Pro" bold main title
    name_font = _fit("Annotator Pro", text_w, int(fh * 0.22), bold=True)
    p.setFont(name_font)
    p.setPen(QPen(WHITE))
    p.drawText(QRectF(text_x, fh * 0.34, text_w, fh * 0.36),
               Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, "Annotator Pro")

    # Tagline
    tag_font = _fit("Draw on your screen", text_w, int(fh * 0.10))
    p.setFont(tag_font)
    p.setPen(QPen(QColor(100, 108, 140)))
    p.drawText(QRectF(text_x, fh * 0.68, text_w, fh * 0.24),
               Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
               "Draw on your screen")

    # Small annotation arrow as decoration
    ax0, ay0 = fw * 0.44, fh * 0.88
    _draw_arrow(p, ax0, ay0, ax0 + fh * 0.18, ay0, max(1.2, fh * 0.030))

    p.end()
    return pix


# ── Splash screen ──────────────────────────────────────────────────────────────

def draw_splash(w: int, h: int) -> QPixmap:
    pix = QPixmap(w, h)
    pix.fill(QColor(0, 0, 0, 0))
    p = QPainter(pix)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    fw, fh = float(w), float(h)

    # Background
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QBrush(_bg_gradient(fw, fh)))
    p.drawRect(QRectF(0, 0, fw, fh))

    # Subtle radial glow behind the icon
    glow = QRadialGradient(QPointF(fw / 2, fh / 2), fh * 0.55)
    glow.setColorAt(0.0, QColor(10, 132, 255, 28))
    glow.setColorAt(1.0, QColor(10, 132, 255, 0))
    p.setBrush(QBrush(glow))
    p.drawRect(QRectF(0, 0, fw, fh))

    # Pen centred, scaled to ~60 % of height
    pen_size = fh * 0.60
    _draw_pen(p, fw * 0.50, fh * 0.46, pen_size, -40)

    # App name below — auto-fit to 80 % of image width
    name_font = QFont("Segoe UI")
    name_font.setBold(True)
    name_font.setPixelSize(max(10, int(fh * 0.14)))
    while QFontMetrics(name_font).horizontalAdvance("Screen Annotator Pro") > fw * 0.80:
        name_font.setPixelSize(name_font.pixelSize() - 1)
    p.setFont(name_font)
    p.setPen(QPen(WHITE))
    p.drawText(QRectF(0, fh * 0.72, fw, fh * 0.18),
               Qt.AlignmentFlag.AlignCenter, "Screen Annotator Pro")

    p.end()
    return pix


# ── System-tray icon (transparent background, for Windows taskbar tray) ────────

def draw_tray(size: int) -> QPixmap:
    """Pen on transparent background — no background rect, no arrow.
    Designed to read cleanly at 16 px on any taskbar colour."""
    pix = QPixmap(size, size)
    pix.fill(QColor(0, 0, 0, 0))
    p = QPainter(pix)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    s = float(size)
    _draw_pen(p, s * 0.50, s * 0.46, s * 0.88, -40)
    p.end()
    return pix


# ── Badge (monochrome disk for lock-screen badge) ──────────────────────────────

def draw_badge(size: int) -> QPixmap:
    pix = QPixmap(size, size)
    pix.fill(QColor(0, 0, 0, 0))
    p = QPainter(pix)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    s = float(size)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QBrush(WHITE))
    p.drawEllipse(QRectF(0, 0, s, s))
    # Small pen silhouette in blue
    _draw_pen(p, s * 0.50, s * 0.50, s * 0.88, -40)
    p.end()
    return pix


# ── Pillow helper ──────────────────────────────────────────────────────────────

def pix_to_pil(pix: QPixmap):
    from PIL import Image
    ba  = QByteArray()
    buf = QBuffer(ba)
    buf.open(QIODeviceBase.OpenModeFlag.WriteOnly)
    pix.save(buf, "PNG")
    buf.close()
    return Image.open(io.BytesIO(bytes(ba))).copy()


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    app = QApplication(sys.argv)
    OUT.mkdir(exist_ok=True)

    print("Generating Microsoft Store icon assets…\n")

    # Dispatch table: which draw function to use per stem
    def _render(stem: str, w: int, h: int) -> QPixmap:
        if stem.startswith("Wide"):
            return draw_wide(w, h)
        if stem == "SplashScreen":
            return draw_splash(w, h)
        if stem == "BadgeLogo":
            return draw_badge(w)
        return draw_square(w)

    for stem, base_w, base_h, scales in ASSETS:
        for scale_label, mult in scales:
            # int(x + 0.5) = round-half-up, matching Microsoft's spec sizes exactly.
            # Python's built-in round() uses banker's rounding which gives wrong
            # results for .5 cases (e.g. round(62.5)=62 instead of the spec's 63).
            pw = int(base_w * mult + 0.5)
            ph = int(base_h * mult + 0.5)
            pix  = _render(stem, pw, ph)
            name = f"{stem}.scale-{scale_label}.png"
            pix.save(str(OUT / name), "PNG")
            print(f"  ✓  {name:<50}  {pw}×{ph}")
        print()

    # App ICO (square icon, for MSIX / installer)
    ico_path = OUT / "annotate.ico"
    try:
        from PIL import Image
        imgs = [pix_to_pil(draw_square(sz)) for sz in ICO_SIZES]
        imgs[0].save(
            str(ico_path), format="ICO",
            sizes=[(sz, sz) for sz in ICO_SIZES],
            append_images=imgs[1:],
        )
        sizes_str = "/".join(str(s) for s in ICO_SIZES)
        print(f"  ✓  annotate.ico  ({sizes_str} px multi-size)\n")
    except Exception as e:
        draw_square(256).save(str(ico_path), "ICO")
        print(f"  ✓  annotate.ico  (256 px fallback — Pillow error: {e})\n")

    # Tray ICO (transparent pen, for Windows system tray)
    tray_sizes = [16, 24, 32, 48, 64, 256]
    tray_ico = OUT / "tray.ico"
    try:
        from PIL import Image
        timgs = [pix_to_pil(draw_tray(sz)) for sz in tray_sizes]
        timgs[0].save(
            str(tray_ico), format="ICO",
            sizes=[(sz, sz) for sz in tray_sizes],
            append_images=timgs[1:],
        )
        print(f"  ✓  tray.ico  (16/24/32/48/64/256 px — transparent pen)\n")
    except Exception as e:
        draw_tray(256).save(str(tray_ico), "ICO")
        print(f"  ✓  tray.ico  (256 px fallback — {e})\n")

    # Store listing tile icon — 300×300 (uploaded separately in Partner Center)
    store_tile = OUT / "StoreListingIcon_300x300.png"
    draw_square(300).save(str(store_tile), "PNG")
    print(f"  ✓  StoreListingIcon_300x300.png  (Store listing / Partner Center upload)\n")

    total = sum(len(s) for _, _, _, s in ASSETS) + 2
    print(f"Done — {total} files → {OUT}/")


if __name__ == "__main__":
    main()
