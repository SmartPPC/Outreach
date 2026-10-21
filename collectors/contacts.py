"""Find the most direct published contacts for a brand from its own website.

Only reports what the brand publishes (emails, founder/director names, company details). Suggested
addresses are produced only when a published personal address reveals the format, and are always
marked unverified. Contacts stay out of audit.html, which is shared with the prospect.
"""
from __future__ import annotations

import re
import urllib.parse

from . import apollo, dataforseo
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
PLATFORMS = re.compile(r"\b(shopify|google|amazon|paypal|klaviyo|stripe|meta|facebook|apple|microsoft|"
                       r"wix|squarespace|bigcommerce|woocommerce|automattic|trustpilot|yotpo|klarna)\b", re.I)
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
    company_name = next((m for m in COMPANY_NAME_RE.finditer(text)
                         if not PLATFORMS.search(m.group(1))), None)
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


# --- research beyond the brand's own site ------------------------------------------------------------

CH = "https://find-and-update.company-information.service.gov.uk"
CH_RESULT_RE = re.compile(r"(?P<number>[A-Z]{0,2}\d{6,8}) - (?P<status>Incorporated on [^\n]+|Dissolved on [^\n]+)\n"
                          r"(?P<address>[^\n]+)\n(?P<name>[^\n]+)")
OFFICER_RE = re.compile(r"^([A-Z][A-Z'\-]+(?: [A-Z][A-Z'\-]+)*, [A-Z][a-z]+(?: [A-Z][a-z]+)*)$", re.M)
LINKEDIN_ROLES = ["founder", "ecommerce", "amazon", "marketing"]


def org_names(brand: str, site_company: str | None, seller: str | None) -> list[dict]:
    """Every name the business trades or registers under: brand, website operator, Amazon seller."""
    out, seen = [], set()
    for name, kind in ((brand, "brand"), (site_company, "website operator"), (seller, "Amazon seller")):
        if name and "amazon" not in name.lower() and norm_key(name) not in seen:
            seen.add(norm_key(name))
            out.append({"name": name, "kind": kind})
    return out


def norm_key(name: str) -> str:
    return re.sub(r"\b(ltd|limited|llc|llp|inc|plc|co)\b|[^a-z0-9]", "", (name or "").lower())


def parse_ch_search(text: str, wanted: str) -> list[dict]:
    """Companies House search results that match the name exactly (ignoring Ltd/punctuation)."""
    out = []
    for m in CH_RESULT_RE.finditer(text):
        if norm_key(m["name"]) == norm_key(wanted):
            out.append({"number": m["number"], "name": m["name"].strip(), "address": m["address"].strip(),
                        "active": m["status"].startswith("Incorporated"), "status": m["status"].strip()})
    return out


def companies_house(name: str, budget: Budget) -> list[dict]:
    """Active UK companies with this exact name, with the people listed on their officers page."""
    page = dataforseo.page_text(f"{CH}/search/companies?q={urllib.parse.quote_plus(name)}", budget)
    matches = [c for c in parse_ch_search((page or {}).get("text", ""), name) if c["active"]]
    for c in matches[:2]:
        officers = dataforseo.page_text(f"{CH}/company/{c['number']}/officers", budget)
        c["people"] = sorted(set(OFFICER_RE.findall((officers or {}).get("text", ""))))
        c["url"] = f"{CH}/company/{c['number']}/officers"
    return matches[:2]


def linkedin_links(orgs: list[dict]) -> list[dict]:
    """One-click LinkedIn people searches; open them while logged in (LinkedIn needs a login)."""
    links = []
    for org in orgs:
        for role in LINKEDIN_ROLES:
            q = f'"{org["name"]}" {role}'
            links.append({"org": org["name"], "role": role,
                          "url": "https://www.linkedin.com/search/results/people/?keywords=" + urllib.parse.quote(q)})
    return links


def web_mentions(brand: str, marketplace: str, budget: Budget, domain: str | None) -> dict:
    """One Google search for the brand: picks up addresses published elsewhere (Instagram bios,
    press pages), plus any LinkedIn profiles that happen to show up."""
    results = dataforseo.google(f'"{brand}" email OR contact OR founder', marketplace, budget)
    emails, profiles = {}, []
    root = (domain or "").split(".")[0]
    for r in results:
        for e in EMAIL_RE.findall(r["title"] + " " + r["description"]):
            e = e.strip(".").lower()
            if root and root in e.split("@")[1]:
                emails.setdefault(e, r["url"])
        if "linkedin.com/in/" in r["url"]:
            name, _, headline = r["title"].partition(" - ")
            profiles.append({"name": name.strip(), "headline": headline.replace("| LinkedIn", "").strip(" -|"),
                             "url": r["url"]})
    return {"emails": emails, "linkedin_profiles": profiles}


def research(brand: str, marketplace: str, budget: Budget, contacts: dict, seller: str | None) -> dict:
    orgs = org_names(brand, (contacts.get("company") or {}).get("name"), seller)
    mentions = web_mentions(brand, marketplace, budget, contacts.get("domain"))
    known = {e["email"] for e in contacts.get("emails", [])}
    for e, src in mentions["emails"].items():
        if e not in known:
            contacts.setdefault("emails", []).append({"email": e, "type": classify(e, {}), "source": src,
                                                      "on_domain": False, "found_via": "web search"})
    order = {"personal": 0, "business": 1, "role": 2, "generic": 3}
    contacts["emails"] = sorted(contacts.get("emails", []), key=lambda r: (order[r["type"]], _generic_rank(r["email"])))
    best = next((e for e in contacts["emails"] if e["type"] in ("personal", "business")), None)
    if best:
        contacts["recommended_to"] = best["email"]
        contacts["only_generic"] = False
    uk = [o for o in orgs if o["kind"] != "brand" or marketplace == "uk"]
    contacts["organisations"] = orgs
    contacts["companies_house"] = [c for o in uk for c in companies_house(o["name"], budget)] if marketplace == "uk" else []
    contacts["linkedin_profiles"] = mentions["linkedin_profiles"]
    if apollo.configured():
        result = apollo.people_for(orgs, contacts.get("domain"), budget)
        contacts["apollo"] = result
        verified = next((p for p in result["people"] if p.get("email") and p.get("email_status") == "verified"), None)
        if verified:
            contacts["recommended_to"] = verified["email"]
            contacts["recommended_person"] = f'{verified["name"]}, {verified.get("title") or ""}'.strip(", ")
            contacts["only_generic"] = False
    contacts["linkedin_searches"] = linkedin_links(orgs)
    return contacts
