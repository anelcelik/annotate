"""Drawing model and compositing: undo history, numbering, eraser, blur, DPR."""
from PyQt6.QtCore import QPoint, QPointF, QRect, QRectF, Qt
from PyQt6.QtGui import QColor, QImage, QPainter, QPixmap
from PyQt6.QtWidgets import QApplication


def make_canvas(A):
    cv = A.Canvas()
    cv.resize(400, 300)
    return cv


def place(cv, tool, n):
    cv.tool = tool
    for i in range(n):
        cv._place_point(QPointF(20 + i * 30, 20))


def test_callout_numbers_follow_undo(A):
    cv = make_canvas(A)
    place(cv, "callout", 3)
    cv.undo()
    place(cv, "callout", 1)
    assert [s.number for s in cv._shapes] == [1, 2, 3]   # was [1, 2, 4]


def test_steps_and_callouts_count_separately(A):
    cv = make_canvas(A)
    place(cv, "callout", 2)
    place(cv, "steps", 1)
    assert [s.number for s in cv._shapes] == [1, 2, 1]


def test_clear_is_undoable(A):
    cv = make_canvas(A)
    place(cv, "callout", 3)
    assert cv.clear() == 3
    assert cv._shapes == []
    assert cv.undo()
    assert len(cv._shapes) == 3
    assert cv.redo()
    assert cv._shapes == []


def test_toast_undo_only_undoes_the_clear(A):
    cv = make_canvas(A)
    place(cv, "callout", 2)
    cv.clear()
    place(cv, "callout", 1)          # drew something after clearing
    assert not cv.undo_clear()       # a late Undo click must not eat it
    assert len(cv._shapes) == 1


def test_delete_is_undoable_in_place(A):
    cv = make_canvas(A)
    place(cv, "callout", 3)
    middle = cv._shapes[1]
    cv._selected = middle
    assert cv.delete_selected()
    assert middle not in cv._shapes
    cv.undo()
    assert cv._shapes[1] is middle


def test_move_is_undoable(A, qapp):
    from PyQt6.QtTest import QTest
    cv = make_canvas(A)
    cv.tool = "redact"
    shape = A.RedactShape(QPointF(10, 10), QPointF(60, 60))
    cv._commit(shape)
    cv.tool = "select"
    QTest.mousePress(cv, Qt.MouseButton.LeftButton, pos=QPoint(30, 30))
    QTest.mouseMove(cv, QPoint(130, 80))
    QTest.mouseRelease(cv, Qt.MouseButton.LeftButton, pos=QPoint(130, 80))
    moved = shape.bounding_rect().topLeft()
    assert (moved.x(), moved.y()) != (10, 10)
    cv.undo()
    back = shape.bounding_rect().topLeft()
    assert (back.x(), back.y()) == (10, 10)


def test_shapes_changed_signal(A):
    cv = make_canvas(A)
    hits = []
    cv.shapes_changed.connect(lambda: hits.append(1))
    place(cv, "callout", 1)
    cv.undo()
    cv.redo()
    cv.clear()
    assert len(hits) == 4


def test_translucent_pen_has_no_beads(A):
    img = QImage(300, 60, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(0)
    s = A.PenShape(A._with_alpha("#FF3B3B", 128), 12)
    s.pts = [QPointF(x, 30) for x in range(10, 290, 20)]
    p = QPainter(img)
    s.draw(p)
    p.end()
    mid, joint = img.pixelColor(20, 30).alpha(), img.pixelColor(30, 30).alpha()
    assert abs(mid - joint) <= 2          # was 128 vs 192


def _frame(color="#3366cc", w=200, h=100):
    img = QImage(w, h, QImage.Format.Format_ARGB32)
    img.fill(QColor(color))
    return img


def test_eraser_never_punches_through_the_frame(A):
    """Recorder/screenshot path: marks are painted onto a desktop frame."""
    cv = make_canvas(A)
    cv._commit(A.RedactShape(QPointF(0, 40), QPointF(200, 60)))   # black band
    eraser = A.EraserShape(20)
    eraser.pts = [QPointF(20, 50), QPointF(180, 50)]
    cv._commit(eraser)
    frame = _frame()
    p = QPainter(frame)
    cv.paint_marks(p, frame.width(), frame.height(), selection=False)
    p.end()
    c = frame.pixelColor(100, 50)
    # The black band is erased, and what shows is the desktop — not a hole.
    assert (c.name(), c.alpha()) == ("#3366cc", 255)       # was #000000, alpha 0


def test_eraser_keeps_the_clickable_fill(A):
    """On-screen path: the alpha-1 fill that makes the overlay clickable on
    Windows must survive an eraser stroke."""
    cv = make_canvas(A)
    eraser = A.EraserShape(20)
    eraser.pts = [QPointF(20, 50), QPointF(180, 50)]
    cv._commit(eraser)
    img = QImage(200, 100, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(QColor(0, 0, 0, 1))
    p = QPainter(img)
    cv.paint_marks(p, 200, 100)
    p.end()
    assert img.pixelColor(100, 50).alpha() == 1


def test_blur_is_opaque_to_the_edge(A):
    raw = QPixmap(240, 140)
    raw.fill(QColor("white"))
    p = QPainter(raw)
    p.fillRect(40, 40, 160, 60, QColor("black"))   # the "secret"
    p.end()
    padded, target = QRect(0, 0, 240, 140), QRect(40, 40, 160, 60)
    out = A._blur_region(raw, padded, target, 18).toImage()
    assert (out.width(), out.height()) == (160, 60)
    alphas = {out.pixelColor(x, y).alpha()
              for x in range(out.width()) for y in (0, 30, 59)}
    assert alphas == {255}                             # was 130 at the edge


def test_screenshot_marks_land_right_at_125_percent(A, monkeypatch):
    """grabWindow at 125 % returns a pixmap tagged 1.25; the marks were scaled
    twice (1.5625×). A logical (100,100) box must land at device (125,125)."""
    cv = make_canvas(A)
    cv._commit(A.RedactShape(QPointF(100, 100), QPointF(110, 110)))

    class Screen:
        def virtualGeometry(self):
            return QRect(0, 0, 320, 240)

        def grabWindow(self, *_):
            pm = QPixmap(400, 300)                 # device pixels
            pm.fill(QColor("white"))
            pm.setDevicePixelRatio(1.25)            # what Qt does at 125 %
            return pm

    monkeypatch.setattr(QApplication, "primaryScreen", staticmethod(lambda: Screen()))
    img = cv.capture_annotated().toImage()
    assert img.pixelColor(130, 130).name() == "#000000"
    assert img.pixelColor(150, 150).name() == "#ffffff"   # 1.5625× would cover it


def _max_alpha(shape, w=300, h=200):
    img = QImage(w, h, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(0)
    p = QPainter(img)
    shape.draw(p)
    p.end()
    return max(img.pixelColor(x, y).alpha() for x in range(w) for y in range(h)), img


def test_translucent_arrow_is_painted_once(A):
    """Shaft, head fill and head outline overlapped and blended two or three
    times: a 35 % arrow peaked at 73 % with the shaft showing through."""
    arrow = A.ArrowShape(QPointF(20, 180), QPointF(250, 30),
                         A._with_alpha("#32D74B", 90), 12)
    peak, _ = _max_alpha(arrow)
    assert peak <= 91                                     # was 186


def test_translucent_ruler_ends_are_painted_once(A):
    ruler = A.RulerShape(QPointF(20, 100), QPointF(250, 100),
                         A._with_alpha("#32D74B", 90), 8)
    _, img = _max_alpha(ruler)
    assert abs(img.pixelColor(20, 100).alpha() - img.pixelColor(80, 100).alpha()) <= 2
