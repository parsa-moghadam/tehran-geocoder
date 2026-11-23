"""Import locally-downloaded Tehran Municipality data into the SQLite index.

Reads the gitignored JSONL files written by download_tehran_municipality.py:
  data/raw/municipality_streets.jsonl
  data/raw/municipality_plaques.jsonl

Municipality street names are added when OSM has no equivalent nearby.
Municipality house numbers ("پلاک") are attached to the nearest known street
and stored in the `addresses` table with source='tehran_muni'.

Usage: python scripts/import_municipality.py [--no-streets] [--no-plaques]
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend.db import connect, district_at  # noqa: E402
from backend.normalize import fold, normalize  # noqa: E402
from backend.matcher import haversine  # noqa: E402

RAW = ROOT / "data" / "raw"


def read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def nearest_neighborhood(neighs: list[dict], lat: float, lng: float, max_km: float = 1.2) -> str | None:
    best, best_d = None, max_km
    for n in neighs:
        if n["lat"] is None or n["lng"] is None:
            continue
        d = math.hypot((lat - n["lat"]) * 111.0, (lng - n["lng"]) * 90.5)
        if d < best_d:
            best, best_d = n["name"], d
    return best


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--no-streets", action="store_true")
    ap.add_argument("--no-plaques", action="store_true")
    ap.add_argument("--street-radius-m", type=int, default=120,
                    help="skip a municipality street if an OSM street with the same name is this close")
    ap.add_argument("--address-radius-m", type=int, default=300,
                    help="maximum distance from a house number to its street")
    args = ap.parse_args()

    streets_in = read_jsonl(RAW / "municipality_streets.jsonl")
    plaques_in = read_jsonl(RAW / "municipality_plaques.jsonl")
    if not streets_in and not plaques_in:
        print("No municipality JSONL files found. Run download_tehran_municipality.py first.")
        return 1

    conn = connect()
    neighs = [dict(r) for r in conn.execute("SELECT name, lat, lng FROM neighborhoods")]

    # --- streets -----------------------------------------------------------
    rows = [dict(r) for r in conn.execute("SELECT id, name, norm, lat, lng, source FROM streets")]
    by_name: dict[str, list[dict]] = {}
    for r in rows:
        by_name.setdefault(fold(r["name"]), []).append(r)

    added_streets = 0
    if not args.no_streets:
        for m in streets_in:
            name = (m.get("name") or "").strip()
            if not name or not m.get("lat") or not m.get("lng"):
                continue
            key = fold(name)
            near = by_name.get(key, [])
            radius = args.street_radius_m / 1000
            if any(haversine(m["lat"], m["lng"], r["lat"], r["lng"]) <= radius for r in near):
                continue
            district = district_at(conn, m["lat"], m["lng"])
            neighborhood = nearest_neighborhood(neighs, m["lat"], m["lng"])
            cur = conn.execute(
                "INSERT INTO streets(name, norm, kind, neighborhood, district, lat, lng, source, muni_id) "
                "VALUES(?,?,?,?,?,?,?, 'tehran_muni', ?)",
                (name, normalize(name), "street", neighborhood, district,
                 m["lat"], m["lng"], str(m.get("id") or "")),
            )
            row = {"id": cur.lastrowid, "name": name, "norm": normalize(name),
                   "lat": m["lat"], "lng": m["lng"], "source": "tehran_muni"}
            by_name.setdefault(key, []).append(row)
            rows.append(row)
            added_streets += 1
        conn.commit()

    # --- house numbers -----------------------------------------------------
    street_list = [dict(r) for r in conn.execute("SELECT id, name, lat, lng FROM streets")]
    by_name.clear()
    grid: dict[tuple[int, int], list[dict]] = defaultdict(list)
    cell = 0.005  # ~550 m grid — keeps nearest-street lookup local
    for r in street_list:
        by_name.setdefault(fold(r["name"]), []).append(r)
        grid[(int(r["lat"] / cell), int(r["lng"] / cell))].append(r)

    existing_props = {r[0] for r in conn.execute(
        "SELECT property_id FROM addresses WHERE property_id IS NOT NULL")}
    added_addresses = 0
    skipped_far = 0
    if not args.no_plaques:
        radius = args.address_radius_m / 1000
        for h in plaques_in:
            prop = str(h.get("property_id") or "")
            if prop in existing_props:
                continue
            lat, lng = h.get("lat"), h.get("lng")
            if not lat or not lng:
                continue
            # nearest street of ANY name; municipality points sit on a street
            cx, cy = int(lat / cell), int(lng / cell)
            reach = max(1, math.ceil(radius / 0.45))
            best, best_d = None, float("inf")
            for dx in range(-reach, reach + 1):
                for dy in range(-reach, reach + 1):
                    for s in grid.get((cx + dx, cy + dy), ()):
                        d = haversine(lat, lng, s["lat"], s["lng"])
                        if d < best_d:
                            best, best_d = s, d
            if best is None or best_d > radius:
                skipped_far += 1
                continue
            conn.execute(
                "INSERT INTO addresses(street, housenumber, lat, lng, source, property_id) "
                "VALUES(?,?,?,?, 'tehran_muni', ?)",
                (best["name"], str(h.get("plaque") or ""), lat, lng, prop),
            )
            existing_props.add(prop)
            added_addresses += 1
        conn.commit()

    n_streets = conn.execute("SELECT COUNT(*) FROM streets WHERE source='tehran_muni'").fetchone()[0]
    n_addr = conn.execute("SELECT COUNT(*) FROM addresses WHERE source='tehran_muni'").fetchone()[0]
    conn.close()
    print(f"municipality streets in DB: {n_streets} (+{added_streets} this run)")
    print(f"municipality house numbers in DB: {n_addr} (+{added_addresses} this run, "
          f"{skipped_far} too far from a street)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
