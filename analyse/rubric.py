"""Listing-quality checks. Thresholds mirror .claude/skills/outreach/references/scoring-rubric.md;
change both together."""
from __future__ import annotations

GOOD, WARN, FAIL = "good", "warn", "fail"
POINTS = {GOOD: 2, WARN: 1, FAIL: 0}


def _band(value, good_at: float, warn_at: float) -> str:
    if value is None:
        return WARN
    if value >= good_at:
        return GOOD
    return WARN if value >= warn_at else FAIL


def check_listing(p: dict) -> dict:
    title_len = p.get("title_len") or 0
    checks = {
        "images": (_band(p.get("image_count"), 7, 5), f"{p.get('image_count', 0)} images"),
        "video": (GOOD if p.get("video_count") else FAIL, f"{p.get('video_count', 0)} video{'' if p.get('video_count') == 1 else 's'}"),
        "a_plus": (GOOD if p.get("has_aplus") else FAIL,
                   f"A+ with {p.get('aplus_modules', 0)} modules" if p.get("has_aplus") else "no A+"),
        "title": (GOOD if 80 <= title_len <= 200 else WARN, f"{title_len} chars"),
        "bullets": (_band(p.get("bullet_count"), 5, 3),
                    f"{p['bullet_count']} bullets" if p.get("bullet_count") is not None else "bullets not captured"),
        "bullet_depth": (_band(p.get("bullet_avg_len"), 120, 70),
                         f"avg {p['bullet_avg_len']} chars" if p.get("bullet_avg_len") is not None else "not captured"),
        "rating": (_band(p.get("rating"), 4.3, 4.0), f"{p.get('rating') or '–'}★"),
        "reviews": (_band(p.get("review_count"), 100, 20), f"{p.get('review_count') or 0} reviews"),
    }
    score = sum(POINTS[s] for s, _ in checks.values()) / (2 * len(checks))
    return {
        "score": round(score * 100),
        "checks": {k: {"status": s, "detail": d} for k, (s, d) in checks.items()},
    }
