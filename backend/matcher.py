"""Candidate retrieval + ML-friendly ranking.

Returns ALL plausible matches (e.g. every "خیابان اکبری" in Tehran),
each with a match percentage, ranked. User choice feeds the learning loop.
"""
from __future__ import annotations

import math
import re
import sqlite3

from rapidfuzz import fuzz, process

from .normalize import fold, normalize

KIND_LABELS = {
    "street": "خیابان",
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
        self.addresses = [
            dict(r) for r in self.conn.execute(
                "SELECT id, street, housenumber, lat, lng, source, property_id FROM addresses "
                "WHERE housenumber IS NOT NULL AND housenumber != ''"
            )
        ]
        for a in self.addresses:
            a["folded"] = fold(a["street"] or "")
            a["number"] = normalize(str(a["housenumber"])).strip()

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
        # do NOT fall back to the raw query here: for "پلاک ۱۲" there is no
        # street name to match, and falling back would pollute fuzzy results.
        return " ".join(toks), "raw"

    @staticmethod
    def _house_number(parsed: dict, raw: str) -> str:
        f = parsed.get("fields", {})
        if f.get("number"):
            n = normalize(str(f["number"])).strip()
            if n.isdigit():
                return str(int(n))
        text = normalize(raw)
        m = re.search(r"(?:پلاک|پلاك|پ\.|پ|number|no\.?)\s*(\d+)", text)
        if m:
            return str(int(m.group(1)))
        # a trailing standalone 1-4 digit token is usually the house number
        toks = text.split()
        for tok in reversed(toks):
            if tok.isdigit() and 1 <= len(tok) <= 4:
                return str(int(tok))
            if not tok.isdigit():
                break
        return ""

    def _place_at(self, lat: float, lng: float) -> tuple[int | None, str | None]:
        from .db import district_at
        district = district_at(self.conn, lat, lng)
        best, best_d = None, 1.2
        for name, n in self.neighborhoods.items():
            if n.get("lat") is None or n.get("lng") is None:
                continue
            d = math.hypot((lat - n["lat"]) * 111.0, (lng - n["lng"]) * 90.5)
            if d < best_d:
                best, best_d = name, d
        return district, best

    @staticmethod
    def _number_score(wanted: str, actual: str) -> float:
        if wanted == actual:
            return 100.0
        if wanted.isdigit() and actual.isdigit():
            diff = abs(int(wanted) - int(actual))
            if diff <= 3:
                return 95.0 - diff * 12
            return 0.0  # "۱۲" is not a plausible match for "۱۲۴"
        return fuzz.ratio(wanted, actual)

    def _address_candidates(self, q_fold: str, number: str, limit: int) -> list[dict]:
        out = []
        for a in self.addresses:
            if not a["folded"] or not a["lat"] or not a["lng"]:
                continue
            name_score = fuzz.WRatio(q_fold, a["folded"]) if q_fold else 70.0
            if q_fold and a["folded"] == q_fold:
                name_score = 100.0
            elif q_fold and q_fold in a["folded"] and len(a["folded"]) > len(q_fold) * 1.4:
                name_score -= 12  # e.g. "برادران اکبری ۱۲۱" is not "اکبری"
            if q_fold and name_score < 80:
                continue
            num_score = self._number_score(number, a["number"])
            if num_score < 65:
                continue
            score = 0.55 * name_score + 0.45 * num_score
            if name_score >= 95 and num_score >= 95:
                score = 100.0
            district, neighborhood = self._place_at(a["lat"], a["lng"])
            out.append({
                "id": None,
                "address_id": a["id"],
                "name": f"{a['street']}، پلاک {a['housenumber']}",
                "kind": "پلاک",
                "neighborhood": neighborhood,
                "district": district,
                "lat": a["lat"], "lng": a["lng"],
                "match": min(100, round(score)),
                "source": a["source"],
                "property_id": a["property_id"],
                "housenumber": a["housenumber"],
                "_raw": score,
            })
        out.sort(key=lambda c: -c["_raw"])
        return out[:limit]

    def geocode(self, parsed: dict, raw: str, limit: int = 10) -> list[dict]:
        term, field = self._search_term(parsed, raw)
        f = parsed.get("fields", {})
        number = self._house_number(parsed, raw)
        if not term.strip():
            return self._address_candidates("", number, limit) if number else []
        q_fold = fold(term)
        address_candidates = self._address_candidates(q_fold, number, limit) if number else []

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
            raw_score = self._score(s, q_fold, score, f, field)
            if number and not address_candidates:
                raw_score -= 10  # a house number was requested but not found here
            candidates.append({
                "id": s["id"], "name": s["name"],
                "kind": KIND_LABELS.get(s["kind"], s["kind"]),
                "neighborhood": s["neighborhood"], "district": s["district"],
                "lat": s["lat"], "lng": s["lng"], "match": min(100, raw_score),
                "source": s["source"], "_raw": raw_score,
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
                            "match": min(100, self._score(s, q_fold, 100, f, field)),
                            "source": s["source"],
                            "_raw": self._score(s, q_fold, 100, f, field),
                        })

        candidates.sort(key=lambda c: -c["_raw"])
        merged = address_candidates + candidates
        seen_final, out = set(), []
        for c in merged:
            key = (c["name"], round(c["lat"], 5), round(c["lng"], 5))
            if key in seen_final:
                continue
            seen_final.add(key)
            c.pop("_raw", None)
            out.append(c)
            if len(out) >= limit:
                break
        return out

    def _score(self, s: dict, q_fold: str, name_score: float, f: dict, field: str) -> int:
        score = float(name_score)
        if fold(s["norm"]) == q_fold:
            score = 100.0  # exact name match
        # neighborhood agreement
        if f.get("neighborhood") and s["neighborhood"]:
            ns = fuzz.ratio(fold(f["neighborhood"]), fold(s["neighborhood"]))
            score = 0.65 * score + 0.35 * ns
        # district agreement
        if f.get("district") and s["district"]:
            try:
                if int(f["district"]) == int(s["district"]):
                    score += 8
                else:
                    score -= 18
            except ValueError:
                pass
        # prefer tagged streets (known district/neighborhood) over untagged ones
        if s["district"]:
            score += 3
        if s["neighborhood"]:
            score += 1
        # learned entries get a small trust bonus
        if s.get("source") == "learned":
            score += 4
        return max(1, round(score))

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
        addr, addr_d = None, float("inf")
        for a in self.addresses:
            d = haversine(lat, lng, a["lat"], a["lng"])
            if d < addr_d:
                addr, addr_d = a, d
        return {
            "lat": lat, "lng": lng, "district": district,
            "nearest_street": best["name"] if best else None,
            "neighborhood": neigh,
            "distance_m": round(best_d * 1000) if best else None,
            "house_number": (addr["housenumber"] if addr and addr_d < 0.12 else None),
            "house_number_source": (addr["source"] if addr and addr_d < 0.12 else None),
            "house_number_distance_m": round(addr_d * 1000) if addr and addr_d < 0.12 else None,
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