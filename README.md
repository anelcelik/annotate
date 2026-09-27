<p align="center">
  <a href="https://apps.microsoft.com/detail/9NS87MQB29C7"><img src="docs/media/banner.png" alt="Screen Annotator Pro: draw on anything on your screen" width="100%"></a>
</p>

<p align="center">
  <a href="https://apps.microsoft.com/detail/9NS87MQB29C7"><img alt="Get it on the Microsoft Store" src="https://img.shields.io/badge/Microsoft_Store-get_it-0A84FF?style=for-the-badge&labelColor=201e1d"></a>
  <img alt="Windows 10 and 11" src="https://img.shields.io/badge/Windows-10_%7C_11-ec3013?style=for-the-badge&labelColor=201e1d">
  <img alt="Records to MP4" src="https://img.shields.io/badge/records_to-MP4-f3f2f2?style=for-the-badge&labelColor=201e1d">
  <img alt="No account needed" src="https://img.shields.io/badge/account-not_needed-32D74B?style=for-the-badge&labelColor=201e1d">
  <a href="https://annotator.pro/"><img alt="Website: annotator.pro" src="https://img.shields.io/badge/website-annotator.pro-0A84FF?style=for-the-badge&labelColor=201e1d"></a>
</p>

# Screen Annotator Pro

Draw, highlight, annotate, redact, OCR, and now **record** anything on your
screen — live, in real time, without interrupting what's behind it.

<p align="center">
  <img src="docs/media/demo.webp" alt="Drawing an arrow, a label, a circle, a highlight and numbered callouts on a dashboard, sweeping the laser pointer, switching to click-through to change the page underneath while the marks stay, then recording it to MP4" width="100%">
</p>

<p align="center"><a href="docs/media/screen-annotator-pro-promo.mp4"><b>▶ Watch the full video (1080p MP4)</b></a> · <a href="https://apps.microsoft.com/detail/9NS87MQB29C7"><b>Get it on the Microsoft Store</b></a> · <a href="https://annotator.pro/"><b>annotator.pro</b></a></p>

## One dock, 17 tools

A flat dock at the bottom of the screen. The second row only shows what the
tool in your hand actually uses, and every tool has a one-key shortcut.

<p align="center">
  <img src="docs/media/dock.png" alt="The Screen Annotator Pro dock with its tool groups labeled: Draw, Annotate, Redact, Read, History, Mode, Capture, Record and Window" width="100%">
</p>

**Click-through mode** is the part that makes it usable live: your marks stay
on screen while the mouse goes back to the app underneath, so you can keep
demoing without the overlay holding your desktop hostage. `Ctrl+Shift+A`
flips between drawing and click-through. Step-by-step:
[how to draw on your screen in Windows 10 and 11](https://annotator.pro/guides/draw-on-screen-windows).

## Redact in one drag

Blur, pixelate or black-box anything before it ends up in a screenshot, a
meeting or a recording — see
[how to blur sensitive info while screen sharing](https://annotator.pro/guides/blur-screen-while-screen-sharing).

<p align="center">
  <img src="docs/media/redact.webp" alt="Blurring an email address and phone number, pixelating an IBAN and blacking out a live API key on an account settings page" width="100%">
</p>

## Snip & Read

Drag over text you can't select, like a shared screen in a video call, an
image or a scanned PDF, and get it back as real text. Copy it, or send it to
Google Translate in one click. Reading uses the text recognition built into
Windows — offline, instant, in every language you have installed.

<p align="center">
  <img src="docs/media/ocr.webp" alt="Snipping a paragraph off a slide shared in a video call and getting the recognized text in the OCR and Translate window" width="100%">
</p>

## Measure, box and number

A ruler that labels pixel distances, boxes, numbered step markers, a freehand
pen, and undo and redo for all of it.

<p align="center">
  <img src="docs/media/measure.webp" alt="Measuring a headline and a gap with the ruler, boxing a button, placing numbered steps and underlining a word on a design mockup" width="100%">
</p>

## Light and dark

<p align="center">
  <img src="docs/media/themes.png" alt="The dock in the light theme and in the dark theme" width="100%">
</p>

Every animation above is the real app, running from this repo's source: the
dock, the dialogs, the marks and the OCR result are rendered by Screen
Annotator Pro itself. Only the cursor and the captions are added on top, and
the pages being annotated are made-up examples.

## Where the source is

**[`annotateVideo/`](annotateVideo/) is the app.** That's the only folder
that's actively developed, the only one wired into a release pipeline
([`build-video.yml`](.github/workflows/build-video.yml)), and the one that
carries the real Microsoft Store identity
(`Casultra.ScreenAnnotatorPro`, Store ID `9NS87MQB29C7` — see its
[`AppxManifest.xml`](annotateVideo/installer/AppxManifest.xml)). Screen
recording is a feature of this one app, not a separate product — see
[`annotateVideo/README.md`](annotateVideo/README.md) for the full feature
list, hotkeys, and build instructions.

Everything else at the repo root is support material, not app source:

| Path | What it is |
| --- | --- |
| [`annotateVideo/`](annotateVideo/) | **The app.** Live source, builds, and releases. |
| [`archive/`](archive/) | Two frozen snapshots — the app right before and right after recording was added — kept for comparison. Nothing in here is built or maintained going forward; see [`archive/README.md`](archive/README.md). |
| [`docs/`](docs/) | Microsoft Store listing text and screenshots (`infosMS.md`), plus the README media in [`docs/media/`](docs/media/) — reference material, not app code. |

## Releases

Tagging `vX.Y.Z` on `main` builds and publishes a GitHub Release with the
portable `.exe`, the `.msi` installer, the sideload
`.msix`, and an unsigned `.msix` for Partner Center, with the notes from
[`docs/release-notes/`](docs/release-notes/) — see
[`annotateVideo/README.md`](annotateVideo/README.md#installation) for
details. The Microsoft Store listing itself is a manual Partner Center
submission using that unsigned `.msix`.

## License

MIT — see [`archive/before-recording/installer/License.rtf`](archive/before-recording/installer/License.rtf).

Built on Qt for Python (PySide6, LGPLv3); the full list of open-source parts and their licenses is in [`annotateVideo/THIRD_PARTY_NOTICES.txt`](annotateVideo/THIRD_PARTY_NOTICES.txt).

Copyright © 2025–2026 Anel Celik / Casultra · [celikovic.xyz](https://celikovic.xyz)
