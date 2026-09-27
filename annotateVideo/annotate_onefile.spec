# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec — ONE self-contained .exe for a machine with no Python.
#
# Build:  pyinstaller annotate_onefile.spec
#         ANNOTATE_LITE=1 pyinstaller annotate_onefile.spec    (no OCR)
#
# Unlike annotate.spec (a folder build, which is what the Store package and
# the MSI are made from), this produces a single file: Python, Qt, ffmpeg and
# everything else are packed into the .exe and unpacked to a temp folder at
# launch. That costs startup time and disk, and buys "download one file, run
# it, done" — the point being to test on a fresh Windows box.
#
# ANNOTATE_LITE=1 leaves out EasyOCR and Torch. Everything except Snip & Read
# still works, the file is a fraction of the size and it starts far faster.

import os as _os
import sys as _sys
_sys.path.insert(0, SPECPATH)
import build_filters as _bf   # shared, tested drop rules

LITE = _os.environ.get("ANNOTATE_LITE", "") not in ("", "0", "false", "False")
print(f"spec: building the {'LITE (no OCR)' if LITE else 'FULL'} single-file exe")

# ── OCR stack — skipped entirely in a lite build ─────────────────────────────
_ocr_d = _ocr_b = _ocr_h = []
if not LITE:
    try:
        from PyInstaller.utils.hooks import collect_all
        _e_d, _e_b, _e_h = collect_all('easyocr')
        _d_d, _d_b, _d_h = collect_all('deep_translator')
        _t_d, _t_b, _t_h = collect_all('torch')
        _v_d, _v_b, _v_h = collect_all('torchvision')
        _ocr_d = _e_d + _d_d + _t_d + _v_d
        _ocr_b = _e_b + _d_b + _t_b + _v_b
        _ocr_h = _e_h + _d_h + _t_h + _v_h
    except Exception as e:
        print(f"spec: OCR packages not collectable ({e}) — building without them")

# ── ffmpeg: the recorder is useless without it, so it must be in here ────────
_FFMPEG = []
for _cand in ('vendor/ffmpeg.exe', 'ffmpeg.exe', 'vendor/ffmpeg', 'ffmpeg'):
    if _os.path.isfile(_cand):
        _FFMPEG = [(_cand, '.')]
        print(f"spec: bundling {_cand} ({_os.path.getsize(_cand) / 1e6:.0f} MB)")
        break
else:
    raise SystemExit(
        "spec: no ffmpeg binary found.\n"
        "A single-file build has no PATH to fall back on — put ffmpeg.exe in "
        "vendor/ before building, or recording will not work on the target "
        "machine."
    )

# ── Optional bits: present in the repo, absent in a bare copy of the folder ──
_datas = list(_FFMPEG)
for _src, _dst in (('icons/tray.ico', 'icons'), ('icons/annotate.ico', 'icons'),
                   ('THIRD_PARTY_NOTICES.txt', 'licenses'),
                   ('vendor/ffmpeg-LICENSE.txt', 'licenses'),
                   ('vendor/ffmpeg-README.txt', 'licenses')):
    if _os.path.isfile(_src):
        _datas.append((_src, _dst))

_manifest = next((m for m in ('installer/app.manifest',
                              '../installer/app.manifest')
                  if _os.path.isfile(m)), None)
_icon = 'icons/annotate.ico' if _os.path.isfile('icons/annotate.ico') else None

_lite_excludes = (list(_bf.LITE_EXCLUDES) if LITE
                  else ['torch.cuda', 'torch.backends.cudnn'])

a = Analysis(
    ['annotate.py'],
    pathex=[],
    binaries=_ocr_b,
    datas=_datas + _ocr_d,
    hiddenimports=[
        'shiboken6',
        'video_recorder', 'hotkeys', 'platform_win', 'ocr_win', 'redact_finder',
        'pyaudiowpatch',
        'winrt.windows.media.ocr', 'winrt.windows.graphics.imaging',
        'winrt.windows.storage.streams', 'winrt.windows.globalization',
        'winrt.windows.foundation.collections',
        'winrt.windows.foundation', 'winrt.windows.applicationmodel',
        'winrt.windows.applicationmodel.activation',
        'winrt.windows.services.store', 'winrt.runtime.interop',
        'pynput.keyboard._win32',
        'pynput.mouse._win32',
    ] + ([] if LITE else [
        'easyocr', 'easyocr.detection', 'easyocr.recognition',
        'easyocr.utils', 'easyocr.config', 'easyocr.model',
        'easyocr.model.vgg_model', 'easyocr.model.modules',
        'easyocr.model.ConvNextViT_model',
        'deep_translator', 'deep_translator.google',
        'deep_translator.exceptions', 'deep_translator.base',
        'torch', 'torch.nn', 'torch.nn.functional',
        'torch.utils', 'torch.utils.data',
        'torchvision', 'torchvision.transforms',
        'numpy', 'scipy', 'scipy.ndimage', 'skimage', 'PIL', 'PIL.Image',
    ]) + _ocr_h,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'PySide6.QtNetwork',        'PySide6.QtSql',
        'PySide6.QtTest',           'PySide6.QtXml',
        'PySide6.QtBluetooth',      'PySide6.QtDBus',
        'PySide6.QtMultimedia',     'PySide6.QtMultimediaWidgets',
        'PySide6.QtPositioning',    'PySide6.QtPrintSupport',
        'PySide6.QtQml',            'PySide6.QtQuick',
        'PySide6.QtQuickWidgets',   'PySide6.QtRemoteObjects',
        'PySide6.QtSensors',        'PySide6.QtSerialPort',
        'PySide6.QtSvg',            'PySide6.QtSvgWidgets',
        'PySide6.QtWebChannel',     'PySide6.QtWebSockets',
        'PySide6.QtWebEngineCore',  'PySide6.QtWebEngineWidgets',
        'PySide6.Qt3DCore',         'PySide6.Qt3DRender',
        'PySide6.Qt3DAnimation',    'PySide6.Qt3DExtras',
        'PySide6.Qt3DInput',        'PySide6.Qt3DLogic',
        'tkinter', '_tkinter', 'curses', 'lib2to3', 'test',
    ] + _lite_excludes,
    noarchive=False,
)

# ── Strip what the app never loads — see build_filters.py ──────────────────
a.binaries = TOC(_bf.filter_toc(a.binaries, _bf.keep_binary))
a.datas = TOC(_bf.filter_toc(a.datas, _bf.keep_data))

pyz = PYZ(a.pure, a.zipped_data)

# Everything into EXE (no COLLECT) — that is what makes it a single file.
# UPX is deliberately off here: an unsigned, UPX-packed single-file exe is one
# of the strongest heuristics antivirus engines use, and this build exists to
# be downloaded and run on a machine that has never seen it before.
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='ScreenAnnotatorPro-Portable' + ('' if LITE else '-EasyOCR'),
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=[_icon] if _icon else None,
    manifest=_manifest,
)
