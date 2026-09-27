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

import importlib.util
import os
import platform
import queue
import re
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
    names = parse_dshow_devices(proc.stderr or "")
    _audio_devices_cache = names
    return names


_DSHOW_DEVICE = re.compile(r'"([^"]+)"\s*\(([^)]*)\)\s*$')


def parse_dshow_devices(listing: str, kind: str = "audio") -> list[str]:
    """Audio input names out of `ffmpeg -list_devices true -f dshow`.

    ffmpeg 5 changed this listing: there are no "DirectShow audio devices"
    headers any more, each device carries its type instead —
        [dshow @ 0000…] "Microphone (Realtek Audio)" (audio)
    Parsing only the old headers found nothing on every current ffmpeg, so
    the microphone list was always empty and recording fell back to a device
    called "default" — which DirectShow does not have. Both formats are read.
    """
    names, in_section = [], False
    for line in listing.splitlines():
        if "DirectShow audio devices" in line:          # ffmpeg 4 and older
            in_section = kind == "audio"
            continue
        if "DirectShow video devices" in line:
            in_section = kind == "video"
            continue
        if "Alternative name" in line:
            continue
        m = _DSHOW_DEVICE.search(line)                  # ffmpeg 5 and newer
        if m:
            kinds = [k.strip() for k in m.group(2).split(",")]
            if kind in kinds and m.group(1) not in names:
                names.append(m.group(1))
            continue
        if in_section and '"' in line:
            name = line.split('"')[1]
            if name not in names:
                names.append(name)
    return names


_video_devices_cache: list[str] | None = None


def list_video_devices(ffmpeg: str | None = None, refresh: bool = False) -> list[str]:
    """Cameras ffmpeg can open: DirectShow names on Windows, /dev/video* on
    Linux."""
    global _video_devices_cache
    if _video_devices_cache is not None and not refresh:
        return _video_devices_cache
    if not IS_WIN:
        _video_devices_cache = sorted(str(p) for p in Path("/dev").glob("video*"))
        return _video_devices_cache
    ffmpeg = ffmpeg or find_ffmpeg()
    if not ffmpeg:
        return []
    try:
        proc = subprocess.run(
            [ffmpeg, "-hide_banner", "-list_devices", "true", "-f", "dshow",
             "-i", "dummy"],
            capture_output=True, text=True, timeout=15, creationflags=_NO_WINDOW)
    except Exception:
        return []
    _video_devices_cache = parse_dshow_devices(proc.stderr or "", "video")
    return _video_devices_cache


def camera_command(ffmpeg: str, device: str, side: int = 480, fps: int = 30) -> list[str]:
    """A camera as square BGRA frames on stdout — for the webcam bubble."""
    if IS_WIN:
        source = ["-f", "dshow", "-rtbufsize", "64M", "-i", f"video={device}"]
    elif IS_MAC:
        source = ["-f", "avfoundation", "-framerate", str(fps), "-i", device or "0"]
    else:
        source = ["-f", "v4l2", "-i", device or "/dev/video0"]
    return [ffmpeg, "-hide_banner", "-loglevel", "error", *source,
            "-vf", f"scale={side}:{side}:force_original_aspect_ratio=increase,"
                   f"crop={side}:{side},fps={fps}",
            "-f", "rawvideo", "-pix_fmt", "bgra", "pipe:1"]


def resolve_audio_device(wanted: str) -> str | None:
    """The input to record from: the chosen one if it is still there, else
    the first microphone ffmpeg can see. None when there is no microphone.
    Only DirectShow needs this — Pulse and AVFoundation have a real default."""
    if not IS_WIN:
        return wanted or ""
    devices = list_audio_devices() or list_audio_devices(refresh=True)
    if wanted and wanted in devices:
        return wanted
    return devices[0] if devices else None


# ── The PC's own sound (Windows, WASAPI loopback) ───────────────────────────────

def _wasapi_loopback():
    """(rate, channels, open(callback) -> close) for the default speakers'
    loopback, or None where there is no such thing (not Windows, no
    PyAudioWPatch, no output device)."""
    if not IS_WIN:
        return None
    try:
        import pyaudiowpatch as pa
    except Exception:
        return None
    try:
        audio = pa.PyAudio()
        info = audio.get_host_api_info_by_type(pa.paWASAPI)
        speakers = audio.get_device_info_by_index(info["defaultOutputDevice"])
        if not speakers.get("isLoopbackDevice"):
            speakers = next((d for d in audio.get_loopback_device_info_generator()
                             if speakers["name"] in d["name"]), None)
        if speakers is None:
            audio.terminate()
            return None
    except Exception:
        return None
    rate = int(speakers["defaultSampleRate"])
    channels = max(1, min(2, int(speakers["maxInputChannels"])))

    def open_stream(callback):
        def cb(data, frames, _time, _status):
            callback(data)
            return (None, pa.paContinue)
        stream = audio.open(format=pa.paInt16, channels=channels, rate=rate,
                            input=True, input_device_index=speakers["index"],
                            frames_per_buffer=rate // 20, stream_callback=cb)
        stream.start_stream()

        def close():
            try:
                stream.stop_stream()
                stream.close()
            finally:
                audio.terminate()
        return close
    return rate, channels, open_stream


def system_audio_available() -> bool:
    if not IS_WIN:
        return False
    return importlib.util.find_spec("pyaudiowpatch") is not None


class SystemAudioCapture:
    """What the PC plays, into a WAV beside the recording; it is mixed in
    once the video is done.

    WASAPI hands out nothing at all while the PC is silent, so silence is
    filled in by the clock — otherwise every quiet stretch would pull the
    rest of the sound earlier and out of step with the picture."""

    def __init__(self, path: str, source=None, clock=time.monotonic):
        self.path = path
        self._source = source if source is not None else _wasapi_loopback()
        self._clock = clock
        self._wav = None
        self._close = None
        self._lock = threading.Lock()
        self._frames = 0
        self._paused_at: float | None = None
        self._paused_total = 0.0
        self._timer: threading.Timer | None = None
        self.started_at = 0.0
        self.error = ""

    @property
    def seconds(self) -> float:
        rate = getattr(self, "_rate", 0)
        return self._frames / rate if rate else 0.0

    def start(self) -> bool:
        if self._source is None:
            self.error = "no playback device to listen to"
            return False
        import wave
        self._rate, self._channels, opener = self._source
        try:
            self._wav = wave.open(self.path, "wb")
            self._wav.setnchannels(self._channels)
            self._wav.setsampwidth(2)
            self._wav.setframerate(self._rate)
            self.started_at = self._clock()
            self._close = opener(self.feed)
        except Exception as e:
            self.error = str(e)
            self._finish_file()
            return False
        self._tick()
        return True

    def _due(self) -> int:
        """Frames that should exist by now, pauses left out."""
        now = self._paused_at if self._paused_at is not None else self._clock()
        return int((now - self.started_at - self._paused_total) * self._rate)

    def feed(self, data: bytes):
        with self._lock:
            if self._wav is None or self._paused_at is not None:
                return
            n = len(data) // (2 * self._channels)
            gap = self._due() - n - self._frames
            if gap > self._rate // 20:                  # more than 50 ms missing
                self._write_silence(gap)
            self._wav.writeframesraw(data)
            self._frames += n

    def _write_silence(self, frames: int):
        self._wav.writeframesraw(b"\0" * (frames * 2 * self._channels))
        self._frames += frames

    def _tick(self):
        """Fill silence while nothing plays; keeps the WAV in step."""
        with self._lock:
            if self._wav is None:
                return
            if self._paused_at is None:
                gap = self._due() - self._frames
                if gap > self._rate // 10:              # 100 ms of nothing
                    self._write_silence(gap)
        self._timer = threading.Timer(0.1, self._tick)
        self._timer.daemon = True
        self._timer.start()

    def pause(self, on: bool):
        with self._lock:
            if on and self._paused_at is None:
                self._paused_at = self._clock()
            elif not on and self._paused_at is not None:
                self._paused_total += self._clock() - self._paused_at
                self._paused_at = None

    def stop(self):
        if self._timer is not None:
            self._timer.cancel()
        if self._close is not None:
            try:
                self._close()
            except Exception:
                pass
            self._close = None
        with self._lock:
            if self._wav is not None and self._paused_at is None:
                gap = self._due() - self._frames
                if gap > 0:
                    self._write_silence(gap)
            self._finish_file()

    def _finish_file(self):
        if self._wav is not None:
            try:
                self._wav.close()
            except Exception:
                pass
            self._wav = None


def has_audio_stream(path: str) -> bool:
    ffmpeg = find_ffmpeg()
    if not ffmpeg or not os.path.exists(path):
        return False
    try:
        out = subprocess.run([ffmpeg, "-hide_banner", "-i", path],
                             capture_output=True, text=True, timeout=20,
                             creationflags=_NO_WINDOW)
    except (OSError, subprocess.TimeoutExpired):
        return False
    return "Audio:" in (out.stderr or "")


def mix_audio_command(ffmpeg: str, video: str, wav: str, dst: str, *,
                      offset: float = 0.0, has_mic: bool = False) -> list[str]:
    """The recording with the PC's sound added (and mixed with the microphone
    when there is one). `offset` is how many seconds after the video's first
    frame the sound started; the picture is copied, not re-encoded."""
    if offset >= 0:
        ms = int(round(offset * 1000))
        shift = f"adelay={ms}|{ms}," if ms else ""
    else:
        shift = f"atrim=start={-offset:.3f},asetpts=PTS-STARTPTS,"
    if has_mic:
        graph = (f"[1:a]{shift}aresample=async=1000[s];"
                 "[0:a][s]amix=inputs=2:duration=first:dropout_transition=0:normalize=0[a]")
    else:
        graph = f"[1:a]{shift}aresample=async=1000[a]"
    return [ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
            "-progress", "pipe:1", "-nostats",
            "-i", video, "-i", wav, "-filter_complex", graph,
            "-map", "0:v", "-map", "[a]", "-c:v", "copy",
            "-c:a", "aac", "-b:a", "160k", "-shortest",
            "-movflags", "+faststart", dst]


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

from PySide6.QtCore import QObject, QRect, QPointF, QTimer, Qt, Signal
from PySide6.QtGui import QColor, QImage, QPainter, QPen, QPolygonF, QCursor
from PySide6.QtWidgets import QApplication


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


# ── Recording one window ──────────────────────────────────────────────────────

def native_to_logical(rect: QRect) -> QRect:
    """Physical pixels (what Win32 reports) to Qt's coordinates. Qt keeps each
    screen's top-left corner where Windows has it and scales only its size,
    so the mapping depends on the screen the rectangle is on."""
    c = rect.center()
    for scr in QApplication.screens():
        g, dpr = scr.geometry(), scr.devicePixelRatio()
        native = QRect(g.x(), g.y(), round(g.width() * dpr), round(g.height() * dpr))
        if native.contains(c):
            return QRect(g.x() + round((rect.x() - g.x()) / dpr),
                         g.y() + round((rect.y() - g.y()) / dpr),
                         round(rect.width() / dpr), round(rect.height() / dpr))
    return QRect(rect)


_SHELL_CLASSES = {"Progman", "WorkerW", "Shell_TrayWnd", "Shell_SecondaryTrayWnd"}


def list_windows() -> list[tuple[int, str, QRect]]:
    """The windows you can see, front to back: (handle, title, rectangle in
    Qt coordinates). Windows only — elsewhere [] and the caller lets you drag
    an area instead."""
    if platform.system() != "Windows":
        return []
    import ctypes
    from ctypes import wintypes
    user32, dwm = ctypes.windll.user32, ctypes.windll.dwmapi
    H = wintypes.HWND
    for fn, args in ((user32.IsWindowVisible, [H]), (user32.IsIconic, [H]),
                     (user32.GetWindowTextLengthW, [H]),
                     (user32.GetWindowTextW, [H, wintypes.LPWSTR, ctypes.c_int]),
                     (user32.GetClassNameW, [H, wintypes.LPWSTR, ctypes.c_int]),
                     (user32.GetWindowLongW, [H, ctypes.c_int]),
                     (user32.GetWindowThreadProcessId, [H, ctypes.POINTER(wintypes.DWORD)]),
                     (user32.GetWindowRect, [H, ctypes.POINTER(wintypes.RECT)]),
                     (dwm.DwmGetWindowAttribute, [H, wintypes.DWORD, ctypes.c_void_p,
                                                  wintypes.DWORD])):
        fn.argtypes = args
    own, found = os.getpid(), []

    def visit(hwnd, _lparam):
        if not hwnd or not user32.IsWindowVisible(hwnd) or user32.IsIconic(hwnd):
            return True
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if pid.value == own:                        # the overlay, the dock
            return True
        cloaked = wintypes.DWORD()                  # on another virtual desktop
        dwm.DwmGetWindowAttribute(hwnd, 14, ctypes.byref(cloaked), ctypes.sizeof(cloaked))
        n = user32.GetWindowTextLengthW(hwnd)
        if cloaked.value or n == 0 or user32.GetWindowLongW(hwnd, -20) & 0x80:
            return True                             # WS_EX_TOOLWINDOW: not a window you'd pick
        cls = ctypes.create_unicode_buffer(64)
        user32.GetClassNameW(hwnd, cls, 64)
        if cls.value in _SHELL_CLASSES:
            return True
        title = ctypes.create_unicode_buffer(n + 1)
        user32.GetWindowTextW(hwnd, title, n + 1)
        r = wintypes.RECT()                         # without the invisible resize border
        if dwm.DwmGetWindowAttribute(hwnd, 9, ctypes.byref(r), ctypes.sizeof(r)) != 0:
            user32.GetWindowRect(hwnd, ctypes.byref(r))
        rect = QRect(r.left, r.top, r.right - r.left, r.bottom - r.top)
        if rect.width() >= 80 and rect.height() >= 50:
            found.append((int(hwnd), title.value, native_to_logical(rect)))
        return True

    proc = ctypes.WINFUNCTYPE(wintypes.BOOL, H, wintypes.LPARAM)(visit)
    user32.EnumWindows(proc, 0)
    return found


def bring_to_front(hwnd: int):
    if platform.system() == "Windows" and hwnd:
        import ctypes
        from ctypes import wintypes
        ctypes.windll.user32.SetForegroundWindow.argtypes = [wintypes.HWND]
        ctypes.windll.user32.SetForegroundWindow(hwnd)


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

    started  = Signal(str)      # output path
    tick     = Signal(float)    # elapsed seconds
    finishing = Signal()        # pipe closed, ffmpeg flushing
    finished = Signal(str)      # output path, file is on disk
    failed   = Signal(str)      # human-readable reason

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
        audio_device = None
        if config.audio:
            audio_device = resolve_audio_device(config.audio_device)
            if audio_device is None:
                self._unexclude()
                self.failed.emit(
                    "No microphone was found. Plug one in, or turn off "
                    "\u201cRecord the microphone\u201d in Settings \u2192 Recording.")
                return False
        self._encoder = FFmpegEncoder(
            ffmpeg, self._path, w, h, config.fps,
            crf=config.crf, preset=config.preset,
            audio_device=audio_device)
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
        # At 125 %/150 % Qt tags the grab with the screen's scale, and QPainter
        # applies that tag by itself — on top of self._scale below, which is
        # already worked out from the pixels. Drop the tag so the scale is
        # applied exactly once and the marks land where they are on screen.
        img.setDevicePixelRatio(1.0)
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
        # The laser hides the real pointer on screen; drawing ours on top of
        # the dot would put back the arrow the presenter just got rid of.
        laser_live = (composite and self._canvas.tool == "laser"
                      and self._canvas._laser_pos is not None
                      and not getattr(self._overlay, "passthrough", False))
        cursor = self._cursor and not laser_live
        if composite or cursor:
            p = QPainter(img)
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            p.scale(*self._scale)
            p.translate(-self._origin)
            if composite:
                # paint_marks, not render_annotations: an eraser stroke must
                # erase marks, never punch a hole in the desktop underneath.
                self._canvas.paint_marks(p, img.width(), img.height(),
                                         selection=False)
            if cursor:
                self._draw_cursor(p)
            p.end()

        self._writer.set_frame(bytes(img.constBits()))

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


# ── Recording on the graphics chip ───────────────────────────────────────────
#
# The CPU recorder grabs every frame with GDI on the GUI thread, paints the
# marks on in Python, pipes raw BGRA (1 GB/s at 4K) into ffmpeg and encodes
# with x264: at 4K that is ~29 ms of the 33 ms frame budget on the UI thread
# before encoding, and x264 alone keeps ~4 cores busy.
#
# Here ffmpeg does all of it on the GPU instead: ddagrab (Desktop
# Duplication) captures the screen as a D3D11 texture, scale_d3d11 converts
# it to NV12 on the GPU, and Media Foundation's hardware H.264 encoder takes
# the texture as is. Every Windows laptop has such an encoder in its
# integrated graphics (Intel Quick Sync, AMD VCN, NVIDIA NVENC). Python only
# starts and stops the process. The overlay is captured as it is on screen
# (not excluded), so the marks are in the video; the dock is still excluded
# with WDA_EXCLUDEFROMCAPTURE, which Desktop Duplication honours.
#
# First version, deliberately narrow: one screen (ddagrab's output_idx and
# Qt's screen order can disagree on multi-monitor setups), no pause. If
# ffmpeg gives up in the first seconds — no hardware encoder, no desktop
# duplication — the controller falls back to the CPU recorder.

GPU_QUALITY_BPP = {"high": 0.12, "balanced": 0.07, "small": 0.04}   # bits/pixel/frame


def gpu_bitrate(width: int, height: int, fps: int, quality: str) -> int:
    bpp = GPU_QUALITY_BPP.get(quality, GPU_QUALITY_BPP["balanced"])
    return max(1_000_000, int(width * height * fps * bpp))


def gpu_record_command(ffmpeg: str, path: str, fps: int, *, size: tuple,
                       crop: tuple | None = None, cursor: bool = True,
                       quality: str = "balanced", audio_device: str | None = None,
                       hardware: bool = True, adapter: int = 0,
                       output: int = 0) -> list[str]:
    """The ffmpeg command for a GPU recording. `size` is the output (w, h) in
    physical pixels; `crop` is (x, y) of that area inside the screen, or None
    for the whole screen. `adapter`/`output` pick the graphics chip and the
    screen on it (see gpu_target). Split out so it can be read and tested."""
    w, h = _even(size[0]), _even(size[1])
    grab = (f"ddagrab=output_idx={output}:framerate={fps}"
            f":draw_mouse={1 if cursor else 0}")
    if crop is not None:
        grab += f":video_size={w}x{h}:offset_x={crop[0]}:offset_y={crop[1]}"
    chain = grab + ",scale_d3d11=format=nv12"
    if not hardware:                   # software MFT wants frames in memory
        chain += ",hwdownload,format=nv12"
    cmd = [ffmpeg, "-hide_banner", "-loglevel", "error", "-y"]
    if adapter:                        # a screen on the second graphics chip
        cmd += ["-init_hw_device", f"d3d11va=dda:{adapter}", "-filter_hw_device", "dda"]
    if audio_device is not None:
        cmd += ["-f", "dshow", "-thread_queue_size", "1024",
                "-i", f"audio={audio_device}"]
    cmd += ["-filter_complex", chain + "[v]", "-map", "[v]"]
    if audio_device is not None:
        cmd += ["-map", "0:a"]
    cmd += ["-c:v", "h264_mf", "-b:v", str(gpu_bitrate(w, h, fps, quality))]
    if hardware:
        cmd += ["-hw_encoding", "1"]
    if audio_device is not None:
        cmd += ["-c:a", "aac", "-b:a", "160k", "-af", "aresample=async=1000"]
    cmd += ["-movflags", "+faststart", path]
    return cmd


def gpu_recording_possible() -> bool:
    return IS_WIN and bool(find_ffmpeg())


def dxgi_outputs() -> list[dict]:
    """Every screen as Desktop Duplication numbers it: which graphics chip
    (adapter) and which of its outputs, with its desktop rectangle in
    physical pixels. Qt counts screens its own way, so this is how a Qt
    screen is found again for ddagrab. Windows only; [] elsewhere."""
    if not IS_WIN:
        return []
    import ctypes
    from ctypes import POINTER, byref, c_uint, c_ulong, c_long, c_void_p, wintypes

    class GUID(ctypes.Structure):
        _fields_ = [("a", c_ulong), ("b", ctypes.c_ushort), ("c", ctypes.c_ushort),
                    ("d", ctypes.c_ubyte * 8)]

    class OUTPUT_DESC(ctypes.Structure):
        _fields_ = [("DeviceName", wintypes.WCHAR * 32), ("Desktop", wintypes.RECT),
                    ("Attached", wintypes.BOOL), ("Rotation", c_uint),
                    ("Monitor", wintypes.HMONITOR)]

    def call(obj, index, restype, argtypes=(), *args):
        vtbl = ctypes.cast(obj, POINTER(POINTER(c_void_p))).contents
        proto = ctypes.WINFUNCTYPE(restype, c_void_p, *argtypes)
        return proto(vtbl[index])(obj, *args)

    OUT_PTR = (c_uint, POINTER(c_void_p))

    iid = GUID(0x770AAE78, 0xF26F, 0x4DBA,
               (ctypes.c_ubyte * 8)(0xA8, 0x29, 0x25, 0x3C, 0x83, 0xD1, 0xB3, 0x87))
    factory = c_void_p()
    try:
        if ctypes.windll.dxgi.CreateDXGIFactory1(byref(iid), byref(factory)) != 0:
            return []
    except (OSError, AttributeError):
        return []
    found = []
    try:
        a = 0
        while True:
            adapter = c_void_p()        # IDXGIFactory1::EnumAdapters1 = 12
            if call(factory, 12, c_long, OUT_PTR, a, byref(adapter)) != 0:
                break
            o = 0
            while True:
                out = c_void_p()        # IDXGIAdapter::EnumOutputs = 7
                if call(adapter, 7, c_long, OUT_PTR, o, byref(out)) != 0:
                    break
                desc = OUTPUT_DESC()    # IDXGIOutput::GetDesc = 7
                if call(out, 7, c_long, (POINTER(OUTPUT_DESC),), byref(desc)) == 0 \
                        and desc.Attached:
                    r = desc.Desktop
                    found.append({"name": desc.DeviceName, "adapter": a, "output": o,
                                  "rect": QRect(r.left, r.top, r.right - r.left,
                                                r.bottom - r.top)})
                call(out, 2, c_ulong)   # Release
                o += 1
            call(adapter, 2, c_ulong)
            a += 1
    except Exception:               # never let this stop a recording: the
        found = []                  # caller falls back to the normal recorder
    finally:
        call(factory, 2, c_ulong)
    return found


def gpu_target(region: QRect | None, outputs: list[dict] | None = None):
    """What a GPU recording of `region` (Qt coordinates; None = everything)
    captures: (adapter, output, size, crop) in physical pixels. None when the
    area spans screens — one Desktop Duplication stream is one screen, so the
    normal recorder takes those."""
    screens = QApplication.screens()
    if region is None or not region.isValid():
        if len(screens) != 1:
            return None
        region = screens[0].geometry()
    scr = next((s for s in screens if s.geometry().contains(region)), None)
    if scr is None:
        return None
    g, dpr = scr.geometry(), scr.devicePixelRatio()
    outputs = dxgi_outputs() if outputs is None else outputs
    match = (next((o for o in outputs if o["name"] == scr.name()), None)
             or next((o for o in outputs if o["rect"].topLeft() == g.topLeft()), None))
    if match is None and len(screens) > 1:
        return None
    adapter, output = (match["adapter"], match["output"]) if match else (0, 0)
    size, crop = (round(g.width() * dpr), round(g.height() * dpr)), None
    if region != g:
        crop = (round((region.x() - g.x()) * dpr) // 2 * 2,
                round((region.y() - g.y()) * dpr) // 2 * 2)
        size = (round(region.width() * dpr), round(region.height() * dpr))
    return adapter, output, size, crop


def concat_command(ffmpeg: str, list_file: str, dst: str) -> list[str]:
    """Paused GPU recordings come in pieces: join them, copying the streams."""
    return [ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-f", "concat",
            "-safe", "0", "-i", list_file, "-c", "copy", "-movflags", "+faststart", dst]


class HardwareRecorder(QObject):
    """ffmpeg capturing and encoding on the GPU by itself. Same signals as
    ScreenRecorder, plus `fell_back` when it can't run on this machine.

    ffmpeg can't pause a capture, so pausing ends the current piece and
    resuming starts the next; stopping joins the pieces (streams copied)."""

    started   = Signal(str)
    tick      = Signal(float)
    finishing = Signal()
    finished  = Signal(str)
    failed    = Signal(str)
    fell_back = Signal(str)        # gave up early: use the CPU recorder

    EARLY_MS = 2000

    def __init__(self, parent=None):
        super().__init__(parent)
        self._proc: subprocess.Popen | None = None
        self._err: list[str] = []
        self._path = ""
        self._pieces: list[str] = []
        self._closing: list[threading.Thread] = []
        self._args: tuple = ()
        self._t0 = 0.0
        self._banked = 0.0              # seconds recorded before the last pause
        self.active = False
        self.paused = False
        self._clock = QTimer(self)
        self._clock.setInterval(200)
        self._clock.timeout.connect(self._on_clock)
        self._watchdog = QTimer(self)
        self._watchdog.setSingleShot(True)
        self._watchdog.timeout.connect(self._check_early)

    def start(self, config: "RecordConfig", target: tuple,
              audio_device: str | None) -> bool:
        ffmpeg = find_ffmpeg()
        if not ffmpeg or self.active:
            return False
        try:
            self._path = config.new_path()
        except OSError as e:
            self.failed.emit(f"Recordings cannot be written to {config.out_dir}\n\n{e}")
            return False
        adapter, output, size, crop = target
        self._args = (ffmpeg, config.fps, dict(
            size=size, crop=crop, cursor=config.cursor, quality=config.quality,
            audio_device=audio_device, adapter=adapter, output=output))
        self._pieces, self._closing = [], []
        self._banked, self.paused = 0.0, False
        if not self._launch():
            return False
        self.active = True
        self._clock.start()
        self._watchdog.start(self.EARLY_MS)
        self.started.emit(self._path)
        return True

    def _command(self, path: str) -> list[str]:
        ffmpeg, fps, kw = self._args
        return gpu_record_command(ffmpeg, path, fps, **kw)

    def _launch(self) -> bool:
        base = os.path.splitext(self._path)[0]
        piece = f"{base}.part{len(self._pieces)}.mp4"
        try:
            self._proc = subprocess.Popen(self._command(piece), stdin=subprocess.PIPE,
                                          stdout=subprocess.DEVNULL,
                                          stderr=subprocess.PIPE,
                                          creationflags=_NO_WINDOW)
        except OSError as e:
            if not self._pieces:
                self.fell_back.emit(str(e))
            else:
                self.failed.emit(f"The recording couldn't carry on: {e}")
            return False
        self._pieces.append(piece)
        self._err = []
        threading.Thread(target=self._drain, args=(self._proc,), daemon=True,
                         name="gpu-rec-stderr").start()
        self._t0 = time.perf_counter()
        return True

    def _drain(self, proc):
        for raw in iter(proc.stderr.readline, b""):
            self._err.append(raw.decode("utf-8", "replace").rstrip())
            del self._err[:-20]
        try:
            proc.stderr.close()
        except OSError:
            pass

    def _died(self) -> bool:
        return self._proc is not None and self._proc.poll() is not None

    def _check_early(self):
        if self.active and self._died():
            self._shut(delete=True)
            self.fell_back.emit("\n".join(self._err[-5:]) or "ffmpeg stopped")

    def _on_clock(self):
        self.tick.emit(self.elapsed())
        if self.active and self._died() and not self._watchdog.isActive():
            err = "\n".join(self._err[-5:]) or "ffmpeg stopped unexpectedly"
            self._shut(delete=False)
            self.failed.emit(f"The recording stopped: {err}")

    def _shut(self, delete: bool):
        self.active = False
        self._clock.stop()
        self._watchdog.stop()
        if delete:
            for piece in self._pieces:
                try:
                    os.remove(piece)
                except OSError:
                    pass

    def elapsed(self) -> float:
        if not self._t0:
            return 0.0
        running = 0.0 if self.paused else time.perf_counter() - self._t0
        return max(0.0, self._banked + running)

    @staticmethod
    def _quit(proc) -> int:
        try:
            proc.stdin.write(b"q")              # ffmpeg's own "finish up" key
            proc.stdin.flush()
            proc.stdin.close()
        except OSError:
            pass
        try:
            return proc.wait(timeout=30)
        except subprocess.TimeoutExpired:
            proc.kill()
            return -1

    def pause(self, on: bool):
        if not self.active or on == self.paused:
            return
        if on:
            self._banked += time.perf_counter() - self._t0
            self.paused = True
            self._watchdog.stop()
            proc, self._proc = self._proc, None
            th = threading.Thread(target=self._quit, args=(proc,), daemon=True,
                                  name="gpu-rec-piece")
            th.start()
            self._closing.append(th)
        else:
            self.paused = False
            if not self._launch():
                self._shut(delete=False)

    def stop(self):
        if not self.active:
            return
        self.active = False
        self._clock.stop()
        self._watchdog.stop()
        if not self.paused:
            self._banked += time.perf_counter() - self._t0
        self.paused = True                      # the clock stands still now
        self.finishing.emit()
        proc, self._proc = self._proc, None
        pieces, closing, path = list(self._pieces), list(self._closing), self._path
        ffmpeg = self._args[0]

        def close_out():
            rc = self._quit(proc) if proc is not None else 0
            for th in closing:
                th.join(timeout=35)
            done = [p for p in pieces if os.path.exists(p) and os.path.getsize(p) > 0]
            error = "" if done else ("\n".join(self._err[-5:]) or f"ffmpeg exited with {rc}")
            if len(done) == 1:
                try:
                    os.replace(done[0], path)
                except OSError as e:
                    error = str(e)
            elif done:
                listing = os.path.splitext(path)[0] + ".parts.txt"
                with open(listing, "w", encoding="utf-8") as f:
                    for piece in done:
                        f.write("file '" + piece.replace("'", "'\\''") + "'\n")
                try:
                    out = subprocess.run(concat_command(ffmpeg, listing, path),
                                         capture_output=True, text=True, timeout=300,
                                         creationflags=_NO_WINDOW)
                    if out.returncode != 0:
                        error = (out.stderr or "").strip()[-300:] or "joining failed"
                except (OSError, subprocess.TimeoutExpired) as e:
                    error = str(e)
                for leftover in done + [listing]:
                    if not error or leftover == listing:
                        try:
                            os.remove(leftover)
                        except OSError:
                            pass
            try:
                if not error:
                    self.finished.emit(path)
                else:
                    self.failed.emit(error)
            except RuntimeError:
                pass

        threading.Thread(target=close_out, daemon=True, name="gpu-rec-finish").start()


# ── Exporting a finished recording ────────────────────────────────────────────
#
# Recording always produces an MP4: H.264 encodes in real time, which is the
# one hard requirement while frames are arriving. Everything else is a
# conversion afterwards.
#
# GIF in particular *cannot* be done live. A good GIF needs a colour palette
# chosen from the whole clip — palettegen has to see the footage before
# paletteuse can quantise it — so it is inherently a second pass. Encoding one
# live means a fixed 256-colour palette and a file several times larger for
# visibly worse output.

EXPORT_FORMATS = {
    "gif":  ("GIF",  ".gif",
             "Loops by itself in chat, issues and docs. No sound, and large "
             "past a few seconds."),
    "webm": ("WebM", ".webm",
             "VP9 — noticeably smaller than MP4 for the web. Keeps sound."),
    "mp4":  ("MP4",  ".mp4",
             "H.264. Re-encode to shrink a recording or scale it down."),
}

GIF_WIDTHS = [0, 1280, 960, 720, 480]        # 0 = leave it alone
GIF_RATES = [10, 12, 15, 24]


def convert_command(ffmpeg: str, src: str, dst: str, kind: str,
                    fps: int = 12, width: int = 0,
                    progress: bool = True) -> list[str]:
    """The ffmpeg command line for one export. Split out so it can be read
    (and tested) without running anything."""
    if kind not in EXPORT_FORMATS:
        raise RecorderError(f"unknown export format: {kind}")

    cmd = [ffmpeg, "-hide_banner", "-loglevel", "error", "-y"]
    if progress:
        cmd += ["-progress", "pipe:1", "-nostats"]
    cmd += ["-i", src]

    # -2 rather than -1: H.264 and VP9 both want even dimensions, and it costs
    # a GIF nothing.
    scale = f"scale={width}:-2:flags=lanczos" if width else ""

    if kind == "gif":
        chain = [f"fps={fps}"]
        if scale:
            chain.append(scale)
        chain.append(
            "split[s0][s1];[s0]palettegen=stats_mode=diff[p];"
            "[s1][p]paletteuse=dither=bayer:bayer_scale=5:diff_mode=rectangle")
        cmd += ["-filter_complex", ",".join(chain), "-loop", "0", "-an"]
    elif kind == "webm":
        if scale:
            cmd += ["-vf", scale]
        cmd += ["-c:v", "libvpx-vp9", "-crf", "34", "-b:v", "0",
                "-row-mt", "1", "-deadline", "good", "-cpu-used", "4",
                "-c:a", "libopus", "-b:a", "128k"]
    else:                                     # mp4
        if scale:
            cmd += ["-vf", scale]
        cmd += ["-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
                "-pix_fmt", "yuv420p", "-movflags", "+faststart",
                "-c:a", "aac", "-b:a", "160k"]

    cmd.append(dst)
    return cmd


def trim_command(ffmpeg: str, src: str, dst: str, start: float, end: float,
                 progress: bool = True) -> list[str]:
    """Keep `start`–`end` seconds of a recording. Re-encoded rather than
    stream-copied: a copy can only cut on a keyframe, which is seconds away
    in a screen recording, so the cut would land in the wrong place."""
    if end <= start:
        raise RecorderError("the end has to come after the start")
    cmd = [ffmpeg, "-hide_banner", "-loglevel", "error", "-y"]
    if progress:
        cmd += ["-progress", "pipe:1", "-nostats"]
    # -ss before -i seeks fast; re-encoding makes it frame-accurate anyway.
    cmd += ["-ss", f"{start:.3f}", "-i", src, "-t", f"{end - start:.3f}",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
            "-pix_fmt", "yuv420p", "-movflags", "+faststart",
            "-c:a", "aac", "-b:a", "160k", dst]
    return cmd


def trimmed_path(src: str) -> str:
    base, ext = os.path.splitext(src)
    candidate, n = f"{base}-trimmed{ext}", 2
    while os.path.exists(candidate):
        candidate = f"{base}-trimmed-{n}{ext}"
        n += 1
    return candidate


def frame_at(path: str, seconds: float, width: int = 560) -> bytes:
    """One frame of a video as PNG bytes (b"" if it cannot be had)."""
    ffmpeg = find_ffmpeg()
    if not ffmpeg or not os.path.exists(path):
        return b""
    cmd = [ffmpeg, "-hide_banner", "-loglevel", "error",
           "-ss", f"{max(0.0, seconds):.3f}", "-i", path, "-frames:v", "1",
           "-vf", f"scale={width}:-2", "-f", "image2pipe", "-vcodec", "png",
           "pipe:1"]
    try:
        out = subprocess.run(cmd, capture_output=True, timeout=15,
                             creationflags=_NO_WINDOW)
    except (OSError, subprocess.TimeoutExpired):
        return b""
    return out.stdout if out.returncode == 0 else b""


def export_path(src: str, kind: str) -> str:
    """Sibling of the recording, with the new extension — and never clobbering
    something already there."""
    ext = EXPORT_FORMATS[kind][1]
    base = os.path.splitext(src)[0]
    candidate = base + ext
    n = 2
    while os.path.exists(candidate):
        candidate = f"{base}-{n}{ext}"
        n += 1
    return candidate


def probe_duration(path: str) -> float:
    """Seconds of media in `path`, 0.0 if it cannot be told.

    Parsed out of ffmpeg's own banner rather than ffprobe: the single-file
    Windows build bundles ffmpeg only, so ffprobe is not there to call.
    """
    ffmpeg = find_ffmpeg()
    if not ffmpeg or not os.path.exists(path):
        return 0.0
    try:
        out = subprocess.run([ffmpeg, "-hide_banner", "-i", path],
                             capture_output=True, text=True, timeout=20,
                             creationflags=_NO_WINDOW)
    except (OSError, subprocess.TimeoutExpired):
        return 0.0
    for line in (out.stderr or "").splitlines():
        line = line.strip()
        if line.startswith("Duration:"):
            stamp = line.split("Duration:", 1)[1].split(",", 1)[0].strip()
            try:
                h, m, sec = stamp.split(":")
                return int(h) * 3600 + int(m) * 60 + float(sec)
            except ValueError:
                return 0.0
    return 0.0


class MediaConverter(QObject):
    """Runs one ffmpeg conversion off the GUI thread, reporting progress."""

    progress = Signal(float)     # 0.0 – 1.0, or -1 when it cannot be known
    done     = Signal(str)       # output path
    failed   = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._proc: subprocess.Popen | None = None
        self._thread: threading.Thread | None = None
        self._cancelled = False

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self, src: str, dst: str, kind: str, *, fps: int = 12,
              width: int = 0, duration: float = 0.0,
              trim: tuple[float, float] | None = None) -> bool:
        if self.running:
            return False
        ffmpeg = find_ffmpeg()
        if not ffmpeg:
            self.failed.emit(FFMPEG_HELP)
            return False
        if not os.path.exists(src):
            self.failed.emit("The recording is no longer on disk.")
            return False

        self._cancelled = False
        if kind == "trim":
            start, end = trim
            cmd = trim_command(ffmpeg, src, dst, start, end)
            duration = end - start
        else:
            cmd = convert_command(ffmpeg, src, dst, kind, fps=fps, width=width)
        self._thread = threading.Thread(
            target=self._run, args=(cmd, dst, duration), daemon=True,
            name="video-convert")
        self._thread.start()
        return True

    def run(self, cmd: list[str], dst: str, duration: float = 0.0) -> bool:
        """Any prepared ffmpeg command line, reported like a conversion."""
        if self.running:
            return False
        self._cancelled = False
        self._thread = threading.Thread(
            target=self._run, args=(cmd, dst, duration), daemon=True,
            name="video-convert")
        self._thread.start()
        return True

    def cancel(self):
        self._cancelled = True
        if self._proc and self._proc.poll() is None:
            try:
                self._proc.terminate()
            except Exception:
                pass

    def _run(self, cmd: list[str], dst: str, duration: float):
        def emit(signal, arg):
            try:
                signal.emit(arg)
            except RuntimeError:            # dialog closed underneath us
                pass
        try:
            self._proc = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                creationflags=_NO_WINDOW)
        except OSError as e:
            emit(self.failed, f"could not start ffmpeg: {e}")
            return

        errors: list[str] = []
        drain = threading.Thread(
            target=lambda: errors.extend(
                l.decode("utf-8", "replace").rstrip()
                for l in self._proc.stderr if l.strip()),
            daemon=True)
        drain.start()

        for raw in self._proc.stdout:
            line = raw.decode("utf-8", "replace").strip()
            if line.startswith("out_time_us=") and duration > 0:
                try:
                    done = int(line.split("=", 1)[1]) / 1_000_000
                    emit(self.progress, max(0.0, min(1.0, done / duration)))
                except ValueError:
                    pass
            elif line == "progress=end":
                emit(self.progress, 1.0)
        code = self._proc.wait()
        drain.join(timeout=2)
        for pipe in (self._proc.stdout, self._proc.stderr):
            try:
                pipe.close()
            except OSError:
                pass

        if self._cancelled:
            try:
                os.remove(dst)
            except OSError:
                pass
            return
        if code != 0:
            tail = "\n".join(errors[-6:]) or f"ffmpeg exited with code {code}"
            try:
                os.remove(dst)
            except OSError:
                pass
            emit(self.failed, tail)
            return
        emit(self.done, dst)


class CameraFeed(QObject):
    """A camera through ffmpeg, as square frames — off the GUI thread."""

    frame = Signal(QImage)
    ended = Signal(str)            # why it stopped; "" when asked to

    def __init__(self, side: int = 480, parent=None):
        super().__init__(parent)
        self.side = side
        self._proc: subprocess.Popen | None = None
        self._stopping = False

    def start(self, cmd: list[str]) -> bool:
        try:
            self._proc = subprocess.Popen(cmd, stdout=subprocess.PIPE,
                                          stderr=subprocess.PIPE,
                                          creationflags=_NO_WINDOW)
        except OSError as e:
            self.error = str(e)
            return False
        threading.Thread(target=self._read, daemon=True, name="camera").start()
        return True

    def _read(self):
        size, proc = self.side * self.side * 4, self._proc
        while True:
            data = proc.stdout.read(size)
            if not data or len(data) < size:
                break
            img = QImage(data, self.side, self.side, self.side * 4,
                         QImage.Format.Format_ARGB32).copy()
            try:
                self.frame.emit(img)
            except RuntimeError:
                return
        reason = ""
        if not self._stopping:
            err = (proc.stderr.read() or b"").decode("utf-8", "replace").strip()
            reason = err.splitlines()[-1] if err else "the camera stopped"
        for pipe in (proc.stdout, proc.stderr):
            try:
                pipe.close()
            except OSError:
                pass
        try:
            self.ended.emit(reason)
        except RuntimeError:
            pass

    def stop(self):
        self._stopping = True
        proc, self._proc = self._proc, None
        if proc and proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                proc.kill()
