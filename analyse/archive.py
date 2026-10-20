"""Save a finished audit into audits/<slug>/ so it's kept in the repo (runs/ is temporary and gitignored).

    python -m analyse.archive runs/<slug> [--link https://claude.ai/artifact/...]

Copies the deliverables (not the raw API dumps), writes a README for the folder and adds a row to
audits/INDEX.md. Commit and push afterwards; the script prints the commands.
"""
from __future__ import annotations

import argparse
import re
import shutil
from pathlib import Path

from collectors.common import ROOT, read_json

AUDITS_DIR = ROOT / "audits"
DELIVERABLES = ["email.md", "audit.html", "findings.json", "evidence.md", "dataset.json", "input.json", "job_ad.txt",
                "contacts.json"]
INDEX_HEADER = ("# Audits\n\n| Date | Brand | Marketplace | Est. revenue /mo | Audit page | Folder |\n"
                "|---|---|---|---|---|---|\n")


def email_points(email: str) -> list[str]:
    return [re.sub(r"\*\*", "", m) for m in re.findall(r"^\s*\d\.\s+(.+)$", email, re.M)]


def contact_lines(c: dict) -> list[str]:
    if not c or not c.get("website"):
        return ["- No contacts collected (pass --website)."]
    lines = [f"- **Recommended To:** {c.get('recommended_to') or '–'}"]
    lines += [f"- {e['email']} ({e['type']}, from {e['source']})" for e in c.get("emails", [])]
    lines += [f"- {p['name']}: {p['role']} (from {p['source']})" for p in c.get("people", [])]
    lines += [f"- Suggested: {s['email']} for {s['name']} ({s['status']})" for s in c.get("suggested", [])]
    co = c.get("company") or {}
    if co.get("name") or co.get("number"):
        lines.append(f"- Company: {co.get('name') or '–'} {('(' + co['number'] + ')') if co.get('number') else ''}".rstrip())
    if c.get("only_generic"):
        lines.append("- Only shared inboxes are published; find the founder or ecommerce lead on LinkedIn.")
    return lines


def archive(run: Path, link: str | None = None, audits_dir: Path = AUDITS_DIR) -> Path:
    if not (run / "dataset.json").exists():
        raise SystemExit(f"{run} has no dataset.json; run the audit first")
    dest = audits_dir / run.name
    dest.mkdir(parents=True, exist_ok=True)
    for name in DELIVERABLES:
        if (run / name).exists():
            shutil.copy2(run / name, dest / name)

    d = read_json(run / "dataset.json")
    p, focus = d["prospect"], d.get("focus") or {}
    email = (run / "email.md").read_text() if (run / "email.md").exists() else ""
    gaps = [f"{s['step']}: {s.get('reason') or s.get('error')}"
            for s in (d.get("coverage") or {}).get("steps", []) if s["status"] != "ok"]
    revenue = focus.get("est_monthly_revenue")
    share = focus.get("hero_revenue_share")
    lines = [
        f"# {p['brand']} ({p['domain']})",
        "",
        f"- **Audited:** {d['generated']}",
        f"- **Input:** {p.get('input')}",
        f"- **Audit page:** {link or 'not published'}",
        f"- **Catalogue:** {focus.get('total_asins', '–')} ASINs, {focus.get('live_asins', '–')} live; "
        f"{focus.get('hero_families', '–')} best-seller families make {round(share * 100) if share else '–'}% "
        f"of ~{p['currency']}{revenue:,.0f}/mo" if revenue else "- **Catalogue:** –",
        "",
        "## Email points",
        "",
        *[f"{i}. {pt}" for i, pt in enumerate(email_points(email), 1)],
        "",
        "## Contacts",
        "",
        *contact_lines(read_json(run / "contacts.json", {})),
        "",
        "## Data gaps",
        "",
        *([f"- {g}" for g in gaps] or ["- none"]),
        "",
        "Files: `email.md` (outreach script), `audit.html` (detailed report), `evidence.md` (sources), "
        "`findings.json`, `dataset.json`.",
        "",
    ]
    (dest / "README.md").write_text("\n".join(lines))

    index = audits_dir / "INDEX.md"
    text = index.read_text() if index.exists() else INDEX_HEADER
    row = (f"| {d['generated']} | {p['brand']} | {p['domain']} | "
           f"{p['currency']}{revenue:,.0f} | {link or '–'} | [{run.name}]({run.name}/) |" if revenue else
           f"| {d['generated']} | {p['brand']} | {p['domain']} | – | {link or '–'} | [{run.name}]({run.name}/) |")
    rows = [r for r in text.splitlines() if f"[{run.name}]" not in r]  # re-archiving replaces the row
    index.write_text("\n".join(rows).rstrip("\n") + "\n" + row + "\n")
    return dest


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("run", type=Path)
    ap.add_argument("--link", help="published audit page URL")
    args = ap.parse_args()
    dest = archive(args.run, args.link)
    brand = read_json(args.run / "dataset.json")["prospect"]
    print(f"✓ saved {dest.relative_to(ROOT)}")
    print(f'  git add audits && git commit -m "Audit: {brand["brand"]} ({brand["marketplace"]})" && git push')


if __name__ == "__main__":
    main()
