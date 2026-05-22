# Screen Annotator Pro

A fullscreen transparent overlay that lets you draw, highlight, and annotate anything on your screen in real time — without interrupting what's behind it.

Built with Python and PyQt6. Available on the **Microsoft Store** (Casultra).

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

### Other Tools
| Tool | Key | Description |
|---|---|---|
| Laser Pointer | `I` | Real-time glowing dot — no marks left, OS cursor hidden |

---

## Keyboard Shortcuts

| Shortcut | Action |
|---|---|
| `Ctrl + Z` | Undo last shape |
| `Ctrl + Y` | Redo (restore undone shape) |
| `C` | Clear all shapes |
| `Esc` | Hide overlay (app stays in tray) |
| `Delete` | Remove selected shape (Select tool) |
| `Ctrl + Shift + A` | Toggle overlay — customisable in Settings |
| **Hold Shift** | 45° snap for lines / perfect square for rect |

---

## Toolbar Controls

- **16-colour swatch palette** + custom colour picker
- **Opacity slider** (10–100 %) — softens any colour for new shapes
- **Stroke size slider** (1–30 px)
- **Text size slider** (8–72 pt)
- **📷 Screenshot** — hides overlay, grabs all monitors, shows Copy / Save PNG / Discard
- **⏸ Pause** — hides overlay; resume from tray or hotkey
- **↩ Undo / ↪ Redo**
- **🗑 Clear all**
- **⚙ Settings** — hotkey, start on boot, Help & Features reference

---

## Settings

Open via the **⚙ Settings** button in the toolbar.

| Setting | Description |
|---|---|
| Activation Shortcut | Change the global hotkey (default `Ctrl + Shift + A`) |
| Start on boot | Adds to Windows startup registry; app launches hidden in the tray |
| celikovic.xyz | Developer website |
| ? Help | Opens the full feature reference and keyboard shortcut guide |

Settings are saved to:
- **Windows:** `%APPDATA%\ScreenAnnotatorPro\settings.json`
- **Linux / macOS:** `~/.config/ScreenAnnotatorPro/settings.json`

---

## Installation

### Microsoft Store (recommended)
Search **"Screen Annotator Pro"** in the Microsoft Store, or use Store ID **`9NS87MQB29C7`**.

### Manual — MSI installer
Download `ScreenAnnotatorPro-Setup.msi` from the [latest release](https://github.com/anelcelik/annotate/releases/latest) and run it.  
Installs to `%ProgramFiles%\Screen Annotator Pro` with Start Menu and Desktop shortcuts.

### Manual — MSIX sideload
Download `ScreenAnnotatorPro.msix` from the [latest release](https://github.com/anelcelik/annotate/releases/latest).  
Right-click → **Install**, or run:
```powershell
Add-AppxPackage ScreenAnnotatorPro.msix
```
> **Note:** The sideload MSIX is signed with a self-signed development certificate.
> You must first trust it by installing the `.pfx` (or enable Developer Mode in Windows Settings).
> The Microsoft Store version is signed by Microsoft automatically — no manual trust step needed.

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
| `pynput >= 1.7` | Global hotkey (optional — app still works without it) |

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

The GitHub Actions workflow (`.github/workflows/build.yml`) builds everything automatically on every push to `main` and on version tags.

### Trigger a release manually
```bash
git tag v1.0.2
git push origin v1.0.2
```

This runs the full pipeline:
1. Generates all icons (`create_icons.py`)
2. Builds `ScreenAnnotatorPro.exe` via PyInstaller (single file, icon embedded)
3. Builds `ScreenAnnotatorPro-Setup.msi` via WiX 4 (license UI, Start Menu + Desktop shortcuts)
4. Packs `ScreenAnnotatorPro.msix` via `makeappx`, signs with a dev cert
5. Creates a GitHub Release with both files attached

### Local build (Windows)
```powershell
pip install pyinstaller
python create_icons.py
pyinstaller annotate.spec

# MSI (requires WiX 4)
dotnet tool install --global wix --version 4.0.5
wix extension add --global WixToolset.UI.wixext/4.0.5
wix build installer/annotate.wxs -ext WixToolset.UI.wixext -arch x64 -o dist/ScreenAnnotatorPro-Setup.msi
```

---

## Microsoft Store Submission

The MSIX package identity matches the Casultra Partner Center account:

| Field | Value |
|---|---|
| Package Name | `Casultra.ScreenAnnotatorPro` |
| Publisher | `CN=BD1D6788-5A7D-4A7F-9751-817381E6C28C` |
| Store ID | `9NS87MQB29C7` |
| PFN | `Casultra.ScreenAnnotatorPro_38f0gytd267x6` |

Upload the **unsigned** `ScreenAnnotatorPro.msix` to Partner Center — Microsoft re-signs it automatically.

---

## Project Structure

```
annotate.py              Main application (overlay, tools, settings, UI)
create_icons.py          Generates all Microsoft Store icon assets
annotate.spec            PyInstaller build spec (single-file exe)
requirements.txt         Python dependencies
annotate.desktop         Linux desktop entry
installer/
  annotate.wxs           WiX 4 MSI definition
  AppxManifest.xml       MSIX package manifest
  License.rtf            MIT license shown in the MSI installer UI
.github/
  workflows/
    build.yml            CI/CD: icons → exe → MSI → MSIX → GitHub Release
```

---

## Windows Notes

- Requires Windows 10/11 with **Desktop Window Manager (DWM)** enabled for transparent compositing
- High-DPI monitors are handled automatically (`PassThrough` scale rounding)
- On Windows, the toolbar shadow is replaced with a painted border to avoid a WS_EX_LAYERED dirty-rect bug
- Global hotkey requires `pynput` (`pip install pynput`)
- On Wayland (Linux), the global hotkey is unavailable — use the tray icon instead

---

## License

MIT License — see [installer/License.rtf](installer/License.rtf) for the full text.

Copyright © 2025 Anel Celik / Casultra

---

## Developer

**Casultra** · [celikovic.xyz](https://celikovic.xyz)
