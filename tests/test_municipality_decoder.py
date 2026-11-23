"""Offline checks for the map.tehran.ir response decoder (no network needed)."""
from scripts.download_tehran_municipality import decode_coord, decode_key, decode_property


def test_decode_key():
    assert decode_key("2zkM") == 693
    assert decode_key("=jQyNA=M") == 4422


def test_decode_coord():
    # observed live pair: key 693, l -> "51.3847654,35.6947097"
    assert decode_coord("38-5171?62%03'5?=4604", 693) == (51.3847654, 35.6947097)


def test_decode_property_wrapper():
    raw = ("orikldlowriukeounprwwtsierpnDUwNzYxNzUiLCJjZW50ZXIiOiJQT0lOVCg1NzIwMTM0LjIyOTQyNzU3NiA0MjU4NzAwLjE5NTA2NzkxKSJ9fQ=="
           "eyJwcm9wZXJ0eV9pZF9kYXRhIjp7InByb3BlcnR5X2lkIjoxODMxNTAyNiwicGxhcXVlIjoiNTgiLCJ4IjoiNTEuMzg0ODQwMDU1MTAwMzMiLCJ5IjoiMzUuNjk0NzQ5M"
           "@87odworniinpoesdiuktulprfelkrw")
    out = decode_property(raw)["property_id_data"]
    assert out["property_id"] == 18315026
    assert out["plaque"] == "58"
