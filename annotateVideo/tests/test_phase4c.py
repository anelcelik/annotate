"""Phase 4, part 3 (5.9): the PC's own sound, the webcam bubble."""
import math
import os
import shutil
import struct
import subprocess
import time
import wave

import pytest
from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QImage, QWheelEvent
from PySide6.QtTest import QTest

FFMPEG = os.environ.get("SCREEN_ANNOTATOR_FFMPEG") or shutil.which("ffmpeg")
needs_ffmpeg = pytest.mark.skipif(not FFMPEG, reason="no ffmpeg")

LISTING = '''
[dshow @ 000001] "Integrated Camera" (video)
[dshow @ 000001]   Alternative name "@device_pnp_\\\\?\\usb#vid"
[dshow @ 000001] "OBS Virtual Camera" (video)
[dshow @ 000001] "Microphone Array (Realtek)" (audio)
'''


def test_cameras_and_microphones_are_told_apart(A):
    import video_recorder as vr
    assert vr.parse_dshow_devices(LISTING, "video") == ["Integrated Camera",
                                                        "OBS Virtual Camera"]
    assert vr.parse_dshow_devices(LISTING) == ["Microphone Array (Realtek)"]


def test_camera_command_gives_square_frames(A):
    import video_recorder as vr
    cmd = vr.camera_command("ffmpeg", "Integrated Camera", 480)
    assert "crop=480:480" in " ".join(cmd) and cmd[-3:] == ["-pix_fmt", "bgra", "pipe:1"]


# ── the PC's sound ────────────────────────────────────────────────────────────

class Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


def fake_source(rate=48000, channels=2):
    def opener(callback):
        return lambda: None
    return rate, channels, opener


def tone(frames, channels=2):
    return b"".join(struct.pack("<h", int(8000 * math.sin(i / 8))) * channels
                    for i in range(frames))


def test_silence_is_filled_in_and_pauses_are_left_out(A, tmp_path):
    import video_recorder as vr
    clock = Clock()
    cap = vr.SystemAudioCapture(str(tmp_path / "pc.wav"), fake_source(), clock)
    assert cap.start()
    clock.t = 0.5
    cap.feed(tone(4800))                         # 0.1 s of sound, ending at 0.5 s
    clock.t = 1.0
    cap.pause(True)
    clock.t = 3.0                                # two seconds paused
    cap.pause(False)
    clock.t = 3.5
    cap.stop()
    with wave.open(str(tmp_path / "pc.wav")) as w:
        assert w.getnframes() == 72000           # 1.5 s: 3.5 minus the pause
        frames = w.readframes(w.getnframes())
    sample = lambda i: struct.unpack_from("<h", frames, i * 4)[0]
    assert sample(1000) == 0                     # silence before the sound…
    assert any(sample(i) for i in range(19200, 24000))    # …the sound at 0.4–0.5 s
    assert sample(30000) == 0


def test_no_playback_device_means_no_capture(A, tmp_path):
    import video_recorder as vr
    cap = vr.SystemAudioCapture(str(tmp_path / "pc.wav"), source=None)
    cap._source = None
    assert not cap.start() and cap.error


def test_mix_command(A):
    import video_recorder as vr
    cmd = " ".join(vr.mix_audio_command("ffmpeg", "v.mp4", "pc.wav", "o.mp4", offset=0.25))
    assert "adelay=250|250" in cmd and "-c:v copy" in cmd and "amix" not in cmd
    cmd = " ".join(vr.mix_audio_command("ffmpeg", "v.mp4", "pc.wav", "o.mp4",
                                        offset=-0.1, has_mic=True))
    assert "atrim=start=0.100" in cmd and "amix=inputs=2" in cmd


def make_video(path, seconds=2):
    subprocess.run([FFMPEG, "-loglevel", "error", "-y", "-f", "lavfi", "-i",
                    f"testsrc=size=320x240:rate=15:duration={seconds}",
                    "-pix_fmt", "yuv420p", str(path)], check=True, timeout=60)


def make_wav(path, seconds=2, rate=48000):
    with wave.open(str(path), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(tone(int(seconds * rate)))


@needs_ffmpeg
def test_mixing_adds_a_sound_track(A, tmp_path, monkeypatch):
    import video_recorder as vr
    monkeypatch.setattr(vr, "find_ffmpeg", lambda: FFMPEG)
    video, pc, out = tmp_path / "v.mp4", tmp_path / "pc.wav", tmp_path / "o.mp4"
    make_video(video)
    make_wav(pc)
    assert not vr.has_audio_stream(str(video))
    subprocess.run(vr.mix_audio_command(FFMPEG, str(video), str(pc), str(out), offset=0.1),
                   check=True, capture_output=True, timeout=60)
    assert vr.has_audio_stream(str(out))
    assert vr.probe_duration(str(out)) == pytest.approx(2.0, abs=0.2)


@needs_ffmpeg
def test_a_recording_gets_the_pcs_sound_mixed_in(A, overlay, tmp_path, monkeypatch):
    import video_recorder as vr
    monkeypatch.setattr(vr, "find_ffmpeg", lambda: FFMPEG)
    monkeypatch.setattr(A, "find_ffmpeg", lambda: FFMPEG)
    monkeypatch.setattr(A, "system_audio_available", lambda: True)
    rc = overlay.recording
    overlay.settings.set("rec_sys_audio", True)
    monkeypatch.setattr(rc, "_make_sys_audio", lambda path: vr.SystemAudioCapture(
        str(tmp_path / "rec.pc-sound.wav"), fake_source()))
    video = tmp_path / "rec.mp4"
    make_video(video)
    rc._on_started(str(video))
    assert rc._sys_audio is not None
    QTest.qWait(600)                              # silence fills in by the clock
    rc._on_finishing()
    rc._on_finished(str(video))
    deadline = time.monotonic() + 30
    while rc._mixer is not None and time.monotonic() < deadline:
        QTest.qWait(50)
    assert vr.has_audio_stream(str(video))
    assert not (tmp_path / "rec.pc-sound.wav").exists()
    assert not (tmp_path / "rec.mixing.mp4").exists()
    rc._result_bar.close()


# ── webcam bubble ─────────────────────────────────────────────────────────────

@needs_ffmpeg
def test_webcam_bubble_shows_the_camera_in_a_circle(A, settings):
    cmd = [FFMPEG, "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i",
           "color=c=0x32D74B:size=640x480:rate=30",
           "-vf", "scale=480:480:force_original_aspect_ratio=increase,crop=480:480",
           "-f", "rawvideo", "-pix_fmt", "bgra", "pipe:1"]
    bubble = A.WebcamBubble(settings, command=cmd)
    assert bubble.start()
    deadline = time.monotonic() + 15
    while bubble._img is None and time.monotonic() < deadline:
        QTest.qWait(30)
    assert bubble._img is not None
    img = bubble.grab().toImage()
    mid = img.pixelColor(img.width() // 2, img.height() // 2)
    assert mid.green() > 180 and mid.red() < 100          # the camera's picture
    assert img.pixelColor(2, 2).alpha() == 0               # round, not square
    before = bubble.width()
    bubble.wheelEvent(QWheelEvent(QPointF(10, 10), QPointF(10, 10), QPoint(), QPoint(0, 120),
                                  Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier,
                                  Qt.ScrollPhase.NoScrollPhase, False))
    assert bubble.width() == before + 20 and settings.get("cam_size") == before + 20
    closed = []
    bubble.closed.connect(lambda: closed.append(True))
    bubble.close_bubble()
    assert closed and settings.get("cam_pos") == [bubble.x(), bubble.y()]


def test_no_camera_says_so(A, overlay, monkeypatch):
    monkeypatch.setattr(A, "list_video_devices", lambda: [])
    overlay.toggle_webcam()
    assert overlay._webcam is None


@pytest.mark.skipif(not __import__("sys").platform.startswith("win"),
                    reason="WASAPI loopback is Windows-only")
def test_system_audio_can_be_opened_on_windows(A):
    import video_recorder as vr
    assert vr.system_audio_available()
    src = vr._wasapi_loopback()               # None on a machine with no speakers
    if src is None:
        pytest.skip("no playback device on this machine")
    rate, channels, opener = src
    assert rate >= 8000 and channels in (1, 2)
    close = opener(lambda data: None)
    close()
