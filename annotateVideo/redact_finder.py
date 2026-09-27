"""
redact_finder.py — what on a screen is private, given its recognized text.

Pure Python: lines of (word, box) in, (kind, box) out. The boxes come from
Windows' text recognition (ocr_win.recognize_words); the overlay covers each
one with a blur. Card numbers and IBANs are only taken when their checksum
holds, so an order number or a date doesn't get blurred for looking long.
"""

import re

EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}")
CARD = re.compile(r"(?<![\d])(?:\d[ -]?){12,18}\d(?![\d])")
IBAN = re.compile(r"\b[A-Z]{2}\d{2}(?: ?[A-Z0-9]){11,30}\b")
PHONE = re.compile(r"(?<![\w+])(?:\+|00)?\(?\d[\d ()./-]{6,}\d")
DATE = re.compile(r"^\d{1,4}[./-]\d{1,2}[./-]\d{1,4}$")
KEY_PREFIX = re.compile(r"^(sk|pk|rk)[-_](live|test)[-_]|^sk-|^ghp_|^gho_|^github_pat_|"
                        r"^xox[abpr]-|^AKIA|^ASIA|^AIza|^glpat-|^eyJ", re.I)
TOKEN = re.compile(r"^[A-Za-z0-9_\-+/=]{24,}$")
HEX = re.compile(r"^[0-9a-fA-F]{32,}$")
SECRET_LABEL = re.compile(r"^(password|passwort|kennwort|pass|pwd|pin|secret|token|"
                          r"api[-_ ]?key|contraseña|mot de passe)[:=]?$", re.I)

KINDS = {"email": "email address", "card": "card number", "iban": "IBAN",
         "phone": "phone number", "key": "key or token", "password": "password"}


def luhn(digits: str) -> bool:
    total, alt = 0, False
    for ch in reversed(digits):
        d = int(ch)
        if alt:
            d = d * 2 - 9 if d > 4 else d * 2
        total, alt = total + d, not alt
    return total % 10 == 0


def iban_ok(text: str) -> bool:
    s = text.replace(" ", "").upper()
    if not 15 <= len(s) <= 34:
        return False
    moved = s[4:] + s[:4]
    try:
        return int("".join(str(int(c, 36)) for c in moved)) % 97 == 1
    except ValueError:
        return False


def _looks_like_key(word: str) -> bool:
    w = word.strip(".,;:()[]{}'\"")
    if KEY_PREFIX.search(w) and len(w) >= 16:
        return True
    if HEX.match(w):
        return True
    # Mixed case and digits: a token, not a file name or a snake_case word.
    return bool(TOKEN.match(w)) and any(c.isdigit() for c in w) \
        and any(c.isupper() for c in w) and any(c.islower() for c in w)


def _union(boxes):
    x0 = min(b[0] for b in boxes)
    y0 = min(b[1] for b in boxes)
    x1 = max(b[0] + b[2] for b in boxes)
    y1 = max(b[1] + b[3] for b in boxes)
    return (x0, y0, x1 - x0, y1 - y0)


def find_private(lines) -> list:
    """[(kind, (x, y, w, h)), …] for everything private in `lines`, each
    line a list of (word, (x, y, w, h))."""
    found = []
    for words in lines:
        if not words:
            continue
        text, spans = "", []
        for word, box in words:
            if text:
                text += " "
            spans.append((len(text), len(text) + len(word), box))
            text += word
        taken = [False] * len(words)

        def cover(start, end, kind):
            hit = [i for i, (a, b, _box) in enumerate(spans) if a < end and b > start]
            if hit and not all(taken[i] for i in hit):
                for i in hit:
                    taken[i] = True
                found.append((kind, _union([spans[i][2] for i in hit])))

        for m in EMAIL.finditer(text):
            cover(m.start(), m.end(), "email")
        for m in IBAN.finditer(text):
            if iban_ok(m.group()):
                cover(m.start(), m.end(), "iban")
        for m in CARD.finditer(text):
            digits = re.sub(r"\D", "", m.group())
            if 13 <= len(digits) <= 19 and luhn(digits):
                cover(m.start(), m.end(), "card")
        for m in PHONE.finditer(text):
            s = m.group().strip()
            digits = re.sub(r"\D", "", s)
            if DATE.match(s) or not (9 <= len(digits) <= 15 or
                                     (s.startswith(("+", "00")) and len(digits) >= 8)):
                continue
            cover(m.start(), m.end(), "phone")
        for i, (word, _box) in enumerate(words):
            if not taken[i] and _looks_like_key(word):
                cover(spans[i][0], spans[i][1], "key")
            label = word.rstrip(":=")
            marked = word.endswith((":", "=")) or (
                i + 1 < len(words) and words[i + 1][0] in (":", "="))
            if SECRET_LABEL.match(label) and marked:
                nxt = i + 1
                if nxt < len(words) and words[nxt][0] in (":", "="):
                    nxt += 1
                if nxt < len(words) and not taken[nxt]:
                    cover(spans[nxt][0], spans[nxt][1], "password")
    return found


def summary(found) -> str:
    """'2 email addresses, 1 card number' — for the message afterwards."""
    counts = {}
    for kind, _box in found:
        counts[kind] = counts.get(kind, 0) + 1
    parts = []
    for kind, n in counts.items():
        name = KINDS[kind]
        if n > 1:
            name = name + ("es" if name.endswith("s") else "s")
            name = name.replace("key or tokens", "keys or tokens")
        parts.append(f"{n} {name}")
    return ", ".join(parts)
