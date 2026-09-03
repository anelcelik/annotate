# Versions

**[`annotateVideo/`](../annotateVideo/) is the live copy** — the one that actually
builds, ships, and gets committed to. Screen recording is a feature of it, not
a separate app; its own [`AppxManifest.xml`](../annotateVideo/installer/AppxManifest.xml)
carries the real Store identity (`Casultra.ScreenAnnotatorPro`), and
[`build-video.yml`](../.github/workflows/build-video.yml) is what builds and
releases it.

The folders in here are **frozen snapshots**, kept so you can always tell what
changed and open an old one directly without touching git.

| Folder | What it is |
| --- | --- |
| [`before-recording/`](before-recording/) | The app immediately before recording was added — no `video_recorder.py`, no Record button. Was "MS Store version/" at the repo root; last built as v4.0.0. |
| [`after-recording/`](after-recording/) | A snapshot of `annotateVideo/` taken right as recording landed. `annotateVideo/` itself keeps moving past this point — this folder won't. |

Earlier toolbar-redesign snapshots (vertical panel → horizontal dock) were
removed from here since they predate recording and weren't worth carrying
forward — they're still in git history (`git log --oneline -- archive/`) if
ever needed.

## Adding the next snapshot

When a change to `annotateVideo/` is worth freezing (a redesign, a feature
milestone):

1. Finish and verify the change in `annotateVideo/` first — that's still the
   only copy actually wired into the build.
2. Copy the *tracked* files into a new, clearly-named folder here — skip
   `.git`, `__pycache__`, `dist/`, and generated `icons/`:
   ```
   mkdir archive/<short-name>
   git ls-files annotateVideo | while read f; do
     mkdir -p "archive/<short-name>/$(dirname "${f#annotateVideo/}")"
     cp "$f" "archive/<short-name>/${f#annotateVideo/}"
   done
   git add archive/<short-name>
   ```
3. Update the table above.

## Why not just git tags?

Git already has real history (`git log`, `git tag`) and that's still the
source of truth for the live app. These folders exist purely so you (or
anyone browsing the repo) can see "old vs new" at a glance without running
git commands — they're a convenience layer on top of git, not a replacement
for it.
