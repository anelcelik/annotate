"""6.0: GPU recording on any screen and with pause."""
import os
import shutil
import time

import pytest
from PySide6.QtCore import QRect
from PySide6.QtTest import QTest

import video_recorder as VR

FFMPEG = os.environ.get("SCREEN_ANNOTATOR_FFMPEG") or shutil.which("ffmpeg")


class FakeScreen:
    def __init__(self, name, x, y, w, h, dpr):
        self._n, self._g, self._dpr = name, QRect(x, y, w, h), dpr

    def name(self):
        return self._n

    def geometry(self):
        return self._g

    def devicePixelRatio(self):
        return self._dpr


def two_screens(monkeypatch):
    class App:
        @staticmethod
        def screens():      # a 150 % laptop on the iGPU, a monitor on the dGPU
            return [FakeScreen(r"\\.\DISPLAY1", 0, 0, 1280, 720, 1.5),
                    FakeScreen(r"\\.\DISPLAY2", 1920, 0, 2560, 1440, 1.0)]
    monkeypatch.setattr(VR, "QApplication", App)
    return [{"name": r"\\.\DISPLAY1", "adapter": 0, "output": 0,
             "rect": QRect(0, 0, 1920, 1080)},
            {"name": r"\\.\DISPLAY2", "adapter": 1, "output": 0,
             "rect": QRect(1920, 0, 2560, 1440)}]


def test_gpu_target_finds_the_right_screen_and_chip(monkeypatch):
    outs = two_screens(monkeypatch)
    assert VR.gpu_target(QRect(1920, 0, 2560, 1440), outs) == (1, 0, (2560, 1440), None)
    assert VR.gpu_target(QRect(100, 50, 400, 300), outs) == (0, 0, (600, 450), (150, 74))
    assert VR.gpu_target(QRect(1000, 0, 1500, 500), outs) is None      # spans both
    assert VR.gpu_target(None, outs) is None                           # "all monitors"


def test_gpu_target_matches_by_position_when_names_differ(monkeypatch):
    outs = two_screens(monkeypatch)
    for o in outs:
        o["name"] = "?"
    assert VR.gpu_target(QRect(1920, 0, 2560, 1440), outs)[:2] == (1, 0)


@pytest.mark.skipif(__import__("sys").platform != "win32", reason="DXGI is Windows-only")
def test_dxgi_lists_the_screens_on_windows():
    outs = VR.dxgi_outputs()
    assert isinstance(outs, list)
    for o in outs:
        assert o["name"].startswith("\\\\.\\") and o["rect"].width() > 0


def test_second_chip_gets_its_own_device():
    cmd = VR.gpu_record_command("ffmpeg", "o.mp4", 30, size=(2560, 1440), adapter=1, output=2)
    assert cmd[cmd.index("-init_hw_device") + 1] == "d3d11va=dda:1"
    assert "ddagrab=output_idx=2" in " ".join(cmd)
    plain = VR.gpu_record_command("ffmpeg", "o.mp4", 30, size=(1920, 1080))
    assert "-init_hw_device" not in plain


@pytest.mark.skipif(not FFMPEG, reason="no ffmpeg")
def test_pause_makes_pieces_that_are_joined(qapp, tmp_path, monkeypatch):
    monkeypatch.setattr(VR, "find_ffmpeg", lambda refresh=False: FFMPEG)
    rec = VR.HardwareRecorder()
    # ffmpeg standing in for Desktop Duplication: a live test picture.
    monkeypatch.setattr(rec, "_command", lambda path: [
        FFMPEG, "-hide_banner", "-loglevel", "error", "-y", "-re", "-f", "lavfi",
        "-i", "testsrc=size=160x120:rate=10", "-c:v", "libx264",
        "-pix_fmt", "yuv420p", path])
    done = []
    rec.finished.connect(done.append)
    rec.failed.connect(lambda m: done.append("FAILED " + m))
    cfg = VR.RecordConfig(out_dir=str(tmp_path))
    assert rec.start(cfg, (0, 0, (160, 120), None), None)
    QTest.qWait(1200)
    rec.pause(True)
    assert rec.paused
    QTest.qWait(800)                                # not recorded
    rec.pause(False)
    QTest.qWait(1200)
    assert 2.0 < rec.elapsed() < 3.0
    rec.stop()
    deadline = time.monotonic() + 30
    while not done and time.monotonic() < deadline:
        QTest.qWait(50)
    assert done and not done[0].startswith("FAILED"), done
    # Both pieces, back to back. (The stand-in source runs a little past each
    # "q"; the length depends on it, not on the joining.)
    assert VR.probe_duration(done[0]) >= 2.0
    assert sorted(p.name for p in tmp_path.iterdir()) == [done[0].split("/")[-1].split("\\")[-1]]
