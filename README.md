# Screen Annotator Pro

Draw, highlight, annotate, redact, OCR, and now **record** anything on your
screen — live, in real time, without interrupting what's behind it.

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
| [`docs/`](docs/) | Microsoft Store listing text and screenshots (`infosMS.md`) — reference copy for Partner Center, not app code. |

## Releases

Tagging `vX.Y.Z` on `main` builds and publishes a GitHub Release with the
single-file `.exe` (full and lite), the sideload `.msix`, and an unsigned
`.msix` for Partner Center — see
[`annotateVideo/README.md`](annotateVideo/README.md#installation) for
details. The Microsoft Store listing itself is a manual Partner Center
submission using that unsigned `.msix`.

## License

MIT — see [`archive/before-recording/installer/License.rtf`](archive/before-recording/installer/License.rtf).

Copyright © 2025–2026 Anel Celik / Casultra · [celikovic.xyz](https://celikovic.xyz)
