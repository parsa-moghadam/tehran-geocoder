"""Diagnose golden-set failures fixture by fixture."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import joblib
from backend.features import sent_features
from backend.normalize import tokenize
from backend.parser import FIELDS
import sqlite3

model = joblib.load(ROOT / "data" / "models" / "parser-1763886060.joblib") if False else None
# load latest versioned model
models = sorted((ROOT / "data" / "models").glob("parser-*.joblib"))
model = joblib.load(models[-1])
conn = sqlite3.connect(str(ROOT / "data" / "tehran.db"))
neighs = {r[0] for r in conn.execute("SELECT name FROM neighborhoods")}

fixtures = json.loads((ROOT / "tests" / "fixtures" / "addresses.json").read_text(encoding="utf-8"))
for fx in fixtures:
    tokens = tokenize(fx["input"])
    labels = model.predict([sent_features(tokens, neighs)])[0]
    pred = {}
    prev = None
    for tok, lab in zip(tokens, labels):
        key = FIELDS.get(lab)
        if key is None:
            prev = lab
            continue
        if key in pred and (lab.startswith("I-") or (key == "neighborhood" and prev == "NEIGH")):
            pred[key] += " " + tok
        else:
            pred[key] = tok
        prev = lab
    fails = []
    for k, v in fx["expected"].items():
        got = pred.get(k, "")
        if got.replace(" ", "") != str(v).replace(" ", ""):
            fails.append(f"{k}: want '{v}' got '{got}'")
    if fails:
        print("FAIL:", fx["input"])
        for f in fails:
            print("   ", f)
        print("    labels:", list(zip(tokens, labels)))