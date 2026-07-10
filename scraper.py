#!/usr/bin/env python3
"""
Customer Support Tracker — NWA · Stillwater · Ponca City
Scrapes 25+ sources, filters for customer support / admin / logistics /
banking / healthcare roles. Updates docs/jobs.json for GitHub Pages.
No email — dashboard only.
"""

import requests
from bs4 import BeautifulSoup
import json, os, hashlib, logging, re, time
from datetime import datetime

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

JOBS_FILE = "docs/jobs.json"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )
}

# ──────────────────────────────────────────────────────────────────────────────
# GEOGRAPHIC FILTER — city-level, state-aware
#
# Ambiguous city names (exist in many states) require an AR/OK qualifier.
# Unambiguous NWA names may match bare. Blank location passes (local pages).
# ──────────────────────────────────────────────────────────────────────────────

# Cities that are unique enough to match without a state
UNAMBIGUOUS_CITIES = [
    "bentonville", "bella vista", "siloam springs", "cave springs",
    "elm springs", "pea ridge", "tontitown", "prairie grove",
    "ponca city", "northwest arkansas", "nwa",
]

# Ambiguous names — must appear with AR/Arkansas (or OK/Oklahoma for Stillwater)
AMBIGUOUS_AR = [
    "rogers", "lowell", "centerton", "gravette", "highfill", "gentry",
    "fayetteville", "springdale", "west fork", "elkins", "greenland",
    "johnson", "farmington", "lincoln", "goshen",
    "benton county", "washington county",
]
AMBIGUOUS_OK = ["stillwater"]

_AR_PAT = re.compile(r"\b(ar|ark|arkansas)\b", re.I)
_OK_PAT = re.compile(r"\b(ok|okla|oklahoma)\b", re.I)


def is_valid_location(loc: str) -> bool:
    """True if blank/unknown, an unambiguous NWA city, or an ambiguous city
    qualified by the right state."""
    if not loc or not loc.strip():
        return True
    l = loc.lower()
    for city in UNAMBIGUOUS_CITIES:
        if city in l:
            return True
    if _AR_PAT.search(l):
        for city in AMBIGUOUS_AR:
            if city in l:
                return True
    if _OK_PAT.search(l):
        for city in AMBIGUOUS_OK:
            if city in l:
                return True
    return False


# Regex for pulling a location string out of surrounding card text
LOC_REGEX = re.compile(
    r"\b(Bentonville|Bella Vista|Siloam Springs|Cave Springs|Elm Springs|"
    r"Pea Ridge|Tontitown|Prairie Grove|Ponca City|Northwest Arkansas|NWA|"
    r"Rogers,?\s*(?:AR|Ark|Arkansas)|Lowell,?\s*(?:AR|Ark|Arkansas)|"
    r"Centerton,?\s*(?:AR|Ark|Arkansas)|Fayetteville,?\s*(?:AR|Ark|Arkansas)|"
    r"Springdale,?\s*(?:AR|Ark|Arkansas)|Stillwater,?\s*(?:OK|Okla|Oklahoma))\b",
    re.I
)

# ──────────────────────────────────────────────────────────────────────────────
# KEYWORD FILTERS
# ──────────────────────────────────────────────────────────────────────────────

INCLUDE_KEYWORDS = [
    # Customer-facing
    "customer service", "customer support", "customer care", "customer success",
    "customer relations", "customer experience", "client services", "client support",
    "client relations", "guest services",
    # Account / Admin
    "account coordinator", "account representative", "account specialist",
    "administrative assistant", "administrative coordinator", "administrative specialist",
    "administrative clerk", "office clerk",
    "office manager", "office coordinator", "office administrator",
    "executive assistant", "operations assistant", "operations coordinator",
    "operations specialist", "operations support", "operations analyst",
    "data entry", "data coordinator", "records coordinator", "records clerk",
    "receptionist", "front desk", "office support",
    "file clerk", "document specialist",
    "entry level", "entry-level",
    "support representative", "service representative",
    # Amy-specific strengths
    "cash handling", "cash management", "staff scheduling",
    "mediation", "conflict resolution", "event coordinator",
    "resident assistant", "resident advisor", "hall director",
    # Freight / Logistics
    "logistics coordinator", "logistics specialist", "logistics analyst",
    "logistics support", "supply chain coordinator", "supply chain analyst",
    "freight coordinator", "freight agent", "freight operations",
    "freight billing", "freight claims",
    "dispatch", "dispatcher", "load planner", "load coordinator",
    "shipment coordinator", "shipping coordinator", "transportation coordinator",
    "transportation analyst", "carrier relations", "carrier coordinator",
    "claims coordinator", "claims specialist", "billing coordinator",
    "billing specialist", "billing representative", "billing analyst",
    "pricing coordinator", "pricing analyst",
    # Banking / Finance
    "bank teller", "teller", "personal banker",
    "branch coordinator", "loan processor", "loan coordinator", "loan officer",
    "mortgage coordinator", "mortgage processor",
    "financial services", "financial representative", "financial specialist",
    "collections coordinator", "collections specialist", "collections representative",
    "compliance coordinator", "compliance specialist", "fraud analyst",
    "credit analyst", "banking associate", "banking specialist",
    # Call center / Communication
    "call center", "contact center", "help desk", "support specialist",
    "communications coordinator", "communications specialist",
    # General coordinator
    "program coordinator", "project coordinator",
    # Healthcare (non-clinical / front office)
    "patient access", "patient registration", "registrar",
    "patient services", "patient account", "patient representative",
    "patient coordinator", "scheduler", "scheduling coordinator",
    "unit secretary", "medical receptionist", "front office",
    "insurance verification", "prior authorization",
    "medical records", "health information", "admissions coordinator",
    "switchboard", "medical biller", "medical billing", "medical coder",
    "referral coordinator", "intake coordinator", "office assistant",
]

# Hard excludes — matched with word-boundary regex (see is_relevant)
HARD_EXCLUDE_KEYWORDS = [
    # Driving / physical labour
    "truck driver", "cdl driver", "forklift operator", "warehouse associate",
    "warehouse worker", "picker", "packer", "stocker", "dock worker",
    "material handler", "janitor", "custodian", "groundskeeper",
    # Clinical / medical (keep non-clinical healthcare roles)
    "registered nurse", "school nurse", "rn", "lpn", "cna", "aprn",
    "nurse", "nurse practitioner", "physician", "pharmacist",
    "physical therapist", "occupational therapist", "respiratory therapist",
    "paramedic", "emt", "phlebotomist", "phlebotomy",
    "radiology technologist", "radiologic", "sonographer", "sonography",
    "surgical tech", "surgery", "scrub tech", "anesthesia",
    "medical assistant", "clinical", "therapist", "dietitian", "dietician",
    "lab technician", "laboratory", "pathology",
    # Technical / Engineering
    "software engineer", "software developer", "web developer", "devops",
    "data scientist", "machine learning", "cybersecurity", "network engineer",
    "electrical engineer", "mechanical engineer", "civil engineer",
    "maintenance mechanic", "hvac technician", "electrician", "plumber",
    # Senior / management
    "vice president", "vp", "chief", "cto", "cfo", "coo",
    "regional manager", "district manager", "general manager",
    "senior manager", "store manager", "marketing manager",
    "product manager", "people manager", "hiring manager",
    "supervisor", "director",
    "account development",
    "dean",
    "911",
    # Academic
    "professor", "faculty", "instructor", "teacher",
    # Marketing noise
    "request a quote", "get a quote", "truck load quote",
    "full truckload", "less than truckload", "learn more",
    "view all", "see all jobs", "see open", "join our team",
]

# Precompile exclude patterns with word boundaries so "rn" ≠ "intern",
# "911" only matches as a standalone token, etc.
_EXCLUDE_PATTERNS = [
    (kw, re.compile(r"\b" + re.escape(kw) + r"\b", re.I))
    for kw in HARD_EXCLUDE_KEYWORDS
]


def is_relevant(title: str, extra: str = ""):
    combined = (title + " " + extra).lower()
    for kw, pat in _EXCLUDE_PATTERNS:
        if pat.search(combined):
            return False, f"excluded:{kw}"
    for kw in INCLUDE_KEYWORDS:
        if kw in combined:
            return True, kw
    return False, "no_match"


# ──────────────────────────────────────────────────────────────────────────────
# SOURCE REGISTRY  — single definition, drives scrapers AND dashboard
# ──────────────────────────────────────────────────────────────────────────────

ARVEST_URL = (
    "https://css-arvest-prd.inforcloudsuite.com/hcm/Jobs/form/"
    "JobBoard%28ARV,EXTERNAL%29.JobSearchCompositeForm"
    "?csk.JobBoard=EXTERNAL&csk.HROrganization=ARV"
    "&menu=JobsNavigationMenu.NewJobSearch"
)
BOFA_URL = (
    "https://careers.bankofamerica.com/en-us/job-search"
    "?ref=search&search=jobsByLocation&start=0&rows=25"
    "&searchstring=Fayetteville%2C+AR&searchstring=Bentonville%2C+AR"
    "&searchstring=Springdale%2C+AR&searchstring=Rogers%2C+AR"
)
CENTENNIAL_URL = (
    "https://recruiting.ultipro.com/CEN1011CENBA/JobBoard/"
    "51298f34-52ec-478d-bafa-d62ea4ea8c52/"
    "?q=&o=postedDateDesc&w=&wc=&we=&wpst=&f4=C67HCFOqPkiqxo0wXsSoig"
)
PHILLIPS66_URL = (
    "https://careers.phillips66.com/search/"
    "?createNewAlert=false&q=&locationsearch=ponca+city"
    "&optionsFacetsDD_dept=&optionsFacetsDD_department="
)
MERCY_URL = (
    "https://careers.mercy.net/jobs?page=1&location=Springdale,%20AR"
    "&woe=7&regionCode=US&stretchUnit=MILES&stretch=25"
    "&categories=Support%20Services"
)
MANA_URL = "https://careers-mana.icims.com/jobs/search?ss=1&searchRelation=keyword_all&searchCategory=8721"
NWMED_URL = "https://chsmedcareers.com/ar/northwest-medical-center-springdale"
WREG_URL  = "https://www.wregional.com/main/open-positions"
ADP_HEALTH_URL = (
    "https://workforcenow.adp.com/mascsr/default/mdf/recruitment/recruitment.html"
    "?cid=102b6d5e-4045-46b7-a5d5-3dfdcf08d104&ccId=19000101_000001&lang=en_US"
)
ADP_NWA_URL = (
    "https://workforcenow.adp.com/mascsr/default/mdf/recruitment/recruitment.html"
    "?cid=dd3989d6-a17f-4803-bdaa-54bf26faf499&ccId=19000101_000001&lang=en_US"
)

ALL_SOURCES = [
    # Freight & Logistics
    {"name": "ArcBest",       "url": "https://careers.arcb.com/careersmarketplace/OpenPositions/", "category": "freight"},
    {"name": "J.B. Hunt",     "url": "https://jbhunt.wd501.myworkdayjobs.com/Careers",             "category": "freight"},
    {"name": "Tyson Foods",   "url": "https://www.tysonfoods.com/careers",                         "category": "freight"},
    # Banking
    {"name": "Arvest Bank",         "url": ARVEST_URL,      "category": "banking"},
    {"name": "Simmons Bank",        "url": "https://simmonsbank.wd5.myworkdayjobs.com/SimmonsCareers", "category": "banking"},
    {"name": "First National Bank", "url": "https://recruiting.paylocity.com/recruiting/jobs/All/dcb49edc-c676-411b-8b7b-104a72fec402/The-First-National-Bank-of-Fort-Smith", "category": "banking"},
    {"name": "Regions Bank",        "url": "https://careers.regions.com/us/en/search-results",     "category": "banking"},
    {"name": "Bank of America",     "url": BOFA_URL,        "category": "banking"},
    {"name": "Centennial Bank",     "url": CENTENNIAL_URL,  "category": "banking"},
    # Corporate
    {"name": "Phillips 66 (Ponca City)", "url": PHILLIPS66_URL, "category": "corporate"},
    # Community
    {"name": "Rogers (City)",       "url": "https://www.rogersar.gov/Jobs.aspx",                   "category": "community"},
    {"name": "Bentonville (City)",  "url": "https://www.bentonvillear.com/1414/Employment-Opportunities", "category": "community"},
    {"name": "Fayetteville (City)", "url": "https://www.governmentjobs.com/careers/fayettevillear", "category": "community"},
    {"name": "Springdale (City)",   "url": "https://www.governmentjobs.com/careers/springdalear",  "category": "community"},
    {"name": "Bella Vista (City)",  "url": "https://recruiting.paylocity.com/recruiting/jobs/All/b1e8c19e-977f-41ec-89e7-a138ab6e72eb/City-of-Bella-Vista", "category": "community"},
    {"name": "Lowell (City)",       "url": "https://www.lowellarkansas.gov/jobs",                  "category": "community"},
    {"name": "City of Stillwater",  "url": "https://stillwaterok.gov/Jobs.aspx",                   "category": "community"},
    {"name": "City of Ponca City",  "url": "https://www.poncacityok.gov/Jobs.aspx",                "category": "community"},
    {"name": "Washington County AR","url": "https://www.washingtoncountyar.gov/government/departments-f-z/human-resources/job-postings", "category": "community"},
    {"name": "Springdale Library",  "url": "https://springdalelibrary.org/employment/",            "category": "community"},
    {"name": "UAF",                 "url": "https://uasys.wd5.myworkdayjobs.com/UAF_External_Career_Site", "category": "community"},
    {"name": "NWACC",               "url": "https://nwacc.wd1.myworkdayjobs.com/NWACC_External_Career_Site", "category": "community"},
    {"name": "JBU",                 "url": "https://www.jbu.edu/human-resources/staff-job-listings/", "category": "community"},
    {"name": "Oklahoma State Univ.","url": "https://jobs.okstate.edu/jobs/search/search-page-oklahoma-state", "category": "community"},
    {"name": "ADP (NWA)",           "url": ADP_NWA_URL,     "category": "community"},
    # Healthcare
    {"name": "MANA Clinics",              "url": MANA_URL,        "category": "healthcare"},
    {"name": "NW Medical Center (Springdale)", "url": NWMED_URL,  "category": "healthcare"},
    {"name": "Washington Regional",       "url": WREG_URL,        "category": "healthcare"},
    {"name": "UAMS (NWA campuses)",       "url": "https://uasys.wd5.myworkdayjobs.com/UAMS_All_Careers", "category": "healthcare"},
    {"name": "ADP (Healthcare)",          "url": ADP_HEALTH_URL,  "category": "healthcare"},
    {"name": "Mercy (Springdale)",        "url": MERCY_URL,       "category": "healthcare"},
    {"name": "AR Blue Cross",             "url": "https://arkbluecross.wd1.myworkdayjobs.com/ABCBS_External_Careers", "category": "healthcare"},
    # Misc — email a resume / check manually (no scraper)
    {"name": "Team 1 Supplier Services",  "url": "https://team1supplierservices.com/careers", "category": "misc", "note": "Email resume"},
    {"name": "RitePak",                   "url": "https://ritepak-us.com/services/",           "category": "misc", "note": "Email resume"},
    {"name": "ICS Pharmacy Services",     "url": "https://icsrx.com/careers/",                 "category": "misc", "note": "Email resume"},
    {"name": "Walmart HQ (all Bentonville)", "url": "https://careers.walmart.com/us/en/results?searchQuery=Bentonville", "category": "misc", "note": "Check manually"},
]

# ──────────────────────────────────────────────────────────────────────────────
# HELPERS
# ──────────────────────────────────────────────────────────────────────────────

def make_id(source, title, url=""):
    return hashlib.md5(f"{source}|{title}|{url}".encode()).hexdigest()[:12]


def make_job(source, title, url, platform, category="freight",
             location="", posted="", match_reason=""):
    return {
        "id":           make_id(source, title, url),
        "title":        title,
        "district":     source,
        "location":     location,
        "url":          url,
        "platform":     platform,
        "category":     category,
        "match_reason": match_reason,
        "posted_date":  posted,
        "first_seen":   datetime.now().strftime("%Y-%m-%d"),
    }


def load_jobs():
    if os.path.exists(JOBS_FILE):
        with open(JOBS_FILE) as f:
            return json.load(f)
    return {"last_updated": None, "jobs": [], "sources": []}


def save_jobs(data):
    os.makedirs("docs", exist_ok=True)
    with open(JOBS_FILE, "w") as f:
        json.dump(data, f, indent=2, default=str)
    log.info(f"Saved {len(data['jobs'])} jobs to {JOBS_FILE}")


def _safe(fn, *args, **kwargs):
    """Run a scraper; never let one failure kill the whole run."""
    name = getattr(fn, "__name__", str(fn))
    try:
        return fn(*args, **kwargs) or []
    except Exception as e:
        log.error(f"SCRAPER FAILED [{name}]: {e}")
        return []


def pw_get_soup(url, wait=4):
    try:
        from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout
    except ImportError:
        log.warning("Playwright not installed")
        return None
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(args=["--no-sandbox", "--disable-dev-shm-usage"])
            try:
                ctx  = browser.new_context(user_agent=HEADERS["User-Agent"])
                page = ctx.new_page()
                try:
                    page.goto(url, wait_until="networkidle", timeout=40000)
                except PWTimeout:
                    page.wait_for_timeout(5000)
                time.sleep(wait)
                html = page.content()
            finally:
                browser.close()
        return BeautifulSoup(html, "html.parser")
    except Exception as e:
        log.error(f"Playwright error on {url}: {e}")
        return None


def scrape_links(soup, name, base, platform, category, location="",
                 href_words=None, title_skip=None, use_loc_regex=False):
    """Generic link-based scraper core shared by simple HTML sources."""
    jobs, added = [], set()
    href_words = href_words or ["job", "career", "position", "posting", "opportunity", "req"]
    title_skip = title_skip or ["home", "about", "contact", "login", "search",
                                 "department", "more info", "apply now", "back to"]
    for a in soup.find_all("a", href=True):
        href  = a["href"]
        title = a.get_text(strip=True)
        if not title or len(title) < 5 or href in added:
            continue
        if not any(w in href.lower() for w in href_words):
            continue
        if any(x in title.lower() for x in title_skip):
            continue
        added.add(href)
        loc = location
        if use_loc_regex:
            parent = a.find_parent(["li", "div", "tr", "article"])
            if parent:
                m = LOC_REGEX.search(parent.get_text())
                if m:
                    loc = m.group(0)
            if not is_valid_location(loc):
                continue
        full_url   = href if href.startswith("http") else base + (href if href.startswith("/") else "/" + href)
        ok, reason = is_relevant(title)
        if ok:
            jobs.append(make_job(name, title, full_url, platform,
                                 category=category, location=loc, match_reason=reason))
    return jobs


# ──────────────────────────────────────────────────────────────────────────────
# WORKDAY  (shared paginated API scraper with facet support)
# ──────────────────────────────────────────────────────────────────────────────

WORKDAY_SOURCES = [
    {"name": "J.B. Hunt",    "category": "freight",
     "api_url":  "https://jbhunt.wd501.myworkdayjobs.com/wday/cxs/jbhunt/Careers/jobs",
     "base_url": "https://jbhunt.wd501.myworkdayjobs.com/en-US/Careers",
     "facets":   {}},
    {"name": "Simmons Bank", "category": "banking",
     "api_url":  "https://simmonsbank.wd5.myworkdayjobs.com/wday/cxs/simmonsbank/SimmonsCareers/jobs",
     "base_url": "https://simmonsbank.wd5.myworkdayjobs.com/en-US/SimmonsCareers",
     "facets":   {}},
    {"name": "UAF",          "category": "community",
     "api_url":  "https://uasys.wd5.myworkdayjobs.com/wday/cxs/uasys/UAF_External_Career_Site/jobs",
     "base_url": "https://uasys.wd5.myworkdayjobs.com/en-US/UAF_External_Career_Site",
     "facets":   {}},
    {"name": "NWACC",        "category": "community",
     "api_url":  "https://nwacc.wd1.myworkdayjobs.com/wday/cxs/nwacc/NWACC_External_Career_Site/jobs",
     "base_url": "https://nwacc.wd1.myworkdayjobs.com/en-US/NWACC_External_Career_Site",
     "facets":   {}},
    {"name": "UAMS (NWA campuses)", "category": "healthcare",
     "api_url":  "https://uasys.wd5.myworkdayjobs.com/wday/cxs/uasys/UAMS_All_Careers/jobs",
     "base_url": "https://uasys.wd5.myworkdayjobs.com/en-US/UAMS_All_Careers",
     "facets":   {
         "locations": [
             "fb151b68b7b21001aa26c48a77ea0000",
             "03a56c757fc5011324ffff44868b0000",
             "c19b12db3cc9100102f52f6f1e380000",
             "c19b12db3cc9100102d81980bf6e0000",
             "effe379d80291001029bcb3f776e0000",
             "22cd5b9376aa1001c99f1caedef10000",
             "17a66cdad98201f7890cfb48ca00e249",
             "17a66cdad98201c5d3537048ca008d49",
         ],
         "workerSubType": ["094c347f88cd01ead28a89ccfb003701"],
     }},
    {"name": "AR Blue Cross", "category": "healthcare",
     "api_url":  "https://arkbluecross.wd1.myworkdayjobs.com/wday/cxs/arkbluecross/ABCBS_External_Careers/jobs",
     "base_url": "https://arkbluecross.wd1.myworkdayjobs.com/en-US/ABCBS_External_Careers",
     "facets":   {
         "timeType": ["fd0286c9aab910f1cf592e736a6f3b91"],
         "locations": [
             "a108694a50b410f54ecf820bedc4ade3",
             "b6b454298e9a1000af1457f7576b0000",
             "a8fdf838a4780108b04e83f8fe0118f4",
         ],
     }},
]


def scrape_workday(source):
    name     = source["name"]
    api_url  = source["api_url"]
    category = source["category"]
    facets   = source.get("facets", {})
    jobs     = []
    offset   = 0
    limit    = 20
    api_hdrs = {**HEADERS, "Content-Type": "application/json", "Accept": "application/json"}
    while True:
        payload = {"limit": limit, "offset": offset, "searchText": "", "appliedFacets": facets}
        try:
            r    = requests.post(api_url, json=payload, headers=api_hdrs, timeout=25)
            data = r.json()
        except Exception as e:
            log.error(f"{name} Workday API error: {e}")
            break
        postings = data.get("jobPostings", [])
        total    = data.get("total", 0)
        if offset == 0:
            log.info(f"{name}: {total} total from Workday")
        if not postings:
            break
        for p in postings:
            title    = p.get("title", "").strip()
            loc      = p.get("locationsText", "") or p.get("primaryLocation", "")
            # Facet-filtered sources are already location-scoped
            if not facets and not is_valid_location(loc):
                continue
            ext_url  = p.get("externalPath", "")
            full_url = source["base_url"].rstrip("/") + ext_url if ext_url else source["base_url"]
            posted   = p.get("postedOn", "")
            ok, reason = is_relevant(title)
            if ok:
                jobs.append(make_job(name, title, full_url, "Workday",
                                     category=category, location=loc,
                                     posted=posted, match_reason=reason))
        offset += limit
        if offset >= total:
            break
        time.sleep(0.4)
    log.info(f"{name}: {len(jobs)} relevant jobs")
    return jobs


# ──────────────────────────────────────────────────────────────────────────────
# FREIGHT
# ──────────────────────────────────────────────────────────────────────────────

def scrape_arcbest():
    name = "ArcBest"
    url  = (
        "https://careers.arcb.com/careersmarketplace/OpenPositions/"
        "?10509=%5B36616%2C27818%2C27807%2C27810%2C36756%2C56719%2C28134"
        "%2C1738333%2C36692%2C36941%2C36950%5D&10509_format=3533"
        "&10508=8400047&10508_format=3532&listFilterMode=1&jobRecordsPerPage=6&"
    )
    soup = pw_get_soup(url, wait=5)
    if not soup:
        return []
    jobs = scrape_links(
        soup, name, "https://careers.arcb.com", "CareersMarketplace", "freight",
        location="Fort Smith, AR",
        href_words=["jobdetail", "openposition", "position", "req", "careers.arcb", "job"],
    )
    log.info(f"{name}: {len(jobs)} jobs")
    return jobs


def scrape_tyson():
    name = "Tyson Foods"
    jobs = []
    # Paginate the API and filter by location as we go
    start, num = 0, 100
    while start < 1000:   # hard cap: 10 pages
        api_url = (f"https://careers.tysonfoods.com/api/apply/v2/jobs"
                   f"?domain=tysonfoods.com&start={start}&num={num}&sort_by=relevance")
        try:
            r    = requests.get(api_url, headers=HEADERS, timeout=20)
            data = r.json()
        except Exception as e:
            log.warning(f"{name} API: {e}")
            break
        positions = data.get("positions", [])
        if not positions:
            break
        for item in positions:
            title  = item.get("name", "").strip()
            loc    = item.get("location", {}).get("name", "") if isinstance(item.get("location"), dict) else str(item.get("location", ""))
            job_id = item.get("id", "")
            url    = f"https://careers.tysonfoods.com/job/{job_id}" if job_id else "https://www.tysonfoods.com/careers"
            if not is_valid_location(loc):
                continue
            ok, reason = is_relevant(title)
            if ok:
                jobs.append(make_job(name, title, url, "Tyson",
                                     category="freight", location=loc, match_reason=reason))
        total = data.get("count", 0)
        start += num
        if start >= total:
            break
        time.sleep(0.5)
    log.info(f"{name}: {len(jobs)} jobs")
    return jobs


# ──────────────────────────────────────────────────────────────────────────────
# BANKING
# ──────────────────────────────────────────────────────────────────────────────

def scrape_arvest():
    name = "Arvest Bank"
    soup = pw_get_soup(ARVEST_URL, wait=6)
    if not soup:
        return []
    jobs = scrape_links(
        soup, name, "https://css-arvest-prd.inforcloudsuite.com", "Infor", "banking",
        href_words=["job", "requisition", "posting", "career", "req"],
        use_loc_regex=True,
    )
    log.info(f"{name}: {len(jobs)} jobs")
    return jobs


def scrape_first_national():
    name = "First National Bank"
    url  = ("https://recruiting.paylocity.com/recruiting/jobs/All/"
            "dcb49edc-c676-411b-8b7b-104a72fec402/The-First-National-Bank-of-Fort-Smith")
    soup = pw_get_soup(url, wait=5)
    if not soup:
        return []
    jobs = scrape_links(
        soup, name, "https://recruiting.paylocity.com", "Paylocity", "banking",
        location="Fort Smith, AR",
        href_words=["recruiting/jobs", "details", "dcb49edc"],
    )
    log.info(f"{name}: {len(jobs)} jobs")
    return jobs


def scrape_regions():
    name = "Regions Bank"
    base = "https://careers.regions.com/us/en/search-results"
    jobs, added = [], set()

    def _parse(s):
        found = scrape_links(
            s, name, "https://careers.regions.com", "Regions", "banking",
            href_words=["/job/", "jobdetails", "careers.regions"],
            use_loc_regex=True,
        )
        for j in found:
            if j["id"] not in added:
                added.add(j["id"])
                jobs.append(j)

    soup = pw_get_soup(base, wait=6)
    if soup:
        _parse(soup)
    for page in range(2, 4):   # cap at 3 pages
        s = pw_get_soup(f"{base}?pg={page}", wait=4)
        if not s:
            break
        prev = len(jobs)
        _parse(s)
        if len(jobs) == prev:
            break
        time.sleep(1)
    log.info(f"{name}: {len(jobs)} jobs")
    return jobs


def scrape_bofa():
    name = "Bank of America"
    soup = pw_get_soup(BOFA_URL, wait=6)
    if not soup:
        return []
    jobs = scrape_links(
        soup, name, "https://careers.bankofamerica.com", "BofA", "banking",
        href_words=["/job-detail/", "job/", "careers.bankofamerica"],
        use_loc_regex=True,
    )
    log.info(f"{name}: {len(jobs)} jobs")
    return jobs


def scrape_centennial():
    name = "Centennial Bank"
    soup = pw_get_soup(CENTENNIAL_URL, wait=7)
    if not soup:
        return []
    jobs, added = [], set()
    for a in soup.find_all("a", href=True):
        href  = a["href"]
        title = a.get_text(strip=True)
        if not title or len(title) < 5 or href in added:
            continue
        if "opportunitydetail" not in href.lower() and "jobboard" not in href.lower():
            continue
        added.add(href)
        parent = a.find_parent(["li", "div", "tr", "article"])
        loc = ""
        if parent:
            m = LOC_REGEX.search(parent.get_text())
            loc = m.group(0) if m else ""
        if not is_valid_location(loc):
            continue
        full_url   = href if href.startswith("http") else "https://recruiting.ultipro.com" + href
        ok, reason = is_relevant(title)
        if ok:
            jobs.append(make_job(name, title, full_url, "UltiPro",
                                 category="banking", location=loc, match_reason=reason))
    log.info(f"{name}: {len(jobs)} jobs")
    return jobs


# ──────────────────────────────────────────────────────────────────────────────
# CORPORATE
# ──────────────────────────────────────────────────────────────────────────────

def scrape_phillips66():
    name = "Phillips 66 (Ponca City)"
    # SuccessFactors search page — try requests first, PW fallback
    soup = None
    try:
        r = requests.get(PHILLIPS66_URL, headers=HEADERS, timeout=20)
        if r.status_code == 200 and "jobTitle" in r.text:
            soup = BeautifulSoup(r.text, "html.parser")
    except Exception as e:
        log.warning(f"{name} requests: {e}")
    if soup is None:
        soup = pw_get_soup(PHILLIPS66_URL, wait=5)
    if not soup:
        return []
    jobs, added = [], set()
    for a in soup.find_all("a", href=re.compile(r"/job/", re.I)):
        href  = a["href"]
        title = a.get_text(strip=True)
        if not title or len(title) < 5 or href in added:
            continue
        added.add(href)
        full_url   = href if href.startswith("http") else "https://careers.phillips66.com" + href
        ok, reason = is_relevant(title)
        if ok:
            jobs.append(make_job(name, title, full_url, "SuccessFactors",
                                 category="corporate", location="Ponca City, OK",
                                 match_reason=reason))
    log.info(f"{name}: {len(jobs)} jobs")
    return jobs


# ──────────────────────────────────────────────────────────────────────────────
# COMMUNITY
# ──────────────────────────────────────────────────────────────────────────────

def scrape_civicengage(name, url, location):
    soup = pw_get_soup(url, wait=5)
    if not soup:
        return []
    base = re.match(r"(https?://[^/]+)", url).group(1)
    jobs = scrape_links(soup, name, base, "CivicEngage", "community", location=location)
    log.info(f"{name}: {len(jobs)} jobs")
    return jobs


def scrape_governmentjobs(name, city_slug, location):
    """NEOGOV boards are JS apps — Playwright required."""
    url  = f"https://www.governmentjobs.com/careers/{city_slug}"
    soup = pw_get_soup(url, wait=6)
    if not soup:
        return []
    jobs, added = [], set()
    for a in soup.find_all("a", href=re.compile(rf"/careers/{city_slug}/jobs/", re.I)):
        href  = a["href"]
        title = a.get_text(strip=True)
        if not title or len(title) < 5 or href in added:
            continue
        added.add(href)
        full_url   = href if href.startswith("http") else "https://www.governmentjobs.com" + href
        ok, reason = is_relevant(title)
        if ok:
            jobs.append(make_job(name, title, full_url, "GovernmentJobs",
                                 category="community", location=location, match_reason=reason))
    log.info(f"{name}: {len(jobs)} jobs")
    return jobs


def scrape_washington_county():
    name = "Washington County AR"
    url  = "https://www.washingtoncountyar.gov/government/departments-f-z/human-resources/job-postings"
    try:
        r    = requests.get(url, headers=HEADERS, timeout=20)
        soup = BeautifulSoup(r.text, "html.parser")
    except Exception as e:
        log.error(f"{name}: {e}")
        return []
    content = soup.find("main") or soup.find(id=re.compile(r"content|main", re.I)) or soup
    jobs, added = [], set()
    for a in content.find_all("a", href=True):
        href  = a["href"]
        title = a.get_text(strip=True)
        if not title or len(title) < 5 or href in added:
            continue
        if any(x in href for x in ["#", "mailto:", "tel:", "facebook", "twitter"]):
            continue
        added.add(href)
        full_url   = href if href.startswith("http") else "https://www.washingtoncountyar.gov" + href
        ok, reason = is_relevant(title)
        if ok:
            jobs.append(make_job(name, title, full_url, "HTML",
                                 category="community", location="Fayetteville, AR",
                                 match_reason=reason))
    log.info(f"{name}: {len(jobs)} jobs")
    return jobs


def scrape_springdale_library():
    name = "Springdale Library"
    url  = "https://springdalelibrary.org/employment/"
    try:
        r    = requests.get(url, headers=HEADERS, timeout=15)
        soup = BeautifulSoup(r.text, "html.parser")
    except Exception as e:
        log.error(f"{name}: {e}")
        return []
    content = soup.find("main") or soup.find(class_=re.compile(r"content|entry|post", re.I)) or soup
    if any(x in content.get_text().lower() for x in ["no open position", "no current"]):
        log.info(f"{name}: no open positions")
        return []
    jobs = []
    for a in content.find_all("a", href=True):
        title = a.get_text(strip=True)
        href  = a["href"]
        if not title or len(title) < 5:
            continue
        if any(x in href for x in ["#", "mailto:", "tel:", "/wp-"]):
            continue
        ok, reason = is_relevant(title)
        if ok:
            full_url = href if href.startswith("http") else "https://springdalelibrary.org" + href
            jobs.append(make_job(name, title, full_url, "Library",
                                 category="community", location="Springdale, AR",
                                 match_reason=reason))
    log.info(f"{name}: {len(jobs)} jobs")
    return jobs


def scrape_jbu():
    name = "JBU"
    url  = "https://www.jbu.edu/human-resources/staff-job-listings/"
    try:
        r    = requests.get(url, headers=HEADERS, timeout=15)
        soup = BeautifulSoup(r.text, "html.parser")
    except Exception as e:
        log.error(f"{name}: {e}")
        return []
    content = soup.find("main") or soup.find(id=re.compile(r"content|main", re.I)) or soup
    skip = ["#", "mailto:", "facebook", "twitter", "linkedin", "instagram",
            "jbu.edu/about", "jbu.edu/admissions", "jbu.edu/student",
            "jbu.edu/academic", "catalog", "calendar", "news", "giving", "alumni"]
    jobs = []
    for a in content.find_all("a", href=True):
        title = a.get_text(strip=True)
        href  = a["href"]
        if not title or len(title) < 5:
            continue
        if any(x in href for x in skip):
            continue
        ok, reason = is_relevant(title)
        if ok:
            full_url = href if href.startswith("http") else "https://www.jbu.edu" + href
            jobs.append(make_job(name, title, full_url, "JBU",
                                 category="community", location="Siloam Springs, AR",
                                 match_reason=reason))
    log.info(f"{name}: {len(jobs)} jobs")
    return jobs


def scrape_osu():
    name = "Oklahoma State Univ."
    url  = (
        "https://jobs.okstate.edu/jobs/search/search-page-oklahoma-state"
        "?page=1&employment_type_uids%5B%5D=6a459435837e4ce324d4b89779b2f709"
        "&employment_type_uids%5B%5D=f13ab2a97d6eba001fa9336859e855a7"
        "&employment_type_uids%5B%5D=264e3580c4d8bff0bdcc2de08fac0d76&query="
    )
    # Try requests first; if no job links found, retry with Playwright
    soup = None
    try:
        r    = requests.get(url, headers=HEADERS, timeout=20)
        s    = BeautifulSoup(r.text, "html.parser")
        if s.find("a", href=re.compile(r"/jobs/\d+|/postings/\d+", re.I)):
            soup = s
    except Exception as e:
        log.warning(f"{name} requests: {e}")
    if soup is None:
        soup = pw_get_soup(url, wait=6)
    if not soup:
        return []
    jobs, added = [], set()
    for a in soup.find_all("a", href=re.compile(r"/jobs/\d+|/postings/\d+", re.I)):
        href  = a["href"]
        title = a.get_text(strip=True)
        if not title or len(title) < 5 or href in added:
            continue
        added.add(href)
        full_url   = href if href.startswith("http") else "https://jobs.okstate.edu" + href
        ok, reason = is_relevant(title)
        if ok:
            jobs.append(make_job(name, title, full_url, "PageUp",
                                 category="community", location="Stillwater, OK",
                                 match_reason=reason))
    log.info(f"{name}: {len(jobs)} jobs")
    return jobs


def scrape_adp(name, url, category, location):
    soup = pw_get_soup(url, wait=6)
    if not soup:
        return []
    jobs, added = [], set()
    for a in soup.find_all("a", href=True):
        href  = a["href"]
        title = a.get_text(strip=True)
        if not title or len(title) < 5 or href in added:
            continue
        if not any(x in href for x in ["recruitment", "job", "posting", "req"]):
            continue
        added.add(href)
        full_url   = href if href.startswith("http") else "https://workforcenow.adp.com" + href
        ok, reason = is_relevant(title)
        if ok:
            jobs.append(make_job(name, title, full_url, "ADP",
                                 category=category, location=location, match_reason=reason))
    log.info(f"{name}: {len(jobs)} jobs")
    return jobs


# ──────────────────────────────────────────────────────────────────────────────
# HEALTHCARE
# ──────────────────────────────────────────────────────────────────────────────

def scrape_mana():
    name = "MANA Clinics"
    soup = pw_get_soup(MANA_URL, wait=6)
    if not soup:
        return []
    jobs, added = [], set()
    for a in soup.find_all("a", href=re.compile(r"/jobs/\d+", re.I)):
        href  = a["href"]
        title = a.get_text(strip=True)
        if not title or len(title) < 5 or href in added:
            continue
        added.add(href)
        full_url   = href if href.startswith("http") else "https://careers-mana.icims.com" + href
        ok, reason = is_relevant(title)
        if ok:
            jobs.append(make_job(name, title, full_url, "iCIMS",
                                 category="healthcare", location="Fayetteville, AR",
                                 match_reason=reason))
    log.info(f"{name}: {len(jobs)} jobs")
    return jobs


def scrape_nw_medical():
    name = "NW Medical Center (Springdale)"
    try:
        r    = requests.get(NWMED_URL, headers=HEADERS, timeout=20)
        soup = BeautifulSoup(r.text, "html.parser")
    except Exception as e:
        log.error(f"{name}: {e}")
        return []
    jobs = scrape_links(
        soup, name, "https://chsmedcareers.com", "CHS", "healthcare",
        location="Springdale, AR",
        href_words=["/job", "/career", "/posting", "/position"],
    )
    log.info(f"{name}: {len(jobs)} jobs")
    return jobs


def scrape_wregional():
    name = "Washington Regional"
    soup = pw_get_soup(WREG_URL, wait=6)
    if not soup:
        return []
    jobs = scrape_links(
        soup, name, "https://www.wregional.com", "WRMC", "healthcare",
        location="Fayetteville, AR",
        href_words=["job", "position", "opening", "career", "req"],
    )
    log.info(f"{name}: {len(jobs)} jobs")
    return jobs


def scrape_mercy():
    name = "Mercy (Springdale)"
    soup = pw_get_soup(MERCY_URL, wait=7)
    if not soup:
        return []
    jobs, added = [], set()
    for a in soup.find_all("a", href=re.compile(r"/job/|/jobs/", re.I)):
        href  = a["href"]
        title = a.get_text(strip=True)
        if not title or len(title) < 5 or href in added:
            continue
        added.add(href)
        full_url   = href if href.startswith("http") else "https://careers.mercy.net" + href
        ok, reason = is_relevant(title)
        if ok:
            jobs.append(make_job(name, title, full_url, "Mercy",
                                 category="healthcare", location="Springdale, AR",
                                 match_reason=reason))
    log.info(f"{name}: {len(jobs)} jobs")
    return jobs


# ──────────────────────────────────────────────────────────────────────────────
# ORCHESTRATION
# ──────────────────────────────────────────────────────────────────────────────

def scrape_all():
    all_jobs = []

    log.info("── Freight & Logistics ──")
    all_jobs.extend(_safe(scrape_arcbest));           time.sleep(2)
    for s in WORKDAY_SOURCES:
        if s["category"] == "freight":
            all_jobs.extend(_safe(scrape_workday, s)); time.sleep(1)
    all_jobs.extend(_safe(scrape_tyson));             time.sleep(2)

    log.info("── Banking ──")
    all_jobs.extend(_safe(scrape_arvest));            time.sleep(2)
    for s in WORKDAY_SOURCES:
        if s["category"] == "banking":
            all_jobs.extend(_safe(scrape_workday, s)); time.sleep(1)
    all_jobs.extend(_safe(scrape_first_national));    time.sleep(2)
    all_jobs.extend(_safe(scrape_regions));           time.sleep(2)
    all_jobs.extend(_safe(scrape_bofa));              time.sleep(2)
    all_jobs.extend(_safe(scrape_centennial));        time.sleep(2)

    log.info("── Corporate ──")
    all_jobs.extend(_safe(scrape_phillips66));        time.sleep(2)

    log.info("── Community ──")
    all_jobs.extend(_safe(scrape_civicengage, "Rogers (City)",      "https://www.rogersar.gov/Jobs.aspx",      "Rogers, AR"));      time.sleep(2)
    all_jobs.extend(_safe(scrape_civicengage, "Bentonville (City)", "https://www.bentonvillear.com/1414/Employment-Opportunities", "Bentonville, AR")); time.sleep(2)
    all_jobs.extend(_safe(scrape_civicengage, "Bella Vista (City)", "https://recruiting.paylocity.com/recruiting/jobs/All/b1e8c19e-977f-41ec-89e7-a138ab6e72eb/City-of-Bella-Vista", "Bella Vista, AR")); time.sleep(2)
    all_jobs.extend(_safe(scrape_civicengage, "Lowell (City)",      "https://www.lowellarkansas.gov/jobs",     "Lowell, AR"));      time.sleep(2)
    all_jobs.extend(_safe(scrape_civicengage, "City of Stillwater", "https://stillwaterok.gov/Jobs.aspx",      "Stillwater, OK"));  time.sleep(2)
    all_jobs.extend(_safe(scrape_civicengage, "City of Ponca City", "https://www.poncacityok.gov/Jobs.aspx",   "Ponca City, OK"));  time.sleep(2)
    all_jobs.extend(_safe(scrape_governmentjobs, "Fayetteville (City)", "fayettevillear", "Fayetteville, AR")); time.sleep(2)
    all_jobs.extend(_safe(scrape_governmentjobs, "Springdale (City)",   "springdalear",   "Springdale, AR"));   time.sleep(2)
    all_jobs.extend(_safe(scrape_washington_county));  time.sleep(1)
    all_jobs.extend(_safe(scrape_springdale_library)); time.sleep(1)
    all_jobs.extend(_safe(scrape_jbu));                time.sleep(1)
    all_jobs.extend(_safe(scrape_osu));                time.sleep(1)
    all_jobs.extend(_safe(scrape_adp, "ADP (NWA)", ADP_NWA_URL, "community", "NWA, AR")); time.sleep(2)
    for s in WORKDAY_SOURCES:
        if s["category"] == "community":
            all_jobs.extend(_safe(scrape_workday, s)); time.sleep(1)

    log.info("── Healthcare ──")
    all_jobs.extend(_safe(scrape_mana));               time.sleep(2)
    all_jobs.extend(_safe(scrape_nw_medical));         time.sleep(2)
    all_jobs.extend(_safe(scrape_wregional));          time.sleep(2)
    all_jobs.extend(_safe(scrape_mercy));              time.sleep(2)
    all_jobs.extend(_safe(scrape_adp, "ADP (Healthcare)", ADP_HEALTH_URL, "healthcare", "NWA, AR")); time.sleep(2)
    for s in WORKDAY_SOURCES:
        if s["category"] == "healthcare":
            all_jobs.extend(_safe(scrape_workday, s)); time.sleep(1)

    # Deduplicate
    seen, unique = set(), []
    for j in all_jobs:
        if j["id"] not in seen:
            seen.add(j["id"])
            unique.append(j)

    log.info(f"Total relevant jobs: {len(unique)}")
    return unique


def find_new_jobs(old_data, new_jobs):
    existing_ids = {j["id"] for j in old_data.get("jobs", [])}
    return [j for j in new_jobs if j["id"] not in existing_ids]


def main():
    log.info("── Customer Support Tracker starting ──")
    old_data = load_jobs()
    new_jobs = scrape_all()

    existing = {j["id"]: j for j in old_data.get("jobs", [])}
    for j in new_jobs:
        if j["id"] in existing:
            j["first_seen"] = existing[j["id"]]["first_seen"]

    brand_new = find_new_jobs(old_data, new_jobs)
    log.info(f"New since last run: {len(brand_new)}")

    save_jobs({
        "last_updated": datetime.now().isoformat(timespec="minutes"),
        "jobs":         new_jobs,
        "sources":      ALL_SOURCES,
    })
    log.info("── Done ──")


if __name__ == "__main__":
    main()
