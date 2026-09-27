"""Phase 3, part 1 (5.3): fading ink, whiteboard/blackboard with pages,
presenter effects (spotlight, halo, click ripples)."""
import time

from PySide6.QtCore import QEvent, QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QImage, QKeyEvent, QPainter


def make_canvas(A):
    cv = A.Canvas()
    cv.resize(600, 400)
    return cv


def line(A, y=50):
    return A.LineShape(QPointF(10, y), QPointF(200, y), "#FF3B3B", 6)


# ── fading ink ────────────────────────────────────────────────────────────────

def test_faded_marks_fade_then_go_and_leave_no_undo_step(A):
    cv = make_canvas(A)
    cv.fade_ink = True
    shape = line(A)
    cv._commit(shape)
    assert shape.fades and cv._fade_timer.isActive()
    now = time.monotonic()
    shape.born = now - (cv.FADE_AFTER + cv.FADE_FOR / 2)
    assert 0.3 < cv._fade_factor(shape, time.monotonic()) < 0.7   # half faded
    shape.born = now - 10
    cv._fade_tick()
    assert cv._shapes == []
    assert not cv.undo()                     # nothing to step over


def test_redactions_never_fade(A):
    cv = make_canvas(A)
    cv.fade_ink = True
    cv._commit(A.RedactShape(QPointF(0, 0), QPointF(50, 50)))
    assert not getattr(cv._shapes[0], "fades", False)


def test_fading_is_drawn_translucent(A):
    cv = make_canvas(A)
    cv.fade_ink = True
    shape = line(A)
    cv._commit(shape)
    shape.born = time.monotonic() - (cv.FADE_AFTER + cv.FADE_FOR / 2)
    img = QImage(300, 100, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(0)
    p = QPainter(img)
    cv.render_annotations(p)
    p.end()
    assert 60 < img.pixelColor(100, 50).alpha() < 200


# ── whiteboard / blackboard ──────────────────────────────────────────────────

def test_board_has_its_own_marks_and_gives_the_desktop_back(A):
    cv = make_canvas(A)
    desk = line(A, 30)
    cv._commit(desk)
    cv.set_board("white", QRectF(0, 0, 600, 400))
    assert cv._shapes == []                  # a clean board
    on_board = line(A, 80)
    cv._commit(on_board)
    cv.set_board("black")                    # switching colour keeps the page
    assert cv._shapes == [on_board]
    cv.set_board(None)
    assert cv._shapes == [desk]              # desktop marks are back
    cv.set_board("white", QRectF(0, 0, 600, 400))
    assert cv._shapes == [on_board]          # and the board kept its page


def test_board_pages(A):
    cv = make_canvas(A)
    cv.set_board("white", QRectF(0, 0, 600, 400))
    first = line(A)
    cv._commit(first)
    assert cv.board_page(1) == 2 and cv._shapes == []
    cv._commit(line(A, 90))
    assert cv.board_page(-1) == 1 and cv._shapes == [first]
    cv.undo()                                # undo belongs to the page
    assert cv._shapes == []


def test_board_is_in_screenshots_and_recordings(A):
    cv = make_canvas(A)
    cv.set_board("black", QRectF(0, 0, 600, 400))
    img = QImage(600, 400, QImage.Format.Format_ARGB32)
    img.fill(QColor("white"))
    p = QPainter(img)
    cv.paint_marks(p, 600, 400, selection=False, live=False)
    p.end()
    assert img.pixelColor(300, 200).name() == "#1e2023"


def key(overlay, k):
    overlay.keyPressEvent(QKeyEvent(QEvent.Type.KeyPress, k,
                                    Qt.KeyboardModifier.NoModifier))


def test_w_opens_and_closes_the_board_in_the_chosen_style(A, overlay):
    key(overlay, Qt.Key.Key_W)
    assert overlay.canvas.board == "white" and overlay.isVisible()
    assert not overlay.passthrough
    key(overlay, Qt.Key.Key_W)                      # one key: closes again
    assert overlay.canvas.board is None
    overlay.settings.set("board_style", "black")
    key(overlay, Qt.Key.Key_W)
    assert overlay.canvas.board == "black"
    key(overlay, Qt.Key.Key_PageDown)
    assert overlay.canvas._page == 1
    key(overlay, Qt.Key.Key_Escape)
    assert overlay.canvas.board is None and not overlay.passthrough
    key(overlay, Qt.Key.Key_Escape)
    assert overlay.passthrough


def test_the_dock_comes_onto_the_board_and_goes_back(A, overlay):
    from PySide6.QtWidgets import QApplication
    dock = overlay.toolbar
    dock._collapse()                                # tucked away as a puck
    before = dock._anchor
    key(overlay, Qt.Key.Key_W)
    screen = QApplication.primaryScreen().availableGeometry()
    assert not dock._collapsed and dock.isVisible()
    assert screen.contains(dock.frameGeometry().center())
    assert dock.frameGeometry().bottom() > screen.center().y()   # bottom half
    key(overlay, Qt.Key.Key_W)
    assert dock._collapsed and dock._anchor == before


# ── presenter effects ────────────────────────────────────────────────────────

def test_spotlight_dims_everything_but_the_cursor(A):
    cv = make_canvas(A)
    cv.set_effect("spotlight", True)
    cv._fx_pos = QPointF(300, 200)
    img = QImage(600, 400, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(0)
    p = QPainter(img)
    cv.render_annotations(p)
    p.end()
    assert img.pixelColor(300, 200).alpha() == 0      # the hole
    assert img.pixelColor(20, 20).alpha() > 100       # dimmed
    cv.set_effect("spotlight", False)
    assert not cv._fx_timer.isActive()


def test_clicks_ripple_even_in_click_through(A, monkeypatch):
    cv = make_canvas(A)
    cv.set_effect("ripples", True)
    state = {"down": False}
    monkeypatch.setattr(cv, "_left_button_down", lambda: state["down"])
    cv._fx_tick()
    state["down"] = True
    cv._fx_tick()
    cv._fx_tick()                            # held: still one ripple
    assert len(cv._ripple_list) == 1
    state["down"] = False
    cv._fx_tick()
    state["down"] = True
    cv._fx_tick()
    assert len(cv._ripple_list) == 2


def test_effects_repaint_only_near_the_cursor(A, monkeypatch):
    cv = make_canvas(A)
    cv.set_effect("halo", True)
    areas = []
    monkeypatch.setattr(cv, "update", lambda *a: areas.append(a[0] if a else None))
    monkeypatch.setattr(A.QCursor, "pos", staticmethod(lambda: cv.mapToGlobal(
        __import__("PySide6.QtCore", fromlist=["QPoint"]).QPoint(100, 100))))
    cv._fx_tick()
    assert areas and all(a is not None and a.width() < 100 for a in areas)


def test_effects_keep_the_overlay_on_screen(A, overlay):
    assert not overlay.isVisible()           # empty, click-through
    overlay.set_effect("halo", True)
    assert overlay.isVisible()
    assert overlay.settings.get("fx_halo")
    overlay.set_effect("halo", False)
    assert not overlay.isVisible()


def test_fade_toggle_sticks(A, overlay):
    overlay.toolbar._set_pref("fade_ink", True)
    assert overlay.canvas.fade_ink and overlay.settings.get("fade_ink")
