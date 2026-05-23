# Screen Annotator Pro

> Draw, highlight, annotate, redact, and OCR anything on your screen — live, in real time, without interrupting what's behind it.

A fullscreen transparent overlay built with **Python + PyQt6**. The overlay sits on top of all windows; you draw on it like a whiteboard, then hide it or clear it when you're done. Everything runs locally — no cloud, no account.

Available on the **Microsoft Store** · **Current version: 2.2.7**

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
| `Ctrl + Z` | Undo last shape |
| `Ctrl + Y` | Redo (restore undone shape) |
| `C` | Clear all shapes |
| `Esc` | Hide overlay (app stays in tray) |
| `Delete` | Remove selected shape (Select tool) |
| **Hold Shift** | 45° snap for lines / perfect square / perfect circle |

---

## Toolbar Controls

- **16-colour swatch palette** + custom colour picker
- **Opacity slider** (10–100 %) — softens any colour for new shapes
- **Stroke size slider** (1–30 px)
- **Text size slider** (8–72 pt)
- **Screenshot** — hides overlay, captures all monitors, shows Copy / Save PNG / Discard
- **Pause** — hides overlay; resume from tray or hotkey
- **Undo / Redo**
- **Clear all**
- **Settings** — hotkey, OCR hotkey, start on boot, help reference

The toolbar is scrollable — if your screen is short or you've expanded a section, scroll inside the toolbar panel.

---

## Settings

Open via the **Settings** button in the toolbar.

| Setting | Description |
|---|---|
| Activation Shortcut | Global hotkey to show/hide the overlay (default `Ctrl+Shift+A`) |
| OCR Shortcut | Global hotkey to activate Snip & Read (default `Ctrl+T`) |
| Start on boot | Adds to Windows startup registry; app launches hidden in the tray |

Settings are saved to:
- **Windows:** `%APPDATA%\ScreenAnnotatorPro\settings.json`
- **Linux / macOS:** `~/.config/ScreenAnnotatorPro/settings.json`

---

## Installation

### Microsoft Store (recommended)
Search **"Screen Annotator Pro"** in the Microsoft Store, or use Store ID **`9NS87MQB29C7`**.  
The Store version is signed by Microsoft and updates automatically.

### MSI installer
Download `ScreenAnnotatorPro-Setup.msi` from the [latest release](https://github.com/anelcelik/annotate/releases/latest) and run it.  
Installs to `%ProgramFiles%\Screen Annotator Pro` with Start Menu and Desktop shortcuts.

### MSIX sideload
Download `ScreenAnnotatorPro.msix` from the [latest release](https://github.com/anelcelik/annotate/releases/latest).  
Right-click → **Install**, or run:
```powershell
Add-AppxPackage ScreenAnnotatorPro.msix
```
> The sideload MSIX is signed with a self-signed development certificate.  
> You must trust it first by installing the `.pfx`, or enable Developer Mode in Windows Settings.  
> The Microsoft Store version is signed by Microsoft — no manual trust step needed.

---

## Running from Source

### Requirements
- Python 3.11+
- Windows 10/11, Linux, or macOS

### Install dependencies
```bash
pip install -r requirements.txt
```

| Package | Purpose |
|---|---|
| `PyQt6 >= 6.4` | UI framework and transparent overlay |
| `Pillow >= 9.0` | Multi-size ICO generation |
| `pynput >= 1.7` | Global hotkey listener |
| `easyocr >= 1.7` | Offline OCR engine (model downloaded on first use) |
| `deep-translator >= 1.11` | Google Translate integration |

### Run
```bash
python annotate.py
```

### Generate icons
```bash
python create_icons.py
```
Outputs 35 Microsoft Store–compliant PNG assets + `annotate.ico` + `tray.ico` into `icons/`.

---

## Building the Installer

The GitHub Actions workflow (`.github/workflows/build.yml`) builds and releases everything automatically on version tags.

### Trigger a release
```bash
git tag v2.2.7
git push origin v2.2.7
```

Full pipeline:
1. Generates all icons (`create_icons.py`)
2. Builds `ScreenAnnotatorPro.exe` via PyInstaller (onedir)
3. Harvests `_internal/` via PowerShell into `installer/AppFiles.wxs`
4. Builds `ScreenAnnotatorPro-Setup.msi` via WiX 4
5. Packs `ScreenAnnotatorPro.msix` via `makeappx`, signs with dev cert
6. Creates a GitHub Release with both files attached

### Local build (Windows)
```powershell
pip install pyinstaller
python create_icons.py
pyinstaller annotate.spec

# Harvest _internal folder into WiX component group
powershell -File installer/harvest.ps1

# MSI (requires WiX 4)
dotnet tool install --global wix --version 4.0.5
wix extension add --global WixToolset.UI.wixext/4.0.5
wix build installer/annotate.wxs installer/AppFiles.wxs `
    -ext WixToolset.UI.wixext -arch x64 `
    -o dist/ScreenAnnotatorPro-Setup.msi `
    -d SourceDir=dist\ScreenAnnotatorPro\_internal
```

---

## Reporting Issues

Found a bug or want to request a feature? [Open an issue](https://github.com/anelcelik/annotate/issues/new/choose).

### Bug reports — please include

1. **What happened** — describe the problem and what you expected instead
2. **Steps to reproduce** — the exact sequence of actions that triggers it
3. **Version** — shown in the tray tooltip or Settings → Help (`v2.2.7`)
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

- **Wayland (Linux):** Global hotkeys are not available — use the tray icon to toggle the overlay
- **macOS:** Not officially supported; the app runs from source but no packaged build is provided
- **Multiple monitors:** Overlay covers all monitors; per-monitor mode is not currently supported
- **OCR first-run:** The ~150 MB EasyOCR model downloads on first use; this requires an internet connection once

---

## Contributing

Pull requests are welcome. For significant changes, open an issue first to discuss the approach.

When submitting a PR:
- Keep changes focused — one feature or fix per PR
- Test on Windows (the primary platform) if your change touches the overlay, hotkeys, or installer
- The app runs cross-platform from source — avoid Windows-only APIs in the core drawing logic

---

## Project Structure

```
annotate.py              Main application (overlay, tools, OCR, settings, UI)
create_icons.py          Generates all Microsoft Store icon assets
annotate.spec            PyInstaller build spec (onedir)
requirements.txt         Python dependencies
annotate.desktop         Linux desktop entry
installer/
  annotate.wxs           WiX 4 MSI definition
  AppxManifest.xml       MSIX package manifest
  harvest.ps1            PowerShell script to harvest _internal/ for WiX
  License.rtf            MIT license shown in the MSI installer UI
.github/
  workflows/
    build.yml            CI/CD: icons → exe → MSI → MSIX → GitHub Release
```

---

## Platform Notes

### Windows
- Requires Windows 10/11 with **Desktop Window Manager (DWM)** enabled for transparent compositing
- High-DPI monitors are handled automatically (`PassThrough` scale rounding)
- Global hotkeys use `pynput` — install via `pip install pynput`

### Linux
- Tested on X11; Wayland disables global hotkeys (use the tray icon instead)
- OCR and all drawing tools work

### macOS
- Runs from source; no packaged build
- Global hotkey may require Accessibility permissions in System Settings

---

## License

MIT License — see [installer/License.rtf](installer/License.rtf) for the full text.

Copyright © 2025 Anel Celik / Casultra

---

## Developer

**Casultra** · [celikovic.xyz](https://celikovic.xyz)  
Microsoft Store · Store ID: `9NS87MQB29C7`
