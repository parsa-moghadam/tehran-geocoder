"""Evaluate the DEPLOYED model on the golden set (no retraining).

Usage: python ml/evaluate.py
"""
from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import joblib  # noqa: E402

from backend.features import sent_features  # noqa: E402
from backend.normalize import tokenize  # noqa: E402
from backend.parser import FIELDS  # noqa: E402

model = joblib.load(ROOT / "data" / "models" / "parser.joblib")
conn = sqlite3.connect(str(ROOT / "data" / "tehran.db"))
neighs = {r[0] for r in conn.execute("SELECT name FROM neighborhoods")}
fixtures = json.loads((ROOT / "tests" / "fixtures" / "addresses.json").read_text(encoding="utf-8"))

total: dict[str, int] = {}
hit: dict[str, int] = {}
for fx in fixtures:
    tokens = tokenize(fx["input"])
    labels = model.predict([sent_features(tokens, neighs)])[0]
    pred: dict[str, str] = {}
    prev = None
    for tok, lab in zip(tokens, labels):
        key = FIELDS.get(lab)
        if key is None:
            prev = lab
            continue
        cont = lab.startswith("I-") or (key == "neighborhood" and prev == "NEIGH")
        if key in pred and cont:
            pred[key] += " " + tok
        else:
            pred[key] = tok
        prev = lab
    for k, v in fx["expected"].items():
        total[k] = total.get(k, 0) + 1
        got = pred.get(k, "")
        if got.replace(" ", "") == str(v).replace(" ", ""):
            hit[k] = hit.get(k, 0) + 1

for k in total:
    print(f"{k:14s} {hit.get(k, 0):2d}/{total[k]:2d} = {hit.get(k, 0) / total[k]:.0%}")
print(f"\nTOTAL: {sum(hit.values())}/{sum(total.values())} = {sum(hit.values()) / sum(total.values()):.0%}")