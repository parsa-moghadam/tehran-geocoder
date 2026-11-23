"""SQLite database: Tehran streets, neighborhoods, districts, learned feedback."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "tehran.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS streets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    norm TEXT NOT NULL,
    kind TEXT NOT NULL DEFAULT 'street',
    neighborhood TEXT,
    district INTEGER,
    lat REAL NOT NULL,
    lng REAL NOT NULL,
    source TEXT NOT NULL DEFAULT 'osm'
);
CREATE INDEX IF NOT EXISTS idx_streets_norm ON streets(norm);
CREATE INDEX IF NOT EXISTS idx_streets_neigh ON streets(neighborhood);

CREATE TABLE IF NOT EXISTS neighborhoods (
    name TEXT PRIMARY KEY,
    district INTEGER,
    lat REAL,
    lng REAL
);

CREATE TABLE IF NOT EXISTS districts (
    id INTEGER PRIMARY KEY,
    name TEXT,
    geometry TEXT
);

CREATE TABLE IF NOT EXISTS addresses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    street TEXT,
    housenumber TEXT,
    lat REAL,
    lng REAL
);

CREATE TABLE IF NOT EXISTS feedback (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    query TEXT NOT NULL,
    norm_query TEXT NOT NULL,
    street_id INTEGER,
    lat REAL,
    lng REAL,
    created_at TEXT DEFAULT (datetime('now'))
);
"""


def connect(db_path: Path = DB_PATH) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


def load_districts_geojson(conn: sqlite3.Connection, path: Path) -> int:
    gj = json.loads(path.read_text(encoding="utf-8"))
    n = 0
    for feat in gj.get("features", []):
        props = feat.get("properties", {})
        num = props.get("area") or props.get("district")
        if num is None:
            import re
            m = re.search(r"منطقه\s*([۰-۹0-9]+)", props.get("name", ""))
            if m:
                num = m.group(1)
        if num is None:
            continue
        from .normalize import normalize
        num = int("".join(c for c in normalize(str(num)) if c.isdigit()))
        conn.execute(
            "INSERT OR REPLACE INTO districts(id, name, geometry) VALUES(?,?,?)",
            (num, props.get("name", f"منطقه {num}"), json.dumps(feat.get("geometry"))),
        )
        n += 1
    conn.commit()
    return n


def load_neighborhoods_geojson(conn: sqlite3.Connection, path: Path) -> int:
    gj = json.loads(path.read_text(encoding="utf-8"))
    n = 0
    for feat in gj.get("features", []):
        props = feat.get("properties", {})
        name = (props.get("name") or "").strip()
        if not name:
            continue
        geom = feat.get("geometry") or {}
        coords = geom.get("coordinates") or []
        pts = coords[0] if geom.get("type") == "Polygon" else (coords[0][0] if coords else [])
        if not pts:
            continue
        lat = sum(p[1] for p in pts) / len(pts)
        lng = sum(p[0] for p in pts) / len(pts)
        district = props.get("district")
        conn.execute(
            "INSERT OR REPLACE INTO neighborhoods(name, district, lat, lng) VALUES(?,?,?,?)",
            (name, district, lat, lng),
        )
        n += 1
    conn.commit()
    return n


def point_in_polygon(lng: float, lat: float, ring: list) -> bool:
    inside = False
    j = len(ring) - 1
    for i in range(len(ring)):
        xi, yi = ring[i][0], ring[i][1]
        xj, yj = ring[j][0], ring[j][1]
        if (yi > lat) != (yj > lat) and lng < (xj - xi) * (lat - yi) / (yj - yi) + xi:
            inside = not inside
        j = i
    return inside


def district_at(conn: sqlite3.Connection, lat: float, lng: float) -> int | None:
    for row in conn.execute("SELECT id, geometry FROM districts"):
        geom = json.loads(row["geometry"])
        rings = geom.get("coordinates", [])
        if geom.get("type") == "MultiPolygon":
            rings = [r for poly in rings for r in poly]
        for ring in rings:
            xs = [p[0] for p in ring]
            ys = [p[1] for p in ring]
            if not (min(xs) <= lng <= max(xs) and min(ys) <= lat <= max(ys)):
                continue
            if point_in_polygon(lng, lat, ring):
                return row["id"]
    return None