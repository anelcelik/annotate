"""Phase 3, part 3 (5.5): editing marks after drawing, pressed keys, hints."""
from PyQt6.QtCore import QEvent, QPointF, Qt
from PyQt6.QtGui import QColor, QKeyEvent, QMouseEvent
from PyQt6.QtWidgets import QPushButton


def make_canvas(A):
    cv = A.Canvas()
    cv.resize(600, 400)
    cv.tool = "select"
    return cv


def mouse(cv, kind, pos, shift=False):
    mods = Qt.KeyboardModifier.ShiftModifier if shift else Qt.KeyboardModifier.NoModifier
    held = Qt.MouseButton.LeftButton if kind != "release" else Qt.MouseButton.NoButton
    ev = QMouseEvent({"press": QEvent.Type.MouseButtonPress,
                      "move": QEvent.Type.MouseMove,
                      "release": QEvent.Type.MouseButtonRelease}[kind],
                     QPointF(pos), QPointF(pos), Qt.MouseButton.LeftButton, held, mods)
    {"press": cv.mousePressEvent, "move": cv.mouseMoveEvent,
     "release": cv.mouseReleaseEvent}[kind](ev)


def drag(cv, a, b, shift=False):
    mouse(cv, "press", a, shift)
    mouse(cv, "move", b, shift)
    mouse(cv, "release", b, shift)


def arrow(A, y=100):
    return A.ArrowShape(QPointF(50, y), QPointF(250, y), "#FF3B3B", 4)


# ── editing ───────────────────────────────────────────────────────────────────

def test_drag_a_handle_to_reshape_undoably(A):
    cv = make_canvas(A)
    a = arrow(A)
    cv._commit(a)
    mouse(cv, "press", QPointF(150, 100)); mouse(cv, "release", QPointF(150, 100))
    assert cv._selection == [a]
    drag(cv, QPointF(250, 100), QPointF(300, 180))       # the tip handle
    assert (a.p2.x(), a.p2.y()) == (300, 180) and (a.p1.x(), a.p1.y()) == (50, 100)
    cv.undo()
    assert (a.p2.x(), a.p2.y()) == (250, 100)


def test_box_corner_resizes_against_the_opposite_corner(A):
    cv = make_canvas(A)
    r = A.RectShape(QPointF(100, 100), QPointF(200, 200), "#000", 3)
    cv._commit(r)
    cv._set_selection([r])
    drag(cv, QPointF(200, 200), QPointF(260, 240))       # bottom-right
    box = A._norm(r.p1, r.p2)
    assert (box.left(), box.top(), box.right(), box.bottom()) == (100, 100, 260, 240)


def test_rubber_band_and_shift_click_select_several(A):
    cv = make_canvas(A)
    a, b, c = arrow(A, 50), arrow(A, 120), arrow(A, 300)
    for s in (a, b, c):
        cv._commit(s)
    drag(cv, QPointF(20, 20), QPointF(400, 150))          # frames a and b
    assert set(cv._selection) == {a, b}
    mouse(cv, "press", QPointF(150, 300), shift=True)     # add c
    mouse(cv, "release", QPointF(150, 300), shift=True)
    assert set(cv._selection) == {a, b, c}


def test_move_and_delete_several_at_once(A):
    cv = make_canvas(A)
    a, b = arrow(A, 50), arrow(A, 120)
    for s in (a, b):
        cv._commit(s)
    cv.select_all()
    drag(cv, QPointF(150, 50), QPointF(170, 80))
    assert (a.p1.y(), b.p1.y()) == (80, 150)
    cv.undo()
    assert (a.p1.y(), b.p1.y()) == (50, 120)
    cv.select_all()
    cv.delete_selected()
    assert cv._shapes == []
    cv.undo()
    assert cv._shapes == [a, b]


def test_restyle_the_selection_as_one_undo_step(A):
    cv = make_canvas(A)
    a = arrow(A)
    cv._commit(a)
    cv._set_selection([a])
    for w in (6, 9, 12):                                   # a slider drag
        cv.restyle_selected(width=w)
    cv.restyle_selected(color="#0A84FF")
    assert a.width == 12 and QColor(a.color).name() == "#0a84ff"
    cv.undo()                                              # colour + width together
    assert a.width == 4 and QColor(a.color).name() == "#ff3b3b"


def test_copy_paste_duplicate(A):
    cv = make_canvas(A)
    a = arrow(A)
    cv._commit(a)
    cv._set_selection([a])
    assert cv.copy_selection() == 1 and cv.paste() == 1
    twin = cv._shapes[-1]
    assert twin is not a and twin.p1.x() == a.p1.x() + 20
    twin.move(5, 5)
    assert a.p1.x() == 50                                  # independent copy
    assert cv.duplicate() == 1 and len(cv._shapes) == 3
    cv.undo()
    assert len(cv._shapes) == 2


def test_keyboard_editing(A, overlay):
    cv = overlay.canvas
    a = arrow(A)
    cv._commit(a)

    def key(k, mods=Qt.KeyboardModifier.NoModifier):
        overlay.keyPressEvent(QKeyEvent(QEvent.Type.KeyPress, k, mods))
    key(Qt.Key.Key_A, Qt.KeyboardModifier.ControlModifier)
    assert cv.tool == "select" and cv._selection == [a]
    key(Qt.Key.Key_Right)
    key(Qt.Key.Key_Down, Qt.KeyboardModifier.ShiftModifier)
    assert (a.p1.x(), a.p1.y()) == (51, 110)
    key(Qt.Key.Key_D, Qt.KeyboardModifier.ControlModifier)
    assert len(cv._shapes) == 2


def test_dock_shows_and_edits_the_selected_style(A, overlay):
    cv, dock = overlay.canvas, overlay.toolbar
    a = arrow(A)
    cv._commit(a)
    dock._activate("select")
    cv._set_selection([a])
    assert dock._editing and cv.pen_width == 4
    dock._set_color("#32D74B")
    assert QColor(a.color).name() == "#32d74b"
    cv._set_selection([])
    assert not dock._editing


# ── pressed keys ──────────────────────────────────────────────────────────────

def state(*vks):
    return lambda vk: vk in vks


def test_shortcuts_and_special_keys_are_shown(A):
    down = set()
    assert A.keys_pressed(down, state(0x11, 0x53)) == "Ctrl + S"
    assert A.keys_pressed(down, state(0x11, 0x53)) == ""          # held: once
    assert A.keys_pressed(set(), state(0x11, 0x10, 0x5A)) == "Ctrl + Shift + Z"
    assert A.keys_pressed(set(), state(0x0D)) == "Enter"
    assert A.keys_pressed(set(), state(0x74)) == "F5"


def test_plain_typing_is_never_shown(A):
    assert A.keys_pressed(set(), state(0x50)) == ""                # "p"
    assert A.keys_pressed(set(), state(0x10, 0x50)) == ""          # "P"
    assert A.keys_pressed(set(), state(0x31)) == ""                # "1"
    assert A.keys_pressed(set(), state(0x20)) == ""                # space


def test_pressed_keys_setting_turns_the_effect_on(A, overlay, monkeypatch):
    monkeypatch.setattr(A, "keys_pressed", lambda down, key_state=None: "Ctrl + K")
    overlay.set_effect("keys", True)
    assert overlay.canvas.keys and overlay.settings.get("fx_keys") and overlay.isVisible()
    overlay.canvas._fx_tick()
    assert overlay.canvas._key_text == "Ctrl + K"
    overlay.set_effect("keys", False)


# ── hints ─────────────────────────────────────────────────────────────────────

def test_hints_show_on_the_dock_and_can_be_switched_off(A, overlay, settings):
    assert overlay.toolbar.testAttribute(Qt.WidgetAttribute.WA_AlwaysShowToolTips)
    tip = overlay.toolbar._tool_btns["arrow"].toolTip()
    assert "Arrow" in tip and "Shift" in tip                      # says what it does
    switch = A.HintSwitch(settings)
    ev = QEvent(QEvent.Type.ToolTip)
    assert not switch.eventFilter(QPushButton(), ev)
    settings.set("show_hints", False)
    assert switch.eventFilter(QPushButton(), ev)                   # swallowed
