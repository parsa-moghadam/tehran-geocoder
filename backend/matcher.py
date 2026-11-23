"""Candidate retrieval + ML-friendly ranking.

Returns ALL plausible matches (e.g. every "خیابان اکبری" in Tehran),
each with a match percentage, ranked. User choice feeds the learning loop.
"""
from __future__ import annotations

import math
import sqlite3

from rapidfuzz import fuzz, process

from .normalize import fold, normalize

KIND_LABELS = {
    "motorway": "بزرگراه", "trunk": "بزرگراه",
    "primary": "خیابان اصلی", "secondary": "خیابان",
    "tertiary": "خیابان", "residential": "خیابان",
    "living_street": "خیابان", "unclassified": "خیابان",
    "boulevard": "بلوار", "square": "میدان", "alley": "کوچه",
}


class Matcher:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
        self.reload()

    def reload(self):
        rows = self.conn.execute(
            "SELECT id, name, norm, kind, neighborhood, district, lat, lng, source FROM streets"
        ).fetchall()
        self.streets = [dict(r) for r in rows]
        self._names = [s["norm"] for s in self.streets]
        self._folded = [fold(s["norm"]) for s in self.streets]
        self.neighborhoods = {
            r["name"]: dict(r)
            for r in self.conn.execute("SELECT name, district, lat, lng FROM neighborhoods")
        }

    # ------------------------------------------------------------------ search
    def _search_term(self, parsed: dict, raw: str) -> tuple[str, str]:
        """What to search for, and which field it came from."""
        f = parsed.get("fields", {})
        if f.get("street"):
            return f["street"], "street"
        if f.get("neighborhood"):
            return f["neighborhood"], "neighborhood"
        # strip city / keywords from raw query
        stop = {"تهران", "خیابان", "خیابون", "خ", "کوچه", "ک", "بلوار", "بل",
                "میدان", "بزرگراه", "منطقه", "پلاک", "واحد", "طبقه", "محله"}
        toks = [t for t in normalize(raw).split() if t not in stop and not t.isdigit()]
        return " ".join(toks) or raw, "raw"

    def geocode(self, parsed: dict, raw: str, limit: int = 10) -> list[dict]:
        term, field = self._search_term(parsed, raw)
        if not term.strip():
            return []
        f = parsed.get("fields", {})
        q_fold = fold(term)

        # neighborhood search: return the neighborhood itself + its streets
        if field == "neighborhood" and term in self.neighborhoods:
            nb = self.neighborhoods[term]
            out = [{
                "id": None, "name": term, "kind": "محله",
                "neighborhood": term, "district": nb["district"],
                "lat": nb["lat"], "lng": nb["lng"], "match": 100,
            }]
            return out

        # fuzzy retrieval over all street names (fast C++ implementation)
        hits = process.extract(q_fold, self._folded, scorer=fuzz.WRatio, limit=60)
        seen: set[tuple] = set()
        candidates = []
        for _choice, score, idx in hits:
            s = self.streets[idx]
            key = (s["norm"], s["neighborhood"], s["district"])
            if key in seen:
                continue
            seen.add(key)
            match = self._score(s, q_fold, score, f, field)
            candidates.append({
                "id": s["id"], "name": s["name"],
                "kind": KIND_LABELS.get(s["kind"], s["kind"]),
                "neighborhood": s["neighborhood"], "district": s["district"],
                "lat": s["lat"], "lng": s["lng"], "match": match,
                "source": s["source"],
            })

        # exact-name duplicates in different neighborhoods must ALL survive:
        # keep every distinct (name, neighborhood) even if fuzzy score is low
        if field in ("street", "raw"):
            for s in self.streets:
                if fold(s["norm"]) == q_fold:
                    key = (s["norm"], s["neighborhood"], s["district"])
                    if key not in seen:
                        seen.add(key)
                        candidates.append({
                            "id": s["id"], "name": s["name"],
                            "kind": KIND_LABELS.get(s["kind"], s["kind"]),
                            "neighborhood": s["neighborhood"], "district": s["district"],
                            "lat": s["lat"], "lng": s["lng"],
                            "match": self._score(s, q_fold, 100, f, field),
                            "source": s["source"],
                        })

        candidates.sort(key=lambda c: -c["match"])
        return candidates[:limit]

    def _score(self, s: dict, q_fold: str, name_score: float, f: dict, field: str) -> int:
        score = float(name_score)
        # neighborhood agreement
        if f.get("neighborhood") and s["neighborhood"]:
            ns = fuzz.ratio(fold(f["neighborhood"]), fold(s["neighborhood"]))
            score = 0.65 * score + 0.35 * ns
        # district agreement
        if f.get("district") and s["district"]:
            try:
                if int(f["district"]) == int(s["district"]):
                    score = min(100, score + 8)
                else:
                    score -= 18
            except ValueError:
                pass
        # learned entries get a small trust bonus
        if s.get("source") == "learned":
            score = min(100, score + 4)
        return max(1, min(100, round(score)))

    # ------------------------------------------------------------- autocomplete
    def autocomplete(self, q: str, limit: int = 8) -> list[dict]:
        qn = fold(q)
        if len(qn) < 2:
            return []
        hits = process.extract(qn, self._folded, scorer=fuzz.WRatio, limit=limit * 3)
        seen, out = set(), []
        for _choice, score, idx in hits:
            s = self.streets[idx]
            if s["name"] in seen:
                continue
            seen.add(s["name"])
            out.append({"name": s["name"], "neighborhood": s["neighborhood"],
                        "district": s["district"], "match": round(score)})
            if len(out) >= limit:
                break
        return out

    # ------------------------------------------------------------------ reverse
    def reverse(self, lat: float, lng: float) -> dict:
        from .db import district_at
        best, best_d = None, float("inf")
        for s in self.streets:
            d = haversine(lat, lng, s["lat"], s["lng"])
            if d < best_d:
                best, best_d = s, d
        district = district_at(self.conn, lat, lng)
        neigh = None
        if best and best_d < 0.4:
            neigh = best["neighborhood"]
        return {
            "lat": lat, "lng": lng, "district": district,
            "nearest_street": best["name"] if best else None,
            "neighborhood": neigh,
            "distance_m": round(best_d * 1000) if best else None,
        }

    # ----------------------------------------------------------------- learning
    def learn(self, query: str, street_id: int | None, lat: float, lng: float) -> int:
        nq = normalize(query)
        cur = self.conn.execute(
            "INSERT INTO feedback(query, norm_query, street_id, lat, lng) VALUES(?,?,?,?,?)",
            (query, nq, street_id, lat, lng),
        )
        # upsert a learned street entry so next search immediately improves
        name = nq
        if street_id:
            row = self.conn.execute("SELECT name FROM streets WHERE id=?", (street_id,)).fetchone()
            if row:
                name = row["name"]
        from .db import district_at
        district = district_at(self.conn, lat, lng)
        self.conn.execute(
            "INSERT INTO streets(name, norm, kind, neighborhood, district, lat, lng, source) "
            "VALUES(?,?,?,?,?,?,?, 'learned')",
            (name, normalize(name), "street", None, district, lat, lng),
        )
        self.conn.commit()
        self.reload()
        return cur.lastrowid


def haversine(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Distance in km."""
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))