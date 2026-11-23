import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.normalize import normalize, fold, tokenize

cases = [
    ("آزادی", "آزادی", "ازادی"),
    ("یوسف\u200cآباد", "یوسف آباد", "یوسفاباد"),
    ("پلاک ۱۲", "پلاک 12", "پلاک12"),
    ("khیابان", "khیابان", "khیابان"),
]
for raw, want_norm, want_fold in cases:
    got_n, got_f = normalize(raw), fold(raw)
    assert got_n == want_norm, (raw, got_n, want_norm)
    assert got_f == want_fold, (raw, got_f, want_fold)
print("normalization tests: OK", tokenize("تهران، خیابان آزادی پلاک ۱۲"))