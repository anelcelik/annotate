# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for Annotate — single-file Windows executable.
# Build: pyinstaller annotate.spec

a = Analysis(
    ['annotate.py'],
    pathex=[],
    binaries=[],
    datas=[('icons/tray.ico', 'icons')],
    hiddenimports=[
        'PyQt6.sip',
        # pynput platform back-ends (optional — only used on Windows for hotkey)
        'pynput.keyboard._win32',
        'pynput.mouse._win32',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='ScreenAnnotatorPro',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,                      # no console window
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['icons/annotate.ico'],        # embedded app icon
)
