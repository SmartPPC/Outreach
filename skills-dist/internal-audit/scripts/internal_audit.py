"""Internal account audit: turn a client's own Seller Central and Amazon Ads exports into one dataset.

    python scripts/internal_audit.py <out_dir> --uploads <dir> --asin B0XXXXXXXX --brand W7 \\
        --period "Sep|2026-09-01|2026-09-30|BusinessReport-10-21-26.csv" \\
        --period "1-20 Oct|2026-10-01|2026-10-20|BusinessReport-10-21-26_1.csv" \\
        --rivals "sephora,ulta,elf,loreal,revolution" --category-words "beauty,makeup,make up,cosmetic" \\
        --off-target "needoh,squishy,dumpling,chocolate,lego"

Files are recognised by their columns, so upload names don't matter. Writes runs/<slug>/internal_audit.json;
scripts/internal_report.py turns that plus the skill-written internal_findings.json into the client PDF.
Which reports to pull, and how to read the output: references/ in this skill.
"""
from __future__ import annotations

import argparse
import datetime as dt
import re
from pathlib import Path

import pandas as pd

import json
import os
import urllib.request

KEEPA_DOMAIN = {"us": 1, "uk": 2, "de": 3, "fr": 4, "jp": 5, "ca": 6, "it": 8, "es": 9, "in": 10, "mx": 11}


def write_json(path: Path, data) -> Path:
    path.write_text(json.dumps(data, indent=2, default=str, ensure_ascii=False))
    return path

KEEPA_EPOCH_MIN = 21564000
ASIN_RE = re.compile(r"^b0[a-z0-9]{8}$")

# Search Query Performance bands: purchase share ÷ click share
PUSH_RATIO, HOLD_RATIO = 1.05, 0.85


# --- loading -------------------------------------------------------------------------------------

def _read(path: Path) -> tuple[pd.DataFrame | None, str]:
    """Return (frame, first line). SQP CSVs carry a metadata line above the header."""
    if path.suffix.lower() in (".xlsx", ".xls"):
        return pd.read_excel(path), ""
    first = path.open(encoding="utf-8-sig").readline()
    skip = 1 if first.startswith("ASIN=") or first.startswith("Brand=") else 0
    return pd.read_csv(path, skiprows=skip, encoding="utf-8-sig"), first


def detect(df: pd.DataFrame, first_line: str = "") -> str | None:
    cols = {c.strip() for c in df.columns}
    if "Search Query" in cols and "Purchases: ASIN Count" in cols:
        return "sqp"
    if "(Child) ASIN" in cols and "Sessions - Total" in cols:
        return "business"
    if "Customer Search Term" in cols:
        return "search_term"
    if "Placement" in cols and "Bidding strategy" in cols:
        return "placement"
    if "Targeting" in cols and "Top-of-search Impression Share" in cols:
        return "targeting"
    if "Advertised ASIN" in cols and "Date" in cols:
        return "advertised"
    if "Campaign name" in cols and "Top-of-search bid adjustment" in cols:
        return "campaigns"
    return None


def load_uploads(folder: Path) -> dict:
    out: dict = {"sqp": [], "business": {}}
    for path in sorted(folder.iterdir()):
        if path.suffix.lower() not in (".csv", ".xlsx", ".xls"):
            continue
        df, first = _read(path)
        df.columns = [str(c).strip() for c in df.columns]
        kind = detect(df, first)
        if kind == "sqp":
            m = re.search(r"(\d{4}-\d\d-\d\d) - (\d{4}-\d\d-\d\d)", first)
            out["sqp"].append((m.group(2) if m else path.stem, m.group(1) if m else "", df))
        elif kind == "business":
            out["business"][path.name] = df
        elif kind:
            out[kind] = df
    out["sqp"].sort(key=lambda w: w[0])
    return out


def num(v) -> float:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return 0.0
    if isinstance(v, (int, float)):
        return float(v)
    s = re.sub(r"[,$£€%]", "", str(v)).strip()
    try:
        return float(s)
    except ValueError:
        return 0.0


def _numeric(df: pd.DataFrame, cols: list[str]) -> pd.DataFrame:
    df = df.copy()
    for c in cols:
        if c in df.columns:
            df[c] = df[c].map(num)
    return df


# --- sections ------------------------------------------------------------------------------------

def business_rows(frames: dict, asin: str) -> dict:
    out = {}
    for name, df in frames.items():
        df = _numeric(df, ["Sessions - Total", "Units Ordered", "Ordered Product Sales", "Featured Offer (Buy Box) Percentage"])
        row = df[df["(Child) ASIN"] == asin]
        tot = {"sessions": df["Sessions - Total"].sum(), "units": df["Units Ordered"].sum(),
               "sales": df["Ordered Product Sales"].sum(), "asins": int(len(df))}
        r = row.iloc[0] if len(row) else None
        out[name] = {
            "title": None if r is None else r["Title"],
            "sessions": 0 if r is None else r["Sessions - Total"],
            "units": 0 if r is None else r["Units Ordered"],
            "sales": 0 if r is None else r["Ordered Product Sales"],
            "buy_box": None if r is None else r["Featured Offer (Buy Box) Percentage"],
            "account": tot,
        }
        u, s = out[name]["units"], out[name]["sessions"]
        out[name]["cvr"] = round(100 * u / s, 2) if s else None
    return out


ADV_NUM = ["Spend", "Clicks", "Impressions", "7 Day Total Sales", "7 Day Total Orders (#)", "7 Day Total Units (#)",
           "7 Day Advertised SKU Units (#)"]


def advertised(df: pd.DataFrame, asin: str) -> tuple[pd.DataFrame, dict]:
    df = _numeric(df, ADV_NUM)
    df["Date"] = pd.to_datetime(df["Date"])
    a = df[df["Advertised ASIN"] == asin]
    agg = {"spend": ("Spend", "sum"), "clicks": ("Clicks", "sum"), "sales": ("7 Day Total Sales", "sum"),
           "orders": ("7 Day Total Orders (#)", "sum"), "units": ("7 Day Advertised SKU Units (#)", "sum")}
    weekly = a.groupby(pd.Grouper(key="Date", freq="W-SAT")).agg(**agg).reset_index()
    by_campaign = a.groupby("Campaign Name").agg(**agg).reset_index().sort_values("spend", ascending=False)
    by_campaign["cost_per_order"] = by_campaign.spend / by_campaign.orders.replace(0, float("nan"))
    return a, {
        "date_range": [str(a.Date.min().date()), str(a.Date.max().date())] if len(a) else None,
        "campaigns": sorted(a["Campaign Name"].unique().tolist()),
        "weekly": [{"week_end": str(r.Date.date()), **{k: round(float(r[k]), 2) for k in agg}} for _, r in weekly.iterrows()],
        "by_campaign": _records(by_campaign),
        "total": {k: round(float(a[v[0]].sum()), 2) for k, v in agg.items()},
    }


def period_rows(adv: pd.DataFrame, business: dict, periods: list[dict]) -> list[dict]:
    """Join each Business Report period to SP ad spend over the same dates."""
    out = []
    for p in periods:
        b = next((v for k, v in business.items() if k.endswith(p["file"]) or p["file"] in k), None)
        days = (dt.date.fromisoformat(p["end"]) - dt.date.fromisoformat(p["start"])).days + 1
        m = (adv.Date >= p["start"]) & (adv.Date <= p["end"])
        sp = {"spend": float(adv[m].Spend.sum()), "orders": float(adv[m]["7 Day Total Orders (#)"].sum()),
              "units": float(adv[m]["7 Day Advertised SKU Units (#)"].sum()), "clicks": float(adv[m].Clicks.sum())}
        row = {"label": p["label"], "start": p["start"], "end": p["end"], "days": days, "sp": sp, "business": b}
        if b:
            row["units_per_day"] = round(b["units"] / days, 1)
            row["sp_tacos"] = round(100 * sp["spend"] / b["sales"], 1) if b["sales"] else None
            row["sp_cost_per_unit"] = round(sp["spend"] / sp["units"], 2) if sp["units"] else None
            row["ad_cvr"] = round(100 * sp["units"] / sp["clicks"], 2) if sp["clicks"] else None
        out.append(row)
    return out


def campaign_rows(df: pd.DataFrame, names: list[str], match: str | None) -> list[dict]:
    df = _numeric(df, ["Total cost", "Sales", "Purchases", "Clicks", "Impressions", "Campaign budget amount",
                       "Top-of-search bid adjustment"])
    keep = df["Campaign name"].isin(names)
    if match:
        keep |= df["Campaign name"].str.contains(match, case=False, na=False)
    d = df[keep].copy()
    d["cost_per_order"] = d["Total cost"] / d.Purchases.replace(0, float("nan"))
    d["acos"] = 100 * d["Total cost"] / d.Sales.replace(0, float("nan"))
    cols = ["Campaign name", "State", "Type", "Targeting", "Campaign bid strategy", "Top-of-search bid adjustment",
            "Campaign budget amount", "Total cost", "Sales", "Purchases", "Clicks", "cost_per_order", "acos",
            "Top-of-search impression share"]
    return _records(d[[c for c in cols if c in d.columns]].sort_values("Total cost", ascending=False))


def classify_query(q: str, ratio: float | None, cfg: dict) -> str:
    if any(re.search(rf"\b{re.escape(b)}\b", q) for b in cfg["brand_terms"]):
        return "defend"
    if any(re.search(rf"\b{re.escape(w)}\b", q) for w in cfg["off_target"]) or "amazon" in q:
        return "cut"
    if any(re.search(rf"\b{re.escape(r)}\b", q) for r in cfg["rivals"]):
        return "test"
    if ratio is None:
        return "hold"
    return "push" if ratio >= PUSH_RATIO else ("hold" if ratio >= HOLD_RATIO else "cut")


def sqp(weeks: list, n_weeks: int, cfg: dict, min_sales: int = 3) -> dict:
    cols = ["Search Query Volume", "Impressions: Total Count", "Impressions: ASIN Count", "Clicks: Total Count",
            "Clicks: ASIN Count", "Purchases: Total Count", "Purchases: ASIN Count"]
    trend = []
    for end, start, df in weeks:
        df = _numeric(df, cols)
        trend.append({"week": f"{start} – {end}", "asin_purchases": df["Purchases: ASIN Count"].sum(),
                      "asin_clicks": df["Clicks: ASIN Count"].sum()})
    recent = weeks[-n_weeks:]
    frames = []
    for end, start, df in recent:
        d = _numeric(df, cols)
        d["q"] = d["Search Query"].astype(str).str.strip("￼ ").str.strip().str.lower()
        frames.append(d)
    if not frames:
        return {"weeks": [], "rows": [], "trend": trend}
    a = pd.concat(frames).groupby("q")[cols].sum()
    rows = []
    for q, r in a.iterrows():
        clk = 100 * r["Clicks: ASIN Count"] / r["Clicks: Total Count"] if r["Clicks: Total Count"] else 0
        pur = 100 * r["Purchases: ASIN Count"] / r["Purchases: Total Count"] if r["Purchases: Total Count"] else 0
        ratio = pur / clk if clk else None
        group = classify_query(q, ratio, cfg)
        if r["Purchases: ASIN Count"] < min_sales and not (group in ("test", "cut") and r["Search Query Volume"] / len(recent) > 20000):
            continue
        rows.append({"query": q, "volume_per_week": round(r["Search Query Volume"] / len(recent)),
                     "impression_share": round(100 * r["Impressions: ASIN Count"] / r["Impressions: Total Count"], 2) if r["Impressions: Total Count"] else 0,
                     "click_share": round(clk, 2), "purchase_share": round(pur, 2),
                     "ratio": round(ratio, 2) if ratio is not None else None,
                     "asin_purchases": int(r["Purchases: ASIN Count"]), "group": group})
    order = {"push": 0, "defend": 1, "hold": 2, "test": 3, "cut": 4}
    rows.sort(key=lambda r: (order[r["group"]], -r["volume_per_week"]))
    return {"weeks": [f"{s} – {e}" for e, s, _ in recent], "rows": rows, "trend": trend}


ST_NUM = ["Spend", "Clicks", "Impressions", "7 Day Total Sales", "7 Day Total Orders (#)"]


def search_terms(df: pd.DataFrame, campaigns: list[str], cfg: dict) -> tuple[pd.DataFrame, dict]:
    s = _numeric(df[df["Campaign Name"].isin(campaigns)], ST_NUM)
    s["q"] = s["Customer Search Term"].astype(str).str.lower().str.strip()
    s["bucket"] = s.q.map(lambda q: bucket(q, cfg))
    g = s.groupby("bucket").agg(spend=("Spend", "sum"), clicks=("Clicks", "sum"),
                                orders=("7 Day Total Orders (#)", "sum"), sales=("7 Day Total Sales", "sum"))
    g = _rates(g)
    g["share"] = 100 * g.spend / g.spend.sum()
    top = s.groupby("q").agg(spend=("Spend", "sum"), orders=("7 Day Total Orders (#)", "sum")).sort_values("spend", ascending=False)
    top["cost_per_order"] = top.spend / top.orders.replace(0, float("nan"))
    return s, {"date_range": [str(s["Start Date"].min())[:10], str(s["End Date"].max())[:10]] if "Start Date" in s else None,
               "buckets": _records(g.sort_values("spend", ascending=False).reset_index()),
               "total": {k: round(float(g[k].sum()), 2) for k in ("spend", "clicks", "orders", "sales")},
               "top_terms": _records(top.head(25).reset_index())}


def bucket(q: str, cfg: dict) -> str:
    if ASIN_RE.match(q):
        return "Rival product pages"
    if any(re.search(rf"\b{re.escape(b)}\b", q) for b in cfg["brand_terms"]):
        return "Own brand"
    if any(re.search(rf"\b{re.escape(w)}\b", q) for w in cfg["off_target"]):
        return "Off-target"
    if "amazon" in q:
        return "Amazon's own"
    if any(re.search(rf"\b{re.escape(r)}\b", q) for r in cfg["rivals"]):
        return "Rival brand searches"
    if any(re.search(rf"\b{re.escape(w)}\b", q) for w in cfg["category_words"]):
        return "Category searches"
    if re.search(r"\b(teen|teens|tween|girl|girls|women|womens|woman|men|mens|adult|adults|kids|boys)\b", q):
        return "Audience searches"
    return "Generic searches"


def query_spend(st: pd.DataFrame, queries: list[str]) -> dict:
    out = {}
    for q in queries:
        r = st[st.q == q]
        spend, orders = float(r.Spend.sum()), float(r["7 Day Total Orders (#)"].sum())
        out[q] = {"spend": round(spend, 2), "orders": int(orders), "cost_per_order": round(spend / orders, 2) if orders else None}
    return out


def targeting(df: pd.DataFrame, campaigns: list[str], queries: list[str]) -> dict:
    t = _numeric(df[df["Campaign Name"].isin(campaigns)], ["Spend", "7 Day Total Orders (#)", "Clicks"])
    t["k"] = t.Targeting.astype(str).str.lower().str.strip()
    in_account = {q: sorted(t[t.k == q]["Match Type"].astype(str).unique().tolist()) for q in queries}
    top = t.sort_values("Spend", ascending=False).head(15)
    return {"in_account": in_account,
            "top_targets": [{"target": r.Targeting, "match": r["Match Type"], "spend": round(r.Spend, 2),
                             "orders": int(r["7 Day Total Orders (#)"]),
                             "tos_share": None if pd.isna(r["Top-of-search Impression Share"]) else round(100 * num(r["Top-of-search Impression Share"]), 1)}
                            for _, r in top.iterrows()]}


def placement(df: pd.DataFrame, campaigns: list[str]) -> dict:
    p = _numeric(df[df["Campaign Name"].isin(campaigns)], ST_NUM)
    agg = {"spend": ("Spend", "sum"), "clicks": ("Clicks", "sum"), "orders": ("7 Day Total Orders (#)", "sum"),
           "sales": ("7 Day Total Sales", "sum")}
    g = _rates(p.groupby("Placement").agg(**agg))
    g["share"] = 100 * g.spend / g.spend.sum()
    tos = p[p.Placement.str.contains("Top of Search", case=False, na=False)]
    c = _rates(tos.groupby("Campaign Name").agg(**agg))
    return {"by_placement": _records(g.sort_values("spend", ascending=False).reset_index()),
            "top_of_search_by_campaign": _records(c.sort_values("spend", ascending=False).reset_index())}


def rank_weekly(asin: str, marketplace: str, since: str) -> list[dict]:
    """Weekly median sales rank from Keepa (cached responses cost nothing)."""
    key = os.environ.get("KEEPA_KEY")
    if not key:
        raise RuntimeError("no KEEPA_KEY set; sales-rank history skipped")
    url = (f"https://api.keepa.com/product?key={key}&domain={KEEPA_DOMAIN[marketplace]}&asin={asin}"
           f"&history=1&days=400")
    with urllib.request.urlopen(url, timeout=60) as r:
        raw = r.read()
    if raw[:2] == b"\x1f\x8b":
        import gzip
        raw = gzip.decompress(raw)
    resp = json.loads(raw)
    prod = next((p for p in resp.get("products") or [] if p.get("asin") == asin), None)
    csv = (prod or {}).get("csv") or []
    ranks = csv[3] if len(csv) > 3 and csv[3] else []
    pts = {dt.datetime.utcfromtimestamp((ranks[i] + KEEPA_EPOCH_MIN) * 60): ranks[i + 1]
           for i in range(0, len(ranks), 2) if ranks[i + 1] > 0}
    s = pd.Series(pts).sort_index()
    s = s[s.index >= since]
    w = s.resample("W-SAT").median()
    return [{"week_end": str(i.date()), "rank": int(v)} for i, v in w.items() if not pd.isna(v)]


def _rates(g: pd.DataFrame) -> pd.DataFrame:
    g = g.copy()
    g["cpc"] = g.spend / g.clicks.replace(0, float("nan"))
    g["cvr"] = 100 * g.orders / g.clicks.replace(0, float("nan"))
    g["cost_per_order"] = g.spend / g.orders.replace(0, float("nan"))
    g["acos"] = 100 * g.spend / g.sales.replace(0, float("nan"))
    return g


def _records(df: pd.DataFrame) -> list[dict]:
    return [{k: (None if (isinstance(v, float) and pd.isna(v)) else (round(v, 2) if isinstance(v, float) else v))
             for k, v in r.items()} for r in df.to_dict("records")]


# --- main ----------------------------------------------------------------------------------------

def build(uploads: Path, asin: str, cfg: dict, periods: list[dict], marketplace: str = "us",
          campaign_match: str | None = None, sqp_weeks: int = 3, with_rank: bool = True) -> dict:
    up = load_uploads(uploads)
    data: dict = {"asin": asin, "marketplace": marketplace, "generated": str(dt.date.today()),
                  "files": {"sqp_weeks": len(up["sqp"]), "business": sorted(up["business"]),
                            "reports": sorted(k for k in up if k not in ("sqp", "business"))},
                  "config": cfg}
    business = business_rows(up["business"], asin) if up["business"] else {}
    data["business"] = business
    campaigns: list[str] = []
    if "advertised" in up:
        adv, data["advertised"] = advertised(up["advertised"], asin)
        campaigns = data["advertised"]["campaigns"]
        if campaign_match:  # e.g. only the advent campaigns, not every campaign that ever showed the ASIN
            campaigns = [c for c in campaigns if campaign_match.lower() in c.lower()]
            data["advertised"]["campaigns"] = campaigns
        data["periods"] = period_rows(adv, business, periods)
    if "campaigns" in up:
        data["campaigns"] = campaign_rows(up["campaigns"], campaigns, campaign_match)
    if up["sqp"]:
        data["sqp"] = sqp(up["sqp"], sqp_weeks, cfg)
    queries = [r["query"] for r in data.get("sqp", {}).get("rows", [])]
    if "search_term" in up and campaigns:
        st, data["search_terms"] = search_terms(up["search_term"], campaigns, cfg)
        data["query_spend"] = query_spend(st, queries)
    if "targeting" in up and campaigns:
        data["targeting"] = targeting(up["targeting"], campaigns, queries)
    if "placement" in up and campaigns:
        data["placement"] = placement(up["placement"], campaigns)
    if with_rank and data.get("advertised", {}).get("date_range"):
        start = (dt.date.fromisoformat(data["advertised"]["date_range"][0]) - dt.timedelta(days=14)).isoformat()
        try:
            data["rank_weekly"] = rank_weekly(asin, marketplace, start)
        except Exception as e:  # keep the audit going without the rank history
            data["rank_weekly_error"] = str(e)
    return data


def _words(s: str | None) -> list[str]:
    return [w.strip().lower() for w in (s or "").split(",") if w.strip()]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("run", type=Path)
    ap.add_argument("--uploads", type=Path, required=True)
    ap.add_argument("--asin", required=True)
    ap.add_argument("--marketplace", default="us")
    ap.add_argument("--brand", required=True, help="brand name as shoppers search it, e.g. W7")
    ap.add_argument("--brand-terms", help="extra own-brand words, comma separated (product line names)")
    ap.add_argument("--rivals", default="", help="rival brand words, comma separated")
    ap.add_argument("--category-words", default="", help="words that mark a search as in-category")
    ap.add_argument("--off-target", default="", help="words that mark a search as a different product")
    ap.add_argument("--campaign-match", help="only use campaigns whose name contains this (e.g. ADVENT)")
    ap.add_argument("--period", action="append", default=[],
                    help='"label|YYYY-MM-DD|YYYY-MM-DD|business report file name" (repeatable)')
    ap.add_argument("--sqp-weeks", type=int, default=3)
    ap.add_argument("--no-rank", action="store_true", help="skip Keepa sales-rank history (needs KEEPA_KEY)")
    args = ap.parse_args()
    cfg = {"brand_terms": _words(args.brand) + _words(args.brand_terms), "rivals": _words(args.rivals),
           "category_words": _words(args.category_words), "off_target": _words(args.off_target)}
    periods = []
    for p in args.period:
        label, start, end, file = p.split("|")
        periods.append({"label": label, "start": start, "end": end, "file": file})
    args.run.mkdir(parents=True, exist_ok=True)
    data = build(args.uploads, args.asin, cfg, periods, args.marketplace, args.campaign_match, args.sqp_weeks,
                 not args.no_rank)
    out = write_json(args.run / "internal_audit.json", data)
    st = data.get("search_terms", {}).get("total")
    print(f"✓ {out}")
    if st:
        print(f"  SP search-term spend ${st['spend']:,.0f}, {st['orders']:.0f} orders")
    if data.get("sqp"):
        print(f"  Search Query Performance: {len(data['sqp']['rows'])} searches over {len(data['sqp']['weeks'])} weeks")


if __name__ == "__main__":
    main()
