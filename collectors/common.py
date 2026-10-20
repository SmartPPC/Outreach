"""Shared plumbing for collectors: config, HTTP with caching, per-run budget, run-dir IO."""
from __future__ import annotations

import hashlib
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RUNS_DIR = ROOT / "runs"
CACHE_DIR = RUNS_DIR / ".cache"
CACHE_TTL_SECONDS = int(os.environ.get("APA_CACHE_TTL", 7 * 24 * 3600))

MARKETPLACES = {
    "us": {
        "domain": "amazon.com",
        "keepa_domain": 1,
        "js": "us",
        "d4s_location": 2840,
        "d4s_language": "en_US",
        "spapi_host": "https://sellingpartnerapi-na.amazon.com",
        "marketplace_id": "ATVPDKIKX0DER",
        "ads_host": "https://advertising-api.amazon.com",
        "ads_token_host": "https://api.amazon.com",
        "currency": "$",
    },
    "uk": {
        "domain": "amazon.co.uk",
        "keepa_domain": 2,
        "js": "uk",
        "d4s_location": 2826,
        "d4s_language": "en_GB",
        "spapi_host": "https://sellingpartnerapi-eu.amazon.com",
        "marketplace_id": "A1F83G8C2ARO7P",
        "ads_host": "https://advertising-api-eu.amazon.com",
        "ads_token_host": "https://api.amazon.co.uk",
        "currency": "£",
    },
}


def load_env(path: Path | None = None) -> None:
    """Minimal .env loader (no dependency). Existing env vars win."""
    path = path or ROOT / ".env"
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def env(name: str) -> str | None:
    value = os.environ.get(name)
    return value or None


class BudgetExceeded(RuntimeError):
    pass


@dataclass
class Budget:
    """Caps paid API usage per run. Units are provider-specific (Keepa tokens, request counts)."""

    limits: dict[str, float] = field(default_factory=lambda: {
        "keepa": float(os.environ.get("APA_BUDGET_KEEPA", 400)),
        "junglescout": float(os.environ.get("APA_BUDGET_JS", 60)),
        "dataforseo": float(os.environ.get("APA_BUDGET_D4S", 40)),
        "spapi": float(os.environ.get("APA_BUDGET_SPAPI", 60)),
        "ads": float(os.environ.get("APA_BUDGET_ADS", 20)),
    })
    used: dict[str, float] = field(default_factory=dict)

    def spend(self, provider: str, units: float = 1) -> None:
        total = self.used.get(provider, 0) + units
        if total > self.limits.get(provider, float("inf")):
            raise BudgetExceeded(f"{provider} budget {self.limits[provider]} exceeded")
        self.used[provider] = total

    def report(self) -> dict:
        return {p: {"used": self.used.get(p, 0), "limit": lim} for p, lim in self.limits.items()}


def _cache_key(method: str, url: str, body) -> Path:
    raw = json.dumps([method, url, body], sort_keys=True, default=str)
    return CACHE_DIR / (hashlib.sha1(raw.encode()).hexdigest() + ".json")


def http_json(
    method: str,
    url: str,
    *,
    headers: dict | None = None,
    params: dict | None = None,
    body=None,
    form: dict | None = None,
    cache: bool = True,
    retries: int = 3,
):
    """JSON request with an on-disk cache so reruns of the same prospect cost nothing."""
    if params:
        url = f"{url}{'&' if '?' in url else '?'}{urllib.parse.urlencode(params)}"
    cache_body = body if body is not None else form
    path = _cache_key(method, _strip_secrets(url), cache_body)
    if cache and path.exists() and time.time() - path.stat().st_mtime < CACHE_TTL_SECONDS:
        return json.loads(path.read_text())

    headers = dict(headers or {})
    data = None
    if body is not None:
        data = json.dumps(body).encode()
        headers.setdefault("Content-Type", "application/json")
    elif form is not None:
        data = urllib.parse.urlencode(form).encode()
        headers.setdefault("Content-Type", "application/x-www-form-urlencoded")
    headers.setdefault("Accept", "application/json")

    last_err = None
    for attempt in range(retries):
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=90) as resp:
                text = resp.read().decode()
                result = json.loads(text) if text else {}
                break
        except urllib.error.HTTPError as e:
            detail = e.read().decode(errors="replace")[:500]
            last_err = RuntimeError(f"{method} {_strip_secrets(url)} -> {e.code}: {detail}")
            if e.code in (429, 500, 502, 503, 504) and attempt < retries - 1:
                time.sleep(2 ** (attempt + 1))
                continue
            raise last_err from None
        except urllib.error.URLError as e:
            last_err = RuntimeError(f"{method} {_strip_secrets(url)} -> {e.reason}")
            if attempt < retries - 1:
                time.sleep(2 ** (attempt + 1))
                continue
            raise last_err from None
    else:
        raise last_err

    if cache:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(result))
    return result


def _strip_secrets(url: str) -> str:
    parts = urllib.parse.urlsplit(url)
    query = [(k, "***" if k.lower() in {"key", "api_key", "token"} else v)
             for k, v in urllib.parse.parse_qsl(parts.query)]
    return urllib.parse.urlunsplit(parts._replace(query=urllib.parse.urlencode(query)))


def lwa_access_token(refresh_token: str, client_id: str, client_secret: str,
                     token_host: str = "https://api.amazon.com") -> str:
    """Login-with-Amazon token exchange shared by SP-API and the Ads API."""
    resp = http_json("POST", f"{token_host}/auth/o2/token", cache=False, form={
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
        "client_id": client_id,
        "client_secret": client_secret,
    })
    return resp["access_token"]


def run_dir(slug: str) -> Path:
    path = RUNS_DIR / slug
    path.mkdir(parents=True, exist_ok=True)
    return path


def write_json(path: Path, data) -> Path:
    path.write_text(json.dumps(data, indent=2, default=str))
    return path


def read_json(path: Path, default=None):
    return json.loads(path.read_text()) if path.exists() else default


def chunks(items: list, size: int):
    for i in range(0, len(items), size):
        yield items[i:i + size]
