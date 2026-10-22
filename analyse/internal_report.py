"""Render the client-facing internal audit (HTML + A4 PDF) from internal_audit.json + internal_findings.json.

    python -m analyse.internal_report runs/<slug>

Numbers come from internal_audit.json (analyse/internal_audit.py). Wording, colours and actions come from
internal_findings.json, written by the internal-audit skill. Layout: .claude/skills/internal-audit/templates/report.html.
"""
from __future__ import annotations

import html
import subprocess
import sys
from pathlib import Path

from analyse.pdf import chromium
from collectors.common import ROOT, read_json

TEMPLATE = ROOT / ".claude/skills/internal-audit/templates/report.html"
GROUPS = [("push", "Push: shoppers buy {brand} more than they click it", "g-push"),
          ("defend", "Defend: own-brand searches", "g-push"),
          ("hold", "Hold: converting at or below market", "g-hold"),
          ("test", "Test small: rival-brand searches", "g-hold"),
          ("cut", "Cut or limit: shoppers buy something else", "g-cut")]
PILL = {"g": "p-g", "a": "p-a", "r": "p-r"}
SOURCES = "Seller Central Business Reports, Brand Analytics, Amazon Ads, Keepa"


def e(v) -> str:
    return html.escape("" if v is None else str(v))


def money(v, cur="$", dp=0) -> str:
    return "–" if v is None else f"{cur}{v:,.{dp}f}"


def pct(v, dp=1) -> str:
    return "–" if v is None else f"{v:.{dp}f}%"


def vol(v: float) -> str:
    return f"{v:,.0f}" if v < 1000 else (f"{v / 1000:.1f}k" if v < 10000 else f"{v / 1000:.0f}k")


def bullets(items) -> str:
    return f"<ul>{''.join(f'<li>{i}</li>' for i in items)}</ul>" if items else ""


def h2(n: int, title: str) -> str:
    return f'<h2><span class="num">{n}</span>{e(title)}</h2>'


def table(head: list[str], rows: list[str], cls: str = "", numeric_from: int = 1) -> str:
    th = "".join(f'<th{" class=n" if i >= numeric_from else ""}>{h}</th>' for i, h in enumerate(head))
    return f'<table class="{cls}"><thead><tr>{th}</tr></thead>{"".join(rows)}</table>'


def tiles_html(f: dict) -> str:
    out = []
    for t in f.get("tiles") or []:
        cls = "tile hot" if t.get("hot") else "tile"
        v = f'<div class="v{" bad" if t.get("bad") else ""}">{e(t["value"])}</div>'
        out.append(f'<div class="{cls}"><div class="l">{e(t["label"])}</div>{v}<div class="s">{e(t.get("sub"))}</div></div>')
    return f'<div class="tiles">{"".join(out)}</div>' if out else ""


def sqp_section(d: dict, f: dict, cur: str) -> str:
    rows_by_group: dict[str, list] = {}
    over = f.get("group_overrides") or {}
    skip = set(f.get("exclude_queries") or [])
    for r in d.get("sqp", {}).get("rows", []):
        if r["query"] in skip:
            continue
        rows_by_group.setdefault(over.get(r["query"], r["group"]), []).append(r)
    qs = d.get("query_spend") or {}
    rows = []
    for key, label, cls in GROUPS:
        if not rows_by_group.get(key):
            continue
        rows.append(f'<tr class="grp {cls}"><td colspan="7">{e(label.format(brand=f.get("brand", "")))}</td></tr>')
        for r in rows_by_group[key]:
            ratio = r["ratio"]
            col = "good" if ratio and ratio >= 1.05 else ("bad" if ratio is not None and ratio < 0.85 else "warn")
            s = qs.get(r["query"], {})
            cpo = s.get("cost_per_order")
            cpo_txt = money(cpo, cur) if cpo else ("no orders" if s.get("spend", 0) >= 25 else "–")
            bad = " bad" if (cpo and cpo > f.get("cpo_alert", 40)) or (not cpo and s.get("spend", 0) >= 25) else ""
            rows.append(f'<tr><td class="k">{e(r["query"])}</td><td class="n">{vol(r["volume_per_week"])}</td>'
                        f'<td class="n {col}"><b>{pct(r["purchase_share"])}</b></td>'
                        f'<td class="n">{"–" if ratio is None else f"{ratio:.1f}×"}</td><td class="n">{r["asin_purchases"]}</td>'
                        f'<td class="n">{money(s.get("spend"), cur)}</td><td class="n{bad}">{cpo_txt}</td></tr>')
    weeks = d.get("sqp", {}).get("weeks", [])
    span = f"{weeks[0].split(' – ')[0]} – {weeks[-1].split(' – ')[1]}" if weeks else ""
    st = d.get("search_terms", {}).get("date_range") or ["", ""]
    key = (f'<div class="callout">Brand Analytics Search Query Performance, {e(span)}. Ratio = purchase share ÷ click share. '
           f'Above 1×: {e(f.get("brand"))} wins more than its share of sales. Below 1×: shoppers click, then buy elsewhere. '
           f'Sales = units bought from that search. Ad spend YTD = Sponsored Products spend on that exact search, '
           f'{e(st[0])} – {e(st[1])}. <b>Green</b> = push, <b>amber</b> = hold or test, <b>red</b> = cut.</div>')
    head = ["Search", "Searches<br>/wk", "Purchase<br>share", "Ratio", "Sales", "Ad spend<br>YTD", "Ad cost<br>/ order"]
    return key + table(head, rows, "long") + bullets(f.get("push_notes"))


def campaign_section(d: dict, f: dict, cur: str) -> str:
    labels = f.get("campaign_labels") or {}
    rows = []
    for c in d.get("campaigns", []):
        name = c["Campaign name"]
        lab = labels.get(name)
        if not lab:
            continue
        short, tone, verdict = lab[:3]
        cpo = c.get("cost_per_order")
        rows.append(f'<tr><td>{e(short)}</td><td class="n">{money(c.get("Total cost"), cur)}</td><td class="n">{c.get("Purchases", 0):,.0f}</td>'
                    f'<td class="n{" bad" if cpo and cpo > f.get("cpo_alert", 40) else ""}">{money(cpo, cur)}</td>'
                    f'<td class="n">{pct(c.get("acos"), 0)}</td><td><span class="pill {PILL[tone]}">{e(verdict)}</span></td></tr>')
    return table(["Campaign", "Spend", "Orders", "Cost / order", "ACOS", ""], rows) + bullets(f.get("campaign_notes"))


def spend_section(d: dict, f: dict, cur: str) -> str:
    out = []
    st = d.get("search_terms")
    if st:
        verdicts = f.get("bucket_verdicts") or {}
        rows = []
        for b in st["buckets"]:
            v = verdicts.get(b["bucket"])
            pill = f'<span class="pill {PILL[v[0]]}">{e(v[1])}</span>' if v else ""
            rows.append(f'<tr><td class="k">{e(b["bucket"])}</td><td class="n">{money(b["spend"], cur)}</td><td class="n">{b["share"]:.0f}%</td>'
                        f'<td class="n">{b["orders"]:,.0f}</td><td class="n">{pct(b.get("cvr"))}</td>'
                        f'<td class="n{" bad" if (b.get("cost_per_order") or 0) > f.get("cpo_alert", 40) else ""}">{money(b.get("cost_per_order"), cur)}</td><td>{pill}</td></tr>')
        t = st["total"]
        rows.append(f'<tr><td><b>Total</b></td><td class="n"><b>{money(t["spend"], cur)}</b></td><td class="n">100%</td>'
                    f'<td class="n"><b>{t["orders"]:,.0f}</b></td><td class="n">{pct(100 * t["orders"] / t["clicks"] if t["clicks"] else None)}</td>'
                    f'<td class="n"><b>{money(t["spend"] / t["orders"] if t["orders"] else None, cur)}</b></td><td></td></tr>')
        dr = st.get("date_range") or ["", ""]
        out.append(f'<div class="keep"><p>Sponsored Products, {e(dr[0])} – {e(dr[1])}, grouped by what the shopper searched for.</p>'
                   + table(["Search type", "Spend", "Share", "Orders", "Conv.", "Cost / order", ""], rows) + "</div>")
        out.append(bullets(f.get("spend_notes")))
    pl = d.get("placement")
    if pl:
        rows = [f'<tr><td>{e(r["Placement"].replace(" on Amazon", ""))}</td><td class="n">{money(r["spend"], cur)}</td><td class="n">{r["share"]:.0f}%</td>'
                f'<td class="n">{r["orders"]:,.0f}</td><td class="n{" bad" if (r.get("cost_per_order") or 0) > f.get("cpo_alert", 40) * 0.9 else ""}">{money(r.get("cost_per_order"), cur)}</td>'
                f'<td class="n">{pct(r.get("acos"), 0)}</td></tr>' for r in pl["by_placement"]]
        out.append('<div class="keep"><h3>Where the ads appear</h3>' + table(["Placement", "Spend", "Share", "Orders", "Cost / order", "ACOS"], rows) + "</div>")
        labels = f.get("campaign_labels") or {}
        rows = [f'<tr><td>{e((labels.get(r["Campaign Name"]) or [r["Campaign Name"]])[0])}</td><td class="n">{money(r["spend"], cur)}</td>'
                f'<td class="n">{money(r.get("cost_per_order"), cur)}</td><td class="n">{pct(r.get("acos"), 0)}</td></tr>'
                for r in pl["top_of_search_by_campaign"]]
        out.append(table(["Top of search, by campaign", "Spend", "Cost / order", "ACOS"], rows) + bullets(f.get("placement_notes")))
    weekly = {w["week_end"]: w for w in d.get("advertised", {}).get("weekly", [])}
    ranks = d.get("rank_weekly") or []
    if weekly and ranks:
        price = f.get("weekly_price") or {}
        rows = []
        for r in ranks:
            w = weekly.get(r["week_end"])
            if not w:
                continue
            rows.append(f'<tr><td>w/e {e(r["week_end"])}</td><td class="n">{money(w["spend"], cur)}</td><td class="n">{w["orders"]:,.0f}</td>'
                        f'<td class="n">{e(price.get(r["week_end"], "–"))}</td><td class="n">{r["rank"]:,}</td></tr>')
        out.append('<div class="keep"><h3>Has the spend helped ranking?</h3>'
                   + table(["Week", "SP spend", "Ad orders", "Price", "Sales rank"], rows) + bullets(f.get("rank_notes")) + "</div>")
    return "".join(out)


def render(run: Path) -> tuple[Path, Path]:
    d = read_json(run / "internal_audit.json")
    f = read_json(run / "internal_findings.json")
    if not d or not f:
        raise SystemExit("needs internal_audit.json and internal_findings.json in the run folder")
    cur = f.get("currency", "$")
    col = {"ink": "#111111", "accent": "#E4007C", "accent_soft": "#FDEAF3", **(f.get("brand_colours") or {})}
    sec = f.get("sections") or {}
    parts = [f'<div class="band"><div class="logo">{e(f.get("logo_text") or f.get("brand"))}</div><div>'
             f'<div class="sub"><b>{e(f.get("marketplace_label"))}</b> · {e(f.get("product"))} · {e(d["asin"])}</div>'
             f'<h1>{e(f.get("title", "Sales, conversion and ad spend review"))}</h1><div class="sub">{e(f.get("date"))}</div></div></div>',
             f'<p class="lead">{f.get("lead", "")}</p>', tiles_html(f)]
    n = 0

    def section(title: str, body: str):
        nonlocal n
        if body.strip():
            n += 1
            parts.append(h2(n, title) + body)

    conv = sec.get("conversion") or {}
    section("Conversion rate", (table(["Product", "Category", "Conversion"],
                                      [f'<tr><td><b>{e(r[0])}</b></td><td>{e(r[1])}</td><td class="n {e(r[3]) if len(r) > 3 else ""}"><b>{e(r[2])}</b></td></tr>'
                                       for r in conv.get("rows", [])], numeric_from=2) if conv.get("rows") else "") + bullets(conv.get("bullets")))
    cat = sec.get("category") or {}
    section("Category", (table(["Listing", "Category"], [f'<tr><td>{e(r[0])}</td><td class="{"bad" if len(r) > 2 and r[2] else ""}">{e(r[1])}</td></tr>'
                                                         for r in cat.get("rows", [])], numeric_from=9) if cat.get("rows") else "")
            + (f'<div class="callout">{cat["callout"]}</div>' if cat.get("callout") else ""))
    if sec.get("listing"):
        section("Listing and mobile", f"<p>{sec['listing']}</p>")
    if d.get("sqp"):
        section("Where to push spend", sqp_section(d, f, cur))
    if f.get("campaign_labels") and d.get("campaigns"):
        section("Ad spend by campaign", campaign_section(d, f, cur))
    section("Where the ad money has gone", spend_section(d, f, cur))
    acts = "".join(f'<li><b>{a["title"]}</b> {a.get("detail", "")}<div class="why">{a.get("why", "")}</div></li>' for a in f.get("actions", []))
    section("Actions", f'<ol class="actions">{acts}</ol>' if acts else "")
    tg = [f'<tr><td>{e(t["measure"])}</td><td class="n{" bad" if t.get("bad") else ""}">{e(t["now"])}</td><td class="n">{e(t["target"])}</td></tr>'
          for t in f.get("targets", [])]
    tail = ""
    if f.get("summary"):
        tail += f'<div class="callout dark"><b>Summary:</b> {f["summary"]}</div>'
    tail += f'<p class="foot">{f.get("notes", "")} Sources: {e(f.get("sources", SOURCES))}.</p>'
    if tg:
        n += 1
        parts.append(f'<div class="keep">{h2(n, "Targets for the next 2–3 weeks")}{table(["Measure", "Now", "Target"], tg)}{tail}</div>')
    else:
        parts.append(tail)

    page = (TEMPLATE.read_text().replace("{{TITLE}}", e(f"{f.get('brand')} {f.get('marketplace_label')} review"))
            .replace("{{INK}}", col["ink"]).replace("{{ACCENT}}", col["accent"]).replace("{{ACCENT_SOFT}}", col["accent_soft"])
            .replace("{{BODY}}", "\n".join(parts)))
    out_html = run / "internal-report.html"
    out_html.write_text(page)
    out_pdf = run / f"{f.get('brand', 'Client').replace(' ', '-')}-{d['asin']}-{d['marketplace'].upper()}-Account-Review.pdf"
    subprocess.run([chromium(), "--headless=new", "--no-sandbox", "--disable-gpu", "--no-pdf-header-footer",
                    "--virtual-time-budget=3000", f"--print-to-pdf={out_pdf}", out_html.resolve().as_uri()],
                   check=True, capture_output=True, timeout=120)
    return out_html, out_pdf


if __name__ == "__main__":
    h, p = render(Path(sys.argv[1]))
    print(f"✓ {h}\n✓ {p}")
