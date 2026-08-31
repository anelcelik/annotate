#!/usr/bin/env python3
"""
video_recorder.py — screen recording with the annotation layer baked in.

The module is deliberately split in two halves:

  FFmpegEncoder / PacedWriter   Pure Python, no Qt. They take raw BGRA frames,
                                pace them to a constant frame rate and push
                                them through ffmpeg. Runnable (and testable)
                                without a display.

  ScreenRecorder                The Qt half. Grabs the desktop, paints the
                                canvas shapes on top, hands the bytes to the
                                writer.

Why the desktop grab and the annotations are composited separately
──────────────────────────────────────────────────────────────────
The overlay is a real, visible window. If it ended up in the desktop grab the
annotations would be recorded twice — once as pixels, once as our composite —
and the dock would sit in the middle of every video.

On Windows 10 2004+ we ask the compositor to leave our own windows out of any
screen capture (SetWindowDisplayAffinity / WDA_EXCLUDEFROMCAPTURE). The user
still sees the overlay and the dock; the recording does not. We then draw the
shapes onto each frame ourselves, at full resolution, so they come out crisp
instead of resampled.

Where that call is unavailable (Linux, older Windows) we fall back to
"what you see is what you get": the grab already contains the overlay, so we
skip our own compositing to avoid drawing everything twice.
"""

from __future__ import annotations

import os
import platform
import queue
import shutil
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

IS_WIN = platform.system() == "Windows"
IS_MAC = platform.system() == "Darwin"

# Keep the console window from flashing up on every ffmpeg call on Windows.
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0) if IS_WIN else 0


class RecorderError(RuntimeError):
    """Anything that stops a recording from starting or finishing cleanly."""


# ── Finding ffmpeg ────────────────────────────────────────────────────────────

FFMPEG_ENV = "SCREEN_ANNOTATOR_FFMPEG"

_ffmpeg_cache: str | None | bool = False   # False = "not looked yet"


def find_ffmpeg(refresh: bool = False) -> str | None:
    """Locate an ffmpeg binary: env override, then bundled, then PATH."""
    global _ffmpeg_cache
    if _ffmpeg_cache is not False and not refresh:
        return _ffmpeg_cache

    name = "ffmpeg.exe" if IS_WIN else "ffmpeg"
    candidates: list[str] = []

    env = os.environ.get(FFMPEG_ENV, "").strip()
    if env:
        candidates.append(env)

    # Next to the frozen executable, and inside the PyInstaller bundle.
    bases = [os.path.dirname(os.path.abspath(sys.argv[0])),
             os.path.dirname(os.path.abspath(__file__))]
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        bases.append(meipass)
    for base in bases:
        candidates.append(os.path.join(base, name))
        candidates.append(os.path.join(base, "ffmpeg", name))

    for c in candidates:
        if c and os.path.isfile(c) and os.access(c, os.X_OK):
            _ffmpeg_cache = c
            return c

    _ffmpeg_cache = shutil.which("ffmpeg")
    return _ffmpeg_cache


FFMPEG_HELP = (
    "Recording needs ffmpeg, and it wasn't found on this machine.\n\n"
    "Install it once and recording lights up:\n"
    "  •  Windows:  winget install Gyan.FFmpeg   (or drop ffmpeg.exe next to "
    "this app)\n"
    "  •  Linux:    install the ffmpeg package from your distribution\n\n"
    f"You can also point the app straight at a binary with the {FFMPEG_ENV} "
    "environment variable."
)


def ffmpeg_version(ffmpeg: str | None = None) -> str:
    ffmpeg = ffmpeg or find_ffmpeg()
    if not ffmpeg:
        return ""
    try:
        out = subprocess.run([ffmpeg, "-hide_banner", "-version"],
                             capture_output=True, text=True, timeout=10,
                             creationflags=_NO_WINDOW)
        return out.stdout.splitlines()[0] if out.stdout else ""
    except Exception:
        return ""


_audio_devices_cache: list[str] | None = None


def list_audio_devices(ffmpeg: str | None = None,
                       refresh: bool = False) -> list[str]:
    """Input device names for the mic dropdown. Empty list = use the default.

    Cached: this shells out to ffmpeg, and the Settings dialog asks for it
    every time it is opened (and again on every theme switch).
    """
    global _audio_devices_cache
    if _audio_devices_cache is not None and not refresh:
        return _audio_devices_cache
    ffmpeg = ffmpeg or find_ffmpeg()
    if not ffmpeg:
        return []
    if not IS_WIN:
        # PulseAudio/PipeWire: "default" follows whatever the user picked in
        # their sound settings, which is nearly always what they want.
        return []
    try:
        proc = subprocess.run(
            [ffmpeg, "-hide_banner", "-list_devices", "true", "-f", "dshow",
             "-i", "dummy"],
            capture_output=True, text=True, timeout=15, creationflags=_NO_WINDOW)
    except Exception:
        _audio_devices_cache = []
        return []
    names, in_audio = [], False
    for line in (proc.stderr or "").splitlines():
        if "DirectShow audio devices" in line:
            in_audio = True
            continue
        if "DirectShow video devices" in line:
            in_audio = False
            continue
        if in_audio and '"' in line and "Alternative name" not in line:
            names.append(line.split('"')[1])
    _audio_devices_cache = names
    return names


# ── Recording configuration ───────────────────────────────────────────────────

QUALITY_PRESETS = {
    # name        crf  x264 preset   description shown in Settings
    "high":      (18, "veryfast", "Sharpest, largest file"),
    "balanced":  (23, "veryfast", "Good quality, sensible size"),
    "small":     (28, "faster",   "Smallest file, softer detail"),
}


def default_output_dir() -> str:
    home = Path.home()
    for candidate in (home / "Videos", home / "Movies"):
        if candidate.is_dir():
            return str(candidate / "ScreenAnnotatorPro")
    return str(home / "ScreenAnnotatorPro")


@dataclass
class RecordConfig:
    fps: int = 30
    quality: str = "balanced"
    audio: bool = False
    audio_device: str = ""          # "" = system default input
    cursor: bool = True
    area: str = "all"               # "all" | "screen" | "region"
    out_dir: str = field(default_factory=default_output_dir)

    @property
    def crf(self) -> int:
        return QUALITY_PRESETS.get(self.quality, QUALITY_PRESETS["balanced"])[0]

    @property
    def preset(self) -> str:
        return QUALITY_PRESETS.get(self.quality, QUALITY_PRESETS["balanced"])[1]

    def new_path(self) -> str:
        Path(self.out_dir).mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        return str(Path(self.out_dir) / f"annotation_{stamp}.mp4")


# ── ffmpeg process wrapper ────────────────────────────────────────────────────

class FFmpegEncoder:
    """One ffmpeg process eating raw BGRA frames on stdin, writing an MP4."""

    def __init__(self, ffmpeg: str, path: str, width: int, height: int,
                 fps: int, *, crf: int = 23, preset: str = "veryfast",
                 audio_device: str | None = None):
        if width % 2 or height % 2:
            raise RecorderError("frame size must be even for H.264")
        self.ffmpeg = ffmpeg
        self.path = path
        self.width = width
        self.height = height
        self.fps = fps
        self.crf = crf
        self.preset = preset
        self.audio_device = audio_device
        self.frame_size = width * height * 4
        self.frames_written = 0
        self._proc: subprocess.Popen | None = None
        self._err: list[str] = []
        self._err_thread: threading.Thread | None = None

    # ── command line ──────────────────────────────────────────────────────────
    def _audio_input(self) -> list[str]:
        if self.audio_device is None:
            return []
        if IS_WIN:
            dev = self.audio_device or "default"
            return ["-f", "dshow", "-thread_queue_size", "1024",
                    "-i", f"audio={dev}"]
        if IS_MAC:
            return ["-f", "avfoundation", "-thread_queue_size", "1024",
                    "-i", f":{self.audio_device or '0'}"]
        return ["-f", "pulse", "-thread_queue_size", "1024",
                "-i", self.audio_device or "default"]

    def command(self) -> list[str]:
        cmd = [self.ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
               "-f", "rawvideo", "-pix_fmt", "bgra",
               "-s", f"{self.width}x{self.height}",
               "-framerate", str(self.fps),
               "-thread_queue_size", "512",
               "-i", "pipe:0"]
        cmd += self._audio_input()
        cmd += ["-c:v", "libx264", "-preset", self.preset, "-crf", str(self.crf),
                "-pix_fmt", "yuv420p", "-movflags", "+faststart"]
        if self.audio_device is not None:
            # The mic runs on its own clock; let ffmpeg stretch it rather than
            # let it drift away from the video over a long session.
            cmd += ["-c:a", "aac", "-b:a", "160k",
                    "-af", "aresample=async=1000", "-shortest"]
        cmd.append(self.path)
        return cmd

    # ── lifecycle ─────────────────────────────────────────────────────────────
    def start(self):
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        try:
            self._proc = subprocess.Popen(
                self.command(), stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE, creationflags=_NO_WINDOW)
        except OSError as e:
            raise RecorderError(f"could not start ffmpeg: {e}") from e
        self._err_thread = threading.Thread(target=self._drain_stderr,
                                            daemon=True)
        self._err_thread.start()

    def _drain_stderr(self):
        assert self._proc and self._proc.stderr
        for raw in self._proc.stderr:
            line = raw.decode("utf-8", "replace").rstrip()
            if line:
                self._err.append(line)
                del self._err[:-40]          # keep only the tail

    @property
    def alive(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    @property
    def error_tail(self) -> str:
        return "\n".join(self._err[-8:])

    def write(self, frame: bytes):
        if not self._proc or not self._proc.stdin:
            raise RecorderError("encoder is not running")
        if len(frame) != self.frame_size:
            raise RecorderError(
                f"frame is {len(frame)} bytes, expected {self.frame_size}")
        try:
            self._proc.stdin.write(frame)
        except (BrokenPipeError, OSError) as e:
            raise RecorderError(
                f"ffmpeg stopped accepting frames: {self.error_tail or e}") from e
        self.frames_written += 1

    def finish(self, timeout: float = 60.0):
        """Close the pipe and wait for ffmpeg to flush the file."""
        if not self._proc:
            return
        try:
            if self._proc.stdin:
                self._proc.stdin.close()
        except OSError:
            pass
        try:
            code = self._proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            self._proc.kill()
            raise RecorderError("ffmpeg did not finish writing the file in time")
        if self._err_thread:
            self._err_thread.join(timeout=2)
        if code != 0:
            raise RecorderError(f"ffmpeg exited with code {code}: "
                                f"{self.error_tail or 'no output'}")

    def abort(self):
        if not self._proc:
            return
        try:
            if self._proc.stdin:
                self._proc.stdin.close()
        except OSError:
            pass
        try:
            self._proc.terminate()
            self._proc.wait(timeout=5)
        except Exception:
            try:
                self._proc.kill()
            except Exception:
                pass


# ── Constant-rate writer thread ───────────────────────────────────────────────

class PacedWriter(threading.Thread):
    """Emits exactly `fps` frames per second of wall clock.

    The grabber pushes whatever it manages into `set_frame`; this thread owns
    the output cadence. A slow grab repeats the previous frame instead of
    shortening the video, so the finished file always runs at real speed —
    the single most confusing thing to get wrong in a screen recorder.
    """

    def __init__(self, encoder: FFmpegEncoder, fps: int):
        super().__init__(daemon=True, name="video-writer")
        self.encoder = encoder
        self.interval = 1.0 / max(1, fps)
        self._frame: bytes | None = None
        self._lock = threading.Lock()
        self._wake = threading.Event()
        self._running = True
        self._paused = False
        self._flush_on_stop = True
        self.error: str | None = None
        self.dropped = 0            # frames we had to write late (diagnostics)

    # ── producer side ─────────────────────────────────────────────────────────
    def set_frame(self, frame: bytes):
        with self._lock:
            self._frame = frame

    def pause(self, on: bool):
        self._paused = on
        self._wake.set()

    def stop(self):
        self._running = False
        self._wake.set()

    # ── thread ────────────────────────────────────────────────────────────────
    def run(self):
        # Wait for the first real frame so the file never opens on garbage.
        while self._running and self._frame is None:
            self._wake.wait(0.05)
            self._wake.clear()
        if not self._running:
            return

        n = 0
        clock = time.perf_counter()
        try:
            while self._running:
                if self._paused:
                    paused_at = time.perf_counter()
                    while self._running and self._paused:
                        self._wake.wait(0.05)
                        self._wake.clear()
                    clock += time.perf_counter() - paused_at   # freeze the clock
                    continue

                target = clock + n * self.interval
                delay = target - time.perf_counter()
                if delay > 0:
                    time.sleep(delay)
                elif delay < -self.interval:
                    self.dropped += 1        # behind schedule; catch up below

                with self._lock:
                    frame = self._frame
                if frame is None:
                    continue
                self.encoder.write(frame)
                n += 1

            # Stopped before the first scheduled tick — a recording of well
            # under one frame. Emit the frame we have so the user gets a very
            # short video rather than an error about an empty file.
            if self._flush_on_stop and self.encoder.frames_written == 0:
                with self._lock:
                    frame = self._frame
                if frame is not None:
                    self.encoder.write(frame)
        except RecorderError as e:
            self.error = str(e)
        except Exception as e:                              # pragma: no cover
            self.error = f"{type(e).__name__}: {e}"


# ── Windows: keep our own windows out of the capture ──────────────────────────

WDA_NONE = 0x00000000
WDA_EXCLUDEFROMCAPTURE = 0x00000011


def can_exclude_from_capture() -> bool:
    """Whether this OS can hide a visible window from screen capture.

    Windows 10 2004+ only. Nothing equivalent exists on Wayland (wlroots
    screencopy hands over the composited output, with no per-window opt-out)
    or on X11, so on those platforms anything on screen is in the recording —
    which is why the app moves its own chrome out of frame instead.

    Checked up front, before a recording starts, so the UI can get out of the
    way *before* the first frame rather than after it.
    """
    if not IS_WIN:
        return False
    try:
        import ctypes
        return hasattr(ctypes.windll.user32, "SetWindowDisplayAffinity")
    except Exception:
        return False


def exclude_from_capture(widget, on: bool = True) -> bool:
    """Hide a window from screen capture while leaving it visible on screen.

    Returns True if the compositor honoured it. Windows 10 2004+ only.
    """
    if not IS_WIN:
        return False
    try:
        import ctypes
        hwnd = int(widget.winId())
        if not hwnd:
            return False
        ok = ctypes.windll.user32.SetWindowDisplayAffinity(
            ctypes.c_void_p(hwnd),
            ctypes.c_uint(WDA_EXCLUDEFROMCAPTURE if on else WDA_NONE))
        return bool(ok)
    except Exception:
        return False


# ── Qt half: grab, composite, feed ────────────────────────────────────────────

from PyQt6.QtCore import QObject, QRect, QPointF, QTimer, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QImage, QPainter, QPen, QPolygonF, QCursor
from PyQt6.QtWidgets import QApplication


def _even(n: int) -> int:
    """H.264 with yuv420p needs both dimensions even."""
    return n if n % 2 == 0 else n - 1


def virtual_desktop_rect() -> QRect:
    rect = QRect()
    for scr in QApplication.screens():
        rect = rect.united(scr.geometry())
    if rect.isEmpty():
        rect = QApplication.primaryScreen().geometry()
    return rect


def screen_under_cursor() -> QRect:
    scr = QApplication.screenAt(QCursor.pos()) or QApplication.primaryScreen()
    return scr.geometry()


# ── Where frames come from ────────────────────────────────────────────────────
#
# Qt's own grabWindow() is the fast path, and the only one on Windows. It
# returns nothing at all under Wayland, so wlroots compositors (Hyprland,
# Sway) get a second source built on grim. They behave differently in one way
# that matters: grim captures the final composited output, overlay included,
# so on that path the annotations are already in the frame and must not be
# drawn again. See ScreenRecorder._composite.

class DesktopSource:
    """A way to get one frame of the desktop."""

    name = "?"
    gui_thread_only = True      # Qt pixmaps may only be grabbed on the GUI thread
    draws_cursor = False        # True if the source already includes the pointer

    def available(self) -> bool:
        return True

    def grab(self, region: "QRect") -> "QImage | None":
        raise NotImplementedError

    def close(self):
        pass


class QtDesktopSource(DesktopSource):
    name = "qt"
    gui_thread_only = True

    def grab(self, region):
        try:
            pm = QApplication.primaryScreen().grabWindow(
                0, region.x(), region.y(), region.width(), region.height())
        except Exception:
            return None
        if pm is None or pm.isNull():
            return None
        return pm.toImage()


class GrimDesktopSource(DesktopSource):
    """wlroots screen capture, one `grim` per frame.

    A process per frame is not how you would build this for Windows, but on
    Wayland it is the only capture path that does not need a portal session,
    and it runs off the GUI thread — so a ~50 ms grab costs frame rate, never
    responsiveness.
    """

    name = "grim"
    gui_thread_only = False

    def __init__(self, cursor: bool = True):
        self.binary = shutil.which("grim")
        self.draws_cursor = cursor

    def available(self) -> bool:
        return bool(self.binary)

    def grab(self, region):
        cmd = [self.binary, "-t", "ppm"]
        if self.draws_cursor:
            cmd.append("-c")
        cmd += ["-g", f"{region.x()},{region.y()} "
                      f"{region.width()}x{region.height()}", "-"]
        try:
            out = subprocess.run(cmd, capture_output=True, timeout=5)
        except (OSError, subprocess.TimeoutExpired):
            return None
        if out.returncode != 0 or not out.stdout:
            return None
        img = QImage.fromData(out.stdout, "PPM")
        return None if img.isNull() else img


def is_wayland() -> bool:
    return bool(os.environ.get("WAYLAND_DISPLAY")) or \
        os.environ.get("XDG_SESSION_TYPE", "").lower() == "wayland"


def pick_region_natively() -> "QRect | None | bool":
    """Let the compositor's own region picker choose the area.

    Wayland gives a window no say in where it is placed, so the app's
    fullscreen selector cannot cover the screen there. `slurp` is the native
    equivalent and every wlroots setup that has grim tends to have it.

    Returns a QRect, None if the user cancelled, or False if there is no
    native picker to use (caller should fall back to its own).
    """
    if IS_WIN or not is_wayland():
        return False
    slurp = shutil.which("slurp")
    if not slurp:
        return False
    try:
        out = subprocess.run([slurp, "-f", "%x %y %w %h"],
                             capture_output=True, text=True, timeout=120)
    except (OSError, subprocess.TimeoutExpired):
        return False
    if out.returncode != 0 or not out.stdout.strip():
        return None                      # cancelled with Esc
    try:
        x, y, w, h = (int(v) for v in out.stdout.split())
    except ValueError:
        return None
    return QRect(x, y, w, h)


def pick_source(cursor: bool = True) -> DesktopSource:
    """The best capture path this session actually supports."""
    if not IS_WIN and is_wayland():
        grim = GrimDesktopSource(cursor)
        if grim.available():
            return grim
    return QtDesktopSource()


class ScreenRecorder(QObject):
    """Records a region of the desktop with the annotation layer composited in.

    Signals are the whole public surface: the UI connects to them and never
    has to know whether ffmpeg is still chewing on the file.
    """

    started  = pyqtSignal(str)      # output path
    tick     = pyqtSignal(float)    # elapsed seconds
    finishing = pyqtSignal()        # pipe closed, ffmpeg flushing
    finished = pyqtSignal(str)      # output path, file is on disk
    failed   = pyqtSignal(str)      # human-readable reason

    def __init__(self, parent=None):
        super().__init__(parent)
        self._timer = QTimer(self)
        self._timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._timer.setInterval(33)
        self._timer.timeout.connect(self._grab_frame)
        self._clock = QTimer(self)
        self._clock.setInterval(200)
        self._clock.timeout.connect(self._emit_tick)

        self._encoder: FFmpegEncoder | None = None
        self._writer: PacedWriter | None = None
        self._source: DesktopSource | None = None
        self._worker: threading.Thread | None = None
        self._worker_stop = threading.Event()
        self._canvas = None
        self._overlay = None
        self._excluded: list = []
        self._composite = False
        self._region = QRect()
        self._scale = (1.0, 1.0)
        self._origin = QPointF(0, 0)
        self._size = (0, 0)
        self._cursor = True
        self._path = ""
        self._t0 = 0.0
        self._paused_total = 0.0
        self._paused_at = 0.0
        self.active = False
        self.paused = False

    # ── start ─────────────────────────────────────────────────────────────────
    def start(self, canvas, overlay, config: RecordConfig,
              region: QRect | None = None, exclude=()) -> bool:
        if self.active:
            return False

        ffmpeg = find_ffmpeg()
        if not ffmpeg:
            self.failed.emit(FFMPEG_HELP)
            return False

        self._canvas = canvas
        self._overlay = overlay
        self._source = pick_source(config.cursor)
        # grim already burns the real pointer in; only the Qt path needs ours.
        self._cursor = config.cursor and not self._source.draws_cursor

        region = region if region and region.isValid() else virtual_desktop_rect()
        self._region = region

        # Ask the compositor to leave our windows out of the capture. When it
        # works we draw the shapes ourselves at full resolution; when it does
        # not, the grab already contains them and compositing would double up.
        # Off-GUI-thread sources never composite either — canvas shapes may
        # only be read from the thread that owns them.
        self._excluded = [w for w in exclude if exclude_from_capture(w, True)]
        self._composite = (bool(exclude)
                           and len(self._excluded) == len(exclude)
                           and self._source.gui_thread_only)

        probe = self._capture()
        if probe is None or probe.isNull():
            why = "The screen could not be captured."
            if not IS_WIN and is_wayland():
                why += ("\n\nOn a wlroots compositor (Hyprland, Sway) that "
                        "needs grim installed — it is the capture path there. "
                        "On GNOME or KDE Wayland, run the app under XWayland: "
                        "QT_QPA_PLATFORM=xcb python annotate.py")
            self._unexclude()
            self.failed.emit(why)
            return False

        w, h = _even(probe.width()), _even(probe.height())
        if w < 16 or h < 16:
            self._unexclude()
            self.failed.emit("The selected area is too small to record.")
            return False
        self._size = (w, h)
        # Device pixels per logical pixel, derived from the actual grab rather
        # than assumed — this is what keeps annotations aligned at 125 %/150 %.
        self._scale = (w / max(1, region.width()), h / max(1, region.height()))
        ogeo = overlay.geometry()
        self._origin = QPointF(region.x() - ogeo.x(), region.y() - ogeo.y())

        try:
            self._path = config.new_path()
        except OSError as e:
            self._unexclude()
            self.failed.emit(f"Recordings cannot be written to "
                             f"{config.out_dir}\n\n{e}")
            return False
        self._encoder = FFmpegEncoder(
            ffmpeg, self._path, w, h, config.fps,
            crf=config.crf, preset=config.preset,
            audio_device=(config.audio_device if config.audio else None))
        try:
            self._encoder.start()
        except RecorderError as e:
            self._unexclude()
            self.failed.emit(str(e))
            return False

        self._writer = PacedWriter(self._encoder, config.fps)
        self._writer.start()
        self._timer.setInterval(max(1, int(1000 / config.fps)))

        self.active = True
        self.paused = False
        self._t0 = time.perf_counter()
        self._paused_total = 0.0
        self._clock.start()
        self._push(probe)
        if self._source.gui_thread_only:
            self._timer.start(max(1, int(1000 / config.fps)))
        else:
            self._worker_stop.clear()
            self._worker = threading.Thread(target=self._worker_loop,
                                            daemon=True, name="video-grab")
            self._worker.start()
        self.started.emit(self._path)
        return True

    # ── pause / resume ────────────────────────────────────────────────────────
    def pause(self, on: bool):
        if not self.active or on == self.paused:
            return
        self.paused = on
        if on:
            self._paused_at = time.perf_counter()
            self._timer.stop()
        else:
            self._paused_total += time.perf_counter() - self._paused_at
            if self._source and self._source.gui_thread_only:
                self._timer.start()
        if self._writer:
            self._writer.pause(on)

    # ── stop ──────────────────────────────────────────────────────────────────
    def stop(self):
        if not self.active:
            return
        self.active = False
        self.paused = False
        self._timer.stop()
        self._clock.stop()
        self._stop_worker()
        self._unexclude()
        self.finishing.emit()

        writer, encoder, path = self._writer, self._encoder, self._path
        self._writer = self._encoder = None

        def close_out():
            try:
                if writer:
                    writer.stop()
                    writer.join(timeout=10)
                    if writer.error:
                        raise RecorderError(writer.error)
                if encoder:
                    if encoder.frames_written == 0:
                        encoder.abort()
                        raise RecorderError("no frames were captured")
                    encoder.finish()
            except RecorderError as e:
                if encoder:
                    encoder.abort()
                _emit(self.failed, str(e))
                return
            except Exception as e:                          # pragma: no cover
                _emit(self.failed, f"{type(e).__name__}: {e}")
                return
            _emit(self.finished, path)

        def _emit(signal, arg):
            # This runs after the recorder may already be gone — the app can
            # be quitting while ffmpeg flushes. A dead C++ object is a normal
            # end to this thread, not a crash to report.
            try:
                signal.emit(arg)
            except RuntimeError:
                pass

        # ffmpeg needs a moment to flush and move the moov atom; doing that on
        # the GUI thread would freeze the overlay right as the user stops.
        threading.Thread(target=close_out, daemon=True,
                         name="video-finish").start()

    def cancel(self):
        """Stop and throw the file away."""
        if not self.active:
            return
        self.active = False
        self._timer.stop()
        self._clock.stop()
        self._stop_worker()
        self._unexclude()
        if self._writer:
            self._writer.stop()
        if self._encoder:
            self._encoder.abort()
        path, self._path = self._path, ""
        self._writer = self._encoder = None
        try:
            if path and os.path.exists(path):
                os.remove(path)
        except OSError:
            pass

    # ── elapsed ───────────────────────────────────────────────────────────────
    def elapsed(self) -> float:
        if not self._t0:
            return 0.0
        now = self._paused_at if self.paused else time.perf_counter()
        return max(0.0, now - self._t0 - self._paused_total)

    def _emit_tick(self):
        self.tick.emit(self.elapsed())
        # A dead encoder (disk full, bad codec) should surface immediately
        # rather than at stop time, half a talk-track later.
        if self._writer and self._writer.error:
            err = self._writer.error
            self.cancel()
            self.failed.emit(err)

    # ── frame production ──────────────────────────────────────────────────────
    def _capture(self):
        return self._source.grab(self._region) if self._source else None

    def _worker_loop(self):
        """Grab loop for sources that cannot run on the GUI thread.

        It free-runs: a slow source simply produces fewer distinct frames,
        and PacedWriter repeats the last one to keep the output at real speed.
        """
        interval = self._timer.interval() / 1000.0 or 0.033
        while not self._worker_stop.is_set():
            if self.paused:
                self._worker_stop.wait(0.05)
                continue
            t0 = time.perf_counter()
            img = self._capture()
            if img is not None and not img.isNull():
                self._push(img)
            slack = interval - (time.perf_counter() - t0)
            if slack > 0:
                self._worker_stop.wait(slack)

    def _stop_worker(self):
        self._worker_stop.set()
        if self._worker and self._worker.is_alive():
            self._worker.join(timeout=6)
        self._worker = None

    def _grab_frame(self):
        img = self._capture()
        if img is not None and not img.isNull():
            self._push(img)

    def _push(self, img):
        if not self._writer:
            return
        img = img.convertToFormat(QImage.Format.Format_ARGB32)
        w, h = self._size
        if img.width() != w or img.height() != h:
            # Odd capture sizes get rounded down to even for H.264. Trimming a
            # pixel is a crop; resampling every frame for it would not be.
            if 0 <= img.width() - w <= 2 and 0 <= img.height() - h <= 2:
                img = img.copy(0, 0, w, h)
            else:
                img = img.scaled(w, h, Qt.AspectRatioMode.IgnoreAspectRatio,
                                 Qt.TransformationMode.SmoothTransformation)

        # An overlay hidden with Esc is not on screen, so it must not be in
        # the recording either — even though its shapes are still in the model.
        composite = (self._composite and self._canvas is not None
                     and self._overlay is not None and self._overlay.isVisible())
        if composite or self._cursor:
            p = QPainter(img)
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            p.scale(*self._scale)
            p.translate(-self._origin)
            if composite:
                self._canvas.render_annotations(p, selection=False)
            if self._cursor:
                self._draw_cursor(p)
            p.end()

        ptr = img.bits()
        ptr.setsize(img.sizeInBytes())
        self._writer.set_frame(bytes(ptr))

    def _draw_cursor(self, p: QPainter):
        """A stylised pointer at the live cursor position.

        Reading the real cursor bitmap is per-platform work that buys very
        little: what viewers need is to see where the presenter is pointing.
        """
        pos = QCursor.pos()
        ogeo = self._overlay.geometry() if self._overlay else QRect()
        x, y = pos.x() - ogeo.x(), pos.y() - ogeo.y()
        arrow = QPolygonF([
            QPointF(x, y), QPointF(x, y + 17.5), QPointF(x + 4.2, y + 13.4),
            QPointF(x + 7.0, y + 19.6), QPointF(x + 10.1, y + 18.2),
            QPointF(x + 7.4, y + 12.2), QPointF(x + 13.0, y + 12.0),
        ])
        p.setPen(QPen(QColor(0, 0, 0, 200), 1.4))
        p.setBrush(QColor(255, 255, 255, 240))
        p.drawPolygon(arrow)

    # ── housekeeping ──────────────────────────────────────────────────────────
    def _unexclude(self):
        for w in self._excluded:
            exclude_from_capture(w, False)
        self._excluded = []


def format_elapsed(seconds: float) -> str:
    s = int(seconds)
    return f"{s // 3600:d}:{(s % 3600) // 60:02d}:{s % 60:02d}" if s >= 3600 \
        else f"{s // 60:02d}:{s % 60:02d}"
