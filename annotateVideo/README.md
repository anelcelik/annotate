# Screen Annotator Pro — Video

> Draw, highlight, annotate, redact and OCR anything on your screen — live, in
> real time — and **record the whole thing to an MP4** with every mark baked in.

This is the recording branch of Screen Annotator Pro: the same fullscreen
transparent overlay, plus a screen recorder that captures the desktop with your
annotations composited into each frame. Everything runs locally — no cloud, no
account, no upload.

Based on **version 4.0.0** · recording is the new feature in this tree

---

## How it works

Screen Annotator Pro creates a transparent, click-through window that covers your entire screen (or all monitors). When you activate it, the overlay intercepts mouse input so you can draw shapes, write text, and apply redactions directly on top of whatever application is underneath. When you hide or pause the overlay, the underlying apps regain full mouse control instantly — no restart, no alt-tab, no disruption.

The app lives in the system tray and is toggled with a global hotkey (`Ctrl+Shift+A` by default) so you can flip it on and off in under a second during a presentation, meeting, or tutorial recording.

---

## Features

### Drawing Tools

| Tool | Key | Description |
|---|---|---|
| Select / Move | `V` | Click and drag any existing shape |
| Pen | `P` | Freehand stroke |
| Line | `L` | Straight line · **Shift** → 45° snap |
| Arrow | `A` | Line with arrowhead · **Shift** → 45° snap |
| Rectangle | `R` | Outline rectangle · **Shift** → perfect square |
| Circle | `O` | Outline ellipse · **Shift** → perfect circle |
| Ruler | `U` | Line with pixel measurement label · **Shift** → 45° snap |
| Eraser | `E` | Freehand erase (width = stroke × 4) |
| Laser Pointer | `I` | Real-time glowing dot — no marks left, OS cursor hidden |

### Annotation Tools

| Tool | Key | Description |
|---|---|---|
| Text | `T` | Place a text label (size controlled by the Text size slider) |
| Callout | `K` | Auto-numbered filled circles |
| Steps | `S` | Auto-numbered step squares |
| Highlight | `H` | Semi-transparent colour band |

### Redact Tools

| Tool | Key | Description |
|---|---|---|
| Blur | `Z` | Gaussian blur over a selected region |
| Pixelate | `X` | Mosaic / pixel-art redaction |
| Black Box | `D` | Solid opaque black redaction |

### OCR & Translate

| Tool | Key | Description |
|---|---|---|
| Snip & Read | `J` | Drag a region → extract text + translate |

### Recording

| Control | Key | Description |
|---|---|---|
| Record / Stop | `Ctrl+Shift+R` | Records the screen to MP4 with the annotations in it |

---

## Recording

Press **Record** on the dock (or `Ctrl+Shift+R`, or the tray menu). A small
red HUD appears with the elapsed time and Pause / Stop; drag it anywhere.
Press Stop and the file is already on disk — a panel offers **Play**,
**Show in folder**, **Save as…** and **Delete**.

Files go to `Videos/ScreenAnnotatorPro/annotation_YYYYMMDD_HHMMSS.mp4`
(H.264 + AAC), changeable in Settings.

### Exporting — GIF, WebM, smaller MP4

**Export…** on that panel converts the recording. Later on, the tray menu's
**Convert a recording…** opens any file you already have.

| Format | Good for | Notes |
|---|---|---|
| **GIF** | Chat, issue trackers, docs — it loops by itself and needs no player | No sound. Gets large fast: pick a width and 10–12 fps |
| **WebM** | The web — VP9 is noticeably smaller than the same MP4 | Keeps sound. Slower to encode |
| **MP4** | Shrinking or scaling down a recording you already have | H.264, plays everywhere |

Any of them can be scaled down on the way out (1280 / 960 / 720 / 480 px wide);
GIF also re-times to 10, 12, 15 or 24 fps.

Recording always writes MP4 first, and export is always a second pass over
that file. That is not laziness about GIF — it is the only way to make a good
one. A GIF has a 256-colour palette, and choosing a decent palette means
looking at the footage before quantising it (`palettegen` then `paletteuse`).
Encoding a GIF live would mean a fixed generic palette: visibly worse, and
several times larger. H.264, meanwhile, is the one codec that reliably encodes
in real time while frames are still arriving, which is the actual constraint
during a recording.

### What ends up in the frame

Everything you drew, and nothing you didn't. Arrows, callouts, highlights,
blur and pixelate regions, the laser pointer's live glow — all of it is
painted into each frame at full resolution, so it comes out crisp rather than
resampled. The dock, the HUD and the selection outline around a selected shape
are *not* recorded: they are controls, not annotations.

On Windows 10 2004+ this is exact. The app asks the compositor to leave its own
windows out of any screen capture (`WDA_EXCLUDEFROMCAPTURE`) — you still see the
overlay and the dock, the recording doesn't — and then composites the shapes
itself.

No other platform can do that. Wayland's screencopy hands over the composited
output with no per-window opt-out, and X11 has nothing either, so anything
visible is in the file. There the app moves its own chrome out of the frame
instead, automatically:

- **Recording an area** — the dock slides just outside the recorded rectangle
  and stays fully usable. Nothing is lost.
- **Recording everything** — there is no outside, so the dock hides for the
  duration and comes back when you stop. Tool shortcuts still work; stop with
  `Ctrl+Shift+R` or the tray icon.
- **No separate HUD** on these platforms — the dock's own Record cell turns
  red, counts up and stops the recording, so there is no second window to keep
  out of the way.

The recorder also skips its own compositing here, since the grab already
contains the overlay and drawing the shapes again would double them up.

### Settings

| Setting | Choices | Notes |
|---|---|---|
| Area | All monitors · Monitor in use · Pick an area | "Monitor in use" means the one the cursor is on when you hit Record |
| Frame rate | 15 · 24 · 30 · 60 fps | 30 is the sensible default |
| Quality | High (CRF 18) · Balanced (23) · Small file (28) | x264, `veryfast` preset |
| Show the cursor | on / off | A drawn pointer on Windows; the real one on wlroots |
| Record the microphone | on / off | Pause is disabled while the mic is live — the mic has no pause |
| Save to | any folder | Defaults to `Videos/ScreenAnnotatorPro`; exports land beside the recording |
| Shortcut | any combo | `Ctrl+Shift+R` by default |

### ffmpeg

Encoding is done by **ffmpeg**, which the app looks for in three places, in
order: the `SCREEN_ANNOTATOR_FFMPEG` environment variable, next to the
executable (this is what a shipped build uses), then `PATH`. Without it the
Record button explains how to install one instead of failing quietly.

To ship it inside a Windows build, drop `ffmpeg.exe` into `vendor/` before
running `pyinstaller annotate.spec` — the spec picks it up automatically and
prints what it bundled. Leave it out and the build still works; users then need
ffmpeg on PATH.

```
winget install Gyan.FFmpeg        # Windows
sudo pacman -S ffmpeg             # Arch
sudo apt install ffmpeg           # Debian/Ubuntu
```

### How it captures, per platform

| Platform | Capture path | Notes |
|---|---|---|
| Windows | `QScreen.grabWindow` + our own compositing | The real target. Overlay excluded from capture, dock stays put |
| Linux / X11 | `QScreen.grabWindow` | WYSIWYG — the overlay is in the grab, so the dock moves aside |
| Linux / Wayland (wlroots) | `grim`, one frame at a time, off the GUI thread | Hyprland, Sway. Needs `grim` installed. ~15 fps ceiling |
| Linux / Wayland (GNOME, KDE) | none | Run under XWayland: `QT_QPA_PLATFORM=xcb python annotate.py` |

The recorder picks the path itself; the frame rate you asked for is the frame
rate of the file either way. If the capture path can't keep up, the writer
repeats the last frame rather than shortening the video, so a recording always
plays back at real speed.

---

## OCR & Translation

Press `J` (or `Ctrl+T` by default, configurable in Settings) to activate Snip & Read, then drag a rectangle over any text on screen. A resizable popup appears with:

- **Recognized text** — extracted via [EasyOCR](https://github.com/JaidedAI/EasyOCR), runs fully offline with no API key
- **Translate to** — pick any of 50+ languages and press **Go** to translate via Google Translate
- **Copy** buttons for both the OCR result and the translation

> **First use:** The EasyOCR model (~150 MB) is downloaded once and cached in `%APPDATA%\ScreenAnnotatorPro\ocr_models` (Windows) or `~/.config/ScreenAnnotatorPro/ocr_models` (Linux/macOS). All subsequent uses load instantly from disk.

### Supported translation languages

English, Bosnian, German, French, Spanish, Italian, Portuguese, Dutch, Polish, Russian, Ukrainian, Arabic, Chinese (Simplified), Chinese (Traditional), Japanese, Korean, Turkish, Swedish, Norwegian, Danish, Finnish, Czech, Romanian, Hungarian, Greek, Hebrew, Hindi, Thai, Vietnamese, Indonesian, Malay, Croatian, Slovak, Bulgarian, Serbian, Albanian, Lithuanian, Latvian, Estonian, Slovenian, Catalan, Swahili, Afrikaans, Tagalog, Georgian, Armenian, Azerbaijani, Kazakh, Uzbek, Mongolian.

---

## Keyboard Shortcuts

| Shortcut | Action |
|---|---|
| `Ctrl + Shift + A` | Toggle overlay on / off (customisable in Settings) |
| `Ctrl + T` | Activate Snip & Read / OCR (customisable in Settings) |
| `Ctrl + Shift + R` | Start / stop recording (customisable in Settings) |
| `Ctrl + Z` | Undo last shape |
| `Ctrl + Y` | Redo (restore undone shape) |
| `C` | Clear all shapes |
| `Esc` | Hide overlay (app stays in tray) |
| `Delete` | Remove selected shape (Select tool) |
| **Hold Shift** | 45° snap for lines / perfect square / perfect circle |

---

## Toolbar Controls

A single horizontal dock sits at the bottom of the screen. The top row is every tool, always in the same place; the row below it shows only the properties the *active* tool actually uses — a color swatch and stroke slider for Pen, nothing at all for Select, a radius slider for Blur, and so on.

- **6-colour swatch row** + custom colour picker, when the tool uses colour
- **Opacity slider** (10–100 %), **Stroke size slider** (1–30 px), **Text size slider** (8–72 pt) — shown only for the tools that use them
- **Capture** — hides overlay, captures all monitors, shows Copy / Save PNG / Discard
- **Record** — starts recording; the cell turns red and counts up until you stop it
- **Pause** — hides overlay; resume from tray or hotkey
- **Undo / Redo / Clear all**
- **Settings** — hotkey, OCR hotkey, start on boot, appearance, help reference

**Move it** by dragging the dotted grip at the left end — clicking a tool never moves the dock by accident. **Collapse it** by double-clicking that same grip: it shrinks down to a single draggable icon (the active tool, so you can always tell what's armed) that sits wherever you left it; click it once to expand back to the full dock. Wherever you leave it — collapsed or expanded — is remembered across restarts.

---

## Settings

Open via the **Settings** button in the toolbar.

| Setting | Description |
|---|---|
| Activation Shortcut | Global hotkey to show/hide the overlay (default `Ctrl+Shift+A`) |
| OCR Shortcut | Global hotkey to activate Snip & Read (default `Ctrl+T`) |
| Recording | Area, frame rate, quality, cursor, microphone, output folder, shortcut |
| Start on boot | Adds to Windows startup registry; app launches hidden in the tray |
| Appearance | Light or Dark — applies immediately, remembered next launch |

Settings are saved to:
- **Windows:** `%APPDATA%\ScreenAnnotatorPro\settings.json`
- **Linux / macOS:** `~/.config/ScreenAnnotatorPro/settings.json`

---

## Installation

### Microsoft Store
Search **"Screen Annotator Pro"** in the Microsoft Store, or use Store ID **`9NS87MQB29C7`**.  
The Store version is signed by Microsoft and updates automatically.

---

## Support

### Bug reports — please include

1. **What happened** — describe the problem and what you expected instead
2. **Steps to reproduce** — the exact sequence of actions that triggers it
3. **Version** — shown in Settings, bottom-right (e.g. `Version 4.0.0`)
4. **OS and display setup** — e.g. Windows 11, single 4K monitor; or Ubuntu 24.04 Wayland, dual monitors
5. **Error message or crash log** (if any) — on Windows, check `%APPDATA%\ScreenAnnotatorPro\` for any log files; on Linux run `python annotate.py` from terminal to see console output
6. **Screenshot or screen recording** (if visual) — helps a lot for rendering or layout bugs

### Feature requests

Open an issue with a clear description of the use case. What are you trying to do, and how does the current app fall short?

### What's in scope

- Drawing, annotation, and redaction tools
- OCR accuracy and language support
- Hotkey reliability and configurability
- Installer / packaging / update issues
- Performance on specific hardware or OS configurations
- Accessibility improvements

### Known limitations

- **Recording needs ffmpeg** — bundled in a shipped Windows build, otherwise installed once by the user
- **Wayland (Linux):** Global hotkeys are not available — use the tray icon to toggle the overlay
- **Wayland recording:** wlroots compositors (Hyprland, Sway) record through `grim` at roughly 15 fps. GNOME and KDE Wayland need XWayland
- **Only Windows can show the dock on screen without it landing in the video** — everywhere else it is moved aside, or hidden while recording the whole screen
- **Pause + microphone:** Pause is disabled while the mic is recording — a paused video track and a running audio device drift apart
- **System audio** is not captured, only the microphone
- **macOS:** Not officially supported; the app runs from source but no packaged build is provided
- **Multiple monitors:** Overlay covers all monitors; per-monitor mode is not currently supported
- **OCR first-run:** The ~150 MB EasyOCR model downloads on first use; this requires an internet connection once

---

## Repo layout

Everything at root is the live app — what actually builds and ships:

```
annotate.py, dock_toolbar.py   the app
video_recorder.py              screen recording: ffmpeg pipe + capture sources
annotate.spec, requirements.txt, .github/   build + CI
installer/                     Windows (MSIX) + Linux (.desktop) packaging
```

`video_recorder.py` is deliberately split in half. `FFmpegEncoder` and
`PacedWriter` are pure Python — raw BGRA in, MP4 out, no Qt, runnable headless.
`ScreenRecorder` is the Qt half that grabs the desktop, paints the canvas on top
and hands over the bytes. The capture mechanism behind it is a `DesktopSource`,
one per platform.

Everything else is grouped out of the way:

```
docs/       Store listing text, marketing screenshots, screenshot generator
archive/    frozen snapshots of past toolbar redesigns (see archive/README.md)
```

---

## License

MIT License — see [installer/License.rtf](installer/License.rtf) for the full text.

Copyright © 2025 Anel Celik / Casultra

---

## Developer

**Casultra** · [celikovic.xyz](https://celikovic.xyz)  
Microsoft Store · Store ID: `9NS87MQB29C7`
