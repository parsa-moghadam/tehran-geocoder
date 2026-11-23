"""FastAPI app: multi-candidate geocoding + learning loop + demo frontend."""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import db
from .matcher import Matcher
from .normalize import normalize
from .parser import get_parser

ROOT = Path(__file__).resolve().parent.parent

app = FastAPI(title="Tehran Geocoder", version="0.1.0")

conn = db.connect()
matcher = Matcher(conn)
parser = get_parser(neighborhoods=set(matcher.neighborhoods))


@app.get("/api/geocode")
def geocode(q: str, limit: int = 20):
    if not q or not q.strip():
        raise HTTPException(400, "query is empty")
    parsed = parser.parse(q)
    candidates = matcher.geocode(parsed, q, limit=limit)
    return {
        "query": q,
        "normalized": normalize(q),
        "parsed": parsed["fields"],
        "parse_confidence": parsed["confidence"],
        "parser_available": parser.available,
        "candidates": candidates,
    }


@app.get("/api/autocomplete")
def autocomplete(q: str, limit: int = 8):
    return {"query": q, "items": matcher.autocomplete(q, limit=limit)}


@app.get("/api/reverse")
def reverse(lat: float, lng: float):
    if not (35.4 <= lat <= 36.1 and 50.8 <= lng <= 51.9):
        raise HTTPException(400, "coordinates outside Tehran area")
    return matcher.reverse(lat, lng)


class Feedback(BaseModel):
    query: str
    street_id: int | None = None
    lat: float
    lng: float


@app.post("/api/feedback")
def feedback(fb: Feedback):
    if not (35.4 <= fb.lat <= 36.1 and 50.8 <= fb.lng <= 51.9):
        raise HTTPException(400, "coordinates outside Tehran area")
    fid = matcher.learn(fb.query, fb.street_id, fb.lat, fb.lng)
    return {"ok": True, "feedback_id": fid}


@app.get("/health")
def health():
    return {"status": "ok", "streets": len(matcher.streets), "parser": parser.available}


@app.get("/api/stats")
def stats():
    n_streets = conn.execute("SELECT COUNT(*) c FROM streets").fetchone()["c"]
    n_learned = conn.execute("SELECT COUNT(*) c FROM streets WHERE source='learned'").fetchone()["c"]
    n_neigh = conn.execute("SELECT COUNT(*) c FROM neighborhoods").fetchone()["c"]
    n_dist = conn.execute("SELECT COUNT(*) c FROM districts").fetchone()["c"]
    n_fb = conn.execute("SELECT COUNT(*) c FROM feedback").fetchone()["c"]
    return {"streets": n_streets, "learned": n_learned, "neighborhoods": n_neigh,
            "districts": n_dist, "feedback": n_fb, "parser_available": parser.available}


@app.get("/")
def index():
    return FileResponse(ROOT / "frontend" / "index.html")


app.mount("/static", StaticFiles(directory=ROOT / "frontend"), name="static")