"""Train the CRF address parser on synthetic data; evaluate on holdout + golden set.

CPU-only, takes a few minutes. Models are versioned; the golden set gates
acceptance (a worse model is rejected -> rollback-safe learning loop).

Usage: python ml/train_parser.py
"""
from __future__ import annotations

import json
import random
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import joblib  # noqa: E402
import sklearn_crfsuite  # noqa: E402
from sklearn_crfsuite import metrics  # noqa: E402

from backend.features import sent_features  # noqa: E402
from backend.normalize import tokenize  # noqa: E402

DATA = ROOT / "data" / "synthetic_addresses.jsonl"
MODEL_DIR = ROOT / "data" / "models"
FIXTURES = ROOT / "tests" / "fixtures" / "addresses.json"


def load_samples():
    samples = []
    with open(DATA, encoding="utf-8") as f:
        for line in f:
            samples.append(json.loads(line))
    return samples


def field_accuracy(model, fixtures: list[dict], neighborhoods: set[str]) -> dict:
    """Field-level accuracy on the golden set."""
    from backend.parser import FIELDS
    total = {k: 0 for k in ("street", "alley", "number", "unit", "floor", "city", "neighborhood")}
    hit = {k: 0 for k in total}
    for fx in fixtures:
        tokens = tokenize(fx["input"])
        labels = model.predict([sent_features(tokens, neighborhoods)])[0]
        pred: dict[str, str] = {}
        for tok, lab in zip(tokens, labels):
            key = FIELDS.get(lab)
            if key is None:
                continue
            if key in pred and lab.startswith("I-"):
                pred[key] += " " + tok
            else:
                pred[key] = tok
        for k in total:
            expected = fx["expected"].get(k)
            if expected is None:
                continue
            total[k] += 1
            got = pred.get(k, "")
            if got.replace(" ", "") == str(expected).replace(" ", ""):
                hit[k] += 1
    return {k: (round(hit[k] / total[k], 3) if total[k] else None) for k in total}


def main():
    if not DATA.exists():
        print("ERROR: run ml/generate_data.py first")
        return 1
    samples = load_samples()
    random.Random(7).shuffle(samples)
    split = int(len(samples) * 0.9)
    train, test = samples[:split], samples[split:]
    print(f"train={len(train)} test={len(test)}")

    X_train = [sent_features(s["tokens"]) for s in train]
    y_train = [s["labels"] for s in train]
    X_test = [sent_features(s["tokens"]) for s in test]
    y_test = [s["labels"] for s in test]

    crf = sklearn_crfsuite.CRF(
        algorithm="lbfgs", c1=0.1, c2=0.1,
        max_iterations=120, all_possible_transitions=True,
    )
    t0 = time.time()
    crf.fit(X_train, y_train)
    print(f"trained in {time.time() - t0:.0f}s")

    labels = [l for l in crf.classes_ if l != "O"]
    y_pred = crf.predict(X_test)
    print("holdout token metrics:")
    print(metrics.flat_classification_report(y_test, y_pred, labels=labels, digits=3))

    neighborhoods = set()
    try:
        import sqlite3
        conn = sqlite3.connect(str(ROOT / "data" / "tehran.db"))
        neighborhoods = {r[0] for r in conn.execute("SELECT name FROM neighborhoods")}
    except Exception:
        pass

    golden_ok = True
    if FIXTURES.exists():
        fixtures = json.loads(FIXTURES.read_text(encoding="utf-8"))
        acc = field_accuracy(crf, fixtures, neighborhoods)
        print("golden-set field accuracy:", json.dumps(acc, ensure_ascii=False))
        # gate: street/number must stay >= 0.8 on the golden set
        for k in ("street", "number"):
            if acc[k] is not None and acc[k] < 0.8:
                golden_ok = False
                print(f"REJECTED: golden accuracy for '{k}' = {acc[k]} < 0.8")

    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    version = int(time.time())
    versioned = MODEL_DIR / f"parser-{version}.joblib"
    joblib.dump(crf, versioned)
    print(f"saved candidate {versioned.name}")
    if golden_ok:
        joblib.dump(crf, MODEL_DIR / "parser.joblib")
        print("DEPLOYED -> parser.joblib")
    else:
        print("NOT deployed (golden gate failed); previous parser.joblib kept")
    return 0


if __name__ == "__main__":
    sys.exit(main())