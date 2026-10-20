"""Apollo.io: people currently working at the brand, its parent company or its Amazon seller, with
their LinkedIn profile and (for the top few) a verified work email.

People search is free; revealing an email costs one Apollo credit, so only the best few are enriched.
Docs: https://docs.apollo.io/reference/people-api-search , /reference/people-enrichment ,
      /reference/organization-search
"""
from __future__ import annotations

import re

from .common import Budget, env, http_json, proxy_auth

BASE = "https://api.apollo.io/api/v1"
TITLES = ["founder", "co-founder", "owner", "ceo", "managing director", "director", "head of ecommerce",
          "ecommerce", "amazon", "marketplace", "digital", "head of marketing", "marketing", "brand manager"]
# Lower rank = better person to email about Amazon.
RANKS = [(1, ("founder", "owner", "ceo", "chief executive", "managing director", "md")),
         (2, ("amazon", "marketplace", "ecommerce", "e-commerce", "digital", "online")),
         (3, ("marketing", "brand", "growth", "commercial", "sales")),
         (4, ("director", "head", "manager", "lead"))]


def configured() -> bool:
    return bool(env("APOLLO_API_KEY")) or proxy_auth("apollo")


def _headers() -> dict:
    headers = {"Content-Type": "application/json", "Cache-Control": "no-cache"}
    if env("APOLLO_API_KEY"):
        headers["x-api-key"] = env("APOLLO_API_KEY")
    return headers


def rank(title: str | None) -> int:
    t = (title or "").lower()
    return next((r for r, words in RANKS if any(re.search(rf"\b{re.escape(w)}\b", t) for w in words)), 5)


def _norm(name: str | None) -> str:
    return re.sub(r"\b(ltd|limited|llc|llp|inc|plc|co)\b|[^a-z0-9]", "", (name or "").lower())


def find_orgs(name: str, budget: Budget) -> list[dict]:
    budget.spend("apollo_search")
    resp = http_json("POST", f"{BASE}/mixed_companies/search", headers=_headers(),
                     body={"q_organization_name": name, "page": 1, "per_page": 5})
    return parse_orgs(resp, name)


def parse_orgs(resp: dict, name: str) -> list[dict]:
    """Exact-name matches only: a near miss (e.g. a dissolved namesake) is worse than nothing."""
    out = []
    for o in (resp.get("organizations") or []) + (resp.get("accounts") or []):
        if _norm(o.get("name")) == _norm(name):
            out.append({"id": o.get("id") or o.get("organization_id"), "name": o.get("name"),
                        "domain": o.get("primary_domain") or o.get("website_url"), "linkedin": o.get("linkedin_url")})
    return out


def search_people(budget: Budget, domains: list[str] | None = None, org_ids: list[str] | None = None,
                  per_page: int = 25) -> list[dict]:
    body = {"person_titles": TITLES, "include_similar_titles": True, "page": 1, "per_page": per_page}
    if domains:
        body["q_organization_domains_list"] = domains
    if org_ids:
        body["organization_ids"] = org_ids
    budget.spend("apollo_search")
    resp = http_json("POST", f"{BASE}/mixed_people/api_search", headers=_headers(), body=body)
    return parse_people(resp)


def parse_people(resp: dict) -> list[dict]:
    out = []
    for p in (resp.get("people") or []) + (resp.get("contacts") or []):
        org = p.get("organization") or {}
        name = p.get("name") or " ".join(x for x in (p.get("first_name"), p.get("last_name") or p.get("last_name_obfuscated")) if x)
        out.append({"id": p.get("id"), "name": name, "title": p.get("title"),
                    "organisation": org.get("name") or p.get("organization_name"),
                    "linkedin": p.get("linkedin_url"), "email": p.get("email"),
                    "email_status": p.get("email_status"), "rank": rank(p.get("title"))})
    return sorted(out, key=lambda r: r["rank"])


def enrich(person_id: str, budget: Budget) -> dict:
    """Reveal a verified work email for one person (1 Apollo credit)."""
    budget.spend("apollo_credits")
    resp = http_json("POST", f"{BASE}/people/match", headers=_headers(),
                     body={"id": person_id, "reveal_personal_emails": False, "reveal_phone_number": False})
    p = resp.get("person") or {}
    return {"name": p.get("name"), "linkedin": p.get("linkedin_url"), "email": p.get("email"),
            "email_status": p.get("email_status"), "title": p.get("title")}


def people_for(orgs: list[dict], domain: str | None, budget: Budget, enrich_top: int = 3) -> dict:
    """Current staff across the brand's domain and every organisation name found, best roles first."""
    found, matched = {}, []
    if domain:
        for p in search_people(budget, domains=[domain]):
            found.setdefault(p["id"] or p["name"], {**p, "via": domain})
    for org in orgs:
        for o in find_orgs(org["name"], budget):
            matched.append({**o, "kind": org["kind"]})
            if o["id"]:
                for p in search_people(budget, org_ids=[o["id"]]):
                    found.setdefault(p["id"] or p["name"], {**p, "via": f'{org["kind"]}: {o["name"]}'})
    people = sorted(found.values(), key=lambda r: r["rank"])
    for p in people[:enrich_top]:
        if p.get("id") and not (p.get("email") and p.get("email_status") == "verified"):
            info = enrich(p["id"], budget)
            p.update({k: v for k, v in info.items() if v})
    return {"organisations_matched": matched, "people": people}
