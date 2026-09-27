"""The bundled ffmpeg has every part the app calls.

The shipped ffmpeg.exe is built from source with everything else left out
(ffmpeg/build-ffmpeg.sh). A part missing there would only show up as a
failed recording or export on someone's PC, so CI checks the list here —
against the exact exe that gets bundled (SCREEN_ANNOTATOR_FFMPEG)."""
import os
import subprocess
import sys

import pytest

import video_recorder as VR

FF = os.environ.get("SCREEN_ANNOTATOR_FFMPEG") or VR.find_ffmpeg()
WIN = sys.platform == "win32"
pytestmark = pytest.mark.skipif(not FF, reason="no ffmpeg")


def names(flag: str) -> set[str]:
    out = subprocess.run([FF, "-hide_banner", flag], capture_output=True,
                         text=True, timeout=60).stdout
    found = set()
    for line in out.splitlines():
        parts = line.split()
        if flag == "-bsfs" and len(parts) == 1:
            found.add(parts[0])
        elif len(parts) >= 2:
            found.update(parts[1].split(","))
    return found


def missing(flag, wanted):
    return sorted(set(wanted) - names(flag))


def test_encoders():
    wanted = ["libx264", "libvpx-vp9", "libopus", "aac", "gif", "png", "rawvideo"]
    assert not missing("-encoders", wanted + (["h264_mf"] if WIN else []))


def test_decoders():
    assert not missing("-decoders", ["h264", "aac", "pcm_s16le", "png", "rawvideo",
                                     "vp9", "opus", "gif", "mjpeg"])


def test_filters():
    wanted = ["scale", "fps", "split", "crop", "palettegen", "paletteuse", "amix",
              "adelay", "atrim", "aresample", "asetpts", "format", "hwdownload",
              "testsrc", "color", "sine"]
    assert not missing("-filters", wanted + (["ddagrab", "scale_d3d11"] if WIN else []))


def test_formats_and_devices():
    assert not missing("-muxers", ["mp4", "webm", "gif", "image2pipe", "rawvideo"])
    assert not missing("-demuxers", ["rawvideo", "mov", "concat", "wav", "matroska"])
    assert not missing("-devices", ["lavfi"] + (["dshow"] if WIN else []))
    assert not missing("-bsfs", ["vp9_superframe"])
