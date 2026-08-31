# Versions

This repo's root (`annotate.py`, `dock_toolbar.py`, `installer/`, `annotate.spec`,
`.github/workflows/`, …) is the **live copy** — the one that actually builds,
ships, and gets committed to git. It always matches the newest snapshot below.

The folders in here are **frozen snapshots**, one per toolbar redesign, kept
so you can always tell what changed and open an old one directly without
touching git.

| Folder | What it is |
| --- | --- |
| [`v1-vertical-toolbar/`](v1-vertical-toolbar/) | The original app — vertical `Toolbar` panel (31 controls, ~940px tall), dark rounded Settings/Help dialogs. Matches commit `a992110` (v3.0.1), the last Store build before the redesign. |
| [`v2-dock-toolbar/`](v2-dock-toolbar/) | Current state — horizontal dock at the bottom (`dock_toolbar.py`), flat light Settings/Help dialogs to match. Includes `redesign-notes/` with the original proposal (REDESIGN.md, before/after screenshots, the design mockup). |

## Adding a V3

When the next redesign starts:

1. Finish and verify the change at the **root** first (that's still the only
   copy that's actually wired into the build).
2. Snapshot root into a new folder before you keep going:
   ```
   mkdir archive/v3-<short-name>
   git archive HEAD | tar -x -C archive/v3-<short-name>   # if committed, or just `cp -r`
   ```
   Note: `git archive HEAD` only captures what's committed. If root has
   uncommitted changes you want in the snapshot, copy the working tree
   instead (`cp -r` the tracked files, skipping `.git`, `__pycache__`, and
   the `archive/` folder itself).
3. Update the table above.

## Why not just git tags?

Git already has real history (`git log`, `git tag`) and that's still the
source of truth for the live app. These folders exist purely so you (or
anyone browsing the repo) can see "old vs new" at a glance without running
git commands — they're a convenience layer on top of git, not a replacement
for it.
