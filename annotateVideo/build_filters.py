"""
build_filters.py — what the PyInstaller specs leave out of the bundle.

Shared by annotate.spec (folder build → MSIX / Store) and annotate_onefile.spec
(single .exe), and kept out of the specs so it can be tested: a rule that drops
something the app needs only shows up as a crash on a user's machine, so CI
also launches the finished build with --self-test.

Measured on the 5.0 Store package (242 MB installed), everything below was
dead weight: ~48 MB of it, plus 39 MB from a smaller ffmpeg build (see CI).
"""

# Qt DLLs and plugins the app never loads. Matched as substrings of the
# bundled file's path.
QT_DROP = {
    # Qt modules nothing imports
    'Qt6Network', 'Qt6Sql', 'Qt6Test', 'Qt6Xml', 'Qt6Bluetooth', 'Qt6DBus',
    'Qt6Multimedia', 'Qt6MultimediaWidgets', 'Qt6Positioning',
    'Qt6PrintSupport', 'Qt6Qml', 'Qt6Quick', 'Qt6QuickWidgets',
    'Qt6RemoteObjects', 'Qt6Sensors', 'Qt6SerialPort', 'Qt6Svg',
    'Qt6SvgWidgets', 'Qt6WebChannel', 'Qt6WebSockets', 'Qt6WebEngineCore',
    'Qt6WebEngineWidgets', 'Qt63DCore', 'Qt63DRender', 'Qt63DAnimation',
    'Qt63DExtras', 'Qt63DInput', 'Qt63DLogic',
    'qsqlite', 'qsqlodbc', 'qsqlpsql', 'qtvirtualkeyboard',
    # 19.7 MB software OpenGL fallback — every pixel here is QPainter raster
    'opengl32sw',
    # 4.4 MB PDF engine and its image plugin
    'Qt6Pdf', 'qpdf',
    # Image plugins: PNG is built into QtGui and the icons are .ico (qico);
    # nothing reads TIFF, WebP, JPEG, GIF, SVG, TGA, WBMP or ICNS.
    'qtiff', 'qwebp', 'qjpeg', 'qgif', 'qsvg', 'qtga', 'qwbmp', 'qicns',
    # Platform / input plugins for environments the app doesn't run in.
    # (qoffscreen stays: --self-test uses it.)
    'qminimal', 'qtuiotouchplugin',
    # PySide6 also ships the Direct2D platform plugin; Qt only loads qwindows.
    'qdirect2d',
}

# Python modules the lite build (the Store package) doesn't need. Pillow is
# only used by the OCR path, which the lite build doesn't have; OpenSSL comes
# in with ssl/_hashlib and nothing in the lite build makes a network call
# (hashlib falls back to its built-in algorithms without _hashlib).
LITE_EXCLUDES = [
    'easyocr', 'torch', 'torchvision', 'scipy', 'skimage', 'cv2',
    'numpy', 'deep_translator', 'matplotlib', 'pandas',
    'PIL', 'ssl', '_ssl', '_hashlib',
]


def _norm(path: str) -> str:
    return path.replace('\\', '/')


def keep_binary(dest: str) -> bool:
    return not any(drop in dest for drop in QT_DROP)


def keep_data(dest: str) -> bool:
    # Qt's own translations (6.4 MB): the app never installs a QTranslator.
    # (PyQt6 kept them in PyQt6/Qt6/translations, PySide6 in PySide6/translations.)
    path = '/' + _norm(dest)
    return '/Qt6/translations/' not in path and '/PySide6/translations/' not in path


def filter_toc(toc, keep):
    """Filter a PyInstaller TOC (entries are tuples, dest name first)."""
    return [entry for entry in toc if keep(entry[0])]
