"""Build the Tehran SQLite index from the Iran OSM extract.

Extracts named streets/alleys/boulevards/squares inside the Tehran bbox,
assigns municipality district (polygon) and neighborhood (geojson or OSM),
and loads the reference geojson layers.

Usage: python scripts/build_index.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import osmium  # noqa: E402

from backend import db  # noqa: E402
from backend.normalize import normalize  # noqa: E402

RAW = ROOT / "data" / "raw"
PBF = RAW / "iran-latest.osm.pbf"

# Tehran city bounding box (lng_min, lat_min, lng_max, lat_max)
BBOX = (51.05, 35.52, 51.65, 35.85)

ROAD_KINDS = {
    "motorway", "trunk", "primary", "secondary", "tertiary",
    "residential", "living_street", "unclassified",
}
PLACE_KINDS = {"neighbourhood", "suburb", "quarter", "city_district"}


def kind_from_name(name: str, highway: str) -> str:
    if name.startswith("بلوار"):
        return "boulevard"
    if name.startswith("میدان"):
        return "square"
    if name.startswith("بزرگراه") or highway in ("motorway", "trunk"):
        return "motorway"
    if name.startswith("کوچه") or name.startswith("بن‌بست"):
        return "alley"
    return highway


class TehranHandler(osmium.SimpleHandler):
    def __init__(self):
        super().__init__()
        self.streets: dict[tuple, dict] = {}
        self.places: list[dict] = []
        self.addresses: list[dict] = []

    def node(self, n):
        if not n.location.valid():
            return
        lat, lng = n.location.lat, n.location.lon
        if not (BBOX[0] <= lng <= BBOX[2] and BBOX[1] <= lat <= BBOX[3]):
            return
        tags = n.tags
        if tags.get("place") in PLACE_KINDS and "name" in tags:
            self.places.append({"name": tags["name"], "lat": lat, "lng": lng})
        if tags.get("addr:housenumber") and tags.get("addr:street"):
            self.addresses.append({
                "street": tags["addr:street"], "housenumber": tags["addr:housenumber"],
                "lat": lat, "lng": lng,
            })

    def way(self, w):
        tags = w.tags
        hw = tags.get("highway")
        if hw not in ROAD_KINDS or "name" not in tags:
            return
        pts = [(n.location.lon, n.location.lat) for n in w.nodes if n.location.valid()]
        if not pts:
            return
        lng = sum(p[0] for p in pts) / len(pts)
        lat = sum(p[1] for p in pts) / len(pts)
        if not (BBOX[0] <= lng <= BBOX[2] and BBOX[1] <= lat <= BBOX[3]):
            return
        name = tags["name"]
        key = (normalize(name), round(lat, 3), round(lng, 3))
        if key in self.streets:
            return
        self.streets[key] = {
            "name": name, "norm": normalize(name),
            "kind": kind_from_name(name, hw), "lat": lat, "lng": lng,
        }
        if tags.get("addr:housenumber"):
            self.addresses.append({
                "street": name, "housenumber": tags["addr:housenumber"],
                "lat": lat, "lng": lng,
            })


def main():
    if not PBF.exists():
        print("ERROR: data/raw/iran-latest.osm.pbf not found. Run: python scripts/download_data.py --pbf")
        return 1
    conn = db.connect()

    print("loading district polygons ...")
    nd = db.load_districts_geojson(conn, RAW / "tehran_districts_22.geojson")
    print(f"  {nd} districts")
    print("loading neighborhood polygons ...")
    nn = db.load_neighborhoods_geojson(conn, RAW / "tehran_neighborhoods_376.geojson")
    print(f"  {nn} neighborhoods")

    # precompute neighborhood polygon rings + bboxes for fast assignment
    import json
    gj = json.loads((RAW / "tehran_neighborhoods_376.geojson").read_text(encoding="utf-8"))
    neigh_polys = []
    for feat in gj["features"]:
        name = (feat["properties"].get("name") or "").strip()
        geom = feat.get("geometry") or {}
        coords = geom.get("coordinates") or []
        rings = coords if geom.get("type") == "Polygon" else [r for p in coords for r in p]
        for ring in rings:
            xs = [p[0] for p in ring]
            ys = [p[1] for p in ring]
            neigh_polys.append((name, min(xs), min(ys), max(xs), max(ys), ring))

    def assign_neighborhood(lat, lng):
        for name, x0, y0, x1, y1, ring in neigh_polys:
            if x0 <= lng <= x1 and y0 <= lat <= y1 and db.point_in_polygon(lng, lat, ring):
                return name
        return None

    print(f"scanning {PBF.name} for Tehran streets ...")
    h = TehranHandler()
    h.apply_file(str(PBF), locations=True)
    print(f"  {len(h.streets)} street segments, {len(h.places)} place nodes, {len(h.addresses)} addresses")

    # OSM place nodes as additional neighborhoods
    for p in h.places:
        conn.execute(
            "INSERT OR IGNORE INTO neighborhoods(name, district, lat, lng) VALUES(?,?,?,?)",
            (p["name"], None, p["lat"], p["lng"]),
        )

    print("assigning districts/neighborhoods and inserting ...")
    rows = []
    for i, s in enumerate(h.streets.values()):
        district = db.district_at(conn, s["lat"], s["lng"])
        neigh = assign_neighborhood(s["lat"], s["lng"])
        rows.append((s["name"], s["norm"], s["kind"], neigh, district, s["lat"], s["lng"], "osm"))
        if (i + 1) % 5000 == 0:
            print(f"  {i + 1}/{len(h.streets)}")
    conn.executemany(
        "INSERT INTO streets(name, norm, kind, neighborhood, district, lat, lng, source) "
        "VALUES(?,?,?,?,?,?,?,?)", rows,
    )
    conn.executemany(
        "INSERT INTO addresses(street, housenumber, lat, lng) VALUES(?,?,?,?)",
        [(a["street"], a["housenumber"], a["lat"], a["lng"]) for a in h.addresses],
    )
    conn.commit()
    total = conn.execute("SELECT COUNT(*) c FROM streets").fetchone()["c"]
    print(f"done. streets table: {total} rows")
    return 0


if __name__ == "__main__":
    sys.exit(main())