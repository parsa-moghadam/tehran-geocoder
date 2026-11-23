"""Generate synthetic labeled Persian addresses from REAL Tehran street names.

The CRF parser learns from these. Diversity covers: numeral systems,
abbreviations, ZWNJ, comma/no-comma, field order, missing fields.

Usage: python ml/generate_data.py [--count 25000]
"""
from __future__ import annotations

import argparse
import json
import random
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend.normalize import normalize  # noqa: E402

PERSIAN = "۰۱۲۳۴۵۶۷۸۹"
ARABIC = "٠١٢٣٤٥٦٧٨٩"

STREET_KW = ["خیابان", "خیابان", "خیابان", "خیابون", "خ", "خ.", "بلوار", "بل"]
ALLEY_KW = ["کوچه", "کوچه", "کوچه", "ک", "ک.", "کوچه‌ی"]
NUM_KW = ["پلاک", "پلاک", "پ", "پ."]
UNIT_KW = ["واحد"]
FLOOR_KW = ["طبقه", "ط", "ط."]


def digits(n: int) -> str:
    style = random.random()
    s = str(n)
    if style < 0.45:
        return "".join(PERSIAN[int(c)] for c in s)
    if style < 0.6:
        return "".join(ARABIC[int(c)] for c in s)
    return s


def zwnj_variant(name: str) -> str:
    r = random.random()
    if r < 0.2 and " " in name:
        return name.replace(" ", "\u200c", 1)
    if r < 0.3:
        return name.replace(" ", "")
    if r < 0.38:
        return name.replace("ی", "ي").replace("ک", "ك")
    return name


def labeled(tokens: list[tuple[str, str]]) -> dict:
    return {"tokens": [t for t, _ in tokens], "labels": [l for _, l in tokens]}


def gen_one(streets: list[str], alleys: list[str], neighs: list[str], rng: random.Random) -> dict:
    street = zwnj_variant(rng.choice(streets))
    parts: list[tuple[str, str]] = []

    has_city = rng.random() < 0.75
    has_neigh = rng.random() < 0.4
    has_alley = rng.random() < 0.55
    has_num = rng.random() < 0.7
    has_unit = rng.random() < 0.3
    has_floor = rng.random() < 0.2
    has_dist = rng.random() < 0.15

    if has_city:
        parts.append(("تهران", "CITY"))
    if has_dist:
        parts.append(("منطقه", "KW"))
        parts.append((digits(rng.randint(1, 22)), "DIST"))
    if has_neigh:
        parts.append((zwnj_variant(rng.choice(neighs)), "NEIGH"))

    # street phrase
    skw = rng.choice(STREET_KW)
    street_tokens = [(skw, "KW")] + [(w, "B-STREET" if i == 0 else "I-STREET")
                                     for i, w in enumerate(street.split())]

    alley_tokens = []
    if has_alley:
        akw = rng.choice(ALLEY_KW)
        alley_name = zwnj_variant(rng.choice(alleys))
        alley_tokens = [(akw, "KW")] + [(w, "B-ALLEY" if i == 0 else "I-ALLEY")
                                        for i, w in enumerate(alley_name.split())]

    num_tokens = []
    if has_num:
        num_tokens = [(rng.choice(NUM_KW), "KW"), (digits(rng.randint(1, 300)), "NUM")]
        if has_unit:
            num_tokens += [(rng.choice(UNIT_KW), "KW"), (digits(rng.randint(1, 20)), "UNIT")]
        if has_floor:
            num_tokens += [(rng.choice(FLOOR_KW), "KW"), (digits(rng.randint(1, 15)), "FLOOR")]

    # order variations
    order = rng.random()
    if order < 0.7:
        body = street_tokens + alley_tokens + num_tokens
    elif order < 0.85:
        body = num_tokens + street_tokens + alley_tokens  # پلاک ۱۲ خیابان ...
    else:
        body = alley_tokens + street_tokens + num_tokens

    parts += body
    if rng.random() < 0.1:
        parts.append(("تهران", "CITY"))  # trailing city

    # join: commas optional
    sep = "، " if rng.random() < 0.4 else " "
    text = sep.join(t for t, _ in parts)
    # re-tokenize exactly as inference does, keeping labels aligned
    tokens, labels = [], []
    for t, l in parts:
        for sub in normalize(t).split():
            tokens.append(sub)
            labels.append(l)
    return {"text": text, "tokens": tokens, "labels": labels}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--count", type=int, default=25000)
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()
    rng = random.Random(args.seed)

    conn = sqlite3.connect(str(ROOT / "data" / "tehran.db"))
    conn.row_factory = sqlite3.Row
    streets = [r["name"] for r in conn.execute(
        "SELECT DISTINCT name FROM streets WHERE kind NOT IN ('motorway') LIMIT 20000")]
    alleys = [r["name"] for r in conn.execute(
        "SELECT DISTINCT name FROM streets WHERE kind IN ('alley','residential','living_street') LIMIT 10000")]
    neighs = [r["name"] for r in conn.execute("SELECT name FROM neighborhoods")]
    if not streets:
        print("ERROR: streets table empty. Run scripts/build_index.py (or seed_from_csv.py) first.")
        return 1
    if not alleys:
        alleys = streets
    if not neighs:
        neighs = ["نارمک", "تهرانپارس", "یوسف‌آباد", "سعادت‌آباد", "شهرک غرب", "پیروزی", "نیاوران"]

    out = ROOT / "data" / "synthetic_addresses.jsonl"
    with open(out, "w", encoding="utf-8") as f:
        for _ in range(args.count):
            f.write(json.dumps(gen_one(streets, alleys, neighs, rng), ensure_ascii=False) + "\n")
    print(f"wrote {args.count} samples -> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())