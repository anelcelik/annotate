# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for Screen Annotator Pro — single-file Windows executable.
# Build: pyinstaller annotate.spec

a = Analysis(
    ['annotate.py'],
    pathex=[],
    binaries=[],
    datas=[('icons/tray.ico', 'icons')],
    hiddenimports=[
        'PyQt6.sip',
        'pynput.keyboard._win32',
        'pynput.mouse._win32',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # ── Exclude every Python-level Qt6 module we don't use ───────────────────
    excludes=[
        # Unused Qt6 sub-modules
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
        # Safe stdlib excludes — NOT urllib/http/html/pathlib: pathlib
        # imports urllib.parse internally and PyInstaller hooks need it too.
        'tkinter', '_tkinter',
        'unittest', 'doctest', 'pydoc', 'difflib',
        'email', 'xmlrpc', 'ftplib', 'smtplib',
        'calendar', 'curses', 'lib2to3', 'distutils', 'test',
    ],
    noarchive=False,
)

# ── Strip unused Qt6 native DLLs that survived the Python-level excludes ─────
# PyInstaller's hook may still pull in the compiled Qt6 binaries even when
# the Python bindings are excluded.  Filter them out here directly.
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
    # Unused Qt plugins
    'qsqlite',        'qsqlodbc',         'qsqlpsql',
    'qtvirtualkeyboard',
}
a.binaries = TOC([
    b for b in a.binaries
    if not any(drop in b[0] for drop in _QT_DROP)
])

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
    upx=True,           # requires UPX on PATH — installed in CI via choco
    upx_exclude=[
        # Never compress these — UPX breaks them or slows them down
        'vcruntime*.dll', 'msvcp*.dll', 'python*.dll',
        'Qt6Core.dll', 'Qt6Gui.dll', 'Qt6Widgets.dll',
    ],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['icons/annotate.ico'],
    # Embed our Per-Monitor V2 DPI manifest so Windows never virtualises DPI
    # for this process.  Without this the MS Store WACK tool rejects the app.
    manifest='installer/app.manifest',
)
