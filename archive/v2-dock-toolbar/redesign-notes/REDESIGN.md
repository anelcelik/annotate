# Toolbar redesign — what needs to be done

Replace the vertical `Toolbar` panel with a horizontal dock at the bottom of the screen.

![The dock](docs/dock-toolbar.png)

![In context](docs/dock-in-context.png)

## Why

The current panel is a ~940px column of text rows. It sits on top of the content being
annotated, and it shows all 31 controls whether the active tool uses them or not.
Black Box has no colour, Blur has no stroke, but both sets of widgets are always on screen.

| | Before | After |
| --- | --- | --- |
| Panel height | 940px | 112px |
| Screen covered (1080p) | ~14% | ~4% |
| Controls visible at once | 31 | 17 + only the active tool's properties |
| Clicks to reach any tool | 1–2 (sections collapse) | 1 |

## The design

**Row 1 — tools, always the same.** 17 icon cells, 48×56, grouped Draw / Annotate /
Redact / Read by 2px rules. Shortcut key printed small in the bottom-right of each cell.
Active tool gets an accent tint plus a 4px accent bar on its bottom edge — never a colour
swap on the icon itself. Undo / Redo / Clear sit in a tinted cell behind a rule, away from
the tools. Exit is the only red-filled control, at the far end.

**Row 2 — properties, rewritten per tool.** Left cell shows the active tool's name and key.
To its right, only the properties that tool actually uses, then its tip. Selecting Black
Box empties the row down to the name; selecting Pen fills it with colour, stroke and opacity.

**Chrome.** Zero corner radius, 2px rules, ink `#201e1d` on ground `#f3f2f2`, accent
`#ec3013`, tinted active `#ffe0d9`. Property row is `#eae9e9`.

**Drag.** The dotted grip at the left end is the only drag surface — clicking a tool can
never move the dock by accident.

## Wiring it up

`dock_toolbar.py` is a drop-in. Same constructor, same `_activate(tool_id)`, so the key
handler and the OCR hotkey keep working with no changes.

Add one line to `annotate.py`, immediately **before** `class AnnotationOverlay(QWidget):`
(around line 2252):

```python
from dock_toolbar import Toolbar   # noqa: E402 — horizontal dock
```

It rebinds the name `Toolbar`, so the old class stays in the file. Comment the line out to
flip back. Once you're happy, `Toolbar`, `ToolSection`, `DotPreview` and `TOOL_GROUPS` can
be deleted from `annotate.py`.

## Two edits needed to make the redact sliders live

The dock exposes a Blur radius and a Pixelate cell size. It writes them to
`canvas.blur_radius` and `canvas.pixel_size`. Nothing reads those yet, so without these two
edits the sliders move but do nothing.

**1. Blur radius** — in `Canvas.mouseReleaseEvent`, where the blur is applied:

```python
# before
blurred = _blur_pixmap(raw)
# after
blurred = _blur_pixmap(raw, getattr(self, "blur_radius", 18))
```

**2. Pixelate cell** — in `PixelShape.draw`, replace the hard-coded `pz = 12` with:

```python
pz = getattr(self, "size", 12)
```

and in `Canvas._make_drag`, the `pixel` branch becomes:

```python
if t == "pixel":
    s = PixelShape(p1, p2)
    s.size = getattr(self, "pixel_size", 12)
    return s
```

## To check once it runs

- Icons at 150% and 200% DPI. They're painted with `QPainter` on a 24×24 grid, so they
  scale cleanly, but the shortcut-key glyph is 7pt and worth a look.
- Archivo isn't installed on a stock Windows box — the `FONT` constant falls back to the
  system UI font. Either bundle Archivo or set `FONT = "Segoe UI Variable"`.
- Dock width on a 1366px laptop. It's ~1180px, so it fits, but verify it doesn't clip.
- `_position()` places the dock centred, 28px off the bottom of the *primary* screen's
  available geometry. On a multi-monitor setup you may want the screen under the cursor.

## Not done yet

The Settings dialog and the OCR result window still use the old styling. If the dock lands,
they should get the same treatment — flat, 2px rules, no emoji, flush-left labels.
