"""Download open data for Tehran geocoder (one-time, then fully offline).

Usage:
  python scripts/download_data.py           # small files (geojson, csv)
  python scripts/download_data.py --pbf     # also Iran OSM extract (~220MB)
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"

FILES = {
    "tehran_districts_22.geojson":
        "https://raw.githubusercontent.com/mjalalimanesh/tehran-districts-neighborhoods-map-geojson/main/tehran_districts_22.geojson",
    "tehran_neighborhoods_376.geojson":
        "https://raw.githubusercontent.com/mjalalimanesh/tehran-districts-neighborhoods-map-geojson/main/tehran_neighborhoods_376.geojson",
    "tehran_address_points.csv":
        "https://raw.githubusercontent.com/thisistayeb/Tehran-address/main/Random_add_Tehran.csv",
}
PBF_URL = "https://download.geofabrik.de/asia/iran-latest.osm.pbf"


def download(url: str, dest: Path):
    if dest.exists() and dest.stat().st_size > 0:
        print(f"skip (exists): {dest.name}")
        return
    print(f"downloading {dest.name} ...")
    with requests.get(url, stream=True, timeout=120) as r:
        r.raise_for_status()
        tmp = dest.with_suffix(dest.suffix + ".part")
        with open(tmp, "wb") as f:
            for chunk in r.iter_content(chunk_size=1 << 20):
                f.write(chunk)
        tmp.rename(dest)
    print(f"done: {dest.name} ({dest.stat().st_size / 1e6:.1f} MB)")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pbf", action="store_true", help="also download Iran OSM extract (~220MB)")
    args = ap.parse_args()
    RAW.mkdir(parents=True, exist_ok=True)
    for name, url in FILES.items():
        download(url, RAW / name)
    if args.pbf:
        download(PBF_URL, RAW / "iran-latest.osm.pbf")


if __name__ == "__main__":
    sys.exit(main())