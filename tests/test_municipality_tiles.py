"""Offline checks for the municipality tile URL obfuscation."""
from scripts.download_municipality_tiles import encode_token, tile_url, tile_range


def test_encode_token_matches_browser_capture():
    # Captured from map.tehran.ir: token decodes to 11/1316/807.png?c=UmVocmFb
    inner = f"11/1316/807.png?c={encode_token('Tehran')}"
    assert encode_token(inner) + ".png" == "!jEvMTMxNi84MDcucG5nP2M9VW1Wb2NtRjEY.png"


def test_tile_url_shape():
    url = tile_url(14, 10530, 6451, 7)
    assert url.startswith("https://tile7.tehran.ir/tiles/gtt1/tiles.php?z=")
    assert url.endswith(".png")


def test_tile_range_contains_tehran():
    xs, ys = tile_range(14)
    assert 10530 in xs
    assert 6451 in ys
