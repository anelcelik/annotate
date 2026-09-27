"""Phase 2 (5.2): Windows OCR, region screenshots, typing on the canvas,
the object eraser, real pixelation, markers, the ruler, dirty repaints,
first-run tips and the live dock size."""
import sys

import pytest
from PyQt6.QtCore import QEvent, QPoint, QPointF, QRect, QRectF, Qt
from PyQt6.QtGui import QColor, QFont, QImage, QKeyEvent, QMouseEvent, QPainter, QPixmap
from PyQt6.QtWidgets import QApplication

import ocr_win


# ── Snip & Read ───────────────────────────────────────────────────────────────

def test_ocr_joins_words_per_script():
    assert ocr_win.join_lines([["Hello", "world"], ["42"]], "en-US") == "Hello world\n42"
    assert ocr_win.join_lines([["你", "好"], ["世", "界"]], "zh-Hans-CN") == "你好\n世界"
    assert ocr_win.join_lines([["日", "本"]], "ja") == "日本"


def test_ocr_prepares_small_snips_bigger(qapp):
    img = QImage(120, 20, QImage.Format.Format_RGB32)
    img.fill(QColor("white"))
    out = ocr_win.prepare(img)
    assert (out.width(), out.height()) == (360, 60)          # ×3 for tiny text
    assert out.format() == QImage.Format.Format_ARGB32_Premultiplied
    big = QImage(800, 400, QImage.Format.Format_RGB32)
    assert ocr_win.prepare(big).size() == big.size()


def test_translate_link_and_its_limit(A):
    url = A.translate_url("Grüß dich & tschüss", "en")
    assert url.startswith("https://translate.google.com/?sl=auto&tl=en&text=")
    assert "%26" in url and " " not in url
    assert A.translate_url("x" * 6000, "de") is None          # too long: clipboard


def test_snip_and_read_offered_when_windows_ocr_is(A, monkeypatch):
    monkeypatch.setattr(A, "_ocr_available", None)
    monkeypatch.setattr(ocr_win, "available", lambda: True)
    assert A.ocr_available()


@pytest.mark.skipif(sys.platform != "win32", reason="Windows OCR is Windows-only")
def test_windows_ocr_reads_real_text(qapp):
    """End to end on real Windows: QImage → SoftwareBitmap → OcrEngine."""
    if not ocr_win.available():
        pytest.skip("no OCR language installed on this machine")
    img = QImage(520, 90, QImage.Format.Format_RGB32)
    img.fill(QColor("white"))
    p = QPainter(img)
    p.setPen(QColor("black"))
    p.setFont(QFont("Arial", 28))
    p.drawText(12, 60, "Hello Annotator 2026")
    p.end()
    text = ocr_win.recognize(img, "")
    assert "Hello" in text and "2026" in text


# ── shapes ────────────────────────────────────────────────────────────────────

def test_hit_testing_follows_the_visible_mark(A):
    line = A.LineShape(QPointF(0, 0), QPointF(200, 200), "#000", 4)
    assert line.hit(QPointF(100, 102))
    assert not line.hit(QPointF(180, 20))                 # inside its box, off the line
    rect = A.RectShape(QPointF(0, 0), QPointF(200, 100), "#000", 4)
    assert rect.hit(QPointF(100, 1)) and not rect.hit(QPointF(100, 50))
    circle = A.CircleShape(QPointF(0, 0), QPointF(200, 200), "#000", 4)
    assert circle.hit(QPointF(100, 1)) and not circle.hit(QPointF(100, 100))
    pen = A.PenShape("#000", 6)
    pen.pts = [QPointF(0, 0), QPointF(100, 0), QPointF(100, 100)]
    assert pen.hit(QPointF(100, 50)) and not pen.hit(QPointF(40, 60))
    assert A.HighlightShape(QPointF(0, 0), QPointF(50, 50)).hit(QPointF(25, 25))
    assert not A.EraserShape(20).hit(QPointF(0, 0))       # invisible


def test_multiline_text_and_its_plate(A):
    one = A.TextShape(QPointF(10, 10), "Hi", "#FF3B3B", 20)
    two = A.TextShape(QPointF(10, 10), "Hi\nthere", "#FF3B3B", 20)
    assert two.bounding_rect().height() > one.bounding_rect().height() * 1.6
    assert one.bounding_rect().top() == pytest.approx(10)  # anchored top-left
    boxed = A.TextShape(QPointF(10, 10), "Hi", "#FFFFFF", 20, box=True)
    assert boxed.bounding_rect().contains(one.bounding_rect())
    img = QImage(200, 100, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(0)
    p = QPainter(img)
    boxed.draw(p)
    p.end()
    corner = img.pixelColor(round(boxed.bounding_rect().left()) + 8,
                            round(boxed.bounding_rect().top()) + 2)
    assert corner.alpha() > 200 and corner.red() < 40      # dark plate behind white text


def test_markers_follow_the_size_slider(A):
    assert A.CalloutShape(QPointF(0, 0), 1, "#F00").r == 16     # default unchanged
    assert A.CalloutShape(QPointF(0, 0), 1, "#F00", 40).r == 32
    assert A.StepShape(QPointF(0, 0), 1, "#F00", 8).r == 10     # never too small


def test_ruler_reads_real_pixels(A):
    r = A.RulerShape(QPointF(0, 0), QPointF(100, 0), "#000", 2, scale=1.25)
    assert r.length_px() == 125


def test_real_mosaic_keeps_the_colours(A, qapp):
    raw = QPixmap(100, 40)
    raw.fill(QColor("white"))
    p = QPainter(raw)
    p.fillRect(0, 0, 50, 40, QColor("#0000ff"))
    p.end()
    out = A._mosaic(raw, 20).toImage()
    assert out.size() == raw.size()
    assert out.pixelColor(10, 10) == out.pixelColor(19, 19)      # one flat cell
    assert out.pixelColor(10, 10).blue() > 200                   # the real colour


# ── canvas ────────────────────────────────────────────────────────────────────

def make_canvas(A):
    cv = A.Canvas()
    cv.resize(600, 400)
    return cv


def press(cv, pos):
    ev = QMouseEvent(QEvent.Type.MouseButtonPress, QPointF(pos), QPointF(pos),
                     Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton,
                     Qt.KeyboardModifier.NoModifier)
    cv.mousePressEvent(ev)


def move(cv, pos, held=True):
    b = Qt.MouseButton.LeftButton if held else Qt.MouseButton.NoButton
    ev = QMouseEvent(QEvent.Type.MouseMove, QPointF(pos), QPointF(pos),
                     Qt.MouseButton.NoButton, b, Qt.KeyboardModifier.NoModifier)
    cv.mouseMoveEvent(ev)


def release(cv, pos):
    ev = QMouseEvent(QEvent.Type.MouseButtonRelease, QPointF(pos), QPointF(pos),
                     Qt.MouseButton.LeftButton, Qt.MouseButton.NoButton,
                     Qt.KeyboardModifier.NoModifier)
    cv.mouseReleaseEvent(ev)


def test_object_eraser_removes_touched_marks_in_one_undo(A):
    cv = make_canvas(A)
    a = A.LineShape(QPointF(10, 10), QPointF(200, 10), "#000", 4)
    b = A.RectShape(QPointF(10, 100), QPointF(200, 200), "#000", 4)
    c = A.LineShape(QPointF(10, 300), QPointF(200, 300), "#000", 4)
    for s in (a, b, c):
        cv._commit(s)
    cv.tool, cv.eraser_mode = "eraser", "shapes"
    press(cv, QPointF(100, 12))              # on a
    move(cv, QPointF(100, 100))              # across b's top edge
    release(cv, QPointF(100, 100))
    assert cv._shapes == [c]
    cv.undo()
    assert cv._shapes == [a, b, c]           # both back, in their places
    cv.redo()
    assert cv._shapes == [c]


def test_pixel_eraser_still_available(A):
    cv = make_canvas(A)
    cv.tool, cv.eraser_mode = "eraser", "pixels"
    press(cv, QPointF(10, 10))
    move(cv, QPointF(100, 10))
    release(cv, QPointF(100, 10))
    assert isinstance(cv._shapes[-1], A.EraserShape)


def test_select_picks_the_mark_under_the_pointer_not_its_box(A):
    cv = make_canvas(A)
    below = A.HighlightShape(QPointF(50, 50), QPointF(150, 150))
    diagonal = A.ArrowShape(QPointF(0, 0), QPointF(400, 400), "#000", 4)
    cv._commit(below)
    cv._commit(diagonal)
    cv.tool = "select"
    press(cv, QPointF(140, 60))              # inside the arrow's box, off its line
    assert cv._selected is below


def test_typing_on_the_canvas(A, qapp):
    cv = make_canvas(A)
    cv.tool = "text"
    cv._place_point(QPointF(40, 50))
    assert cv._editor is not None
    cv._editor.setPlainText("Line one\nLine two")
    cv._editor.keyPressEvent(QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Return,
                                       Qt.KeyboardModifier.NoModifier))
    assert cv._editor is None
    shape = cv._shapes[-1]
    assert isinstance(shape, A.TextShape) and shape.text == "Line one\nLine two"
    assert (shape.pos.x(), shape.pos.y()) == (40, 50)


def test_esc_throws_the_text_away(A):
    cv = make_canvas(A)
    cv.tool = "text"
    cv._place_point(QPointF(40, 50))
    cv._editor.setPlainText("never mind")
    cv._editor.keyPressEvent(QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Escape,
                                       Qt.KeyboardModifier.NoModifier))
    assert cv._shapes == [] and cv._editor is None


def test_click_a_label_to_edit_it_undoably(A):
    cv = make_canvas(A)
    label = A.TextShape(QPointF(40, 50), "Old", "#FF3B3B", 20)
    cv._commit(label)
    cv.tool = "text"
    cv._place_point(QPointF(45, 60))          # on the label
    assert cv._editing is label
    cv._editor.setPlainText("New")
    cv.finish_editing()
    assert label.text == "New" and cv._shapes == [label]
    cv.undo()
    assert label.text == "Old"


def test_emptying_a_label_deletes_it(A):
    cv = make_canvas(A)
    label = A.TextShape(QPointF(40, 50), "Bye", "#FF3B3B", 20)
    cv._commit(label)
    cv.tool = "text"
    cv._place_point(QPointF(45, 60))
    cv._editor.setPlainText("")
    cv.finish_editing()
    assert cv._shapes == []


def test_laser_repaints_only_around_itself(A, monkeypatch):
    cv = make_canvas(A)
    cv.tool = "laser"
    areas = []
    monkeypatch.setattr(cv, "update", lambda *a: areas.append(a[0] if a else None))
    move(cv, QPointF(100, 100), held=False)
    move(cv, QPointF(110, 104), held=False)
    assert areas and all(a is not None and a.width() < 100 and a.height() < 100
                         for a in areas)


def test_region_screenshot_is_cropped_with_its_marks(A, monkeypatch):
    cv = make_canvas(A)
    cv._commit(A.RedactShape(QPointF(100, 100), QPointF(110, 110)))

    class Screen:
        def virtualGeometry(self):
            return QRect(0, 0, 320, 240)

        def grabWindow(self, *_):
            pm = QPixmap(400, 300)
            pm.fill(QColor("white"))
            pm.setDevicePixelRatio(1.25)
            return pm

    monkeypatch.setattr(QApplication, "primaryScreen", staticmethod(lambda: Screen()))
    img = cv.capture_annotated(QRect(90, 90, 40, 40)).toImage()
    assert (img.width(), img.height()) == (50, 50)             # 40 logical × 1.25
    assert img.pixelColor(20, 20).name() == "#000000"          # the mark, in place
    assert img.pixelColor(45, 45).name() == "#ffffff"


def test_click_captures_the_whole_screen(A, qapp):
    sel = A.RegionSelector(A.RegionSelector.SHOT_HINT, click_for_screen=True)
    got = []
    sel.chosen.connect(got.append)
    sel.choose()
    pos = QPointF(50, 50)
    for kind, fn in ((QEvent.Type.MouseButtonPress, sel.mousePressEvent),
                     (QEvent.Type.MouseButtonRelease, sel.mouseReleaseEvent)):
        fn(QMouseEvent(kind, pos, sel.mapToGlobal(pos), Qt.MouseButton.LeftButton,
                       Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier))
    assert got and got[0] == QApplication.primaryScreen().geometry()


def test_screenshots_default_to_pictures_screenshots(A, settings, tmp_path, monkeypatch):
    from PyQt6.QtCore import QStandardPaths
    monkeypatch.setattr(QStandardPaths, "writableLocation",
                        staticmethod(lambda *_: str(tmp_path / "Pictures")))
    assert A.screenshot_dir(settings) == str(tmp_path / "Pictures" / "Screenshots")
    settings.set("shot_dir", str(tmp_path))
    assert A.screenshot_dir(settings) == str(tmp_path)


# ── app ───────────────────────────────────────────────────────────────────────

def test_screenshot_has_a_shortcut(A, settings):
    assert "screenshot_hotkey" in A.HOTKEY_SETTINGS
    assert A.shortcut_label(settings, "screenshot_hotkey") == "Ctrl+PrtSc"


def test_welcome_tips_only_on_a_first_run(A, overlay):
    overlay.settings.is_new = False
    assert A.maybe_show_welcome(overlay) is None
    overlay.settings.is_new = True
    tips = A.maybe_show_welcome(overlay)
    assert tips is not None
    for _ in range(3):
        tips._advance()
    assert overlay.settings.get("tips_done")
    assert A.maybe_show_welcome(overlay) is None


def test_dock_resizes_live_and_keeps_its_state(A, overlay):
    dock = overlay.toolbar
    dock.set_record_shortcut("Ctrl+Alt+F9")
    dock.set_recording(True)
    before = dock.sizeHint().width()
    dock.apply_scale(1.0)
    assert dock.sizeHint().width() > before
    assert "Ctrl+Alt+F9" in dock._rec_btn.toolTip()
    assert dock._rec_btn._recording
    dock.apply_scale(0.78)


def test_tool_choices_stick(A, overlay):
    overlay.toolbar._set_pref("eraser_mode", "pixels")
    overlay.toolbar._set_pref("text_box", True)
    assert overlay.canvas.eraser_mode == "pixels" and overlay.canvas.text_box
    assert overlay.settings.get("eraser_mode") == "pixels"


def test_put_away_marks_stay_out_of_screenshots(A, overlay, monkeypatch):
    overlay.canvas._commit(A.RedactShape(QPointF(10, 10), QPointF(60, 60)))
    seen = []
    monkeypatch.setattr(overlay.canvas, "capture_annotated",
                        lambda rect, marks=True: seen.append(marks) or QPixmap(10, 10))
    monkeypatch.setattr(A, "ScreenshotBar", lambda pm, parent: None)
    overlay._shoot(QRect(0, 0, 100, 100))
    overlay.toggle()                               # put the overlay away
    overlay._shoot(QRect(0, 0, 100, 100))
    assert seen == [True, False]
