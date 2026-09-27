"""Phase 4, part 2 (5.8): pen pressure, the pen's eraser end, trimming a
recording, recording one window."""
import shutil
import time

import pytest
from PySide6.QtCore import QEvent, QPoint, QPointF, QRect, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPointingDevice, QTabletEvent
from PySide6.QtTest import QTest

from test_phase3c import make_canvas, mouse


def render(shape, w=400, h=200):
    img = QImage(w, h, QImage.Format.Format_ARGB32)
    img.fill(0)
    p = QPainter(img)
    shape.draw(p)
    p.end()
    return img


def thickness(img, x):
    return sum(1 for y in range(img.height()) if img.pixelColor(x, y).alpha() > 0)


# ── pen pressure ──────────────────────────────────────────────────────────────

def test_pressure_changes_the_width(A):
    s = A.PenShape("#FF3B3B", 20)
    for i in range(31):
        s.add(QPointF(50 + i * 10, 100), 0.1 if i < 15 else 1.0)
    img = render(s)
    assert thickness(img, 100) < thickness(img, 300) - 8


def test_a_mouse_stroke_keeps_one_width(A):
    s = A.PenShape("#FF3B3B", 8)
    s.add(QPointF(10, 10))
    s.add(QPointF(50, 10))
    assert s.pressures is None


def test_see_through_pressure_stroke_has_no_beads(A):
    s = A.PenShape("#80FF3B3B", 14)
    for i in range(60):
        s.add(QPointF(50 + i * 5, 100), 0.8)
    img = render(s)
    alphas = {img.pixelColor(x, 100).alpha() for x in range(80, 320, 3)}
    assert max(alphas) - min(alphas) <= 2


_DEVICES = {}      # an event only points at its device: keep them alive


def tablet(kind, pos, pressure, eraser=False):
    if eraser not in _DEVICES:
        _DEVICES[eraser] = QPointingDevice(
            "pen", 1 + eraser, QPointingDevice.DeviceType.Stylus,
            QPointingDevice.PointerType.Eraser if eraser else QPointingDevice.PointerType.Pen,
            QPointingDevice.Capability.Position | QPointingDevice.Capability.Pressure,
            1, 2)
    dev = _DEVICES[eraser]
    buttons = Qt.MouseButton.NoButton if kind == QEvent.Type.TabletRelease \
        else Qt.MouseButton.LeftButton
    return QTabletEvent(kind, dev, QPointF(pos), QPointF(pos), pressure, 0, 0, 0, 0, 0,
                        Qt.KeyboardModifier.NoModifier, Qt.MouseButton.LeftButton, buttons)


def test_a_pen_stroke_records_pressure(A):
    cv = make_canvas(A)
    cv.tool = "pen"
    for kind, x, pr in ((QEvent.Type.TabletPress, 50, 0.3),
                        (QEvent.Type.TabletMove, 90, 0.9)):
        cv.tabletEvent(tablet(kind, QPointF(x, 50), pr))
        mouse(cv, "press" if kind == QEvent.Type.TabletPress else "move", QPointF(x, 50))
    mouse(cv, "release", QPointF(90, 50))
    stroke = cv._shapes[-1]
    assert stroke.pressures == pytest.approx([0.3, 0.9])


def test_the_pens_eraser_end_erases_then_hands_the_tool_back(A):
    cv = make_canvas(A)
    cv.tool = "arrow"
    cv.tabletEvent(tablet(QEvent.Type.TabletPress, QPointF(10, 10), 0.5, eraser=True))
    assert cv.tool == "eraser"
    cv.tabletEvent(tablet(QEvent.Type.TabletRelease, QPointF(10, 10), 0.0, eraser=True))
    QTest.qWait(20)
    assert cv.tool == "arrow"


# ── trim ──────────────────────────────────────────────────────────────────────

def test_trim_command_reencodes_the_kept_part(A):
    import video_recorder as vr
    cmd = vr.trim_command("ffmpeg", "in.mp4", "out.mp4", 2.5, 10.0)
    assert cmd[cmd.index("-ss") + 1] == "2.500" and cmd[cmd.index("-t") + 1] == "7.500"
    assert cmd.index("-ss") < cmd.index("-i") and "libx264" in cmd
    with pytest.raises(vr.RecorderError):
        vr.trim_command("ffmpeg", "in.mp4", "out.mp4", 5, 5)


def test_range_bar_keeps_its_handles_apart(A):
    bar = A.RangeBar(10.0)
    bar.resize(420, 36)
    bar.set_range(9.9, 10.0, "start")
    assert bar.start == pytest.approx(9.5)
    bar.set_range(2.0, 1.0, "end")
    assert bar.end == pytest.approx(2.5)
    from PySide6.QtGui import QKeyEvent
    bar.keyPressEvent(QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Right,
                                Qt.KeyboardModifier.ShiftModifier))
    assert bar.end == pytest.approx(3.5)


@pytest.fixture
def clip(tmp_path):
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        pytest.skip("no ffmpeg")
    import subprocess
    path = tmp_path / "rec.mp4"
    subprocess.run([ffmpeg, "-loglevel", "error", "-f", "lavfi", "-i",
                    "testsrc=size=320x240:rate=15:duration=4", "-pix_fmt", "yuv420p",
                    str(path)], check=True, timeout=60)
    return str(path)


def test_trim_a_real_recording(A, clip, monkeypatch):
    import video_recorder as vr
    monkeypatch.setattr(vr, "find_ffmpeg", lambda: shutil.which("ffmpeg"))
    assert vr.frame_at(clip, 1.0)[:4] == b"\x89PNG"
    dlg = A.TrimDialog(clip)
    dlg.range.set_range(1.0, 4.0, "start")
    dlg.range.set_range(1.0, 2.5, "end")
    dlg._start()
    deadline = time.monotonic() + 30
    while not dlg._out and time.monotonic() < deadline:
        QTest.qWait(50)
    assert dlg._out.endswith("rec-trimmed.mp4")
    assert vr.probe_duration(dlg._out) == pytest.approx(1.5, abs=0.2)
    dlg.reject()


# ── one window ────────────────────────────────────────────────────────────────

class FakeScreen:
    def __init__(self, x, y, w, h, dpr):
        self._g, self._dpr = QRect(x, y, w, h), dpr

    def geometry(self):
        return self._g

    def devicePixelRatio(self):
        return self._dpr


def test_physical_pixels_map_to_qt_per_screen(A, monkeypatch):
    import video_recorder as vr

    class App:
        @staticmethod
        def screens():                # a 150 % laptop, a 100 % monitor to its right
            return [FakeScreen(0, 0, 1280, 720, 1.5), FakeScreen(1920, 0, 1920, 1080, 1.0)]
    monkeypatch.setattr(vr, "QApplication", App)
    assert vr.native_to_logical(QRect(300, 150, 600, 300)) == QRect(200, 100, 400, 200)
    assert vr.native_to_logical(QRect(2000, 100, 800, 600)) == QRect(2000, 100, 800, 600)


def test_window_picker_takes_the_front_window(A, monkeypatch):
    fronted = []
    monkeypatch.setattr(A, "bring_to_front", fronted.append)
    wins = [(11, "Front", QRect(100, 100, 300, 200)),
            (22, "Behind", QRect(50, 50, 600, 400))]
    picker = A.WindowPicker(wins)
    assert picker.window_at(QPoint(150, 150))[1] == "Front"
    assert picker.window_at(QPoint(60, 60))[1] == "Behind"
    got = []
    picker.chosen.connect(got.append)
    picker._hover = picker.window_at(QPoint(150, 150))
    picker._finish(picker._hover)
    QTest.qWait(300)
    assert fronted == [11] and got == [QRect(100, 100, 300, 200)]


def test_record_one_window_counts_in_on_its_area(A, overlay, monkeypatch):
    rc = overlay.recording
    monkeypatch.setattr(A, "find_ffmpeg", lambda: "ffmpeg")
    monkeypatch.setattr(A, "list_windows", lambda: [(5, "Editor", QRect(10, 20, 640, 480))])
    monkeypatch.setattr(A, "bring_to_front", lambda h: None)
    counted = []
    monkeypatch.setattr(rc, "_count_in", lambda cfg, r: counted.append(r))
    overlay.settings.set("rec_area", "window")
    rc.start()
    assert isinstance(rc._picker, A.WindowPicker)
    rc._picker._finish(rc._picker._windows[0])
    QTest.qWait(300)
    assert counted == [QRect(10, 20, 640, 480)]
