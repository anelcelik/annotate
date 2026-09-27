"""
ocr_win.py — Snip & Read on the text recognition built into Windows.

Windows 10 and 11 ship an OCR engine (Windows.Media.Ocr) that reads every
language whose "Optical character recognition" feature is installed — English
comes with an English Windows, and adding a language in Settings adds its OCR.
It runs offline, needs no model download and costs the package nothing, where
EasyOCR + Torch was ~240 MB, a 150 MB first-run download, ~5 s to start and
~440 MB of RAM held for good. It also reads more than English, which the
EasyOCR setup never did.

Everything here is blocking: call recognize() from a worker thread (a plain
thread joins the multithreaded apartment, where waiting on WinRT is allowed).
"""

import platform

IS_WIN = platform.system() == "Windows"

ADD_LANGUAGE_HELP = (
    "Windows has no text recognition installed for any language. Add it in "
    "Settings → Time & language → Language & region: pick a language → "
    "Language options → install “Optical character recognition”.")

# Scripts written without spaces between words; Windows puts a space between
# every recognised "word" (character) anyway.
_NO_SPACE_TAGS = ("zh", "ja")

_available: bool | None = None


class OcrUnavailable(RuntimeError):
    pass


def available() -> bool:
    """Windows OCR can run here: pywinrt is present and at least one
    recognizer language is installed."""
    global _available
    if _available is None:
        _available = False
        if IS_WIN:
            try:
                from winrt.windows.media.ocr import OcrEngine
                _available = len(OcrEngine.available_recognizer_languages) > 0
            except Exception:
                _available = False
    return _available


def languages() -> list[tuple[str, str]]:
    """(language tag, display name) for every installed recognizer language."""
    if not IS_WIN:
        return []
    try:
        from winrt.windows.media.ocr import OcrEngine
        return [(lang.language_tag, lang.display_name)
                for lang in OcrEngine.available_recognizer_languages]
    except Exception:
        return []


def default_language() -> str:
    """The recognizer Windows would pick from the user's language list."""
    try:
        from winrt.windows.media.ocr import OcrEngine
        engine = OcrEngine.try_create_from_user_profile_languages()
        if engine is not None:
            return engine.recognizer_language.language_tag
    except Exception:
        pass
    langs = languages()
    return langs[0][0] if langs else ""


def prepare(image):
    """The QImage Windows OCR reads best: 32-bit BGRA, and small text scaled
    up — the engine wants letters roughly 20 px tall or more, and a snip of
    ordinary UI text at 100 % scaling is often half that."""
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QImage
    img = image.convertToFormat(QImage.Format.Format_ARGB32_Premultiplied)
    h = img.height()
    factor = 3 if h < 60 else 2 if h < 200 else 1
    if factor > 1:
        img = img.scaled(img.width() * factor, h * factor,
                         Qt.AspectRatioMode.IgnoreAspectRatio,
                         Qt.TransformationMode.SmoothTransformation)
    return img


def join_lines(lines: list[list[str]], language_tag: str) -> str:
    """Words per line → text, without the spaces Windows inserts between
    the characters of Chinese and Japanese."""
    sep = "" if language_tag.lower().startswith(_NO_SPACE_TAGS) else " "
    return "\n".join(sep.join(words) for words in lines).strip()


def _recognize(image, language_tag: str = ""):
    """(OcrResult, engine, scale back to the image's own pixels). Blocking."""
    if not IS_WIN:
        raise OcrUnavailable("Windows text recognition is only available on Windows.")
    try:
        from winrt.windows.globalization import Language
        from winrt.windows.graphics.imaging import BitmapPixelFormat, SoftwareBitmap
        from winrt.windows.media.ocr import OcrEngine
        from winrt.windows.storage.streams import Buffer
    except Exception as e:
        raise OcrUnavailable(f"Windows text recognition couldn't be loaded ({e}).")

    engine = None
    if language_tag:
        try:
            engine = OcrEngine.try_create_from_language(Language(language_tag))
        except Exception:
            engine = None
    if engine is None:
        engine = OcrEngine.try_create_from_user_profile_languages()
    if engine is None:
        raise OcrUnavailable(ADD_LANGUAGE_HELP)

    img = prepare(image)
    full_width = max(1, img.width())
    limit = int(OcrEngine.max_image_dimension)
    if img.width() > limit or img.height() > limit:
        from PySide6.QtCore import Qt
        img = img.scaled(min(img.width(), limit), min(img.height(), limit),
                         Qt.AspectRatioMode.KeepAspectRatio,
                         Qt.TransformationMode.SmoothTransformation)
    data = bytes(img.constBits())
    try:
        # pywinrt takes any buffer-protocol object where WinRT wants an IBuffer.
        bitmap = SoftwareBitmap.create_copy_from_buffer(
            data, BitmapPixelFormat.BGRA8, img.width(), img.height())
    except TypeError:
        buf = Buffer(len(data))
        buf.length = len(data)
        memoryview(buf)[:len(data)] = data
        bitmap = SoftwareBitmap.create_copy_from_buffer(
            buf, BitmapPixelFormat.BGRA8, img.width(), img.height())
    result = engine.recognize_async(bitmap).get()
    return result, engine, full_width / max(1, img.width())


def recognize(image, language_tag: str = "") -> str:
    """Text in a QImage. Blocking — call from a worker thread."""
    result, engine, _scale = _recognize(image, language_tag)
    lines = [[w.text for w in line.words] for line in result.lines]
    return join_lines(lines, engine.recognizer_language.language_tag)


def recognize_words(image, language_tag: str = "") -> list:
    """Every line as [(word, (x, y, w, h)), …], boxes in the image's pixels.
    Blocking — call from a worker thread."""
    result, _engine, s = _recognize(image, language_tag)
    lines = []
    for line in result.lines:
        words = []
        for w in line.words:
            r = w.bounding_rect
            words.append((w.text, (r.x * s, r.y * s, r.width * s, r.height * s)))
        lines.append(words)
    return lines
