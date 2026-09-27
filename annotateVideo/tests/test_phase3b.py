"""Phase 3, part 2 (5.4): recording on the GPU, zoom."""
import os
import subprocess
import sys

import pytest
from PyQt6.QtCore import QEvent, QPointF, QRect, QRectF, Qt
from PyQt6.QtGui import QColor, QImage, QKeyEvent, QPainter, QPixmap

import video_recorder as VR


# ── GPU recording ─────────────────────────────────────────────────────────────

def test_gpu_command_whole_screen():
    cmd = VR.gpu_record_command("ffmpeg", "out.mp4", 30, size=(1920, 1080))
    chain = cmd[cmd.index("-filter_complex") + 1]
    assert chain.startswith("ddagrab=output_idx=0:framerate=30:draw_mouse=1")
    assert "scale_d3d11=format=nv12" in chain and "video_size" not in chain
    assert "hwdownload" not in chain                 # the texture stays on the GPU
    assert cmd[cmd.index("-c:v") + 1] == "h264_mf"
    assert cmd[cmd.index("-hw_encoding") + 1] == "1"
    assert cmd[-1] == "out.mp4" and "-map" in cmd


def test_gpu_command_area_mic_and_software_encoder():
    cmd = VR.gpu_record_command("ffmpeg", "o.mp4", 60, size=(801, 601), crop=(40, 20),
                                cursor=False, audio_device="Mic (USB)", hardware=False)
    chain = cmd[cmd.index("-filter_complex") + 1]
    assert ":video_size=800x600:offset_x=40:offset_y=20" in chain   # even for H.264
    assert "draw_mouse=0" in chain and chain.endswith("hwdownload,format=nv12[v]")
    assert "-hw_encoding" not in cmd
    assert cmd[cmd.index("-i") + 1] == "audio=Mic (USB)" and "0:a" in cmd


def test_gpu_bitrate_scales_with_size_and_quality():
    assert VR.gpu_bitrate(3840, 2160, 30, "balanced") > VR.gpu_bitrate(1920, 1080, 30, "balanced")
    assert VR.gpu_bitrate(1920, 1080, 30, "high") > VR.gpu_bitrate(1920, 1080, 30, "small")
    assert VR.gpu_bitrate(100, 100, 15, "small") == 1_000_000       # a floor


def test_gpu_only_for_one_screen(monkeypatch):
    monkeypatch.setattr(VR, "IS_WIN", True)
    monkeypatch.setattr(VR, "find_ffmpeg", lambda refresh=False: "ffmpeg.exe")
    assert VR.gpu_recording_possible(1)
    assert not VR.gpu_recording_possible(2)


def test_falls_back_to_cpu_when_the_gpu_path_gives_up(A, overlay, monkeypatch):
    rc = overlay.recording
    monkeypatch.setattr(A, "gpu_recording_possible", lambda n: True)
    overlay.settings.set("rec_hardware", True)
    started = []
    monkeypatch.setattr(rc._gpu, "start", lambda *a: started.append("gpu") or True)
    monkeypatch.setattr(rc._cpu, "start", lambda *a, **k: started.append("cpu") or True)
    assert rc._start_on_gpu(rc.config(), None)
    assert rc.recorder is rc._gpu
    rc._gpu_fell_back("no hardware encoder")
    assert rc.recorder is rc._cpu and started == ["gpu", "cpu"]
    assert not rc.gpu_eligible()                     # not again this session


def test_gpu_recording_is_opt_in_for_now(A, overlay, monkeypatch):
    monkeypatch.setattr(A, "gpu_recording_possible", lambda n: True)
    assert not overlay.recording.gpu_eligible()          # off by default (beta)
    overlay.settings.set("rec_hardware", True)
    assert overlay.recording.gpu_eligible()


@pytest.mark.skipif(sys.platform != "win32", reason="Desktop Duplication is Windows-only")
def test_gpu_command_records_on_real_windows(tmp_path):
    """Runs the real command for a second. Hardware encoding first; a runner
    without a GPU falls back to Media Foundation's software encoder, which
    still checks the capture + conversion chain. Skips if the machine has no
    desktop to duplicate."""
    ffmpeg = VR.find_ffmpeg()
    if not ffmpeg:
        pytest.skip("no ffmpeg")
    errors = []
    for hardware in (True, False):
        out = tmp_path / f"gpu-{hardware}.mp4"
        cmd = VR.gpu_record_command(ffmpeg, str(out), 15, size=(640, 360),
                                    crop=(0, 0), cursor=True, hardware=hardware)
        cmd = cmd[:-1] + ["-t", "1", str(out)]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        if r.returncode == 0 and out.exists() and out.stat().st_size > 0:
            assert VR.probe_duration(str(out)) > 0.5
            return
        errors.append(f"hardware={hardware}: {r.stderr.strip()[-900:]}")
    # Which half fails here — the capture, or the encoder?
    probes = {
        "capture only": [ffmpeg, "-hide_banner", "-loglevel", "error", "-filter_complex",
                         "ddagrab=output_idx=0:framerate=5,hwdownload,format=bgra",
                         "-t", "1", "-f", "null", "-"],
        "encoder only": [ffmpeg, "-hide_banner", "-loglevel", "error", "-f", "lavfi",
                         "-i", "testsrc2=size=640x360:rate=15", "-t", "1",
                         "-pix_fmt", "nv12", "-c:v", "h264_mf", "-f", "null", "-"],
    }
    for name, probe in probes.items():
        r = subprocess.run(probe, capture_output=True, text=True, timeout=60)
        errors.append(f"{name}: rc={r.returncode} {r.stderr.strip()[-300:]}")
    pytest.skip("GPU recording can't run on this machine:\n" + "\n".join(errors))


# ── zoom ──────────────────────────────────────────────────────────────────────

def zoomed_canvas(A):
    cv = A.Canvas()
    cv.resize(400, 200)
    still = QPixmap(800, 400)                         # a 2x still
    still.fill(QColor("white"))
    p = QPainter(still)
    p.fillRect(760, 360, 40, 40, QColor("#ff0000"))   # red in the corner
    p.end()
    cv.start_zoom(still, QRectF(0, 0, 400, 200), QPointF(200, 100))
    return cv


def test_magnifier_is_centred_on_the_cursor(A):
    cv = zoomed_canvas(A)
    src = cv.zoom_source()                                    # 4x, 2x still
    side = 2 * cv.LOUPE_R / 4 * 2
    assert (src.width(), src.center().x(), src.center().y()) == (side, 400, 200)


def test_magnifier_sits_beside_the_cursor_and_flips_at_edges(A):
    cv = zoomed_canvas(A)
    cv.zoom_rect = QRectF(0, 0, 2000, 1000)
    cv._zoom_cursor = QPointF(100, 100)
    box = cv.loupe_rect()
    assert box.left() > 100 and box.top() > 100               # below-right
    cv._zoom_cursor = QPointF(1950, 950)
    box = cv.loupe_rect()
    assert box.right() < 1950 and box.bottom() < 950          # flipped


def test_magnifier_paints_the_magnified_still_over_the_marks(A):
    cv = zoomed_canvas(A)
    cv._zoom_cursor = QPointF(390, 190)                       # over the red
    img = QImage(400, 200, QImage.Format.Format_ARGB32)
    img.fill(0)
    p = QPainter(img)
    cv.paint_marks(p, 400, 200, selection=False, live=False)
    p.end()
    box = cv.loupe_rect()
    inside = img.pixelColor(int(box.center().x() + 20), int(box.center().y() + 20))
    assert inside.red() > 200 and inside.green() < 80         # red, magnified
    assert img.pixelColor(20, 20).alpha() == 0                # rest untouched


def test_wheel_zooms_within_limits(A):
    cv = zoomed_canvas(A)
    from PyQt6.QtGui import QWheelEvent
    from PyQt6.QtCore import QPoint

    def wheel(dy):
        cv.wheelEvent(QWheelEvent(QPointF(10, 10), QPointF(10, 10), QPoint(0, 0),
                                  QPoint(0, dy), Qt.MouseButton.NoButton,
                                  Qt.KeyboardModifier.NoModifier,
                                  Qt.ScrollPhase.NoScrollPhase, False))
    for _ in range(20):
        wheel(120)
    assert cv.zoom_factor == cv.ZOOM_MAX
    for _ in range(20):
        wheel(-120)
    assert cv.zoom_factor == cv.ZOOM_MIN


def test_m_zooms_and_esc_leaves(A, overlay, monkeypatch):
    still = QPixmap(100, 100)
    monkeypatch.setattr(overlay.canvas, "capture_annotated",
                        lambda rect=None, marks=True: still)
    overlay.keyPressEvent(QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_M,
                                    Qt.KeyboardModifier.NoModifier))
    assert overlay.canvas.zoom_pix is still and overlay.isVisible()
    overlay.keyPressEvent(QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Escape,
                                    Qt.KeyboardModifier.NoModifier))
    assert overlay.canvas.zoom_pix is None
    assert not overlay.passthrough                              # zoom left, not mode


def test_zoom_has_a_settable_shortcut(A, settings):
    assert "zoom_hotkey" in A.HOTKEY_SETTINGS
    assert settings.get("zoom_hotkey") == ""                    # none by default
