"""Phase 4, part 1 (5.6): more shapes, stamps, saved marks, hold to draw,
the recording countdown."""
import json

from PyQt6.QtCore import QEvent, QPointF, QRect, QRectF, Qt
from PyQt6.QtGui import QColor, QImage, QKeyEvent, QPainter, QPixmap
from PyQt6.QtTest import QTest

from test_phase3c import drag, make_canvas, mouse


def render(shape, w=300, h=200):
    img = QImage(w, h, QImage.Format.Format_ARGB32)
    img.fill(0)
    p = QPainter(img)
    shape.draw(p)
    p.end()
    return img


# ── filled shapes ─────────────────────────────────────────────────────────────

def test_fill_off_tint_solid(A):
    for cls in (A.RectShape, A.CircleShape):
        none = cls(QPointF(50, 50), QPointF(250, 150), "#0A84FF", 6)
        tint = cls(QPointF(50, 50), QPointF(250, 150), "#0A84FF", 6, "tint")
        solid = cls(QPointF(50, 50), QPointF(250, 150), "#0A84FF", 6, "solid")
        assert render(none).pixelColor(150, 100).alpha() == 0
        assert 30 < render(tint).pixelColor(150, 100).alpha() < 120
        assert render(solid).pixelColor(150, 100).alpha() == 255
        assert not none.hit(QPointF(150, 100)) and solid.hit(QPointF(150, 100))


def test_see_through_solid_fill_has_no_darker_ring(A):
    r = A.RectShape(QPointF(50, 50), QPointF(250, 150), "#800A84FF", 10, "solid")
    img = render(r)
    assert img.pixelColor(150, 100).alpha() == img.pixelColor(51, 100).alpha()


# ── arrows ────────────────────────────────────────────────────────────────────

def test_two_headed_arrow(A):
    one = A.ArrowShape(QPointF(50, 100), QPointF(250, 100), "#FF3B3B", 4)
    two = A.ArrowShape(QPointF(50, 100), QPointF(250, 100), "#FF3B3B", 4, heads=2)
    beside_tail = QPointF(61, 104)                 # inside a head, outside the shaft
    assert not one.outline().contains(beside_tail)
    assert two.outline().contains(beside_tail)


def test_drag_the_middle_handle_to_curve_an_arrow(A):
    cv = make_canvas(A)
    a = A.ArrowShape(QPointF(50, 200), QPointF(350, 200), "#FF3B3B", 4)
    cv._commit(a)
    cv._set_selection([a])
    drag(cv, QPointF(200, 200), QPointF(200, 120))    # the middle handle, up
    assert abs(a.mid_point().y() - 120) < 1 and a.bend != 0
    assert a.hit(QPointF(200, 120)) and not a.hit(QPointF(200, 200))
    cv.undo()
    assert a.bend == 0


# ── speech bubble ─────────────────────────────────────────────────────────────

def test_bubble_has_a_tail_you_can_drag(A):
    cv = make_canvas(A)
    t = A.TextShape(QPointF(100, 60), "Look here", "#1C1C1E", 16, "bubble")
    cv._commit(t)
    tip = t.tail_point()
    assert t.bounding_rect().contains(tip)
    cv._set_selection([t])
    drag(cv, tip, QPointF(300, 260))
    assert t.tail_point() == QPointF(300, 260)
    img = QImage(600, 400, QImage.Format.Format_ARGB32)
    img.fill(0)
    p = QPainter(img)
    t.draw(p)
    p.end()
    assert img.pixelColor(290, 245).alpha() > 0            # the tail is drawn


# ── stamps ────────────────────────────────────────────────────────────────────

def test_every_stamp_draws_its_symbol(A):
    for kind in A.STAMPS:
        s = A.StampShape(QPointF(100, 100), kind, "#32D74B", 30)
        img = render(s, 200, 200)
        inks = {img.pixelColor(x, y).name() for x in range(80, 121) for y in range(80, 121)}
        assert "#32d74b" in inks and len(inks) > 2, kind


def test_g_places_a_solid_stamp(A, overlay):
    cv = overlay.canvas
    overlay.keyPressEvent(QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_G,
                                    Qt.KeyboardModifier.NoModifier))
    assert cv.tool == "stamp"
    cv.pen_alpha, cv.stamp_kind = 60, "cross"
    mouse(cv, "press", QPointF(300, 300))
    mouse(cv, "release", QPointF(300, 300))
    s = cv._shapes[-1]
    assert type(s).__name__ == "StampShape" and s.kind == "cross"
    assert QColor(s.color).alpha() == 255


# ── dock ──────────────────────────────────────────────────────────────────────

def test_dock_style_choices_set_new_marks_and_edit_selected(A, overlay):
    from PyQt6.QtWidgets import QPushButton
    dock, cv = overlay.toolbar, overlay.canvas

    def press(text):
        b = next(b for b in dock._props.findChildren(QPushButton) if b.text() == text)
        b.click()
    dock._activate("rect")
    press("Tint")
    assert cv.shape_fill == "tint" and overlay.settings.get("shape_fill") == "tint"
    drag(cv, QPointF(100, 100), QPointF(200, 200))
    r = cv._shapes[-1]
    assert r.fill == "tint"
    dock._activate("select")
    cv._set_selection([r])
    press("Solid")
    assert r.fill == "solid" and cv.shape_fill == "tint"   # the pref stays
    cv.undo()
    assert r.fill == "tint"


# ── saving and opening marks ──────────────────────────────────────────────────

def all_kinds(A):
    pen = A.PenShape("#FF3B3B", 4)
    pen.pts = [QPointF(10, 10), QPointF(40, 30)]
    blurred = QPixmap(40, 20)
    blurred.fill(QColor("#123456"))
    shapes = [
        pen,
        A.LineShape(QPointF(0, 0), QPointF(50, 50), "#000000", 3),
        A.ArrowShape(QPointF(0, 0), QPointF(90, 10), "#FF3B3B", 4, heads=2, bend=20.0),
        A.RectShape(QPointF(5, 5), QPointF(60, 60), "#0A84FF", 3, "tint"),
        A.CircleShape(QPointF(5, 5), QPointF(60, 60), "#0A84FF", 3),
        A.RulerShape(QPointF(0, 0), QPointF(100, 0), "#000000", 2, 1.25),
        A.TextShape(QPointF(30, 30), "Hi\nthere", "#1C1C1E", 16, "bubble"),
        A.CalloutShape(QPointF(20, 20), 3, "#FF3B3B", 20),
        A.StepShape(QPointF(20, 20), 2, "#FF3B3B", 20),
        A.StampShape(QPointF(20, 20), "star", "#FF9F0A", 20),
        A.HighlightShape(QPointF(0, 0), QPointF(80, 20), "#66FFD60A"),
        A.BlurShape(QPointF(0, 0), QPointF(40, 20), blurred),
        A.RedactShape(QPointF(0, 0), QPointF(40, 20)),
    ]
    shapes[1].fades, shapes[1].born = True, 123.0
    return shapes


def test_marks_survive_a_round_trip_through_a_file(A):
    shapes = all_kinds(A)
    back = A.marks_from_json(json.loads(json.dumps(A.marks_to_json(shapes))))
    assert [type(s).__name__ for s in back] == [type(s).__name__ for s in shapes]
    for old, new in zip(shapes, back):
        render(new)                                          # draws fine
        assert new.bounding_rect() == old.bounding_rect()
    assert back[2].heads == 2 and back[2].bend == 20.0 and back[6].box == "bubble"
    assert back[11].blurred.toImage().pixelColor(5, 5).name() == "#123456"
    assert not hasattr(back[1], "fades")                     # never fades away


def test_save_and_open_from_the_overlay(A, overlay, tmp_path, monkeypatch):
    target = tmp_path / "talk.samarks"
    monkeypatch.setattr(A.QFileDialog, "getSaveFileName",
                        staticmethod(lambda *a, **k: (str(tmp_path / "talk"), "")))
    monkeypatch.setattr(A.QFileDialog, "getOpenFileName",
                        staticmethod(lambda *a, **k: (str(target), "")))
    cv = overlay.canvas
    for s in all_kinds(A)[:4]:
        cv._commit(s)
    overlay.keyPressEvent(QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_S,
                                    Qt.KeyboardModifier.ControlModifier))
    assert target.exists() and cv.tool != "steps"            # Ctrl+S isn't Steps
    cv._shapes.clear()
    overlay.keyPressEvent(QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_O,
                                    Qt.KeyboardModifier.ControlModifier))
    assert len(cv._shapes) == 4
    cv.undo()
    assert cv._shapes == []


def test_a_bad_file_is_refused_politely(A, overlay, tmp_path, monkeypatch):
    bad = tmp_path / "x.samarks"
    bad.write_text('{"hello": 1}')
    monkeypatch.setattr(A.QFileDialog, "getOpenFileName",
                        staticmethod(lambda *a, **k: (str(bad), "")))
    overlay.open_marks()
    assert overlay.canvas._shapes == []


# ── hold to draw ──────────────────────────────────────────────────────────────

def test_hold_a_key_to_draw(A, overlay):
    overlay.set_passthrough(True)
    overlay.settings.set("hold_to_draw", "rctrl")
    overlay._poll_hold(key_state=lambda vk: vk == 0xA3)
    assert not overlay._passthrough
    overlay._poll_hold(key_state=lambda vk: False)
    assert overlay._passthrough
    overlay.settings.set("hold_to_draw", "off")
    overlay._poll_hold(key_state=lambda vk: True)
    assert overlay._passthrough


# ── countdown ─────────────────────────────────────────────────────────────────

def test_countdown_then_record_and_cancel(A, overlay, monkeypatch):
    rc = overlay.recording
    began = []
    monkeypatch.setattr(rc, "_begin", lambda cfg, region: began.append(region))
    overlay.settings.set("rec_countdown", True)
    rc._count_in(rc.config(), QRect(0, 0, 800, 600))
    assert rc._countdown is not None and rc._countdown.n == 3 and not began
    rc.toggle()                                              # pressed again: cancel
    assert rc._countdown is None
    rc._count_in(rc.config(), QRect(0, 0, 800, 600))
    for _ in range(3):
        rc._countdown._tick()
    QTest.qWait(250)
    assert began == [QRect(0, 0, 800, 600)] and rc._countdown is None
    overlay.settings.set("rec_countdown", False)
    rc._count_in(rc.config(), None)
    assert began[-1] is None
