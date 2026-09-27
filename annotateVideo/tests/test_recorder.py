"""Recorder compositing and the microphone list."""
import sys

import pytest
from PySide6.QtCore import QPointF, QRect
from PySide6.QtGui import QColor, QPixmap

import video_recorder as VR


class Sink:
    frame = b""

    def set_frame(self, b):
        self.frame = b


def recorder_for(overlay, region, frame_px):
    rec = VR.ScreenRecorder()
    rec._writer = Sink()
    rec._size = frame_px
    rec._scale = (frame_px[0] / region.width(), frame_px[1] / region.height())
    rec._origin = QPointF(region.x() - overlay.geometry().x(),
                          region.y() - overlay.geometry().y())
    rec._composite, rec._canvas, rec._overlay = True, overlay.canvas, overlay
    rec._cursor = False
    return rec


def pixel(rec, x, y):
    w = rec._size[0]
    i = (y * w + x) * 4
    b, g, r, _a = rec._writer.frame[i:i + 4]
    return (r, g, b)


def test_marks_land_right_at_125_percent(A, overlay):
    overlay.set_passthrough(False)                    # overlay on screen
    g = overlay.geometry()
    region = QRect(g.x(), g.y(), 320, 240)
    rec = recorder_for(overlay, region, (400, 300))
    overlay.canvas._commit(A.RedactShape(QPointF(100, 100), QPointF(110, 110)))
    grab = QPixmap(400, 300)
    grab.fill(QColor("white"))
    grab.setDevicePixelRatio(1.25)                    # what Qt does at 125 %
    rec._push(grab.toImage())
    assert pixel(rec, 130, 130) == (0, 0, 0)
    assert pixel(rec, 150, 150) == (255, 255, 255)   # double-scaled would be black


def test_eraser_is_not_a_black_streak_in_video(A, overlay):
    overlay.set_passthrough(False)
    g = overlay.geometry()
    region = QRect(g.x(), g.y(), 200, 100)
    rec = recorder_for(overlay, region, (200, 100))
    eraser = A.EraserShape(20)
    eraser.pts = [QPointF(20, 50), QPointF(180, 50)]
    overlay.canvas._commit(eraser)
    grab = QPixmap(200, 100)
    grab.fill(QColor("#3366cc"))
    rec._push(grab.toImage())
    assert pixel(rec, 100, 50) == (0x33, 0x66, 0xcc)   # was (0, 0, 0)


def test_no_arrow_cursor_over_the_laser(A, overlay, monkeypatch):
    overlay.set_passthrough(False)
    g = overlay.geometry()
    region = QRect(g.x(), g.y(), 200, 100)
    rec = recorder_for(overlay, region, (200, 100))
    rec._cursor = True
    drawn = []
    monkeypatch.setattr(rec, "_draw_cursor", lambda p: drawn.append(1))
    overlay.canvas.tool = "laser"
    overlay.canvas._laser_pos = QPointF(50, 50)
    grab = QPixmap(200, 100)
    grab.fill(QColor("white"))
    rec._push(grab.toImage())
    assert drawn == []
    overlay.canvas.tool = "pen"
    overlay.canvas._laser_pos = None
    rec._push(grab.toImage())
    assert drawn == [1]


NEW_LISTING = r'''
[dshow @ 000001f6b4b5c440] "Integrated Camera" (video)
[dshow @ 000001f6b4b5c440]   Alternative name "@device_pnp_\\?\usb#vid_04f2"
[dshow @ 000001f6b4b5c440] "Microphone Array (Realtek(R) Audio)" (audio)
[dshow @ 000001f6b4b5c440]   Alternative name "@device_cm_{33D9A762}\wave_{A1}"
[dshow @ 000001f6b4b5c440] "Elgato Cam Link 4K" (audio, video)
[dshow @ 000001f6b4b5c440] "OBS Virtual Camera" (none)
dummy: Immediate exit requested
'''

OLD_LISTING = r'''
[dshow @ 0000020f] DirectShow video devices (some may be both video and audio devices)
[dshow @ 0000020f]  "Integrated Camera"
[dshow @ 0000020f]     Alternative name "@device_pnp_\\?\usb"
[dshow @ 0000020f] DirectShow audio devices
[dshow @ 0000020f]  "Microphone (USB Audio)"
[dshow @ 0000020f]     Alternative name "@device_cm_{33D9A762}"
'''


def test_dshow_listing_ffmpeg5_and_newer():
    # The old parser returned [] here — on every current ffmpeg.
    assert VR.parse_dshow_devices(NEW_LISTING) == [
        "Microphone Array (Realtek(R) Audio)", "Elgato Cam Link 4K"]


def test_dshow_listing_ffmpeg4():
    assert VR.parse_dshow_devices(OLD_LISTING) == ["Microphone (USB Audio)"]


def test_mic_falls_back_to_first_device(monkeypatch):
    monkeypatch.setattr(VR, "IS_WIN", True)
    monkeypatch.setattr(VR, "list_audio_devices",
                        lambda ffmpeg=None, refresh=False: ["Mic A", "Mic B"])
    assert VR.resolve_audio_device("") == "Mic A"          # never "default"
    assert VR.resolve_audio_device("Mic B") == "Mic B"
    assert VR.resolve_audio_device("Unplugged mic") == "Mic A"
    monkeypatch.setattr(VR, "list_audio_devices", lambda ffmpeg=None, refresh=False: [])
    assert VR.resolve_audio_device("") is None


def test_mic_elsewhere_uses_the_system_default(monkeypatch):
    monkeypatch.setattr(VR, "IS_WIN", False)
    assert VR.resolve_audio_device("") == ""
