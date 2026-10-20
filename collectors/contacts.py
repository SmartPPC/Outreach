"""Find the most direct published contacts for a brand from its own website.

Only reports what the brand publishes (emails, founder/director names, company details). Suggested
addresses are produced only when a published personal address reveals the format, and are always
marked unverified. Contacts stay out of audit.html, which is shared with the prospect.
"""
from __future__ import annotations

import re
import urllib.parse

from . import dataforseo
from .common import Budget

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
COMPANY_NO_RE = re.compile(r"(?:company|registration|registered)\s*(?:no\.?|number|#)\s*[:.]?\s*([A-Z]{0,2}\d{6,8})", re.I)
COMPANY_NAME_RE = re.compile(r"\b((?:[A-Z][A-Za-z0-9&'.\-]* ){1,5}(?:Ltd|Limited|LLP|LLC|Inc|PLC))\b")  # one line only
NAME = r"([A-Z][a-z]+(?:[ '-][A-Z][a-z]+){1,2})"   # case-sensitive: "Jane Smith", never "SHIP RIGHTS"
ROLE = r"(?i:co-?founder|founder|ceo|chief executive|managing director|director|owner)"
PERSON_RES = [
    re.compile(rf"{NAME}\s*[,\-–|(]\s*(?i:our\s+|the\s+)?({ROLE})"),
    re.compile(rf"\b({ROLE})\s*(?i:and\s+\w+\s*)?[,:\-–]?\s*{NAME}"),
    re.compile(rf"(?i:founded by)\s+{NAME}"),
]
BIZDEV = ("wholesale", "trade", "partner", "partnerships", "press", "pr", "marketing", "business", "collab",
          "affiliates", "sales", "stockist", "retail", "amazon", "ecommerce")
GENERIC = ("hello", "info", "support", "help", "customerservice", "customer", "care", "contact", "enquiries",
           "orders", "admin", "team", "service", "returns", "privacy", "dpo", "legal", "noreply", "no-reply",
           "complaints", "vip", "feedback", "billing", "accounts", "jobs", "careers", "unsubscribe", "shop")
CONTACT_PATHS = ["/", "/pages/contact", "/contact", "/contact-us", "/pages/contact-us", "/pages/about",
                 "/pages/about-us", "/about", "/pages/wholesale", "/policies/terms-of-service",
                 "/policies/privacy-policy"]
GENERIC_PREFERRED = ("hello", "info", "contact", "enquiries", "team", "admin")  # read by staff, unlike complaints@/legal@
NOT_NAMES = {"Free Worldwide", "Happy Customers", "Our Story", "Terms Of", "Privacy Policy", "Read More"}


def classify(email: str, people: dict | None = None) -> str:
    """personal = matches a named person; business = bizdev/trade inbox; generic = customer-facing;
    role = any other shared inbox."""
    local = email.split("@")[0].lower()
    for name in people or {}:
        parts = re.sub(r"[^a-z ]", "", name.lower()).split()
        if parts and (parts[0] in local or parts[-1] in local):
            return "personal"
    if any(local == g or local.startswith(g) for g in GENERIC):
        return "generic"
    if any(local == b or local.startswith(b) for b in BIZDEV):
        return "business"
    if re.fullmatch(r"[a-z]+\.[a-z]+", local):
        return "personal"  # first.last style even without a known name
    return "role"


def extract(text: str, domain: str | None = None) -> dict:
    emails = {e.strip(".").lower() for e in EMAIL_RE.findall(text)}
    emails = {e for e in emails if not e.endswith((".png", ".jpg", ".webp", ".gif")) and "example." not in e}
    people = {}
    for rx in PERSON_RES:
        for m in rx.finditer(text):
            groups = m.groups()
            name = next((g for g in groups if g and g[0].isupper() and " " in g and not re.fullmatch(ROLE, g, re.I)), None)
            role = next((g for g in groups if g and re.fullmatch(ROLE, g, re.I)), "founder")
            if name and name not in NOT_NAMES and len(name) <= 40:
                people.setdefault(name, role.lower())
    company_no = COMPANY_NO_RE.search(text)
    company_name = COMPANY_NAME_RE.search(text)
    return {"emails": sorted(emails), "people": people,
            "company_number": company_no.group(1) if company_no else None,
            "company_name": company_name.group(1).strip() if company_name else None}


def email_format(emails: list[str], people: dict, domain: str) -> str | None:
    """Infer the address format only from a published personal address that matches a known name."""
    for e in emails:
        local, _, dom = e.partition("@")
        if dom != domain or classify(e, people) != "personal":
            continue
        for name in people:
            first, last = name.lower().split()[0], name.lower().split()[-1]
            for fmt, value in (("{first}.{last}", f"{first}.{last}"), ("{first}{last}", f"{first}{last}"),
                               ("{f}{last}", f"{first[0]}{last}"), ("{first}", first)):
                if local == value:
                    return fmt
    return None


def suggest(people: dict, fmt: str | None, domain: str, known: set[str]) -> list[dict]:
    if not fmt:
        return []
    out = []
    for name in people:
        parts = re.sub(r"[^a-z ]", "", name.lower()).split()
        first, last = parts[0], parts[-1]
        addr = fmt.format(first=first, last=last, f=first[0]) + "@" + domain
        if addr not in known:
            out.append({"name": name, "email": addr, "status": "unverified guess, check before sending"})
    return out


def _generic_rank(email: str) -> int:
    local = email.split("@")[0].lower()
    return next((i for i, g in enumerate(GENERIC_PREFERRED) if local.startswith(g)), len(GENERIC_PREFERRED))


def site_candidates(brand: str, website: str | None) -> list[str]:
    if website:
        return [website if website.startswith("http") else f"https://{website}"]
    slug = re.sub(r"[^a-z0-9]", "", brand.lower())
    return [f"https://{slug}.{tld}" for tld in ("co.uk", "com", "co")]


def find_contacts(brand: str, budget: Budget, website: str | None = None, max_pages: int = 8) -> dict:
    root = None
    for cand in site_candidates(brand, website):
        page = dataforseo.page_text(cand.rstrip("/") + "/", budget)  # the parser needs a path on bare domains
        if page and page["text"].strip():
            root, home = cand.rstrip("/"), page
            break
    if not root:
        return {"website": None, "note": "brand website not found; pass --website"}
    domain = urllib.parse.urlsplit(root).netloc.removeprefix("www.")

    pages = {root + "/": home}
    extra = [l["url"] for l in home["links"]
             if re.search(r"contact|about|story|wholesale|trade|press", l["url"] + " " + l["text"], re.I)
             and domain in l["url"]]
    for url in list(dict.fromkeys([root + p for p in CONTACT_PATHS[1:]] + extra)):
        if len(pages) >= max_pages:
            break
        if url not in pages:
            page = dataforseo.page_text(url, budget)
            if page and page["text"].strip():
                pages[url] = page

    found_emails: dict[str, str] = {}
    people: dict[str, dict] = {}
    company = {"name": None, "number": None}
    for url, page in pages.items():
        x = extract(page["text"], domain)
        for e in x["emails"]:
            found_emails.setdefault(e, url)
        for name, role in x["people"].items():
            people.setdefault(name, {"role": role, "source": url})
        company["name"] = company["name"] or x["company_name"]
        company["number"] = company["number"] or x["company_number"]

    order = {"personal": 0, "business": 1, "role": 2, "generic": 3}
    emails = sorted(({"email": e, "type": classify(e, people), "source": src, "on_domain": e.endswith("@" + domain)}
                     for e, src in found_emails.items()),
                    key=lambda r: (not r["on_domain"], order[r["type"]], _generic_rank(r["email"]), r["email"]))
    fmt = email_format([e["email"] for e in emails], people, domain)
    best = next((e for e in emails if e["on_domain"]), emails[0] if emails else None)
    return {
        "website": root,
        "domain": domain,
        "pages_checked": list(pages),
        "emails": emails,
        "people": [{"name": n, **v} for n, v in people.items()],
        "company": company,
        "email_format": fmt,
        "suggested": suggest(people, fmt, domain, set(found_emails)),
        "recommended_to": best["email"] if best else None,
        "only_generic": bool(emails) and all(e["type"] in ("generic", "role") for e in emails if e["on_domain"]),
    }
