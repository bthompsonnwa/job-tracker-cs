#!/usr/bin/env python3
"""
Customer Support Tracker — NWA · Stillwater · Ponca City
Scrapes 20+ sources, filters for customer support / admin / logistics roles.
Updates docs/jobs.json for the GitHub Pages dashboard. No email — dashboard only.
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
# GEOGRAPHIC FILTER — city-level only
# Unknown/blank location passes through (local city pages are inherently local)
# ──────────────────────────────────────────────────────────────────────────────

TARGET_LOCATIONS = [
    # NWA — Benton County
    "bentonville", "rogers", "bella vista", "lowell", "centerton",
    "siloam springs", "cave springs", "elm springs", "gravette", "pea ridge",
    "highfill", "gentry",
    # NWA — Washington County
    "fayetteville", "springdale", "prairie grove", "west fork", "tontitown",
    "elkins", "greenland", "johnson", "farmington", "lincoln", "goshen",
    # NWA aliases
    "nwa", "northwest arkansas", "benton county", "washington county",
    # Oklahoma
    "stillwater", "ponca city",
]

# Regex for extracting location from parent elements in generic scrapers
LOC_REGEX = re.compile(
    r"\b(Bentonville|Rogers|Bella Vista|Lowell|Centerton|Siloam Springs|"
    r"Cave Springs|Elm Springs|Gravette|Pea Ridge|Highfill|Gentry|"
    r"Fayetteville|Springdale|Prairie Grove|West Fork|Tontitown|Elkins|"
    r"Greenland|Johnson|Farmington|Lincoln|Goshen|"
    r"NWA|Northwest Arkansas|Benton County|Washington County|"
    r"Stillwater|Ponca City)\b",
    re.I
)


def is_valid_location(loc: str) -> bool:
    """True if location is blank/unknown or matches a target city."""
    if not loc or not loc.strip():
        return True
    l = loc.lower()
    return any(city in l for city in TARGET_LOCATIONS)


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
    "office manager", "office coordinator", "office administrator",
    "executive assistant", "operations assistant", "operations coordinator",
    "operations specialist", "operations support", "operations analyst",
    "data entry", "data coordinator", "records coordinator",
    "receptionist", "front desk", "office support", "office clerk",
    "file clerk", "records clerk", "document specialist",
    # Entry-level / General
    "entry level", "entry-level", "trainee", "clerk",
    "support representative", "service representative",
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
    "rating coordinator", "yield coordinator", "pricing coordinator",
    "pricing analyst", "brokerage", "truckload",
    "intermodal coordinator", "drayage coordinator",
    # Banking / Finance
    "bank teller", "teller", "personal banker",
    "branch coordinator", "loan processor", "loan coordinator", "loan officer",
    "mortgage coordinator", "mortgage processor",
    "financial services", "financial representative", "financial specialist",
    "collections coordinator", "collections specialist", "collections representative",
    "compliance coordinator", "compliance specialist", "fraud analyst",
    "credit analyst", "banking associate", "banking specialist",
    "treasury coordinator", "wire transfer",
    # Call center / Communication
    "call center", "contact center", "help desk", "support specialist",
    "communications coordinator", "communications specialist",
    # General coordinator
    "program coordinator", "project coordinator",
    # Funeral / Death care
    "funeral", "mortuary", "death care", "bereavement",
    "funeral home", "funeral service", "cremation coordinator",
    "funeral coordinator", "funeral administrative", "funeral answering",
    "after-loss", "afterloss", "grief support coordinator",
]

HARD_EXCLUDE_KEYWORDS = [
    "truck driver", "cdl driver", "forklift operator", "warehouse associate",
    "warehouse worker", "picker", "packer", "stocker", "dock worker",
    "material handler", "janitor", "custodian", "groundskeeper",
    "registered nurse", "school nurse", " rn ", "nurse practitioner",
    "physician", "pharmacist", "physical therapist", "occupational therapist",
    "software engineer", "software developer", "web developer", "devops",
    "data scientist", "machine learning", "cybersecurity", "network engineer",
    "electrical engineer", "mechanical engineer", "civil engineer",
    "maintenance mechanic", "hvac technician", "electrician", "plumber",
    "vice president", "vp ", "chief ", "cto", "cfo", "coo",
    "regional manager", "district manager", "general manager",
    "senior manager", "store manager", "marketing manager",
    "product manager", "people manager", "hiring manager",
    "supervisor",           # too senior for entry-level tracker
    "account development",  # sales/business dev management
    "dean",                 # academic administration
    " 911",                 # emergency dispatch, not logistics
    "professor", "faculty", "instructor", "teacher",
    "request a quote", "get a quote", "truck load quote",
    "full truckload", "less than truckload", "learn more",
    "view all", "see all jobs", "see open", "join our team",
]

# ──────────────────────────────────────────────────────────────────────────────
# SOURCE REGISTRY
# ──────────────────────────────────────────────────────────────────────────────

ALL_SOURCES = [
    # Freight & Logistics
    {"name": "ArcBest",       "url": "https://careers.arcb.com/careersmarketplace/OpenPositions/",     "category": "freight"},
    {"name": "J.B. Hunt",     "url": "https://jbhunt.wd501.myworkdayjobs.com/Careers",                 "category": "freight"},
    {"name": "Tyson Foods",   "url": "https://www.tysonfoods.com/careers",                             "category": "freight"},
    {"name": "XPO",           "url": "https://jobs.xpo.com/search/",                                   "category": "freight"},
    {"name": "Echo Global",   "url": "https://www.echo.com/company/careers/open-positions/",           "category": "freight"},
    # Banking
    {"name": "Arvest Bank",   "url": "https://css-arvest-prd.inforcloudsuite.com/hcm/Jobs/form/JobBoard%28ARV,EXTERNAL%29.JobSearchCompositeForm?navigation=JobBoard%28ARV,EXTERNAL%29.JobSearchCompositeFormNav&csk.JobBoard=EXTERNAL&csk.showusingxi=true&csk.HROrganization=ARV", "category": "banking"},
    {"name": "Simmons Bank",  "url": "https://simmonsbank.wd5.myworkdayjobs.com/SimmonsCareers",       "category": "banking"},
    {"name": "First National Bank", "url": "https://recruiting.paylocity.com/recruiting/jobs/All/dcb49edc-c676-411b-8b7b-104a72fec402/The-First-National-Bank-of-Fort-Smith", "category": "banking"},
    {"name": "Regions Bank",  "url": "https://careers.regions.com/us/en/search-results",              "category": "banking"},
    {"name": "Bank of America","url": "https://careers.bankofamerica.com/en-us/job-search",             "category": "banking"},
    # Corporate
    {"name": "Walmart (Supply Chain)", "url": "https://careers.walmart.com/us/en/results?searchQuery=Bentonville&careerareas=Supply%20Chain%20and%20Transportation", "category": "corporate"},
    {"name": "Walmart (Corporate)",    "url": "https://careers.walmart.com/us/en/results?searchQuery=Bentonville&careerareas=Corporate", "category": "corporate"},
    # Community
    {"name": "Rogers (City)",         "url": "https://www.rogersar.gov/Jobs.aspx",                    "category": "community"},
    {"name": "Bentonville (City)",     "url": "https://www.bentonvillear.com/1414/Employment-Opportunities", "category": "community"},
    {"name": "Fayetteville (City)",    "url": "https://www.governmentjobs.com/careers/fayettevillear",  "category": "community"},
    {"name": "Springdale (City)",      "url": "https://www.governmentjobs.com/careers/springdalear",    "category": "community"},
    {"name": "Bella Vista (City)",     "url": "https://recruiting.paylocity.com/recruiting/jobs/All/b1e8c19e-977f-41ec-89e7-a138ab6e72eb/City-of-Bella-Vista", "category": "community"},
    {"name": "Lowell (City)",          "url": "https://www.lowellarkansas.gov/jobs",                   "category": "community"},
    {"name": "City of Stillwater",     "url": "https://stillwaterok.gov/Jobs.aspx",                    "category": "community"},
    {"name": "City of Ponca City",     "url": "https://www.poncacityok.gov/Jobs.aspx",                 "category": "community"},
    {"name": "Washington County AR",   "url": "https://www.washingtoncountyar.gov/government/departments-f-z/human-resources/job-postings", "category": "community"},
    {"name": "Springdale Library",     "url": "https://springdalelibrary.org/employment/",             "category": "community"},
    {"name": "UAF",                    "url": "https://uasys.wd5.myworkdayjobs.com/UAF_External_Career_Site", "category": "community"},
    {"name": "NWACC",                  "url": "https://nwacc.wd1.myworkdayjobs.com/NWACC_External_Career_Site", "category": "community"},
    {"name": "JBU",                    "url": "https://www.jbu.edu/human-resources/staff-job-listings/", "category": "community"},
    {"name": "Oklahoma State Univ.",   "url": "https://jobs.okstate.edu/jobs/search/search-page-oklahoma-state", "category": "community"},
    {"name": "ADP (NWA)",              "url": "https://workforcenow.adp.com/mascsr/default/mdf/recruitment/recruitment.html?cid=dd3989d6-a17f-4803-bdaa-54bf26faf499", "category": "community"},
    # Funeral
    {"name": "NFDA Career Center",        "url": "https://www.nfda.org/career-center",          "category": "funeral"},
    {"name": "Connecting Directors Jobs",  "url": "https://www.connectingdirectors.com/jobs",    "category": "funeral"},
]

# ──────────────────────────────────────────────────────────────────────────────
# HELPERS
# ──────────────────────────────────────────────────────────────────────────────

def make_id(source, title, url=""):
    return hashlib.md5(f"{source}|{title}|{url}".encode()).hexdigest()[:12]


def is_relevant(title: str, extra: str = ""):
    combined = (title + " " + extra).lower()
    for kw in HARD_EXCLUDE_KEYWORDS:
        if kw.strip() in combined:
            return False, f"excluded:{kw.strip()}"
    for kw in INCLUDE_KEYWORDS:
        if kw in combined:
            return True, kw
    return False, "no_match"


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


def pw_get_soup(url, wait=4):
    try:
        from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout
    except ImportError:
        log.warning("Playwright not installed")
        return None
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(args=["--no-sandbox", "--disable-dev-shm-usage"])
            ctx     = browser.new_context(user_agent=HEADERS["User-Agent"])
            page    = ctx.new_page()
            try:
                page.goto(url, wait_until="networkidle", timeout=40000)
            except PWTimeout:
                page.wait_for_timeout(5000)
            time.sleep(wait)
            html = page.content()
            browser.close()
        return BeautifulSoup(html, "html.parser")
    except Exception as e:
        log.error(f"Playwright error on {url}: {e}")
        return None


# ──────────────────────────────────────────────────────────────────────────────
# WORKDAY  (J.B. Hunt · Simmons Bank · UAF · NWACC)
# ──────────────────────────────────────────────────────────────────────────────

WORKDAY_SOURCES = [
    {"name": "J.B. Hunt",    "category": "freight",
     "api_url":  "https://jbhunt.wd501.myworkdayjobs.com/wday/cxs/jbhunt/Careers/jobs",
     "base_url": "https://jbhunt.wd501.myworkdayjobs.com/en-US/Careers"},
    {"name": "Simmons Bank", "category": "banking",
     "api_url":  "https://simmonsbank.wd5.myworkdayjobs.com/wday/cxs/simmonsbank/SimmonsCareers/jobs",
     "base_url": "https://simmonsbank.wd5.myworkdayjobs.com/en-US/SimmonsCareers"},
    {"name": "UAF",          "category": "community",
     "api_url":  "https://uasys.wd5.myworkdayjobs.com/wday/cxs/uasys/UAF_External_Career_Site/jobs",
     "base_url": "https://uasys.wd5.myworkdayjobs.com/en-US/UAF_External_Career_Site"},
    {"name": "NWACC",        "category": "community",
     "api_url":  "https://nwacc.wd1.myworkdayjobs.com/wday/cxs/nwacc/NWACC_External_Career_Site/jobs",
     "base_url": "https://nwacc.wd1.myworkdayjobs.com/en-US/NWACC_External_Career_Site"},
]


def scrape_workday(source):
    name     = source["name"]
    api_url  = source["api_url"]
    category = source["category"]
    jobs     = []
    offset   = 0
    limit    = 20
    api_hdrs = {**HEADERS, "Content-Type": "application/json", "Accept": "application/json"}
    while True:
        payload = {"limit": limit, "offset": offset, "searchText": "", "appliedFacets": {}}
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
            if not is_valid_location(loc):
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
# ARCBEST  (pre-filtered CareersMarketplace — Playwright)
# ──────────────────────────────────────────────────────────────────────────────

def scrape_arcbest():
    name = "ArcBest"
    url  = (
        "https://careers.arcb.com/careersmarketplace/OpenPositions/"
        "?10509=%5B36616%2C27818%2C27807%2C27810%2C36756%2C56719%2C28134"
        "%2C1738333%2C36692%2C36941%2C36950%5D&10509_format=3533"
        "&10508=8400047&10508_format=3532&listFilterMode=1&jobRecordsPerPage=6&"
    )
    jobs = []
    soup = pw_get_soup(url, wait=5)
    if not soup:
        return jobs
    added = set()
    for a in soup.find_all("a", href=True):
        href  = a["href"]
        title = a.get_text(strip=True)
        if not title or len(title) < 5 or href in added:
            continue
        # CareersMarketplace job detail links
        if not any(x in href.lower() for x in ["jobdetail", "openposition", "position",
                                                 "req", "careers.arcb", "job"]):
            continue
        if any(x in title.lower() for x in ["view all", "see all", "learn more", "apply"]):
            continue
        added.add(href)
        # Pre-filtered by department so location check is lenient; Fort Smith is ArcBest HQ
        full_url   = href if href.startswith("http") else "https://careers.arcb.com" + href
        ok, reason = is_relevant(title)
        if ok:
            jobs.append(make_job(name, title, full_url, "CareersMarketplace",
                                 category="freight", location="Fort Smith, AR",
                                 match_reason=reason))
    log.info(f"{name}: {len(jobs)} jobs")
    return jobs


# ──────────────────────────────────────────────────────────────────────────────
# TYSON FOODS
# ──────────────────────────────────────────────────────────────────────────────

def scrape_tyson():
    name = "Tyson Foods"
    jobs = []
    api_url = "https://careers.tysonfoods.com/api/apply/v2/jobs?domain=tysonfoods.com&start=0&num=100&sort_by=relevance"
    try:
        r    = requests.get(api_url, headers=HEADERS, timeout=20)
        data = r.json()
        for item in data.get("positions", []):
            title  = item.get("name", "").strip()
            loc    = item.get("location", {}).get("name", "")
            job_id = item.get("id", "")
            url    = f"https://careers.tysonfoods.com/job/{job_id}" if job_id else "https://www.tysonfoods.com/careers"
            if not is_valid_location(loc):
                continue
            ok, reason = is_relevant(title)
            if ok:
                jobs.append(make_job(name, title, url, "Tyson",
                                     category="freight", location=loc, match_reason=reason))
        if jobs:
            log.info(f"{name}: {len(jobs)} jobs (API)")
            return jobs
    except Exception as e:
        log.warning(f"{name} API: {e}")
    soup = pw_get_soup("https://www.tysonfoods.com/careers", wait=5)
    if not soup:
        return jobs
    added = set()
    for a in soup.find_all("a", href=True):
        href  = a["href"]
        title = a.get_text(strip=True)
        if not title or len(title) < 5 or href in added:
            continue
        if not any(x in href.lower() for x in ["job", "career", "posting", "req", "position"]):
            continue
        added.add(href)
        parent = a.find_parent(["li", "div", "tr", "article"])
        loc = ""
        if parent:
            m = LOC_REGEX.search(parent.get_text())
            loc = m.group(0) if m else ""
        if not is_valid_location(loc):
            continue
        full_url   = href if href.startswith("http") else "https://www.tysonfoods.com" + href
        ok, reason = is_relevant(title)
        if ok:
            jobs.append(make_job(name, title, full_url, "Tyson",
                                 category="freight", location=loc, match_reason=reason))
    log.info(f"{name}: {len(jobs)} jobs (fallback)")
    return jobs


# ──────────────────────────────────────────────────────────────────────────────
# XPO
# ──────────────────────────────────────────────────────────────────────────────

def scrape_xpo():
    name = "XPO"
    jobs = []
    api_url = "https://jobs.xpo.com/api/apply/v2/jobs?domain=jobs.xpo.com&num=100&start=0"
    try:
        r    = requests.get(api_url, headers=HEADERS, timeout=20)
        data = r.json()
        for item in data.get("positions", []):
            title  = item.get("name", "").strip()
            loc    = item.get("location", {}).get("name", "")
            job_id = item.get("id", "")
            url    = f"https://jobs.xpo.com/job/{job_id}" if job_id else "https://jobs.xpo.com"
            if not is_valid_location(loc):
                continue
            ok, reason = is_relevant(title)
            if ok:
                jobs.append(make_job(name, title, url, "XPO",
                                     category="freight", location=loc, match_reason=reason))
        if jobs:
            log.info(f"{name}: {len(jobs)} jobs (API)")
            return jobs
    except Exception as e:
        log.warning(f"{name} API: {e}")
    soup = pw_get_soup("https://jobs.xpo.com/search/?searchby=distance&createNewAlert=false&q=&geolocation=72701+-+United+States&d=75&lat=36.052&lon=-94.1534", wait=5)
    if not soup:
        return jobs
    added = set()
    for a in soup.find_all("a", href=re.compile(r"/job/", re.I)):
        href  = a["href"]
        title = a.get_text(strip=True)
        if not title or href in added:
            continue
        added.add(href)
        parent = a.find_parent(["li", "div", "tr", "article"])
        loc = ""
        if parent:
            m = LOC_REGEX.search(parent.get_text())
            loc = m.group(0) if m else ""
        if not is_valid_location(loc):
            continue
        full_url   = href if href.startswith("http") else "https://jobs.xpo.com" + href
        ok, reason = is_relevant(title)
        if ok:
            jobs.append(make_job(name, title, full_url, "XPO",
                                 category="freight", location=loc, match_reason=reason))
    log.info(f"{name}: {len(jobs)} jobs (fallback)")
    return jobs


# ──────────────────────────────────────────────────────────────────────────────
# ECHO GLOBAL LOGISTICS
# ──────────────────────────────────────────────────────────────────────────────

_ECHO_JOB_WORDS = re.compile(
    r"\b(coordinator|specialist|representative|analyst|associate|agent|"
    r"advisor|support|service|administrator|assistant|"
    r"broker|planner|processor|clerk|trainee|"
    r"brokerage|logistics|operations|billing|claims|"
    r"executive|account|dispatcher|dispatch)\b", re.I
)

def scrape_echo():
    name = "Echo Global"
    url  = "https://www.echo.com/company/careers/open-positions/"
    jobs = []
    soup = pw_get_soup(url, wait=6)
    if not soup:
        return jobs
    added = set()
    for a in soup.find_all("a", href=True):
        href  = a["href"]
        title = a.get_text(strip=True)
        if not title or len(title) < 5 or href in added:
            continue
        if not any(x in href.lower() for x in ["job", "career", "lever", "greenhouse",
                                                 "workday", "position", "req", "apply"]):
            continue
        if not _ECHO_JOB_WORDS.search(title):
            continue
        if any(x in title.lower() for x in ["request", "quote", "learn more", "view all",
                                              "join our", "truckload freight", "less than"]):
            continue
        added.add(href)
        full_url   = href if href.startswith("http") else "https://www.echo.com" + href
        ok, reason = is_relevant(title)
        if ok:
            jobs.append(make_job(name, title, full_url, "Echo",
                                 category="freight", location="Chicago, IL",
                                 match_reason=reason))
    log.info(f"{name}: {len(jobs)} jobs")
    return jobs


# ──────────────────────────────────────────────────────────────────────────────
# ARVEST BANK
# ──────────────────────────────────────────────────────────────────────────────

def scrape_arvest():
    name = "Arvest Bank"
    url  = (
        "https://css-arvest-prd.inforcloudsuite.com/hcm/Jobs/form/"
        "JobBoard%28ARV,EXTERNAL%29.JobSearchCompositeForm"
        "?csk.JobBoard=EXTERNAL&csk.HROrganization=ARV"
        "&menu=JobsNavigationMenu.NewJobSearch"
    )
    jobs = []
    soup = pw_get_soup(url, wait=6)
    if not soup:
        return jobs
    added = set()
    for a in soup.find_all("a", href=True):
        href  = a["href"]
        title = a.get_text(strip=True)
        if not title or len(title) < 5 or href in added:
            continue
        if not any(x in href.lower() for x in ["job", "requisition", "posting", "career", "req"]):
            continue
        added.add(href)
        parent = a.find_parent(["li", "div", "tr", "article"])
        loc = ""
        if parent:
            m = LOC_REGEX.search(parent.get_text())
            loc = m.group(0) if m else ""
        if not is_valid_location(loc):
            continue
        full_url   = href if href.startswith("http") else "https://css-arvest-prd.inforcloudsuite.com" + href
        ok, reason = is_relevant(title)
        if ok:
            jobs.append(make_job(name, title, full_url, "Infor",
                                 category="banking", location=loc, match_reason=reason))
    log.info(f"{name}: {len(jobs)} jobs")
    return jobs


# ──────────────────────────────────────────────────────────────────────────────
# FIRST NATIONAL BANK (Paylocity)
# ──────────────────────────────────────────────────────────────────────────────

def scrape_first_national():
    name = "First National Bank"
    url  = (
        "https://recruiting.paylocity.com/recruiting/jobs/All/"
        "dcb49edc-c676-411b-8b7b-104a72fec402/The-First-National-Bank-of-Fort-Smith"
    )
    jobs = []
    soup = pw_get_soup(url, wait=5)
    if not soup:
        return jobs
    added = set()
    for a in soup.find_all("a", href=True):
        href  = a["href"]
        title = a.get_text(strip=True)
        if not title or len(title) < 5 or href in added:
            continue
        if not any(x in href for x in ["recruiting/jobs", "Details", "dcb49edc"]):
            continue
        added.add(href)
        full_url   = href if href.startswith("http") else "https://recruiting.paylocity.com" + href
        ok, reason = is_relevant(title)
        if ok:
            jobs.append(make_job(name, title, full_url, "Paylocity",
                                 category="banking", location="Fort Smith, AR",
                                 match_reason=reason))
    log.info(f"{name}: {len(jobs)} jobs")
    return jobs


# ──────────────────────────────────────────────────────────────────────────────
# REGIONS BANK  (paginated — Playwright)
# ──────────────────────────────────────────────────────────────────────────────

def scrape_regions():
    name = "Regions Bank"
    base = "https://careers.regions.com/us/en/search-results"
    jobs = []
    added = set()

    def _parse(s):
        for a in s.find_all("a", href=True):
            href  = a["href"]
            title = a.get_text(strip=True)
            if not title or len(title) < 5 or href in added:
                continue
            if not any(x in href.lower() for x in ["/job/", "jobdetails", "careers.regions"]):
                continue
            added.add(href)
            parent = a.find_parent(["li", "div", "tr", "article"])
            loc = ""
            if parent:
                m = LOC_REGEX.search(parent.get_text())
                loc = m.group(0) if m else ""
            if not is_valid_location(loc):
                continue
            full_url   = href if href.startswith("http") else "https://careers.regions.com" + href
            ok, reason = is_relevant(title)
            if ok:
                jobs.append(make_job(name, title, full_url, "Regions",
                                     category="banking", location=loc, match_reason=reason))

    soup = pw_get_soup(base, wait=6)
    if soup:
        _parse(soup)
    for page in range(2, 8):
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


# ──────────────────────────────────────────────────────────────────────────────
# BANK OF AMERICA  (pre-filtered — Playwright)
# ──────────────────────────────────────────────────────────────────────────────

def scrape_bofa():
    name = "Bank of America"
    url  = (
        "https://careers.bankofamerica.com/en-us/job-search"
        "?ref=search&search=jobsByLocation&start=0&rows=25"
        "&searchstring=Fayetteville%2C+AR"
        "&searchstring=Bentonville%2C+AR"
        "&searchstring=Springdale%2C+AR"
        "&searchstring=Rogers%2C+AR"
    )
    jobs = []
    soup = pw_get_soup(url, wait=6)
    if not soup:
        return jobs
    added = set()
    for a in soup.find_all("a", href=True):
        href  = a["href"]
        title = a.get_text(strip=True)
        if not title or len(title) < 5 or href in added:
            continue
        if not any(x in href.lower() for x in ["/job-detail/", "job/", "careers.bankofamerica"]):
            continue
        added.add(href)
        parent = a.find_parent(["li", "div", "tr", "article"])
        loc = ""
        if parent:
            m = LOC_REGEX.search(parent.get_text())
            loc = m.group(0) if m else ""
        if not is_valid_location(loc):
            continue
        full_url   = href if href.startswith("http") else "https://careers.bankofamerica.com" + href
        ok, reason = is_relevant(title)
        if ok:
            jobs.append(make_job(name, title, full_url, "BofA",
                                 category="banking", location=loc, match_reason=reason))
    log.info(f"{name}: {len(jobs)} jobs")
    return jobs


# ──────────────────────────────────────────────────────────────────────────────
# WALMART  (specific Bentonville search URLs — Playwright)
# ──────────────────────────────────────────────────────────────────────────────

WALMART_SEARCHES = [
    ("Walmart (Supply Chain)",
     "https://careers.walmart.com/us/en/results?searchQuery=Bentonville&careerareas=Supply%20Chain%20and%20Transportation"),
    ("Walmart (Corporate)",
     "https://careers.walmart.com/us/en/results?searchQuery=Bentonville&careerareas=Corporate"),
]

def scrape_walmart_search():
    all_jobs = []
    for name, url in WALMART_SEARCHES:
        jobs  = []
        soup  = pw_get_soup(url, wait=7)
        if not soup:
            continue
        added = set()
        for a in soup.find_all("a", href=True):
            href  = a["href"]
            title = a.get_text(strip=True)
            if not title or len(title) < 5 or href in added:
                continue
            if not any(x in href.lower() for x in ["/jobs/", "/job/", "careers.walmart"]):
                continue
            if any(x in title.lower() for x in ["view all", "see all", "learn more"]):
                continue
            added.add(href)
            full_url   = href if href.startswith("http") else "https://careers.walmart.com" + href
            ok, reason = is_relevant(title)
            if ok:
                jobs.append(make_job(name, title, full_url, "Walmart",
                                     category="corporate", location="Bentonville, AR",
                                     match_reason=reason))
        log.info(f"{name}: {len(jobs)} jobs")
        all_jobs.extend(jobs)
        time.sleep(2)
    return all_jobs


# ──────────────────────────────────────────────────────────────────────────────
# COMMUNITY — GENERIC SCRAPERS
# ──────────────────────────────────────────────────────────────────────────────

def scrape_civicengage(name, url, location, category="community"):
    """CivicPlus/CivicEngage city job pages — Playwright."""
    jobs = []
    soup = pw_get_soup(url, wait=5)
    if not soup:
        return jobs
    added = set()
    for a in soup.find_all("a", href=True):
        href  = a["href"]
        title = a.get_text(strip=True)
        if not title or len(title) < 5 or href in added:
            continue
        if not any(x in href.lower() for x in ["job", "employment", "career",
                                                 "position", "opportunity", "posting"]):
            continue
        if any(x in title.lower() for x in ["home", "about", "contact", "login",
                                              "search", "department", "more info"]):
            continue
        added.add(href)
        full_url   = href if href.startswith("http") else (url.rsplit("/", 1)[0] + "/" + href.lstrip("/"))
        ok, reason = is_relevant(title)
        if ok:
            jobs.append(make_job(name, title, full_url, "CivicEngage",
                                 category=category, location=location, match_reason=reason))
    log.info(f"{name}: {len(jobs)} jobs")
    return jobs


def scrape_governmentjobs(name, city_slug, location, category="community"):
    """GovernmentJobs.com (NEOGOV) city career pages — requests."""
    url  = f"https://www.governmentjobs.com/careers/{city_slug}"
    jobs = []
    try:
        r    = requests.get(url, headers=HEADERS, timeout=20)
        soup = BeautifulSoup(r.text, "html.parser")
        added = set()
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
                                     category=category, location=location, match_reason=reason))
    except Exception as e:
        log.error(f"{name}: {e}")
    log.info(f"{name}: {len(jobs)} jobs")
    return jobs


def scrape_washington_county():
    name = "Washington County AR"
    url  = "https://www.washingtoncountyar.gov/government/departments-f-z/human-resources/job-postings"
    jobs = []
    try:
        r    = requests.get(url, headers=HEADERS, timeout=20)
        soup = BeautifulSoup(r.text, "html.parser")
        content = soup.find("main") or soup.find(id=re.compile(r"content|main", re.I)) or soup
        added = set()
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
    except Exception as e:
        log.error(f"{name}: {e}")
    log.info(f"{name}: {len(jobs)} jobs")
    return jobs


def scrape_springdale_library():
    name = "Springdale Library"
    url  = "https://springdalelibrary.org/employment/"
    jobs = []
    try:
        r    = requests.get(url, headers=HEADERS, timeout=15)
        soup = BeautifulSoup(r.text, "html.parser")
        content = soup.find("main") or soup.find(class_=re.compile(r"content|entry|post", re.I)) or soup
        if any(x in content.get_text().lower() for x in ["no open position", "no current"]):
            log.info(f"{name}: no open positions")
            return jobs
        for a in content.find_all("a", href=True):
            title = a.get_text(strip=True)
            if not title or len(title) < 5:
                continue
            href = a["href"]
            if any(x in href for x in ["#", "mailto:", "tel:", "/wp-"]):
                continue
            ok, reason = is_relevant(title)
            if ok:
                full_url = href if href.startswith("http") else "https://springdalelibrary.org" + href
                jobs.append(make_job(name, title, full_url, "Library",
                                     category="community", location="Springdale, AR",
                                     match_reason=reason))
    except Exception as e:
        log.error(f"{name}: {e}")
    log.info(f"{name}: {len(jobs)} jobs")
    return jobs


def scrape_jbu():
    name = "JBU"
    url  = "https://www.jbu.edu/human-resources/staff-job-listings/"
    jobs = []
    try:
        r       = requests.get(url, headers=HEADERS, timeout=15)
        soup    = BeautifulSoup(r.text, "html.parser")
        content = soup.find("main") or soup.find(id=re.compile(r"content|main", re.I)) or soup
        skip    = ["#", "mailto:", "facebook", "twitter", "linkedin", "instagram",
                   "jbu.edu/about", "jbu.edu/admissions", "jbu.edu/student",
                   "jbu.edu/academic", "catalog", "calendar", "news", "giving", "alumni"]
        for a in content.find_all("a", href=True):
            title = a.get_text(strip=True)
            if not title or len(title) < 5:
                continue
            href = a["href"]
            if any(x in href for x in skip):
                continue
            ok, reason = is_relevant(title)
            if ok:
                full_url = href if href.startswith("http") else "https://www.jbu.edu" + href
                jobs.append(make_job(name, title, full_url, "JBU",
                                     category="community", location="Siloam Springs, AR",
                                     match_reason=reason))
    except Exception as e:
        log.error(f"{name}: {e}")
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
    jobs = []
    try:
        r    = requests.get(url, headers=HEADERS, timeout=20)
        soup = BeautifulSoup(r.text, "html.parser")
        added = set()
        for a in soup.find_all("a", href=re.compile(r"/jobs/\d+|/postings/\d+", re.I)):
            href  = a["href"]
            title = a.get_text(strip=True)
            if not title or len(title) < 5 or href in added:
                continue
            added.add(href)
            full_url   = href if href.startswith("http") else "https://jobs.okstate.edu" + href
            ok, reason = is_relevant(title)
            if ok:
                jobs.append(make_job(name, title, full_url, "PeopleAdmin",
                                     category="community", location="Stillwater, OK",
                                     match_reason=reason))
    except Exception as e:
        log.error(f"{name}: {e}")
    log.info(f"{name}: {len(jobs)} jobs")
    return jobs


def scrape_adp_nwa():
    name = "ADP (NWA)"
    url  = (
        "https://workforcenow.adp.com/mascsr/default/mdf/recruitment/recruitment.html"
        "?cid=dd3989d6-a17f-4803-bdaa-54bf26faf499&ccId=19000101_000001&lang=en_US"
    )
    jobs = []
    soup = pw_get_soup(url, wait=5)
    if not soup:
        return jobs
    added = set()
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
                                 category="community", location="NWA, AR",
                                 match_reason=reason))
    log.info(f"{name}: {len(jobs)} jobs")
    return jobs


# ──────────────────────────────────────────────────────────────────────────────
# FUNERAL
# ──────────────────────────────────────────────────────────────────────────────

def scrape_nfda():
    name = "NFDA Career Center"
    url  = "https://www.nfda.org/career-center"
    jobs = []
    try:
        r    = requests.get(url, headers=HEADERS, timeout=20)
        soup = BeautifulSoup(r.text, "html.parser")
        added = set()
        for a in soup.find_all("a", href=True):
            href  = a["href"]
            title = a.get_text(strip=True)
            if not title or len(title) < 5 or href in added:
                continue
            if not any(x in href.lower() for x in ["job", "career", "posting", "position", "listing"]):
                continue
            added.add(href)
            parent = a.find_parent(["li", "div", "tr", "article"])
            loc = ""
            if parent:
                m = LOC_REGEX.search(parent.get_text())
                loc = m.group(0) if m else ""
            if not is_valid_location(loc):
                continue
            full_url   = href if href.startswith("http") else "https://www.nfda.org" + href
            ok, reason = is_relevant(title)
            if ok:
                jobs.append(make_job(name, title, full_url, "NFDA",
                                     category="funeral", location=loc, match_reason=reason))
    except Exception as e:
        log.error(f"{name}: {e}")
    log.info(f"{name}: {len(jobs)} jobs")
    return jobs


def scrape_connecting_directors():
    name = "Connecting Directors"
    url  = "https://www.connectingdirectors.com/jobs"
    jobs = []
    try:
        r    = requests.get(url, headers=HEADERS, timeout=20)
        soup = BeautifulSoup(r.text, "html.parser")
        added = set()
        for a in soup.find_all("a", href=True):
            href  = a["href"]
            title = a.get_text(strip=True)
            if not title or len(title) < 5 or href in added:
                continue
            if not any(x in href.lower() for x in ["job", "career", "position", "listing", "opportunity"]):
                continue
            added.add(href)
            parent = a.find_parent(["li", "div", "tr", "article"])
            loc = ""
            if parent:
                m = LOC_REGEX.search(parent.get_text())
                loc = m.group(0) if m else ""
            if not is_valid_location(loc):
                continue
            full_url   = href if href.startswith("http") else "https://www.connectingdirectors.com" + href
            ok, reason = is_relevant(title)
            if ok:
                jobs.append(make_job(name, title, full_url, "ConnectingDirectors",
                                     category="funeral", location=loc, match_reason=reason))
    except Exception as e:
        log.error(f"{name}: {e}")
    log.info(f"{name}: {len(jobs)} jobs")
    return jobs


# ──────────────────────────────────────────────────────────────────────────────
# ORCHESTRATION
# ──────────────────────────────────────────────────────────────────────────────

def scrape_all():
    all_jobs = []

    log.info("── Freight & Logistics ──")
    all_jobs.extend(scrape_arcbest());           time.sleep(2)
    for s in WORKDAY_SOURCES:
        if s["category"] == "freight":
            all_jobs.extend(scrape_workday(s));  time.sleep(1)
    all_jobs.extend(scrape_tyson());             time.sleep(2)
    all_jobs.extend(scrape_xpo());               time.sleep(2)
    all_jobs.extend(scrape_echo());              time.sleep(2)

    log.info("── Banking ──")
    all_jobs.extend(scrape_arvest());            time.sleep(2)
    for s in WORKDAY_SOURCES:
        if s["category"] == "banking":
            all_jobs.extend(scrape_workday(s));  time.sleep(1)
    all_jobs.extend(scrape_first_national());    time.sleep(2)
    all_jobs.extend(scrape_regions());           time.sleep(2)
    all_jobs.extend(scrape_bofa());              time.sleep(2)

    log.info("── Corporate ──")
    all_jobs.extend(scrape_walmart_search());    time.sleep(2)

    log.info("── Community ──")
    # CivicEngage city pages (Playwright)
    all_jobs.extend(scrape_civicengage("Rogers (City)",     "https://www.rogersar.gov/Jobs.aspx",            "Rogers, AR"))
    time.sleep(2)
    all_jobs.extend(scrape_civicengage("Bentonville (City)","https://www.bentonvillear.com/1414/Employment-Opportunities", "Bentonville, AR"))
    time.sleep(2)
    all_jobs.extend(scrape_civicengage("Bella Vista (City)","https://recruiting.paylocity.com/recruiting/jobs/All/b1e8c19e-977f-41ec-89e7-a138ab6e72eb/City-of-Bella-Vista", "Bella Vista, AR"))
    time.sleep(2)
    all_jobs.extend(scrape_civicengage("Lowell (City)",     "https://www.lowellarkansas.gov/jobs",           "Lowell, AR"))
    time.sleep(2)
    all_jobs.extend(scrape_civicengage("City of Stillwater","https://stillwaterok.gov/Jobs.aspx",            "Stillwater, OK"))
    time.sleep(2)
    all_jobs.extend(scrape_civicengage("City of Ponca City","https://www.poncacityok.gov/Jobs.aspx",         "Ponca City, OK"))
    time.sleep(2)
    # GovernmentJobs pages (requests)
    all_jobs.extend(scrape_governmentjobs("Fayetteville (City)", "fayettevillear", "Fayetteville, AR"))
    time.sleep(1)
    all_jobs.extend(scrape_governmentjobs("Springdale (City)",   "springdalear",   "Springdale, AR"))
    time.sleep(1)
    # Other community
    all_jobs.extend(scrape_washington_county()); time.sleep(1)
    all_jobs.extend(scrape_springdale_library()); time.sleep(1)
    all_jobs.extend(scrape_jbu());               time.sleep(1)
    all_jobs.extend(scrape_osu());               time.sleep(1)
    all_jobs.extend(scrape_adp_nwa());           time.sleep(2)
    # Workday community (UAF, NWACC)
    for s in WORKDAY_SOURCES:
        if s["category"] == "community":
            all_jobs.extend(scrape_workday(s));  time.sleep(1)

    log.info("── Funeral / Death care ──")
    all_jobs.extend(scrape_nfda());              time.sleep(2)
    all_jobs.extend(scrape_connecting_directors()); time.sleep(2)

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


# ──────────────────────────────────────────────────────────────────────────────
# MAIN
# ──────────────────────────────────────────────────────────────────────────────

def main():
    log.info("── Customer Support Tracker starting ──")
    old_data  = load_jobs()
    new_jobs  = scrape_all()

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
