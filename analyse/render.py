"""Render audit.html + evidence.md from dataset.json and the skill-written findings.json.

    python -m analyse.render runs/<slug>

Layout and styling live in .claude/skills/amazon-audit/templates/audit.html; this fills its slots.
Charts are inline SVG with <title> tooltips; every chart has a table beside or below it.
"""
from __future__ import annotations

import html
import json
import sys
from pathlib import Path

from collectors.common import ROOT, read_json

TEMPLATE = ROOT / ".claude/skills/amazon-audit/templates/audit.html"
STATUS_ICON = {"good": ("✓", "Good"), "warn": ("!", "Needs work"), "fail": ("✕", "Missing")}
KW_STATUS = {
    "push": "Ranks page 1–2, no ads: push to top",
    "missing": "Not visible",
    "brand_defence_gap": "Competitors bidding, brand not defended",
    "organic_top_unprotected": "Top organically, no ad cover",
    "sponsored_only": "Paid only, weak organic",
    "sponsored_support": "Ads supporting organic",
    "own": "Owns the top of page",
}
TIER_LABEL = {"brand": "Brand", "core": "Core", "category": "Category", "long_tail": "Long-tail", "competitor": "Competitor"}


def e(v) -> str:
    return html.escape("" if v is None else str(v))


def money(v, cur: str) -> str:
    if v is None:
        return "–"
    return f"{cur}{v:,.0f}" if v >= 100 else f"{cur}{v:,.2f}"


def pct(v) -> str:
    return "–" if v is None else f"{v * 100:.0f}%"


def num(v) -> str:
    return "–" if v is None else f"{v:,.0f}"


# --- charts --------------------------------------------------------------------------------------

def bar_chart(data: dict[str, float], fmt=num, height: int = 180) -> str:
    """Vertical bars, one series. Labels every other bar when crowded."""
    if not data:
        return '<p class="empty">No dated launches found.</p>'
    items = list(data.items())
    w, pad_l, pad_b, pad_t = 640, 36, 28, 16
    plot_w, plot_h = w - pad_l - 8, height - pad_b - pad_t
    top = max(v for _, v in items) or 1
    step = plot_w / len(items)
    bar_w = max(4, min(36, step - 6))
    label_every = 1 if len(items) <= 12 else 2
    parts = [f'<svg viewBox="0 0 {w} {height}" role="img" class="chart">']
    for frac in (0.5, 1.0):
        y = pad_t + plot_h * (1 - frac)
        parts.append(f'<line x1="{pad_l}" x2="{w - 8}" y1="{y:.1f}" y2="{y:.1f}" class="grid"/>'
                     f'<text x="{pad_l - 6}" y="{y + 4:.1f}" class="tick" text-anchor="end">{e(fmt(top * frac))}</text>')
    for i, (label, v) in enumerate(items):
        x = pad_l + i * step + (step - bar_w) / 2
        h = plot_h * v / top
        y = pad_t + plot_h - h
        parts.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{bar_w:.1f}" height="{max(h, 1):.1f}" rx="3" class="bar">'
                     f'<title>{e(label)}: {e(fmt(v))}</title></rect>')
        if i % label_every == 0:
            parts.append(f'<text x="{x + bar_w / 2:.1f}" y="{height - 8}" class="tick" text-anchor="middle">{e(label)}</text>')
    parts.append(f'<line x1="{pad_l}" x2="{w - 8}" y1="{pad_t + plot_h}" y2="{pad_t + plot_h}" class="axis"/></svg>')
    return "".join(parts)


def hbars(rows: list[tuple[str, float, bool]], fmt=pct) -> str:
    """Horizontal bars for share of voice. Highlighted row = the prospect."""
    if not rows:
        return '<p class="empty">No share-of-voice data.</p>'
    top = max(v for _, v, _ in rows) or 1
    out = ['<div class="hbars">']
    for label, v, mine in rows:
        out.append(f'<div class="hbar{" mine" if mine else ""}"><span class="hbar-label">{e(label)}</span>'
                   f'<span class="hbar-track"><span class="hbar-fill" style="width:{100 * v / top:.1f}%" title="{e(label)}: {e(fmt(v))}"></span></span>'
                   f'<span class="hbar-value">{e(fmt(v))}</span></div>')
    out.append("</div>")
    return "".join(out)


def stacked(parts: dict[str, float], cur: str) -> str:
    total = sum(parts.values())
    if not total:
        return '<p class="empty">Not enough keyword and CPC data to size a budget.</p>'
    segs = "".join(f'<span class="seg s{i}" style="flex:{v}" title="{e(k)}: {e(money(v, cur))}"></span>'
                   for i, (k, v) in enumerate(parts.items()))
    legend = "".join(f'<li><span class="sw s{i}"></span>{e(k)} <b>{e(money(v, cur))}</b> <small>{v / total:.0%}</small></li>'
                     for i, (k, v) in enumerate(parts.items()))
    return f'<div class="stack">{segs}</div><ul class="legend">{legend}</ul>'


# --- sections ------------------------------------------------------------------------------------

def points_html(findings: dict) -> str:
    out = []
    for p in findings.get("points", [])[:5]:
        quote = f'<p class="quote">You asked for: “{e(p["job_ad_quote"])}”</p>' if p.get("job_ad_quote") else ""
        evidence = "".join(f"<li>{e(x)}</li>" for x in p.get("evidence", []))
        out.append(f'<li class="point"><div class="point-body"><span class="tag">{e(p.get("category", ""))}</span>'
                   f'<h3>{e(p["title"])}</h3><p>{e(p["detail"])}</p>{quote}'
                   f'<details><summary>What we saw</summary><ul>{evidence}</ul></details></div></li>')
    return "".join(out)


def stats_html(d: dict) -> str:
    cur = d["prospect"]["currency"]
    cat, content, ads = d["catalogue"], d["content"]["summary"], d["ads_observed"]
    tiles = [
        ("ASINs found", num(d["asin_map"]["discovered"]), f'{num(d["asin_map"]["parents"])} parent listings checked'),
        ("Launched in last 12 months", num(cat["launches_last_12m"]), "new ASINs"),
        ("Est. monthly revenue", money(cat["est_monthly_revenue_keepa"], cur), "lower bound, from 'bought in past month'"),
        ("Listing score", f'{content["avg_score_top_parents"] or "–"}/100', "average of top sellers"),
        ("Sponsored coverage", pct(ads["sponsored_coverage"]), "of their top 30 keywords"),
    ]
    return "".join(f'<div class="stat"><span class="stat-label">{e(a)}</span><span class="stat-value">{e(b)}</span>'
                   f'<span class="stat-note">{e(c)}</span></div>' for a, b, c in tiles)


def content_table(d: dict) -> str:
    checks = ["images", "video", "a_plus", "title", "bullets", "bullet_depth", "rating", "reviews"]
    head = "".join(f"<th>{c.replace('_', ' ').title()}</th>" for c in checks)
    rows = []
    for p in d["content"]["top_parents"]:
        cells = []
        for c in checks:
            ck = p["checks"][c]
            icon, label = STATUS_ICON[ck["status"]]
            cells.append(f'<td><span class="chip {ck["status"]}" title="{e(label)}">{icon}</span> {e(ck["detail"])}</td>')
        title = (p.get("title") or "")[:60]
        rows.append(f'<tr><th scope="row"><a href="https://www.{e(d["prospect"]["domain"])}/dp/{e(p["asin"])}">{e(p["asin"])}</a>'
                    f'<small>{e(title)}</small></th><td class="num">{p["score"]}</td>{"".join(cells)}</tr>')
    return (f'<div class="scroll"><table class="content"><thead><tr><th>Listing</th><th>Score</th>{head}</tr></thead>'
            f'<tbody>{"".join(rows)}</tbody></table></div>')


def keyword_table(d: dict) -> str:
    cur = d["prospect"]["currency"]
    rows = "".join(
        f'<tr><td>{e(k["keyword"])}</td><td>{e(TIER_LABEL[k["tier"]])}</td><td class="num">{num(k["volume"])}</td>'
        f'<td class="num">{e(k["organic_rank"] or "–")}</td><td class="num">{e(k["sponsored_rank"] or "–")}</td>'
        f'<td class="num">{money(k["cpc"], cur)}</td><td><span class="kw-status {e(k["status"])}">{e(KW_STATUS[k["status"]])}</span></td></tr>'
        for k in d["strategy"]["focus_keywords"])
    return (f'<div class="scroll"><table><thead><tr><th>Keyword</th><th>Tier</th><th class="num">Searches/mo</th>'
            f'<th class="num">Organic</th><th class="num">Sponsored</th><th class="num">CPC</th><th>Status</th></tr></thead>'
            f'<tbody>{rows}</tbody></table></div>')


def tier_table(d: dict) -> str:
    rows = "".join(f'<tr><td>{e(TIER_LABEL[t])}</td><td class="num">{v["keywords"]}</td><td class="num">{num(v["volume"])}</td>'
                   f'<td class="num">{v["gaps"]}</td></tr>' for t, v in d["strategy"]["tiers"].items())
    return (f'<table><thead><tr><th>Tier</th><th class="num">Keywords</th><th class="num">Searches/mo</th>'
            f'<th class="num">Gaps</th></tr></thead><tbody>{rows}</tbody></table>')


def attackers_html(d: dict) -> str:
    att = d["competitors"]["brand_term_attackers"]
    if not att:
        return "<p>No competitor ads seen on their brand name in the searches we ran.</p>"
    items = "".join(f'<li><b>{e(a["brand_guess"])}</b> sponsored at position {e(a["position"])} on “{e(a["keyword"])}”'
                    f'<small>{e(a["title"])}</small></li>' for a in att[:8])
    own = "They do appear in their own brand-term ads." if d["competitors"]["prospect_sponsored_on_own_brand"] \
        else "They had no sponsored placement of their own on those searches."
    return f"<ul class=\"attackers\">{items}</ul><p>{own}</p>"


def amc_html(d: dict, findings: dict) -> str:
    bench = d.get("amc_benchmark") or {}
    rows = ""
    labels = {"avg_touches_before_purchase": ("Ad touches before first purchase", lambda v: f"{v:.1f}"),
              "share_3plus_touches": ("Buyers with 3+ ad touches", pct),
              "ntb_share": ("New-to-brand share of ad sales", pct),
              "repeat_rate": ("Buyers who reorder in window", pct),
              "repeat_60d_rate": ("Reorder within 60 days", pct),
              "avg_days_to_repeat": ("Average days to reorder", lambda v: f"{v:.0f}"),
              "multi_ad_type_cvr_lift": ("Conversion lift, SP + SB/SD vs SP only", lambda v: f"{v:.1f}×")}
    for k, (label, f) in labels.items():
        m = (bench.get("metrics") or {}).get(k)
        if m:
            rows += f'<tr><td>{e(label)}</td><td class="num">{e(f(m["median"]))}</td><td class="num">{e(f(m["min"]))}–{e(f(m["max"]))}</td></tr>'
    table = (f'<table><thead><tr><th>Category benchmark ({e(bench.get("category"))})</th><th class="num">Median</th>'
             f'<th class="num">Range</th></tr></thead><tbody>{rows}</tbody></table>') if rows else ""
    hyp = "".join(f"<li>{e(h)}</li>" for h in findings.get("amc_hypotheses", []))
    qs = "".join(f"<li>{e(q)}</li>" for q in findings.get("amc_questions", []))
    rs = d["strategy"]["repeat_signals"]
    signals = (f'Repeat-purchase signals: {e(rs.get("likelihood", "unknown"))} '
               f'(Subscribe &amp; Save on {pct(rs.get("sns_share"))} of ASINs, multipacks {pct(rs.get("multipack_share"))}, '
               f'{"consumable" if rs.get("consumable_category") else "non-consumable"} category).')
    return (f'<p>{signals}</p>{table}<div class="two"><div><h3>What we expect AMC to show</h3><ul>{hyp}</ul></div>'
            f'<div><h3>Questions we would answer in week one</h3><ol>{qs}</ol></div></div>')


def method_html(d: dict) -> str:
    a = d["strategy"]["budget"]["assumptions"]
    steps = d.get("coverage", {}).get("steps", [])
    skipped = [s for s in steps if s["status"] != "ok"]
    skipped_html = "".join(f"<li>{e(s['step'])}: {e(s.get('reason') or s.get('error'))}</li>" for s in skipped)
    return (f"<p>Built from public marketplace data (Keepa, Jungle Scout, DataForSEO, Amazon catalogue and bid "
            f"recommendations) on {e(d['generated'])}. We have not seen this brand's Seller Central or advertising "
            f"account, so spend and budget figures are estimates.</p>"
            f"<p>Budget model: search volume × {a['clicks_per_search']:.0%} of searches producing an ad click × target "
            f"sponsored share of voice by tier × CPC benchmark, plus {a['retention_share']:.0%} for remarketing.</p>"
            + (f"<details><summary>Data gaps in this run</summary><ul>{skipped_html}</ul></details>" if skipped else ""))


def render(run: Path) -> tuple[Path, Path]:
    d = read_json(run / "dataset.json")
    findings = read_json(run / "findings.json")
    if not d or not findings:
        raise SystemExit(f"{run} needs dataset.json and findings.json")
    cur = d["prospect"]["currency"]
    cat = d["catalogue"]
    budget = d["strategy"]["budget"]
    sov = d["competitors"]["share_of_voice"][:8]
    slots = {
        "TITLE": e(f'{d["prospect"]["brand"] or "Prospect"} Amazon Audit'),
        "BRAND": e(d["prospect"]["brand"] or d["prospect"]["input"]),
        "MARKET": e(d["prospect"]["domain"]),
        "DATE": e(d["generated"]),
        "HEADLINE": e(findings.get("headline", "")),
        "POINTS": points_html(findings),
        "STATS": stats_html(d),
        "LAUNCH_CHART": bar_chart(cat["launches_by_quarter"]),
        "REVENUE_CHART": bar_chart({m[2:]: v for m, v in cat["revenue_monthly_top_parents"].items()},
                                   fmt=lambda v: money(v, cur)) if cat["revenue_monthly_top_parents"] else
        '<p class="empty">No sales history available for this run.</p>',
        "CATALOGUE_NOTE": e(findings.get("catalogue_note", "")),
        "CONTENT_TABLE": content_table(d),
        "CONTENT_NOTE": e(findings.get("content_note", "")),
        "AD_SUMMARY": e(findings.get("ad_strategy_summary", "")),
        "TIER_TABLE": tier_table(d),
        "KEYWORD_TABLE": keyword_table(d),
        "BUDGET_CHART": stacked(budget["monthly_by_ad_type"], cur),
        "BUDGET_TOTAL": money(budget["monthly_total"], cur),
        "ATTACKERS": attackers_html(d),
        "SOV_CHART": hbars([(r["brand"], r["avg_sov"], r["is_prospect"]) for r in sov]),
        "AMC": amc_html(d, findings),
        "METHOD": method_html(d),
    }
    page = TEMPLATE.read_text()
    for k, v in slots.items():
        page = page.replace(f"{{{{{k}}}}}", v)
    out_html = run / "audit.html"
    out_html.write_text(page)

    lines = [f"# Evidence: {d['prospect']['brand']} ({d['prospect']['domain']}, {d['generated']})", ""]
    for i, p in enumerate(findings.get("points", [])[:5], 1):
        lines += [f"## {i}. {p['title']}", "", p["detail"], ""] + [f"- {x}" for x in p.get("evidence", [])] + [""]
    lines += ["## Data coverage", "", "```json", json.dumps(d.get("coverage", {}), indent=2), "```"]
    out_md = run / "evidence.md"
    out_md.write_text("\n".join(lines))
    return out_html, out_md


if __name__ == "__main__":
    for path in render(Path(sys.argv[1])):
        print(f"✓ {path}")
