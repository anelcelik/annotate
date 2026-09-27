"""6.2: find and hide private info, copy a recording to the clipboard."""
import time

import pytest
from PySide6.QtCore import QEvent, QUrl, Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtTest import QTest

import redact_finder as RF


def line(*words, y=100, h=20):
    """Words laid out left to right, 10 px per character plus a space."""
    out, x = [], 50
    for w in words:
        out.append((w, (x, y, len(w) * 10, h)))
        x += len(w) * 10 + 10
    return out


def kinds(lines):
    return [k for k, _box in RF.find_private(lines)]


def test_emails_phones_and_labels():
    assert kinds([line("Mail", "anel.celik@example.com", "today")]) == ["email"]
    assert kinds([line("Call", "+49", "176", "1234", "5678")]) == ["phone"]
    assert kinds([line("Password:", "hunter2", "please")]) == ["password"]
    assert kinds([line("PIN", "=", "4711")]) == ["password"]


def test_checksums_keep_ordinary_numbers_readable():
    assert kinds([line("Card", "4111", "1111", "1111", "1111")]) == ["card"]
    assert kinds([line("Order", "4111", "1111", "1111", "1112")]) == []      # bad Luhn
    assert kinds([line("IBAN", "DE89", "3704", "0044", "0532", "0130", "00")]) == ["iban"]
    assert kinds([line("Ref", "DE89", "3704", "0044", "0532", "0130", "01")]) == []
    assert kinds([line("Due", "2026-09-27", "at", "10:30")]) == []           # a date
    assert kinds([line("Pin", "to", "taskbar")]) == []                      # not a label


def test_keys_but_not_file_names():
    assert kinds([line("key", "sk-live-4f8Qp2Lx9ZmN3wR7")]) == ["key"]
    assert kinds([line("token", "ghp_16C7e42F292c6912E7710c838347Ae178B4a")]) == ["key"]
    assert kinds([line("annotation_20260927_183012.mp4")]) == []
    assert kinds([line("commit", "9f1c2e3d4b5a69788796a5b4c3d2e1f0a9b8c7d6")]) == ["key"]


def test_a_match_spanning_words_gets_one_box():
    [(kind, box)] = RF.find_private([line("Card", "4111", "1111", "1111", "1111")])
    assert kind == "card" and box[0] == 100 and box[2] == 190     # four words, one box


def test_summary_counts():
    found = [("email", (0, 0, 1, 1)), ("email", (0, 0, 1, 1)), ("card", (0, 0, 1, 1))]
    assert RF.summary(found) == "2 email addresses, 1 card number"


def screen_grab(A, overlay, monkeypatch):
    from PySide6.QtGui import QColor, QPixmap

    def grab(g):
        pm = QPixmap(g.size())
        pm.fill(QColor("#f5f5f5"))
        return pm
    monkeypatch.setattr(overlay, "_grab_screen", grab)
    monkeypatch.setattr(A.ocr_win, "available", lambda: True)


def test_b_hides_what_it_finds(A, overlay, monkeypatch):
    screen_grab(A, overlay, monkeypatch)
    monkeypatch.setattr(A.ocr_win, "recognize_words", lambda image: [
        line("Mail", "anel.celik@example.com", y=40),
        line("Card", "4111", "1111", "1111", "1111", y=80)])
    cv = overlay.canvas
    overlay.keyPressEvent(QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_B,
                                    Qt.KeyboardModifier.NoModifier))
    deadline = time.monotonic() + 10
    while overlay._scan is not None and time.monotonic() < deadline:
        QTest.qWait(20)
    blurs = [s for s in cv._shapes if type(s).__name__ == "BlurShape"]
    assert len(blurs) == 2 and all(b.blurred and not b.blurred.isNull() for b in blurs)
    cv.undo()                                        # one step takes them all
    assert cv._shapes == []


def test_black_box_style_follows_the_tool(A, overlay, monkeypatch):
    screen_grab(A, overlay, monkeypatch)
    monkeypatch.setattr(A.ocr_win, "recognize_words",
                        lambda image: [line("Password:", "hunter2")])
    overlay.toolbar._activate("redact")
    overlay.auto_redact()
    deadline = time.monotonic() + 10
    while overlay._scan is not None and time.monotonic() < deadline:
        QTest.qWait(20)
    assert [type(s).__name__ for s in overlay.canvas._shapes] == ["RedactShape"]


def test_copy_puts_the_file_on_the_clipboard(A, tmp_path):
    from PySide6.QtWidgets import QApplication
    f = tmp_path / "clip.mp4"
    f.write_bytes(b"x")
    A.copy_file_to_clipboard(str(f))
    urls = QApplication.clipboard().mimeData().urls()
    assert urls == [QUrl.fromLocalFile(str(f))]
