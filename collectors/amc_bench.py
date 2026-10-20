"""Build anonymised AMC category benchmarks from the AMC instances of accounts you manage.

Run monthly, not per prospect:
    python -m collectors.amc_bench --config amc_instances.json --start 2026-04-01 --end 2026-09-30

Per-instance raw results go to runs/.amc/ (gitignored). Only cross-instance medians are written to
benchmarks/amc_<category>.json, and a category with fewer than MIN_INSTANCES is flagged low_sample
so the skill phrases it as a softer hypothesis.

AMC reporting API: https://advertising.amazon.com/API/docs/en-us/guides/amazon-marketing-cloud/
(Endpoint paths below follow the workflowExecutions API; check them against the current docs for
your AMC instance type before the first run.)
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import re
import statistics
import time
import urllib.request
from pathlib import Path

from .common import MARKETPLACES, ROOT, RUNS_DIR, env, http_json, load_env, lwa_access_token, write_json

QUERIES_DIR = ROOT / "amc_queries"
BENCH_DIR = ROOT / "benchmarks"
RAW_DIR = RUNS_DIR / ".amc"
MIN_INSTANCES = 3
QUERIES = ["path_to_purchase", "new_to_brand", "repeat_rate", "ad_type_overlap"]


def _headers(inst: dict, token: str) -> dict:
    return {
        "Authorization": f"Bearer {token}",
        "Amazon-Advertising-API-ClientId": env("ADS_CLIENT_ID"),
        "Amazon-Advertising-API-AdvertiserId": inst["advertiser_id"],
        "Amazon-Advertising-API-MarketplaceId": MARKETPLACES[inst["marketplace"]]["marketplace_id"],
    }


def run_query(inst: dict, token: str, name: str, start: str, end: str, timeout_s: int = 3600) -> list[dict]:
    host = MARKETPLACES[inst["marketplace"]]["ads_host"]
    base = f"{host}/amc/reporting/{inst['instance_id']}/workflowExecutions"
    headers = _headers(inst, token)
    created = http_json("POST", base, headers=headers, cache=False, body={
        "workflow": {"workflowId": f"apa-{name}", "sqlQuery": (QUERIES_DIR / f"{name}.sql").read_text()},
        "timeWindowType": "EXPLICIT",
        "timeWindowStart": f"{start}T00:00:00",
        "timeWindowEnd": f"{end}T00:00:00",
        "outputFormat": "CSV",
    })
    exec_id = created["workflowExecutionId"]
    deadline = time.time() + timeout_s
    while True:
        status = http_json("GET", f"{base}/{exec_id}", headers=headers, cache=False)
        if status.get("status") == "SUCCEEDED":
            break
        if status.get("status") in {"FAILED", "REJECTED", "CANCELLED"} or time.time() > deadline:
            raise RuntimeError(f"AMC {name} on {inst['label']}: {status.get('status')} {status.get('statusReason')}")
        time.sleep(30)
    urls = http_json("GET", f"{base}/{exec_id}/downloadUrls", headers=headers, cache=False).get("downloadUrls") or []
    rows = []
    for url in urls:
        with urllib.request.urlopen(url, timeout=120) as resp:
            rows += list(csv.DictReader(io.StringIO(resp.read().decode())))
    return rows


def _f(v) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def metrics_from_results(results: dict[str, list[dict]]) -> dict:
    m: dict[str, float | None] = {}

    path = results.get("path_to_purchase") or []
    total = sum(_f(r["users"]) for r in path)
    if total:
        weight = {"0": 0, "1": 1, "2": 2, "3": 3, "4": 4, "5+": 5}
        m["avg_touches_before_purchase"] = sum(weight.get(r["touch_bucket"], 0) * _f(r["users"]) for r in path) / total
        m["share_3plus_touches"] = sum(_f(r["users"]) for r in path if r["touch_bucket"] in {"3", "4", "5+"}) / total

    ntb = (results.get("new_to_brand") or [{}])[0]
    if _f(ntb.get("purchases")):
        m["ntb_share"] = _f(ntb.get("ntb_purchases")) / _f(ntb["purchases"])

    rep = (results.get("repeat_rate") or [{}])[0]
    if _f(rep.get("buyers")):
        buyers = _f(rep["buyers"])
        m["repeat_rate"] = _f(rep.get("repeat_buyers")) / buyers
        m["repeat_60d_rate"] = _f(rep.get("repeat_60d")) / buyers
        m["avg_days_to_repeat"] = _f(rep.get("avg_days_to_repeat")) or None

    overlap = results.get("ad_type_overlap") or []
    sp_only = [r for r in overlap if (r["sp"], r["sb"], r["sd"]) == ("1", "0", "0")]
    multi = [r for r in overlap if r["sp"] == "1" and (r["sb"] == "1" or r["sd"] == "1")]

    def cvr(rows):
        exposed = sum(_f(r["exposed_users"]) for r in rows)
        return sum(_f(r["purchasers"]) for r in rows) / exposed if exposed else None

    if (a := cvr(sp_only)) and (b := cvr(multi)):
        m["multi_ad_type_cvr_lift"] = b / a
    return m


def aggregate(per_instance: list[dict]) -> dict:
    keys = sorted({k for inst in per_instance for k in inst["metrics"]})
    out = {}
    for k in keys:
        values = [inst["metrics"][k] for inst in per_instance if inst["metrics"].get(k) is not None]
        if values:
            out[k] = {"median": statistics.median(values), "min": min(values), "max": max(values), "n": len(values)}
    return out


def main() -> None:
    load_env()
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=str(ROOT / "amc_instances.json"))
    ap.add_argument("--start", required=True)
    ap.add_argument("--end", required=True)
    args = ap.parse_args()

    instances = json.loads(Path(args.config).read_text())
    tokens: dict[str, str] = {}
    by_category: dict[str, list[dict]] = {}
    RAW_DIR.mkdir(parents=True, exist_ok=True)

    for inst in instances:
        mp = inst["marketplace"]
        if mp not in tokens:
            tokens[mp] = lwa_access_token(env("ADS_REFRESH_TOKEN"), env("ADS_CLIENT_ID"), env("ADS_CLIENT_SECRET"),
                                          MARKETPLACES[mp]["ads_token_host"])
        results = {}
        for q in QUERIES:
            try:
                results[q] = run_query(inst, tokens[mp], q, args.start, args.end)
            except RuntimeError as e:
                print(f"  ! {e}")
        write_json(RAW_DIR / f"{inst['label']}.json", results)
        by_category.setdefault(inst["category"], []).append({"metrics": metrics_from_results(results)})
        print(f"{inst['label']}: {len(results)}/{len(QUERIES)} queries")

    BENCH_DIR.mkdir(exist_ok=True)
    for category, rows in by_category.items():
        slug = re.sub(r"[^a-z0-9]+", "-", category.lower()).strip("-")
        write_json(BENCH_DIR / f"amc_{slug}.json", {
            "category": category,
            "window": [args.start, args.end],
            "instances": len(rows),
            "low_sample": len(rows) < MIN_INSTANCES,
            "metrics": aggregate(rows),
        })
        print(f"benchmarks/amc_{slug}.json ({len(rows)} instances)")


if __name__ == "__main__":
    main()
