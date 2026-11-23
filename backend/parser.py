"""CRF address parser: free-form Persian address -> structured fields."""
from __future__ import annotations

from pathlib import Path

import joblib

from .features import sent_features
from .normalize import normalize, tokenize

MODEL_PATH = Path(__file__).resolve().parent.parent / "data" / "models" / "parser.joblib"

FIELDS = {
    "CITY": "city",
    "DIST": "district",
    "NEIGH": "neighborhood",
    "B-STREET": "street",
    "I-STREET": "street",
    "B-ALLEY": "alley",
    "I-ALLEY": "alley",
    "NUM": "number",
    "UNIT": "unit",
    "FLOOR": "floor",
}


class AddressParser:
    def __init__(self, model_path: Path = MODEL_PATH, neighborhoods: set[str] | None = None):
        self.model = joblib.load(model_path) if Path(model_path).exists() else None
        self.neighborhoods = neighborhoods or set()

    @property
    def available(self) -> bool:
        return self.model is not None

    def parse(self, text: str) -> dict:
        """Returns {fields: {...}, confidence: float, tokens, labels}."""
        tokens = tokenize(text)
        if not tokens:
            return {"fields": {}, "confidence": 0.0, "tokens": [], "labels": []}
        if self.model is None:
            return {"fields": {}, "confidence": 0.0, "tokens": tokens, "labels": ["O"] * len(tokens)}

        X = [sent_features(tokens, self.neighborhoods)]
        labels = self.model.predict(X)[0]
        try:
            probs = self.model.predict_marginal_proba(X)[0]
            confidence = sum(max(p.values()) for p in probs) / len(probs)
        except Exception:
            confidence = 0.5

        fields: dict[str, str] = {}
        prev = None
        for tok, lab in zip(tokens, labels):
            key = FIELDS.get(lab)
            if key is None:
                prev = lab
                continue
            cont = lab.startswith("I-") or (key == "neighborhood" and prev == "NEIGH")
            if key in fields and cont:
                fields[key] += " " + tok
            else:
                fields[key] = tok
            prev = lab
        if "district" in fields:
            fields["district"] = "".join(c for c in fields["district"] if c.isdigit())
        return {"fields": fields, "confidence": round(float(confidence), 3),
                "tokens": tokens, "labels": labels}


_parser: AddressParser | None = None


def get_parser(neighborhoods: set[str] | None = None) -> AddressParser:
    global _parser
    if _parser is None:
        _parser = AddressParser(neighborhoods=neighborhoods)
    elif neighborhoods:
        _parser.neighborhoods = neighborhoods
    return _parser