"""Print an audit page to an A4 PDF (for attaching to the follow-up email).

    python -m analyse.pdf runs/<slug>

Uses the headless Chromium that ships with the environment. Collapsed "What we saw" sections are opened
and the light theme is forced so the PDF matches the brand colours.
"""
from __future__ import annotations

import glob
import os
import subprocess
import sys
from pathlib import Path

from collectors.common import read_json

PRINT_CSS = ("@page{size:A4;margin:0} html,body{background:#f6f1e7;-webkit-print-color-adjust:exact;"
             "print-color-adjust:exact} .page{padding-block:14mm!important;gap:36px!important} "
             ".point,.hero-card,.stat,tr{break-inside:avoid} h2,h3{break-after:avoid}")


def chromium() -> str:
    found = os.environ.get("CHROMIUM") or next(iter(sorted(glob.glob("/opt/pw-browsers/chromium-*/chrome-linux/chrome"))), None)
    if not found:
        raise SystemExit("No Chromium found; set CHROMIUM to a Chrome/Chromium binary")
    return found


def to_pdf(run: Path) -> Path:
    d = read_json(run / "dataset.json", {})
    brand = (d.get("prospect") or {}).get("brand") or run.name
    if (d.get("focus") or {}).get("scope") == "asin":  # one product: name the file after it and the market
        brand = f'{brand}-{d["focus"]["seed"]}-{d["prospect"]["marketplace"].upper()}'
    page = (run / "audit.html").read_text()
    wrapper = run / "print.html"
    wrapper.write_text('<!doctype html><html data-theme="light"><head><meta charset="utf-8">'
                       f'<meta name="viewport" content="width=device-width,initial-scale=1"><style>{PRINT_CSS}</style>'
                       f'</head><body>{page}<script>document.querySelectorAll("details").forEach(d=>d.open=true)'
                       '</script></body></html>')
    out = run / f"{brand.replace(' ', '-')}-Amazon-Audit.pdf"
    subprocess.run([chromium(), "--headless=new", "--no-sandbox", "--disable-gpu", "--no-pdf-header-footer",
                    "--virtual-time-budget=5000", f"--print-to-pdf={out}", wrapper.resolve().as_uri()],
                   check=True, capture_output=True, timeout=120)
    wrapper.unlink()
    return out


if __name__ == "__main__":
    print(f"✓ {to_pdf(Path(sys.argv[1]))}")
