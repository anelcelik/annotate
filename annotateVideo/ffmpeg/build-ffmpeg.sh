#!/usr/bin/env bash
# build-ffmpeg.sh — a lean ffmpeg.exe with exactly what Screen Annotator Pro
# uses, cross-compiled for 64-bit Windows on Linux (CI: ubuntu-24.04).
#
#   apt install mingw-w64 nasm pkg-config libz-mingw-w64-dev
#   bash build-ffmpeg.sh OUTDIR
#
# The Gyan "essentials" build the app shipped before is 105 MB, of which the
# app touched a small corner; this one is built from the same FFmpeg release
# with everything else left out. Every source below is pinned (tarball
# SHA-256 or git commit). tests/test_ffmpeg_build.py checks the result has
# every encoder, filter and format the app calls, so a component missing here
# fails CI rather than a recording on a user's machine.
#
# License: GPL v3 (x264 is GPL). ffmpeg.exe is a separate program the app
# runs; this script plus the pinned sources is its corresponding source.
set -euo pipefail

OUT="$(realpath -m "${1:?usage: build-ffmpeg.sh OUTDIR}")"
WORK="${WORK:-$(mktemp -d)}"
PREFIX="$WORK/prefix"
HOST=x86_64-w64-mingw32
JOBS="$(nproc)"

FFMPEG_VER=9.0.2
FFMPEG_SHA256=8c3850283eb25fa026482078a04051e0be17347b09ef81a0849bec15a96e002e
X264_COMMIT=b35605ace3ddf7c1a5d67a2eb553f034aef41d55      # "stable" branch
VPX_TAG=v1.15.2
VPX_COMMIT=d168454ecd099805c675d4a98c66f4891373302a
OPUS_VER=1.5.2
OPUS_SHA256=65c1d2f78b9f2fb20082c38cbe47c951ad5839345876e46941612ee87f9a7ce1

mkdir -p "$OUT" "$PREFIX" "$WORK/src"
cd "$WORK/src"
export PKG_CONFIG_PATH="$PREFIX/lib/pkgconfig" PKG_CONFIG_LIBDIR="$PREFIX/lib/pkgconfig"

fetch() {   # url sha256 file
  curl -fsSL --retry 3 -o "$3" "$1"
  echo "$2  $3" | sha256sum -c -
}

git_at() {  # url commit dir [branch/tag]
  git clone --quiet ${4:+--branch "$4"} --depth 50 "$1" "$3"
  git -C "$3" checkout --quiet "$2"
  test "$(git -C "$3" rev-parse HEAD)" = "$2"
}

echo "── x264"
git_at https://code.videolan.org/videolan/x264.git "$X264_COMMIT" x264 stable
( cd x264
  ./configure --host=$HOST --cross-prefix=$HOST- --prefix="$PREFIX" \
      --enable-static --disable-cli --enable-strip --enable-pic
  make -j"$JOBS" && make install )

echo "── libvpx (VP9 encoder, for WebM export)"
git_at https://github.com/webmproject/libvpx.git "$VPX_COMMIT" libvpx "$VPX_TAG"
( cd libvpx
  CROSS=$HOST- ./configure --target=x86_64-win64-gcc --prefix="$PREFIX" \
      --enable-static --disable-shared --disable-examples --disable-tools \
      --disable-docs --disable-unit-tests --disable-vp8 --disable-vp9-decoder \
      --as=nasm
  make -j"$JOBS" && make install )

echo "── opus (audio for WebM export)"
fetch "https://downloads.xiph.org/releases/opus/opus-$OPUS_VER.tar.gz" "$OPUS_SHA256" opus.tar.gz
tar xf opus.tar.gz
( cd "opus-$OPUS_VER"
  ./configure --host=$HOST --prefix="$PREFIX" --enable-static --disable-shared \
      --disable-doc --disable-extra-programs --disable-deep-plc --disable-dred \
      --disable-osce
  make -j"$JOBS" && make install )

echo "── ffmpeg $FFMPEG_VER"
fetch "https://ffmpeg.org/releases/ffmpeg-$FFMPEG_VER.tar.xz" "$FFMPEG_SHA256" ffmpeg.tar.xz
tar xf ffmpeg.tar.xz
list() { local IFS=,; echo "$*"; }

# What the app runs, and why:
#   recording (CPU)  rawvideo pipe in + dshow mic → libx264 + aac → mp4
#   recording (GPU)  ddagrab → scale_d3d11 [→ hwdownload,format] → h264_mf
#   export           gif (fps, scale, split, palettegen, paletteuse),
#                    webm (libvpx-vp9 + libopus), mp4 (libx264 + aac)
#   trim / preview   decode h264/aac, re-encode; one frame as png
#   PC sound         wav in, adelay/atrim/amix/aresample, aac
#   paused GPU takes concat demuxer, streams copied
#   webcam bubble    dshow video (raw, mjpeg or h264) → scale/crop/fps → bgra
#   tests on CI      lavfi test sources
( cd "ffmpeg-$FFMPEG_VER"
  ./configure \
      --prefix="$WORK/ffmpeg-install" --arch=x86_64 --target-os=mingw32 \
      --cross-prefix=$HOST- --pkg-config=pkg-config --pkg-config-flags=--static \
      --extra-cflags="-I$PREFIX/include" \
      --extra-ldflags="-L$PREFIX/lib -static -static-libgcc" \
      --enable-gpl --enable-libx264 --enable-libvpx --enable-libopus \
      --disable-autodetect --enable-zlib --enable-w32threads \
      --enable-d3d11va --enable-mediafoundation \
      --disable-everything --disable-doc --disable-debug --disable-network \
      --disable-ffplay --disable-ffprobe \
      --enable-protocol=$(list file pipe) \
      --enable-indev=$(list dshow lavfi) \
      --enable-demuxer=$(list rawvideo mov matroska concat wav gif image2 image2pipe mjpeg h264 aac) \
      --enable-muxer=$(list mp4 mov webm matroska gif image2 image2pipe rawvideo wav null) \
      --enable-encoder=$(list libx264 h264_mf libvpx_vp9 libopus aac gif png rawvideo pcm_s16le wrapped_avframe) \
      --enable-decoder=$(list h264 aac pcm_s16le png rawvideo vp9 opus gif mjpeg) \
      --enable-parser=$(list h264 aac png vp9 opus mjpeg) \
      --enable-bsf=$(list vp9_superframe aac_adtstoasc h264_mp4toannexb extract_extradata null) \
      --enable-filter=$(list ddagrab scale_d3d11 hwdownload hwupload format scale fps \
          split crop palettegen paletteuse amix adelay atrim aresample asetpts \
          setpts null anull aformat trim hflip vflip transpose pad copy \
          testsrc testsrc2 color sine anullsrc concat)
  make -j"$JOBS"
  $HOST-strip ffmpeg.exe
  cp ffmpeg.exe "$OUT/ffmpeg.exe"
  cp COPYING.GPLv3 "$OUT/ffmpeg-LICENSE.txt" )

cat > "$OUT/ffmpeg-README.txt" <<README
ffmpeg.exe in Screen Annotator Pro
==================================

FFmpeg $FFMPEG_VER, built from source for this app with only the parts it
uses. License: GNU General Public License v3 (it includes x264).

Corresponding source:
  FFmpeg  https://ffmpeg.org/releases/ffmpeg-$FFMPEG_VER.tar.xz  (sha256 $FFMPEG_SHA256)
  x264    https://code.videolan.org/videolan/x264  commit $X264_COMMIT  (GPL v2+)
  libvpx  https://github.com/webmproject/libvpx  $VPX_TAG ($VPX_COMMIT)  (BSD)
  Opus    https://downloads.xiph.org/releases/opus/opus-$OPUS_VER.tar.gz  (BSD)
  Build script: ffmpeg/build-ffmpeg.sh in the app's source; the exact
  configure line is printed by "ffmpeg -buildconf".
README
ls -la "$OUT"
