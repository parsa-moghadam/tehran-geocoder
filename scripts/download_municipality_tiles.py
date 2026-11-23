"""Download Tehran Municipality basemap tiles for fully-offline serving.

The public web map at https://map.tehran.ir uses its own raster basemap
(نقشه معابر) served from tile{1-20}.tehran.ir.  Tile coordinates are wrapped
in a small rotating-base64 token, exactly like the search API names.

This is a BUILD-TIME script.  Results are stored in gitignored data/tiles/
and served by FastAPI at /tiles/{z}/{x}/{y}.png — no runtime network access.

Usage:
  python scripts/download_municipality_tiles.py                 # z10..16
  python scripts/download_municipality_tiles.py --max-zoom 17   # +90k tiles
  python scripts/download_municipality_tiles.py --dry-run       # only count
"""
from __future__ import annotations

import argparse
import base64
import math
import random
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "tiles"

# Web Mercator extent from map.tehran.ir's own configuration.
BBOX_M = (5649919.3827, 4234611.367, 5776193.3535, 4300958.7076)  # xmin,ymin,xmax,ymax
R = 6378137.0
APP = "Tehran"
HEADERS = {"Referer": "https://map.tehran.ir/", "User-Agent": "Mozilla/5.0"}


def _rot(s: str) -> str:
    """Rotate the last character to the front (an involution for len > 1)."""
    return s[-1] + s[1:-1] + s[0]


def encode_token(text: str) -> str:
    """Reproduce the obfuscation used by the map's own JavaScript."""
    b64 = base64.b64encode(_rot(text).encode()).decode()
    return _rot(b64).replace("+", "-").replace("/", "_").replace("=", "!")


def tile_url(z: int, x: int, y: int, subdomain: int) -> str:
    inner = f"{z}/{x}/{y}.png?c={encode_token(APP)}"
    host = f"https://tile{subdomain}.tehran.ir/tiles/gtt1/tiles.php"
    return f"{host}?z={encode_token(inner)}.png"


def bbox_lonlat() -> tuple[float, float, float, float]:
    xmin, ymin, xmax, ymax = BBOX_M
    lon = lambda x: x / R * 180 / math.pi
    lat = lambda y: (2 * math.atan(math.exp(y / R)) - math.pi / 2) * 180 / math.pi
    return lon(xmin), lat(ymin), lon(xmax), lat(ymax)


def tile_range(z: int) -> tuple[range, range]:
    west, south, east, north = bbox_lonlat()
    n = 2 ** z
    x0 = int((west + 180) / 360 * n)
    x1 = int((east + 180) / 360 * n)

    def y_at(lat: float) -> int:
        return int((1 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2 * n)

    return range(x0, x1 + 1), range(y_at(north), y_at(south) + 1)


def tile_path(z: int, x: int, y: int) -> Path:
    return OUT / str(z) / str(x) / f"{y}.png"


def fetch_one(task: tuple[int, int, int], session: requests.Session, retries: int = 3) -> bool:
    z, x, y = task
    dest = tile_path(z, x, y)
    if dest.exists() and dest.stat().st_size > 0:
        return False  # already downloaded (resume-friendly)
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(".tmp")
    for attempt in range(retries):
        try:
            url = tile_url(z, x, y, random.randint(1, 20))
            r = session.get(url, headers=HEADERS, timeout=30)
            r.raise_for_status()
            if not r.content.startswith(b"\x89PNG\r\n\x1a\n"):
                raise ValueError("not a PNG")
            tmp.write_bytes(r.content)
            tmp.replace(dest)
            return True
        except Exception:
            if attempt == retries - 1:
                tmp.unlink(missing_ok=True)
                return False
            time.sleep(0.5 * (attempt + 1))
    return False


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--min-zoom", type=int, default=10)
    ap.add_argument("--max-zoom", type=int, default=16)
    ap.add_argument("--concurrency", type=int, default=16)
    ap.add_argument("--limit", type=int, default=0, help="stop after N tiles (for testing)")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    tasks = []
    for z in range(args.min_zoom, args.max_zoom + 1):
        xs, ys = tile_range(z)
        tasks.extend((z, x, y) for x in xs for y in ys)
    if args.limit:
        tasks = tasks[:args.limit]
    todo = [t for t in tasks if not (tile_path(*t).exists() and tile_path(*t).stat().st_size > 0)]
    print(f"bbox: {tuple(round(v, 4) for v in bbox_lonlat())}")
    print(f"tiles z{args.min_zoom}-{args.max_zoom}: {len(tasks):,} total, {len(todo):,} to download")
    if args.dry_run:
        return 0

    session = requests.Session()
    done = failed = 0
    started = time.time()
    with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
        futures = {pool.submit(fetch_one, t, session): t for t in todo}
        for fut in as_completed(futures):
            ok = fut.result()
            done += 1
            failed += not ok
            if done % 500 == 0 or done == len(todo):
                rate = done / max(1, time.time() - started)
                eta = (len(todo) - done) / rate / 60 if rate else 0
                print(f"  {done:,}/{len(todo):,} tiles · {failed} failed · "
                      f"{rate:.1f}/s · ETA {eta:.0f} min", flush=True)
    print(f"done: {done - failed:,} saved, {failed} failed -> {OUT}")
    return 0 if failed == 0 else 2


if __name__ == "__main__":
    sys.exit(main())
