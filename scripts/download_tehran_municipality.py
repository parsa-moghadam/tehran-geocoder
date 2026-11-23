"""Download Tehran Municipality map data (names + house numbers) once, for offline use.

The public web map at https://map.tehran.ir exposes a small RAPI JSON service.
Its responses are lightly obfuscated; this module implements the same decoding
as the site's own JavaScript (`__dc`, `__dcp`, `Base64.decode` wrappers).

IMPORTANT
---------
This data is NOT open-source licensed. It is downloaded once at BUILD TIME and
stored under gitignored `data/raw/`. Nothing in the running app contacts
map.tehran.ir. See README.md for the provenance/license caveat.

Usage:
  python scripts/download_tehran_municipality.py
  python scripts/download_tehran_municipality.py --no-plaques --limit 40
  python scripts/download_tehran_municipality.py --concurrency 12 --offset-m 30
"""
from __future__ import annotations

import argparse
import base64
import json
import random
import string
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
API = "https://map.tehran.ir/api.php"
HEADERS = {
    "x-requested-with": "XMLHttpRequest",
    "origin": "https://map.tehran.ir",
    "referer": "https://map.tehran.ir/",
    "user-agent": "Mozilla/5.0 (compatible; TehranGeocoderBuild/1.0)",
}

# Broad but small keyword set: enough to harvest thousands of named streets
# without hammering the public service. Add more with --extra-keyword / --keywords-from-db.
LETTERS = "ابپتثجچحخدذرزسشصضطظعغفقکگلمنوهی"
TYPES = ["خیابان", "کوچه", "بلوار", "میدان", "بزرگراه", "پیاده راه", "پاساژ",
         "مجتمع", "بازار", "پارک", "بیمارستان", "مدرسه", "مسجد", "بانک"]
DIRECTIONS = ["شمالی", "جنوبی", "شرقی", "غربی", "مرکزی", "اصلی", "بزرگ", "کوچک",
              "یکم", "دوم", "سوم", "چهارم", "پنجم", "نو", "قدیم"]
COMMON = ["شهید", "امام", "انقلاب", "آزادی", "ولیعصر", "گلستان", "سعادت", "تهران",
          "سهند", "شیراز", "مازندران", "کریمخان", "حافظ", "سعدی", "فردوسی", "ابن سینا",
          "جردن", "کاشان", "دماوند", "پاسداران", "نیاوران", "قلهک", "دروازه", "تجریش",
          "چیذر", "رسالت", "دولت", "ملت", "آرژانتین", "برزیل", "استقلال",
          "کاج", "نسترن", "یاس", "رز", "گل", "بلوط", "چنار", "اقاقیا", "کوچه باغ",
          "مسجد جامع", "شورا", "منابع طبیعی", "آب و برق"]
DIGITS = "۱۲۳۴۵۶۷۸۹۰"


def default_keywords() -> list[str]:
    kws = list(LETTERS) + TYPES + DIRECTIONS + COMMON + list(DIGITS)
    # two-digit house/street numbers that frequently occur in street names
    kws += [f"{a}{b}" for a in "۱۲۳۴۵" for b in "۰۱۲۳۴۵۶۷۸۹"]
    return list(dict.fromkeys(kws))


def keywords_from_db() -> list[str]:
    """Use real neighborhood names as search keywords (great coverage booster)."""
    sys.path.insert(0, str(ROOT))
    try:
        from backend.db import connect
        conn = connect()
        names = [r[0] for r in conn.execute("SELECT name FROM neighborhoods")]
        names += [r[0] for r in conn.execute("SELECT DISTINCT name FROM streets WHERE source='learned'")]
        conn.close()
        return [n for n in names if n and len(n) > 2]
    except Exception as exc:  # DB not built yet -> just skip
        print(f"keywords-from-db skipped: {exc}")
        return []


def _rot(s: str) -> str:
    return s[-1] + s[1:-1] + s[0] if s else s


def _b64decode(s: str) -> str:
    s = s.strip()
    return base64.b64decode(s + "=" * (-len(s) % 4)).decode("utf-8", errors="replace")


def decode_key(name: str) -> int:
    """`parseInt(__dc(data.name))` from scripts.js."""
    try:
        decoded = _b64decode(_rot(name))
        decoded = _rot(decoded)
        if len(decoded) == 2:
            decoded = decoded.lstrip("0")
        return int(decoded or 0)
    except Exception:
        return 0


def decode_text(value: str, offset: int) -> str:
    if not value or len(value) <= offset:
        return ""
    return _b64decode(value[offset:])


def decode_coord(value: str, key: int) -> tuple[float, float] | None:
    """`__dcp(n.l, key)` — key digits are XORed with '0' before use."""
    if not value or not key:
        return None
    k = "".join(chr(ord(c) ^ 0x30) for c in str(key))
    try:
        out = "".join(chr(ord(c) ^ ord(k[i % len(k)])) for i, c in enumerate(value))
        lng, lat = out.split(",")[:2]
        lng, lat = float(lng), float(lat)
        if 35 < lat < 36.2 and 50 < lng < 52:  # sanity: Tehran
            return lng, lat
        return None
    except Exception:
        return None


def decode_property(data: str) -> dict:
    """Reverse-geocoder response: strip 28/28 chars, split at '@', swap, base64."""
    try:
        n = data[28:]
        n = n[:-28] if len(n) >= 28 else n
        r = int(n[n.rfind("@") + 1:])
        n = n[:n.rfind("@")]
        head, tail = n[:r], n[r:]
        return json.loads(_b64decode(tail + head))
    except Exception:
        return {}


class Municipality:
    def __init__(self, concurrency: int, timeout: int = 30):
        self.s = requests.Session()
        self.s.headers.update(HEADERS)
        retry = Retry(total=3, backoff_factor=0.4, status_forcelist=(429, 500, 502, 503, 504))
        self.s.mount("https://", HTTPAdapter(max_retries=retry, pool_maxsize=concurrency * 2))
        self.timeout = timeout

    def rapi(self, module: str, method: str, params: dict) -> dict:
        resname = "bg" + "".join(random.choices(string.ascii_lowercase, k=7))
        form = {"module": module, "method": method, "resName": resname,
                "city": "Tehran", "lang": "fa", **params}
        r = self.s.post(API, data=form, timeout=self.timeout)
        r.raise_for_status()
        return r.json().get(resname, {})

    def search(self, keyword: str) -> list[dict]:
        payload = self.rapi("Search", "doSearch", {
            "keyword": keyword, "lat": "35.6892", "lng": "51.389", "is_advanced": "1",
        })
        data = payload.get("data") or {}
        name = data.get("name") or ""
        key = decode_key(name)
        g = len(name) + 2
        rows = []
        for item in data.get("d") or []:
            title = decode_text(item.get("t", ""), g)
            meta_raw = decode_text(item.get("m", ""), g)
            try:
                meta = json.loads(meta_raw) if meta_raw else {}
            except Exception:
                meta = {}
            if isinstance(meta, str):
                meta = {}
            coord = decode_coord(item.get("l", ""), key)
            if not coord or not title:
                continue
            lng, lat = coord
            rows.append({
                "id": str(item.get("i", "")),
                "name": meta.get("نام") or title,
                "type": meta.get("نوع") or "",
                "address": meta.get("آدرس") or "",
                "lat": round(lat, 7),
                "lng": round(lng, 7),
                "source": "tehran_muni",
                "keyword": keyword,
            })
        return rows

    def plaque(self, lat: float, lng: float) -> dict | None:
        payload = self.rapi("GeoCoder", "getPropertyIdCode", {
            "lat": f"{lat:.7f}", "lng": f"{lng:.7f}",
        })
        data = payload.get("data")
        if not isinstance(data, str):
            return None
        info = (decode_property(data).get("property_id_data") or {})
        if not info.get("property_id"):
            return None
        try:
            x, y = float(info.get("x", 0)), float(info.get("y", 0))
        except (TypeError, ValueError):
            return None
        if not (35 < y < 36.2 and 50 < x < 52):
            return None
        plaque = info.get("plaque")
        if plaque in (None, "", "NULL"):
            return None  # no house number known at this point
        return {"property_id": str(info["property_id"]), "plaque": str(plaque),
                "lat": round(y, 7), "lng": round(x, 7), "source": "tehran_muni"}


def read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def write_jsonl(path: Path, rows: list[dict]):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(f"wrote {len(rows):,} rows -> {path.relative_to(ROOT)}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--concurrency", type=int, default=8)
    ap.add_argument("--limit", type=int, help="max keywords to search (for a quick test)")
    ap.add_argument("--no-plaques", action="store_true", help="only download street names")
    ap.add_argument("--offset-m", type=int, default=0,
                    help="also sample a 3x3 grid around each street point with this spacing")
    ap.add_argument("--max-plaque-points", type=int, default=20000)
    ap.add_argument("--osm-points", type=int, default=0,
                    help="also sample this many random OSM street coordinates for house numbers")
    ap.add_argument("--extra-keyword", action="append", default=[])
    ap.add_argument("--keywords-from-db", action="store_true")
    args = ap.parse_args()

    kws = default_keywords() + list(args.extra_keyword)
    if args.keywords_from_db:
        kws += keywords_from_db()
    kws = list(dict.fromkeys(kws))
    if args.limit:
        kws = kws[:args.limit]
    print(f"searching {len(kws)} keywords with {args.concurrency} workers ...")

    api = Municipality(args.concurrency)
    streets: dict[str, dict] = {}
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
        futures = {pool.submit(api.search, kw): kw for kw in kws}
        for i, fut in enumerate(as_completed(futures), 1):
            try:
                for row in fut.result():
                    key = (row["name"], row["lat"], row["lng"])
                    streets.setdefault(key, row)
            except Exception as exc:
                print(f"  search failed ({futures[fut]}): {exc}", file=sys.stderr)
            if i % 25 == 0:
                print(f"  {i}/{len(kws)} keywords, {len(streets)} unique streets "
                      f"({time.time() - t0:.0f}s)")
    street_rows = sorted(streets.values(), key=lambda r: (r["name"], r["lat"]))
    write_jsonl(RAW / "municipality_streets.jsonl", street_rows)

    if args.no_plaques:
        return 0

    # sample house numbers at municipality street coordinates
    points: dict[tuple[float, float], dict] = {}
    for row in street_rows:
        points[(row["lat"], row["lng"])] = row
        if args.offset_m:
            dlat = args.offset_m / 111000
            dlng = args.offset_m / (111000 * 0.814)
            for d1 in (-dlat, 0, dlat):
                for d2 in (-dlng, 0, dlng):
                    if d1 == 0 and d2 == 0:
                        continue
                    points[(round(row["lat"] + d1, 7), round(row["lng"] + d2, 7))] = row
    if args.osm_points:
        sys.path.insert(0, str(ROOT))
        try:
            from backend.db import connect
            conn = connect()
            osm = [(r["lat"], r["lng"]) for r in conn.execute("SELECT lat, lng FROM streets")]
            conn.close()
            random.shuffle(osm)
            for lat, lng in osm[:args.osm_points]:
                points.setdefault((lat, lng), {"name": "osm"})
        except Exception as exc:
            print(f"osm-points skipped: {exc}")
    pts = list(points.items())[:args.max_plaque_points]
    print(f"querying house numbers at {len(pts):,} points ...")

    plaques: dict[str, dict] = {}
    t1 = time.time()
    with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
        futures = {}
        for (lat, lng), street in pts:
            fut = pool.submit(api.plaque, lat, lng)
            futures[fut] = street
        for i, fut in enumerate(as_completed(futures), 1):
            try:
                row = fut.result()
                if row:
                    plaques.setdefault(row["property_id"], row)
            except Exception as exc:
                print(f"  plaque failed: {exc}", file=sys.stderr)
            if i % 500 == 0:
                print(f"  {i:,}/{len(pts):,} points, {len(plaques)} house numbers "
                      f"({time.time() - t1:.0f}s)")
    # keep earlier runs (so a second pass with --osm-points is cumulative)
    for old in read_jsonl(RAW / "municipality_plaques.jsonl"):
        plaques.setdefault(str(old.get("property_id")), old)
    write_jsonl(RAW / "municipality_plaques.jsonl", list(plaques.values()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
