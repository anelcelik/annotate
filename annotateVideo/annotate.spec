# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for Screen Annotator Pro — single-file Windows executable.
# Build: pyinstaller annotate.spec

# ── Collect EasyOCR + deep-translator data/binaries/imports ──────────────────
# collect_all() handles every file the package ships so nothing is missed.
# Wrapped in try/except so local builds without these packages still work.
import os as _os

# Same switch as annotate_onefile.spec: ANNOTATE_LITE=1 leaves out EasyOCR and
# Torch. Everything except Snip & Read still works, and the package drops from
# roughly a gigabyte to something you can install on a test VM.
LITE = _os.environ.get("ANNOTATE_LITE", "") not in ("", "0", "false", "False")
print(f"spec: folder build, {'LITE (no OCR)' if LITE else 'FULL'}")

try:
    if LITE:
        raise RuntimeError("lite build: skipping the OCR stack")
    from PyInstaller.utils.hooks import collect_all
    _easyocr_d, _easyocr_b, _easyocr_h  = collect_all('easyocr')
    _dt_d,      _dt_b,      _dt_h        = collect_all('deep_translator')
    _torch_d,   _torch_b,   _torch_h     = collect_all('torch')
    _tv_d,      _tv_b,      _tv_h        = collect_all('torchvision')
except Exception as _e:
    if not LITE:
        print(f"spec: OCR packages not collectable ({_e})")
    _easyocr_d = _easyocr_b = _easyocr_h = []
    _dt_d      = _dt_b      = _dt_h      = []
    _torch_d   = _torch_b   = _torch_h   = []
    _tv_d      = _tv_b      = _tv_h      = []

# ── Bundle ffmpeg, if a binary is sitting here to bundle ─────────────────────
# Recording shells out to ffmpeg. Drop ffmpeg.exe in vendor/ (or beside this
# spec) and it ships inside the app; leave it out and the build still works —
# the app then looks for ffmpeg on PATH and tells the user how to get it.
import os as _os
_FFMPEG = []
for _cand in ('vendor/ffmpeg.exe', 'ffmpeg.exe', 'vendor/ffmpeg', 'ffmpeg'):
    if _os.path.isfile(_cand):
        _FFMPEG = [(_cand, '.')]
        print(f"spec: bundling {_cand} "
              f"({_os.path.getsize(_cand) / 1e6:.0f} MB)")
        break
else:
    print("spec: no ffmpeg binary found — recording will need one on PATH")

a = Analysis(
    ['annotate.py'],
    pathex=[],
    binaries=_easyocr_b + _dt_b + _torch_b + _tv_b,
    datas=[
        ('icons/tray.ico', 'icons'),
        ('installer/app.manifest', '.'),
    ] + _FFMPEG + _easyocr_d + _dt_d + _torch_d + _tv_d,
    hiddenimports=[
        'PyQt6.sip',
        'video_recorder',
        'pynput.keyboard._win32',
        'pynput.mouse._win32',
    ] + ([] if LITE else [
        # EasyOCR
        'easyocr', 'easyocr.detection', 'easyocr.recognition',
        'easyocr.utils', 'easyocr.config', 'easyocr.model',
        'easyocr.model.vgg_model', 'easyocr.model.modules',
        'easyocr.model.ConvNextViT_model',
        # deep-translator
        'deep_translator', 'deep_translator.google',
        'deep_translator.exceptions', 'deep_translator.base',
        # Torch (CPU-only build)
        'torch', 'torch.nn', 'torch.nn.functional',
        'torch.utils', 'torch.utils.data',
        'torchvision', 'torchvision.transforms',
        # Numeric / image
        'numpy', 'scipy', 'scipy.ndimage', 'skimage',
        'PIL', 'PIL.Image',
    ]) + _easyocr_h + _dt_h + _torch_h + _tv_h,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # Qt modules we don't use
        'PyQt6.QtNetwork',        'PyQt6.QtSql',
        'PyQt6.QtTest',           'PyQt6.QtXml',
        'PyQt6.QtBluetooth',      'PyQt6.QtDBus',
        'PyQt6.QtMultimedia',     'PyQt6.QtMultimediaWidgets',
        'PyQt6.QtPositioning',    'PyQt6.QtPrintSupport',
        'PyQt6.QtQml',            'PyQt6.QtQuick',
        'PyQt6.QtQuickWidgets',   'PyQt6.QtRemoteObjects',
        'PyQt6.QtSensors',        'PyQt6.QtSerialPort',
        'PyQt6.QtSvg',            'PyQt6.QtSvgWidgets',
        'PyQt6.QtWebChannel',     'PyQt6.QtWebSockets',
        'PyQt6.QtWebEngineCore',  'PyQt6.QtWebEngineWidgets',
        'PyQt6.Qt3DCore',         'PyQt6.Qt3DRender',
        'PyQt6.Qt3DAnimation',    'PyQt6.Qt3DExtras',
        'PyQt6.Qt3DInput',        'PyQt6.Qt3DLogic',
        # Torch CUDA — we install CPU-only, exclude CUDA stubs so they
        # don't get bundled even if discovered
        'torch.cuda', 'torch.backends.cudnn',
        # Safe stdlib excludes
        'tkinter', '_tkinter',
        'tkinter', '_tkinter',
        'curses', 'lib2to3', 'test',
    ] + ([
        'easyocr', 'torch', 'torchvision', 'scipy', 'skimage', 'cv2',
        'numpy', 'deep_translator', 'matplotlib', 'pandas',
    ] if LITE else []),
    noarchive=False,
)

# ── Strip unused Qt6 native DLLs ─────────────────────────────────────────────
_QT_DROP = {
    'Qt6Network',     'Qt6Sql',           'Qt6Test',
    'Qt6Xml',         'Qt6Bluetooth',     'Qt6DBus',
    'Qt6Multimedia',  'Qt6MultimediaWidgets',
    'Qt6Positioning', 'Qt6PrintSupport',
    'Qt6Qml',         'Qt6Quick',         'Qt6QuickWidgets',
    'Qt6RemoteObjects','Qt6Sensors',      'Qt6SerialPort',
    'Qt6Svg',         'Qt6SvgWidgets',
    'Qt6WebChannel',  'Qt6WebSockets',
    'Qt6WebEngineCore','Qt6WebEngineWidgets',
    'Qt63DCore',      'Qt63DRender',      'Qt63DAnimation',
    'Qt63DExtras',    'Qt63DInput',       'Qt63DLogic',
    'qsqlite',        'qsqlodbc',         'qsqlpsql',
    'qtvirtualkeyboard',
}
a.binaries = TOC([
    b for b in a.binaries
    if not any(drop in b[0] for drop in _QT_DROP)
])

pyz = PYZ(a.pure, a.zipped_data)

_UPX_EXCLUDE = [
    'ffmpeg.exe',                      # UPX-packing ffmpeg breaks it
    'vcruntime*.dll', 'msvcp*.dll', 'python*.dll',
    'Qt6Core.dll', 'Qt6Gui.dll', 'Qt6Widgets.dll',
    'torch_*.dll', '_C.pyd', 'numpy*.pyd',
]

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='ScreenAnnotatorPro',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=_UPX_EXCLUDE,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['icons/annotate.ico'],
    manifest='installer/app.manifest',
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=_UPX_EXCLUDE,
    name='ScreenAnnotatorPro',
)
