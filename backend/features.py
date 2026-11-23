"""CRF feature extraction shared by training (ml/) and inference (backend/).

Labels:
  O        - irrelevant token
  KW       - field keyword (خیابان، کوچه، پلاک، ...)
  CITY     - city name
  DIST     - municipality district number
  NEIGH    - neighborhood name
  B-STREET / I-STREET
  B-ALLEY  / I-ALLEY
  NUM      - plaque number
  UNIT     - unit number
  FLOOR    - floor number
"""
from __future__ import annotations

KW_STREET = {"خیابان", "خیابون", "خ", "بلوار", "بل", "بزرگراه", "بزگراه", "میدان", "خیابانِ"}
KW_ALLEY = {"کوچه", "کوی", "ک", "بن‌بست", "بنبست", "کوچه‌ی"}
KW_NUM = {"پلاک", "پ", "شماره", "نمره"}
KW_UNIT = {"واحد"}
KW_FLOOR = {"طبقه", "ط"}
KW_DISTRICT = {"منطقه"}
CITIES = {"تهران", "تهرن", "شمیران", "شمیرانات", "ری", "شهرری"}


def _kw_class(word: str) -> str | None:
    if word in KW_STREET:
        return "street"
    if word in KW_ALLEY:
        return "alley"
    if word in KW_NUM:
        return "num"
    if word in KW_UNIT:
        return "unit"
    if word in KW_FLOOR:
        return "floor"
    if word in KW_DISTRICT:
        return "district"
    return None


def word_features(tokens: list[str], i: int, neighborhoods: set[str] | None = None) -> dict:
    w = tokens[i]
    kw = _kw_class(w)
    f = {
        "bias": 1.0,
        "word": w,
        "word[-2:]": w[-2:],
        "word[-3:]": w[-3:],
        "word[:2]": w[:2],
        "is_digit": w.isdigit(),
        "has_digit": any(c.isdigit() for c in w),
        "len": str(len(w)),
        "kw": kw or "",
        "is_city": w in CITIES,
        "is_neigh": bool(neighborhoods and w in neighborhoods),
    }
    if i > 0:
        p = tokens[i - 1]
        f.update({
            "-1:word": p,
            "-1:kw": _kw_class(p) or "",
            "-1:is_city": p in CITIES,
            "-1:is_digit": p.isdigit(),
        })
    else:
        f["BOS"] = True
    if i > 1:
        f["-2:kw"] = _kw_class(tokens[i - 2]) or ""
    if i < len(tokens) - 1:
        n = tokens[i + 1]
        f.update({
            "+1:word": n,
            "+1:kw": _kw_class(n) or "",
            "+1:is_digit": n.isdigit(),
        })
    else:
        f["EOS"] = True
    return f


def sent_features(tokens: list[str], neighborhoods: set[str] | None = None) -> list[dict]:
    return [word_features(tokens, i, neighborhoods) for i in range(len(tokens))]