"""Persian text normalization for address matching.

Handles the three numeral systems (Persian/Arabic/Latin), Arabic letter
variants, ZWNJ, diacritics and invisible direction marks.
"""
from __future__ import annotations

import re

_PERSIAN_DIGITS = "۰۱۲۳۴۵۶۷۸۹"
_ARABIC_DIGITS = "٠١٢٣٤٥٦٧٨٩"

_DIGIT_MAP = {}
for i, (p, a) in enumerate(zip(_PERSIAN_DIGITS, _ARABIC_DIGITS)):
    _DIGIT_MAP[ord(p)] = str(i)
    _DIGIT_MAP[ord(a)] = str(i)

_LETTER_MAP = {
    ord("ي"): "ی",
    ord("ك"): "ک",

    ord("\u200c"): " ",   # ZWNJ -> space (ولی‌عصر -> ولی عصر)
    ord("\u200d"): "",    # ZWJ
    ord("\u200e"): "",    # LRM
    ord("\u200f"): "",    # RLM
    ord("\u0640"): "",    # tatweel
}

_DIACRITICS = re.compile(r"[\u064B-\u065F\u0670]")
_SPACES = re.compile(r"\s+")

# tokens that separate fields in free-form addresses
SEPARATORS = re.compile(r"[،,;:|/\\()\[\]{}«»\"']+")


def normalize(text: str) -> str:
    """Canonical form used for parsing and matching."""
    if not text:
        return ""
    text = text.translate(_DIGIT_MAP)
    text = text.translate(_LETTER_MAP)
    text = _DIACRITICS.sub("", text)
    text = text.replace("ـ", "")
    text = SEPARATORS.sub(" ", text)
    text = _SPACES.sub(" ", text).strip()
    return text


# Aggressive letter folding used ONLY for fuzzy matching, never for parsed text
_FOLD_MAP = {
    ord("آ"): "ا", ord("أ"): "ا", ord("إ"): "ا",
    ord("ة"): "ه", ord("ؤ"): "و", ord("ئ"): "ی", ord("ء"): "",
}


def fold(text: str) -> str:
    """Aggressive form for fuzzy name comparison (spaces removed)."""
    return normalize(text).translate(_FOLD_MAP).replace(" ", "")


def tokenize(text: str) -> list[str]:
    return normalize(text).split()


def to_persian_digits(text: str) -> str:
    return "".join(_PERSIAN_DIGITS[int(c)] if c.isdigit() else c for c in text)