"""Download best-seller gallery images and lay them out at phone size, so the skill can judge whether
callouts are readable on a mobile screen and whether the main image works as a search thumbnail.

Images live on m.media-amazon.com; if the environment blocks it, the step is skipped (ImagesBlocked).
"""
from __future__ import annotations

import io
import urllib.error
import urllib.request
from pathlib import Path

CDN = "https://m.media-amazon.com/images/I/"
PHONE_W = 375          # CSS width of a typical phone screen
THUMB_W = 150          # roughly a search-result thumbnail
GAP = 12


class ImagesBlocked(RuntimeError):
    pass


def fetch(file: str) -> bytes:
    try:
        with urllib.request.urlopen(CDN + file, timeout=30) as resp:
            return resp.read()
    except urllib.error.HTTPError:
        raise
    except (urllib.error.URLError, OSError) as e:
        raise ImagesBlocked(f"can't reach m.media-amazon.com ({e}); add it to Allowed domains") from e


def phone_sheet(images: list[dict], out: Path, fetcher=fetch) -> Path | None:
    """Main image at thumbnail size, then every gallery image at phone width, in one PNG."""
    from PIL import Image, ImageDraw

    tiles = []
    for img in images:
        file = img.get("medium") or img.get("file")
        if not file:
            continue
        try:
            im = Image.open(io.BytesIO(fetcher(file))).convert("RGB")
        except urllib.error.HTTPError:
            continue
        tiles.append((img.get("variant") or "", im))
    if not tiles:
        return None

    def fit(im, w):
        return im.resize((w, round(im.height * w / im.width)))

    thumb = fit(tiles[0][1], THUMB_W)
    phones = [(label, fit(im, PHONE_W)) for label, im in tiles]
    cols = 3
    rows = (len(phones) + cols - 1) // cols
    row_h = max(p.height for _, p in phones) + 28
    width = cols * (PHONE_W + GAP) + GAP
    height = thumb.height + 48 + rows * row_h + GAP
    sheet = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(sheet)
    draw.text((GAP, 8), "Search thumbnail (main image at ~150px)", fill="black")
    sheet.paste(thumb, (GAP, 26))
    y0 = thumb.height + 48
    for i, (label, im) in enumerate(phones):
        x = GAP + (i % cols) * (PHONE_W + GAP)
        y = y0 + (i // cols) * row_h
        draw.text((x, y), f"{label} at phone width ({PHONE_W}px)", fill="black")
        sheet.paste(im, (x, y + 18))
    out.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out)
    return out
