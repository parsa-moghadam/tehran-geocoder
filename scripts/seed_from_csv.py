"""Seed the streets table from the open Tehran-address CSV (5000+ points).

Lets the demo run before the full OSM extract finishes downloading.
Street names are taken from the address text segments.

Usage: python scripts/seed_from_csv.py
"""
from __future__ import annotations

import csv
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend import db  # noqa: E402
from backend.normalize import normalize  # noqa: E402

CSV = ROOT / "data" / "raw" / "tehran_address_points.csv"


def main():
    if not CSV.exists():
        print("ERROR: run scripts/download_data.py first")
        return 1
    conn = db.connect()
    db.load_districts_geojson(conn, ROOT / "data" / "raw" / "tehran_districts_22.geojson")
    db.load_neighborhoods_geojson(conn, ROOT / "data" / "raw" / "tehran_neighborhoods_376.geojson")

    seen = set()
    rows = []
    with open(CSV, encoding="utf-8") as f:
        for rec in csv.DictReader(f):
            try:
                lat = float(rec["Lat"])
                lng = float(rec["Lang"])
            except (ValueError, KeyError):
                continue
            addr = (rec.get(" Address") or rec.get("Address") or "").strip()
            parts = [normalize(p).strip() for p in addr.split("،")]
            parts = [p for p in parts if p]
            # typical layout: استان تهران، تهران، محله، خیابان، ...
            street = None
            for p in parts[2:]:
                if p and p not in ("تهران", "استان تهران") and not p.isdigit():
                    street = p
                    break
            if not street:
                continue
            neigh = (rec.get(" neighbourhood") or rec.get("neighbourhood") or "").strip() or None
            zone = rec.get("municipality_zone") or None
            try:
                zone = int(zone) if zone else None
            except ValueError:
                zone = None
            key = (normalize(street), neigh)
            if key in seen:
                continue
            seen.add(key)
            rows.append((street, normalize(street), "street", neigh, zone, lat, lng, "csv"))

    conn.executemany(
        "INSERT INTO streets(name, norm, kind, neighborhood, district, lat, lng, source) "
        "VALUES(?,?,?,?,?,?,?,?)", rows,
    )
    conn.commit()
    print(f"seeded {len(rows)} streets from CSV")
    return 0


if __name__ == "__main__":
    sys.exit(main())