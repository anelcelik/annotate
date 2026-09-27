# Screen Annotator Pro

> Draw, highlight, annotate, redact and OCR anything on your screen — live, in
> real time — and **record the whole thing to an MP4** with every mark baked in.

A fullscreen transparent overlay, plus a screen recorder that captures the
desktop with your annotations composited into each frame. Everything runs
locally — no cloud, no account, no upload.

This folder is the live source for the whole app — see the
[repo root README](../README.md) for how it fits together with `archive/` and
`docs/`.

---

## How it works

Screen Annotator Pro creates a transparent window covering your entire screen
(or all monitors), and it has two modes.

| Mode | The overlay | You |
|---|---|---|
| **Drawing** | takes the mouse | draw, annotate, redact |
| **Click-through** | ignores the mouse | type, click, switch apps — normally |

Your marks stay on screen in both. `Ctrl+Shift+A` switches between them (and is
rebindable), Esc drops you into click-through, and picking any tool on the dock
puts you straight back into drawing. The dock stays clickable either way.

This is the difference between an overlay you can present with and one that
holds your desktop hostage — you demo the app underneath, mark it up, keep
demoing, all without the annotations going anywhere. It matters most while
recording, which is exactly when you need to use the machine *and* draw on it.

The app starts in click-through mode: it appearing should never be the reason
you cannot click something.

The app lives in the system tray and is toggled with a global hotkey (`Ctrl+Shift+A` by default) so you can flip it on and off in under a second during a presentation, meeting, or tutorial recording.

---

## Features

### Drawing Tools

| Tool | Key | Description |
|---|---|---|
| Select / Edit | `V` | Click a mark to select it · drag to move · white handles reshape it (arrow tip, box corner…) · the dock's colour / stroke / opacity restyle it · drag across empty space or **Shift**-click to select several · `Ctrl+C` / `Ctrl+V` / `Ctrl+D` / `Ctrl+A` · arrow keys nudge (**Shift** = 10 px) · all undoable |
| Pen | `P` | Freehand stroke · with a pen (Surface, Wacom, Windows Ink) the width follows the pressure, and the pen's eraser end erases |
| Line | `L` | Straight line · **Shift** → 45° snap |
| Arrow | `A` | Line with arrowhead · **HEADS** One / Both · **Shift** → 45° snap · select it and drag the middle handle to curve it |
| Rectangle | `R` | **FILL** Off / Tint / Solid · **Shift** → perfect square |
| Circle | `O` | **FILL** Off / Tint / Solid · **Shift** → perfect circle |
| Ruler | `U` | Line labelled with its length in real screen pixels (125 px for 100 logical px at 125 %) · **Shift** → 45° snap |
| Eraser | `E` | **Shapes** (default): touch a mark to remove it, one undo step per drag · **Pixels**: rub out part of a mark |
| Laser Pointer | `I` | Real-time glowing dot — no marks left, OS cursor hidden |

### Presenting

| Feature | Key | Description |
|---|---|---|
| Whiteboard | `W` | Opens / closes a board over the current screen — white or dark per Settings → General · the dock moves onto it and back · `PgDn`/`PgUp` pages (own undo each) · `Esc` leaves · desktop marks come back afterwards |
| Spotlight | `F` | Dims everything but the cursor's surroundings · mouse wheel sizes it · also Presenter menu on the dock |
| Cursor halo · Show clicks | dock → Presenter | Highlight around the cursor, ripple on every click — work in click-through mode and are recorded |
| Webcam bubble | dock → Presenter | Your camera in a circle on top of everything — a real window, so it is in recordings · drag to move, wheel to size, right-click: mirror / rounded square / close · camera picked in Settings → Recording |
| Show pressed shortcuts | Settings → General or dock → Presenter | A pill near the bottom of the screen shows shortcuts and special keys as you press them (`Ctrl + Shift + Z`, `F5`, `Enter`…) — never plain typing, so passwords stay out of recordings · off by default · recorded |
| Fading ink | FADE on the drawing tools | Marks disappear after ~3 s (fade over 1 s); blur, pixelate and black boxes never fade |
| Magnifier | `M` | A round loupe beside the cursor, Greenshot-style — crosshair on the pixel under the cursor, sharp pixels from 4× · wheel 2×–16× · shows a still taken when you press M, marks included · `Esc`, `M` or right-click leaves · optional global shortcut |

### Annotation Tools

| Tool | Key | Description |
|---|---|---|
| Text | `T` | Click and type right there — Enter finishes, Shift+Enter adds a line, Esc cancels · **BOX** Off / Box (a plate behind it) / Bubble (a speech bubble — drag its tail with Select) · click a label to edit it |
| Callout | `K` | Auto-numbered filled circles |
| Steps | `S` | Auto-numbered step squares |
| Stamp | `G` | Click to place ✓ ✗ ! ? or ★ on a disc in the current colour · SIZE sets how big |
| Highlight | `H` | Semi-transparent colour band |

### Redact Tools

| Tool | Key | Description |
|---|---|---|
| Blur | `Z` | Gaussian blur over a selected region |
| Pixelate | `X` | A real mosaic of what's underneath (cells of 10 px or more, so small text can't be read back) |
| Black Box | `D` | Solid opaque black redaction |

### OCR & Translate

| Tool | Key | Description |
|---|---|---|
| Snip & Read | `J` | Drag a region → copy its text, or translate it (Windows' built-in OCR — see below) |

### Recording

| Control | Key | Description |
|---|---|---|
| Record / Stop | `Ctrl+Alt+R` | Records the screen to MP4 with the annotations in it · a 3-2-1 countdown first (never recorded; Record again cancels; Settings → Recording turns it off) |

---

## Recording

Areas: all monitors, the monitor in use, an area you drag, or **a window you click** (it comes to the front and its area is recorded).

Press **Record** on the dock (or `Ctrl+Alt+R`, or the tray menu) — its own
Record cell turns red and counts up; press it again (or `Ctrl+Alt+R`, or the
tray menu) to stop. The file is already on disk — a panel offers **Play**,
**Trim…** (drag the start and end on a timeline with a frame preview; saves `…-trimmed.mp4` beside it), **Show in folder**, **Save as…** and **Delete** (which moves the file to the
Recycle Bin, so a misclick can be undone).

Files go to `Videos/ScreenAnnotatorPro/annotation_YYYYMMDD_HHMMSS.mp4`
(H.264 + AAC), changeable in Settings.

### Exporting — GIF, WebM, smaller MP4

**Make GIF** on that panel does it in one click at sensible defaults
(720 px, 12 fps). **Export…** opens the same panel with every option. Later on, the tray menu's
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

On Windows 10 2004+, by default, this is exact. The app asks the compositor to
leave its own windows out of any screen capture (`WDA_EXCLUDEFROMCAPTURE`) —
the overlay always, and the dock (full bar and collapsed puck both) when
**Settings → Recording → Keep the dock visible while recording** is on, which
it is out of the box. It only trusts this if *every* dock window actually
takes the flag; if even one refuses, whatever did apply is undone and the dock
falls back to the same move-aside/hide behavior below, automatically, for that
recording. The overlay's own exclusion is what lets the app composite the
shapes itself at full resolution instead of capturing them pre-resampled.

No other platform can exclude a window from capture at all. Wayland's
screencopy hands over the composited output with no per-window opt-out, and
X11 has nothing either, so anything visible is in the file — and that's also
where Windows lands whenever the exclusion above doesn't take. Either way, the
app moves its own chrome out of the frame instead, automatically:

- **Recording an area** — the dock slides just outside the recorded rectangle
  and stays fully usable. Nothing is lost.
- **Recording everything** — there is no outside, so the dock hides for the
  duration and comes back when you stop. Tool shortcuts still work; stop with
  `Ctrl+Alt+R` or the tray icon.

The recorder also skips its own compositing wherever the overlay wasn't
actually excluded, since the grab already contains it and drawing the shapes
again would double them up.

### Settings

| Setting | Choices | Notes |
|---|---|---|
| Area | All monitors · Monitor in use · Pick an area | "Monitor in use" means the one the cursor is on when you hit Record |
| Keep the dock visible while recording | on / off | Windows 10 2004+ only. On by default; see [What ends up in the frame](#what-ends-up-in-the-frame) |
| Record with the graphics chip (beta) | on / off | Windows. ffmpeg captures (Desktop Duplication), converts and encodes (Media Foundation, hardware) on the GPU — Python only starts and stops it. Any one screen, area or window: the Qt screen is matched to its DXGI adapter/output (by device name, then position), a screen on a second graphics chip gets its own D3D11 device. Pause ends a piece and resume starts the next; stop joins them with the concat demuxer (streams copied). "All monitors" across several screens uses the CPU recorder. Falls back to the CPU recorder by itself if the PC can't. Off by default until confirmed on more hardware (CI runners have no GPU) |
| Frame rate | 15 · 24 · 30 · 60 fps | 30 is the sensible default |
| Quality | High (CRF 18) · Balanced (23) · Small file (28) | x264, `veryfast` preset |
| Show the cursor | on / off | A drawn pointer on Windows; the real one on wlroots |
| Record the microphone | on / off | Pause is disabled while the mic is live — the mic has no pause |
| Save to | any folder | Defaults to `Videos/ScreenAnnotatorPro`; exports land beside the recording |
| Shortcut | any combo | `Ctrl+Alt+R` by default |

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
| Windows | `QScreen.grabWindow` + our own compositing | The real target. Overlay always excluded; dock excluded too by default, falls back to moving/hiding if that doesn't take |
| Linux / X11 | `QScreen.grabWindow` | WYSIWYG — the overlay is in the grab, so the dock moves aside |
| Linux / Wayland (wlroots) | `grim`, one frame at a time, off the GUI thread | Hyprland, Sway. Needs `grim` installed. ~15 fps ceiling |
| Linux / Wayland (GNOME, KDE) | none | Run under XWayland: `QT_QPA_PLATFORM=xcb python annotate.py` |

The recorder picks the path itself; the frame rate you asked for is the frame
rate of the file either way. If the capture path can't keep up, the writer
repeats the last frame rather than shortening the video, so a recording always
plays back at real speed.

---

## OCR & Translation

Press `J` (or `Ctrl+Alt+T` by default, configurable in Settings) to activate
Snip & Read, then drag a rectangle over any text on screen. A resizable window
appears with:

- **Recognized text** — editable, so a misread letter can be fixed before
  copying, with a **Copy text** button
- **Read as** — which language to read the snip as, when Windows has more
  than one recognizer installed
- **Translate to** + **Open in Google Translate** — hands the text to Google
  Translate in your browser (very long text goes via the clipboard)

On Windows the reading is done by the OCR engine built into Windows 10 and 11
(`Windows.Media.Ocr`, see `ocr_win.py`): offline, instant, nothing to
download, and it reads every language whose *Optical character recognition*
feature is installed — English comes with an English Windows; add others in
Settings → Time & language → Language & region → a language → Language
options. Up to 5.1 this was EasyOCR + Torch: ~240 MB more to ship, a 150 MB
model download on first use, English only, and the Store build couldn't carry
it at all.

Off Windows, Snip & Read uses [EasyOCR](https://github.com/JaidedAI/EasyOCR)
if it is installed (`pip install easyocr Pillow`) and hides itself if not.

### Supported translation languages

English, Bosnian, German, French, Spanish, Italian, Portuguese, Dutch, Polish, Russian, Ukrainian, Arabic, Chinese (Simplified), Chinese (Traditional), Japanese, Korean, Turkish, Swedish, Norwegian, Danish, Finnish, Czech, Romanian, Hungarian, Greek, Hebrew, Hindi, Thai, Vietnamese, Indonesian, Malay, Croatian, Slovak, Bulgarian, Serbian, Albanian, Lithuanian, Latvian, Estonian, Slovenian, Catalan, Swahili, Afrikaans, Tagalog, Georgian, Armenian, Azerbaijani, Kazakh, Uzbek, Mongolian.

---

## Keyboard Shortcuts

| Shortcut | Action |
|---|---|
| `Ctrl + Shift + A` | Draw ⇄ click-through (customisable in Settings) |
| `Ctrl + Shift + H` | Show / hide the overlay entirely (customisable) |
| `Ctrl + Alt + T` | Activate Snip & Read / OCR (customisable in Settings) |
| `Ctrl + PrtSc` | Screenshot: drag an area, click for a whole screen, Enter for all screens (customisable) |
| `Ctrl + Alt + R` | Start / stop recording (customisable in Settings) |
| `Ctrl + Z` | Undo — drawing, moving, deleting and Clear all |
| `Ctrl + Y` | Redo (restore undone shape) |
| `C` | Clear all shapes (`Ctrl + Z` brings them back) |
| `Esc` | Drop into click-through — marks stay up, the dock stays reachable |

Up to 5.0 the defaults were `Ctrl+T` (Snip & Read) and `Ctrl+Shift+R`
(record) — new tab and hard reload in every browser, so pressing either one
in a browser did both things at once. 5.1 moves anyone still on those two defaults
to the new ones once. On Windows each shortcut is now registered with
`RegisterHotKey`, so it belongs to this app alone while it runs, and if
another program already owns a combination the app says so (a tray message
at launch, a note in Settings) instead of the shortcut silently doing
nothing. A combination has to include Ctrl, Alt or Win (function keys may
stand alone), so a shortcut can never swallow ordinary typing.
| `Delete` | Remove the selected marks (Select tool) |
| `Ctrl + C` / `Ctrl + V` / `Ctrl + D` | Copy / paste / duplicate the selected marks |
| `Ctrl + A` | Select every mark |
| `Ctrl + S` / `Ctrl + O` | Save the marks on screen to a `.samarks` file / open saved marks on top (also in the tray menu; one `Ctrl + Z` takes them away) |
| Arrow keys | Nudge the selection 1 px (`Shift` = 10 px) |
| **Hold Shift** | 45° snap for lines / perfect square / perfect circle |

---

## Toolbar Controls

The dock is its own window, so it stays clickable even when the overlay is
letting clicks through — that is the way back into drawing when a global hotkey
is unavailable. It carries the mode cell: **Drawing ON** (filled, accent) or
**Drawing OFF** (muted). Click it to switch.

A single horizontal dock sits at the bottom of the screen. The top row is every tool, always in the same place; the row below it shows only the properties the *active* tool actually uses — a color swatch and stroke slider for Pen, nothing at all for Select, a radius slider for Blur, and so on.

- **6-colour swatch row** + custom colour picker, when the tool uses colour
- **Opacity slider** (10–100 %), **Stroke size slider** (1–30 px), **Text size slider** (8–72 pt) — shown only for the tools that use them
- **Capture** — drag an area (or click for that whole screen, Enter for all of them); the marks are in the picture, the dock isn't. Copy / Save PNG / Discard — Save starts in Pictures\Screenshots and then remembers where you saved last
- **Record** — starts recording; the cell turns red and counts up until you stop it
- **Pause** — hides overlay; resume from tray or hotkey
- **Minimise** — collapses the dock to the puck in one click (double-clicking the grip still does it too)
- **Undo / Redo / Clear all**
- **Settings** — hotkey, OCR hotkey, start on boot, appearance, help reference

**Move it** by dragging the dotted grip at the left end — clicking a tool never moves the dock by accident. **Collapse it** by double-clicking that same grip: it shrinks down to a single draggable icon (the active tool, so you can always tell what's armed) that sits wherever you left it; click it once to expand back to the full dock. Wherever you leave it — collapsed or expanded — is remembered across restarts.

---

## Asking for a Store review

Only right after the app has just done its job — a screenshot copied or
saved, a recording saved (and its panel closed without deleting it), an
export finished — and only once that has happened at least three times, on
at least two different days. Never on a timer, so never in the middle of a
presentation, never while recording, never over another dialog.

**Write a review** opens the Store's own rating dialog on top of the app
(`StoreContext.RequestRateAndReviewAppAsync`) where the installed package
allows it, and the Store's review page
(`ms-windows-store://review/?ProductId=…`) otherwise. **Maybe later** buys a
fortnight of silence, **Don't ask again** is permanent, and Esc counts as
"later" rather than "never", so dismissing it is never punishing. Nothing is
gated behind reviewing, and the prompt deliberately does not screen for happy
users first — a rating you got by only asking people who already said they
liked it is not worth having.

Up to 5.0 it waited for eight hours of accumulated use, which almost nobody
ever reached.

Windows only; there is no Store to review on anywhere else.

## Settings

Open via the **Settings** button in the toolbar.

| Setting | Description |
|---|---|
| Draw / click-through | Global hotkey to switch modes (default `Ctrl+Shift+A`) |
| Show / hide the overlay | Global hotkey to put it away entirely (default `Ctrl+Shift+H`) |
| OCR Shortcut | Global hotkey to activate Snip & Read (default `Ctrl+Alt+T`) |
| Screenshot shortcut | Global hotkey for Capture (default `Ctrl+PrtSc`) |
| Recording | Area (incl. one window), frame rate, quality, cursor, microphone, **the PC's sound** (WASAPI loopback, mixed in when you stop), 3-2-1 countdown, webcam-bubble camera, output folder, shortcut |
| Start with Windows | App launches hidden in the tray at sign-in. The Store package uses a manifest startup task (the only kind a package can have — its Run-key writes are invisible to Windows); the portable .exe uses the Run key. Also switchable in Windows Settings → Apps → Startup |
| Dock size | 100 / 90 / 78 / 70 / 60 % — for displays the dock runs off the edge of. Applies immediately |
| Appearance | Light or Dark — applies immediately, remembered next launch |
| Hold a key to draw (Shortcuts tab) | Off / Right Ctrl / Right Shift — hold it to draw, let go to click through; the app you were in gets the keyboard back |
| Show a hint when hovering over a button | Hover hints with what a button does and its key — on by default, also shown in click-through mode |
| Show pressed shortcuts on screen | See *Presenting* — off by default |

Settings are saved to:
- **Windows:** `%APPDATA%\ScreenAnnotatorPro\settings.json`
- **Linux / macOS:** `~/.config/ScreenAnnotatorPro/settings.json`

---

## Installation

### Test builds

Every push and pull request builds and self-tests everything but keeps
nothing (artifact storage has a quota). To get test builds, use **Actions →
Build single-file Windows EXE (video) → Run workflow**; that run keeps them
for five days:

| Artifact | What it is | Install |
|---|---|---|
| `ScreenAnnotatorPro-Portable` | One ~60 MB .exe, everything included (Snip & Read uses Windows' OCR) | Run it. SmartScreen → More info → Run anyway |
| `…Video-installers` | The `.msi` installer, the sideload `.msix` + `.cer` (see `INSTALL-MSIX.txt`) and the unsigned Store-submission `.msix` | MSI: double-click. MSIX: trust the .cer first |

A `vX.Y.Z` tag puts all of it on the GitHub Release instead.

The MSIX now carries the **same package identity as the Store app**
(`Casultra.ScreenAnnotatorPro`) — recording is a feature of the one app, not a
separate package — so it will conflict with an existing Store install on the
same machine rather than sit alongside it; uninstall one to test the other. It
is signed with a throwaway CI certificate, which Windows will not trust until
you import the included `.cer` into `LocalMachine\TrustedPeople` from an admin
shell. If that is more ceremony than you want, the .exe needs none of it.

### Microsoft Store
Search **"Screen Annotator Pro"** in the Microsoft Store, or use Store ID **`9NS87MQB29C7`**.  
The Store version is signed by Microsoft and updates automatically.

---

## Support

### Bug reports — please include

1. **What happened** — describe the problem and what you expected instead
2. **Steps to reproduce** — the exact sequence of actions that triggers it
3. **Version** — shown in Settings, bottom-right (e.g. `Version 5.0.1`)
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

- **Recording needs ffmpeg** — bundled in a shipped Windows build: a 13 MB ffmpeg 9.0.2 built from source for this app by `ffmpeg/build-ffmpeg.sh` (only the encoders, filters and formats the app calls; x264, libvpx, Opus; every source pinned; GPLv3 — its license and source list ship beside it, see Settings → Licenses). `tests/test_ffmpeg_build.py` checks the shipped exe has every part the app uses. From source, ffmpeg is installed once by the user
- **Wayland (Linux):** Global hotkeys are not available — use the tray icon to toggle the overlay
- **Wayland recording:** wlroots compositors (Hyprland, Sway) record through `grim` at roughly 15 fps. GNOME and KDE Wayland need XWayland
- **Only Windows can show the dock on screen without it landing in the video**, and even there it isn't guaranteed — everywhere else, and whenever it fails on Windows too, the dock is moved aside or hidden while recording instead
- **Pause + microphone:** Pause is disabled while the mic is recording — a paused video track and a running audio device drift apart
- **System audio** is not captured, only the microphone
- **macOS:** Not officially supported; the app runs from source but no packaged build is provided
- **Multiple monitors:** Overlay covers all monitors; per-monitor mode is not currently supported
- **OCR languages:** Snip & Read reads the languages whose Windows OCR feature is installed (see OCR & Translation)

---

## Repo layout

Everything in *this* folder is the live app — what actually builds and ships:

```
annotate.py, dock_toolbar.py   the app
video_recorder.py              screen recording: ffmpeg pipe + capture sources
hotkeys.py                     global shortcuts (RegisterHotKey / pynput)
platform_win.py                start with Windows, activation, Store rating
ocr_win.py                     Snip & Read on Windows' built-in OCR
build_filters.py               what the specs leave out of the bundle
annotate.spec, annotate_onefile.spec, requirements.txt   build
installer/                     MSIX manifest, WiX (MSI) installer
tests/                         pytest suite (offscreen; CI runs it on Windows)
```

`video_recorder.py` is deliberately split in half. `FFmpegEncoder` and
`PacedWriter` are pure Python — raw BGRA in, MP4 out, no Qt, runnable headless.
`ScreenRecorder` is the Qt half that grabs the desktop, paints the canvas on top
and hands over the bytes. The capture mechanism behind it is a `DesktopSource`,
one per platform.

CI (`.github/workflows/build-video.yml`) and everything not specific to the
app itself — Store listing text, frozen historical snapshots — live one level
up, at the repo root; see the [root README](../README.md) and
[`../archive/README.md`](../archive/README.md).

---

## License

MIT License — see
[`../archive/before-recording/installer/License.rtf`](../archive/before-recording/installer/License.rtf)
for the full text.

Copyright © 2025–2026 Anel Celik / Casultra

---

## Developer

**Casultra** · [celikovic.xyz](https://celikovic.xyz)  
Microsoft Store · Store ID: `9NS87MQB29C7`
