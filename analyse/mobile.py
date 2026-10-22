"""Mobile-shopper checks for the best-sellers. Most Amazon traffic is the app or mobile web: images are
small, titles are cut short in search, bullets sit collapsed under "About this item" and A+ modules stack
full-width. Thresholds mirror .claude/skills/outreach/references/mobile-rubric.md; change both together.
"""
from __future__ import annotations

import html
import re

from . import checks
from .rubric import FAIL, GOOD, POINTS, WARN

ZOOM_MIN, ZOOM_GOOD = 1000, 1600        # px on the longest side; below 1000 Amazon disables zoom
MOBILE_TITLE_CHARS = 80                 # roughly what mobile search shows before truncating
LONG_BULLET = 250
HEAVY_TEXT_WORDS = 30                   # words of copy inside one A+ image
NON_BRAND_CREATORS = {"influencer", "customer", "creator", "user", "buyer"}
SIZE_RE = re.compile(r"\b\d+(?:\.\d+)?\s?(?:ml|l|g|kg|oz|fl\s?oz|cm|mm|pack|pcs|pieces|count|ct|capsules|tablets|"
                     r"sachets|x)\b|\bpack of \d+|\b\d+\s?-?\s?pack\b", re.I)


def _zoom(images: list[dict]) -> tuple[str, str] | None:
    sizes = [max(i.get("w") or 0, i.get("h") or 0) for i in images if i.get("w") or i.get("h")]
    if not sizes:
        return None
    small = sum(1 for s in sizes if s < ZOOM_MIN)
    if small:
        return FAIL, f"{small} of {len(sizes)} images under {ZOOM_MIN}px, so they can't be zoomed"
    soft = sum(1 for s in sizes if s < ZOOM_GOOD)
    if soft:
        return WARN, f"all zoomable, but {soft} under {ZOOM_GOOD}px look soft when pinched"
    return GOOD, f"all {len(sizes)} images zoomable ({min(sizes)}px+)"


def _video(videos: list[dict]) -> tuple[str, str]:
    if not videos:
        return FAIL, "no video on the listing"
    brand = [v for v in videos if (v.get("creator") or "").strip().lower() not in NON_BRAND_CREATORS]
    if not brand:
        return WARN, f"{len(videos)} video(s), all influencer or customer: no brand-made video"
    if all(not v.get("duration") for v in brand):  # Keepa sometimes doesn't record the length
        return GOOD, f"{len(brand)} brand video(s) (length not recorded)"
    short = [v for v in brand if v.get("duration") and v["duration"] <= 90]
    if not short:
        return WARN, f"brand video is {min(v['duration'] for v in brand if v.get('duration'))}s; aim for 60s or less on mobile"
    return GOOD, f"{len(brand)} brand video(s), shortest {min(v.get('duration') or 0 for v in short)}s"


def _title(title: str, brand: str) -> tuple[str, str]:
    head = (title or "")[:MOBILE_TITLE_CHARS]
    missing = []
    if checks.norm(brand) and checks.norm(brand) not in checks.norm(head):
        missing.append("brand")
    full_type = checks.product_type(title)
    if full_type and full_type not in head.lower():
        missing.append("product type")
    if SIZE_RE.search(title or "") and not SIZE_RE.search(head):
        missing.append("size/pack")
    if not missing:
        return GOOD, f"first {MOBILE_TITLE_CHARS} characters carry brand, product and size"
    status = FAIL if "product type" in missing else WARN
    return status, f"cut off on mobile before the {', '.join(missing)}"


def _bullets(features: list[str] | None) -> tuple[str, str] | None:
    if features is None:
        return None
    if not features:
        return FAIL, "no bullets"
    long = sum(1 for f in features if len(f) > LONG_BULLET)
    first = features[0]
    if long:
        return WARN, f"{long} bullet(s) over {LONG_BULLET} characters; mobile shows these collapsed"
    return GOOD, f"{len(features)} bullets, first is {len(first)} characters"


def text_words(alt: str) -> int:
    """Amazon's A+ alt text quotes the copy inside the image: "Text reads 'x' and 'y'"."""
    quoted = re.findall(r"'([^']+)'", html.unescape(alt))
    return sum(len(q.split()) for q in quoted)


def _aplus(alts: list[str], has_aplus: bool) -> tuple[str, str] | None:
    if not has_aplus:
        return FAIL, "no A+ content"
    if not alts:
        return None
    heavy = sum(1 for a in alts if text_words(a) > HEAVY_TEXT_WORDS)
    if heavy >= 3:
        return FAIL, f"{heavy} of {len(alts)} A+ images are text-heavy, too small to read when stacked on a phone"
    if heavy:
        return WARN, f"{heavy} of {len(alts)} A+ images are text-heavy for a phone screen"
    return GOOD, f"{len(alts)} A+ images with light, phone-friendly text"


def check(p: dict, brand: str) -> dict:
    images = p.get("images_detail") or []
    results = {
        "zoom": _zoom(images),
        "image_count": (GOOD if len(images) >= 7 else WARN if len(images) >= 5 else FAIL,
                        f"{len(images)} gallery images") if images else None,
        "video": _video(p.get("videos_detail") or []) if "videos_detail" in p else None,
        "title_on_mobile": _title(p.get("title") or "", brand),
        "bullets_on_mobile": _bullets(p.get("features")),
        "a_plus_on_mobile": _aplus(p.get("aplus_alt") or [], bool(p.get("has_aplus"))) if "aplus_alt" in p else None,
    }
    known = {k: v for k, v in results.items() if v}
    score = round(100 * sum(POINTS[s] for s, _ in known.values()) / (2 * len(known))) if known else None
    return {"score": score, "checks": {k: {"status": s, "detail": d} for k, (s, d) in known.items()}}
