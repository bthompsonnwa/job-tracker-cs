#!/usr/bin/env python3
"""
Amy's Job Tracker — Freight / Banking / Corporate / Remote / Funeral
Scrapes 13+ sources across AR, OK, MO, KS + Remote.
Updates docs/jobs.json for the GitHub Pages dashboard.
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
# GEOGRAPHIC FILTER  (AR · OK · MO · KS · TX · Remote)
# ──────────────────────────────────────────────────────────────────────────────

VALID_STATES = {
    "ar", "arkansas",
    "ok", "oklahoma",
    "mo", "missouri",
    "ks", "kansas",
    # Texas removed per user request
}

REMOTE_WORDS = {"remote", "work from home", "wfh", "virtual", "anywhere", "telecommute"}


def is_valid_location(loc: str) -> bool:
    """Return True if the location is blank (unknown) or in a target state/remote."""
    if not loc or loc.strip() == "":
        return True          # can't tell → don't exclude
    l = loc.lower()
    for kw in REMOTE_WORDS:
        if kw in l:
            return True
    for state in VALID_STATES:
        # word-boundary style check
        if re.search(r"\b" + re.escape(state) + r"\b", l):
            return True
    return False


# ──────────────────────────────────────────────────────────────────────────────
# KEYWORD FILTERS
# ──────────────────────────────────────────────────────────────────────────────

INCLUDE_KEYWORDS = [
    # Customer-facing
    "customer service", "customer support", "customer care", "customer success",
    "customer relations", "customer experience", "client services", "client support",
    "client relations", "guest services",
    # Account / Admin support (no sales)
    "account coordinator", "account representative",
    "account specialist",
    # Admin / Office
    "administrative assistant", "administrative coordinator", "administrative specialist",
    "office manager", "office coordinator", "office administrator",
    "executive assistant", "operations assistant", "operations coordinator",
    "operations specialist", "operations support", "operations analyst",
    "data entry", "data coordinator", "records coordinator",
    "receptionist", "front desk", "office support", "office clerk",
    "file clerk", "records clerk", "document specialist",
    # Entry-level / General
    "entry level", "entry-level",
    "associate", "trainee", "clerk",
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
    "bank teller", "teller", "personal banker", "relationship banker",
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
    # Funeral / Death care (remote services)
    "funeral", "mortuary", "death care", "bereavement",
    "funeral home", "funeral service", "cremation coordinator",
    "funeral coordinator", "funeral administrative", "funeral answering",
    "after-loss", "afterloss", "grief support coordinator",
]

# Applied only to remote job board scrapers (WWR, Remote.co) — much tighter
REMOTE_EXCLUDE_KEYWORDS = [
    "crypto", "blockchain", "web3", "nft", "defi",
    "video editor", "video production", "videographer",
    "graphic design", "graphic designer", "ux designer", "ui designer",
    "motion design", "illustrator",
    "copywriter", "content writer", "technical writer", "writer",
    "game developer", "game designer", "game artist",
    "software", "developer", "engineer", "coding", "programmer",
    "devops", "sre ", "cloud architect",
    "animator", "3d artist", "photographer",
    "trader", "trading", "quant",
    "attorney", "lawyer", "paralegal",
    "therapist", "counselor", "social worker",
    "teacher", "tutor", "instructor",
    "recruiter", "talent acquisition",
    "cfo", "coo", "cto", "vice president", "vp ",
]

HARD_EXCLUDE_KEYWORDS = [
    # Driving / physical labour
    "truck driver", "cdl driver", "forklift operator", "warehouse associate",
    "warehouse worker", "picker", "packer", "stocker", "dock worker",
    "material handler", "janitor", "custodian", "groundskeeper",
    # Medical
    "registered nurse", "school nurse", " rn ", "nurse practitioner",
    "physician", "pharmacist", "physical therapist", "occupational therapist",
    # Technical / Engineering (too senior/specialized)
    "software engineer", "software developer", "web developer", "devops",
    "data scientist", "machine learning", "cybersecurity", "network engineer",
    "electrical engineer", "mechanical engineer", "civil engineer",
    "maintenance mechanic", "hvac technician", "electrician", "plumber",
    # Senior management (keep account manager, branch manager, office manager)
    "vice president", "vp ", "chief ", "cto", "cfo", "coo",
    "regional manager", "district manager", "general manager",
    "senior manager", "store manager", "marketing manager",
    "product manager", "people manager", "hiring manager",
    # Academic
    "professor", "faculty", "instructor", "teacher",
    # Echo / marketing noise
    "request a quote", "get a quote", "truck load quote",
    "full truckload", "less than truckload", "learn more",
    "view all", "see all jobs", "see open", "join our team",
]

# ──────────────────────────────────────────────────────────────────────────────
# SOURCE REGISTRY  (shown in dashboard Sources panel)
# ──────────────────────────────────────────────────────────────────────────────

ALL_SOURCES = [
    # Freight & Logistics
    {"name": "ArcBest",        "url": "https://careers.arcb.com/",                                             "category": "freight"},
    {"name": "J.B. Hunt",      "url": "https://jbhunt.wd501.myworkdayjobs.com/Careers",                        "category": "freight"},
    {"name": "Tyson Foods",    "url": "https://www.tysonfoods.com/careers",                                    "category": "freight"},
    {"name": "XPO",            "url": "https://jobs.xpo.com/search/",                                          "category": "freight"},
    {"name": "Echo Global",    "url": "https://www.echo.com/company/careers/open-positions/",                  "category": "freight"},
    # Banking
    {"name": "Arvest Bank",    "url": "https://css-arvest-prd.inforcloudsuite.com/hcm/Jobs/form/JobBoard%28ARV,EXTERNAL%29.JobSearchCompositeForm?navigation=JobBoard%28ARV,EXTERNAL%29.JobSearchCompositeFormNav&csk.JobBoard=EXTERNAL&csk.showusingxi=true&csk.HROrganization=ARV", "category": "banking"},
    {"name": "Simmons Bank",   "url": "https://simmonsbank.wd5.myworkdayjobs.com/SimmonsCareers",              "category": "banking"},
    {"name": "First National Bank", "url": "https://recruiting.paylocity.com/recruiting/jobs/All/dcb49edc-c676-411b-8b7b-104a72fec402/The-First-National-Bank-of-Fort-Smith", "category": "banking"},
    {"name": "Regions Bank",   "url": "https://careers.regions.com/us/en/search-results",                     "category": "banking"},
    {"name": "Bank of America","url": "https://careers.bankofamerica.com/en-us/job-search?ref=search&start=0&rows=10&search=getAllJobs&filters=area%3DAdministration%2Carea%3DCustomer+Service%2Carea%3DOperations+%26+Support", "category": "banking"},
    # Corporate
    {"name": "Walmart",        "url": "https://walmart.wd5.myworkdayjobs.com/WalmartExternal",                 "category": "corporate"},
    # Remote
    {"name": "We Work Remotely", "url": "https://weworkremotely.com/categories/remote-customer-service-jobs", "category": "remote"},
    {"name": "Remote.co",      "url": "https://remote.co/remote-jobs/customer-service/",                      "category": "remote"},
    # Funeral / Death care
    {"name": "NFDA Career Center",       "url": "https://www.nfda.org/career-center",                         "category": "funeral"},
    {"name": "Connecting Directors Jobs", "url": "https://www.connectingdirectors.com/jobs",                   "category": "funeral"},
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
        "district":     source,      # "district" kept for dashboard compat
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
    """Playwright helper — renders JS-heavy pages, returns BeautifulSoup or None."""
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
# WORKDAY  (J.B. Hunt · Simmons Bank · Walmart)
# ──────────────────────────────────────────────────────────────────────────────

WORKDAY_SOURCES = [
    {
        "name":     "J.B. Hunt",
        "category": "freight",
        "api_url":  "https://jbhunt.wd501.myworkdayjobs.com/wday/cxs/jbhunt/Careers/jobs",
        "base_url": "https://jbhunt.wd501.myworkdayjobs.com/en-US/Careers",
    },
    {
        "name":     "Simmons Bank",
        "category": "banking",
        "api_url":  "https://simmonsbank.wd5.myworkdayjobs.com/wday/cxs/simmonsbank/SimmonsCareers/jobs",
        "base_url": "https://simmonsbank.wd5.myworkdayjobs.com/en-US/SimmonsCareers",
    },
    {
        "name":     "Walmart",
        "category": "corporate",
        "api_url":  "https://walmart.wd5.myworkdayjobs.com/wday/cxs/walmart/WalmartExternal/jobs",
        "base_url": "https://walmart.wd5.myworkdayjobs.com/en-US/WalmartExternal",
    },
]


def scrape_workday(source):
    name     = source["name"]
    api_url  = source["api_url"]
    category = source["category"]
    jobs     = []
    offset   = 0
    limit    = 20
    api_headers = {**HEADERS, "Content-Type": "application/json", "Accept": "application/json"}

    while True:
        payload = {"limit": limit, "offset": offset, "searchText": "", "appliedFacets": {}}
        try:
            r    = requests.post(api_url, json=payload, headers=api_headers, timeout=25)
            data = r.json()
        except Exception as e:
            log.error(f"{name} Workday API error: {e}")
            break

        postings = data.get("jobPostings", [])
        if not postings:
            break

        for p in postings:
            title = p.get("title", "").strip()
            loc   = p.get("locationsText", "") or p.get("primaryLocation", "")
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

        total = data.get("total", 0)
        offset += limit
        if offset >= total:
            break
        time.sleep(0.5)

    log.info(f"{name}: {len(jobs)} relevant jobs (Workday)")
    return jobs


# ──────────────────────────────────────────────────────────────────────────────
# ARCBEST  (CareersMarketplace — Playwright)
# ──────────────────────────────────────────────────────────────────────────────

def scrape_arcbest():
    name = "ArcBest"
    # Base job list — unfiltered so we catch all office/admin roles
    url  = "https://careers.arcb.com/"
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
        if not any(x in href.lower() for x in ["openposition", "jobdetail", "careers.arcb", "position", "req"]):
            continue
        added.add(href)
        # Try to get location from parent element
        parent = a.find_parent(["li", "div", "tr", "article"])
        loc    = ""
        if parent:
            loc_m = re.search(r"\b(Fort Smith|Fayetteville|Springdale|Rogers|Bentonville|NWA|Remote|Arkansas|AR)\b",
                              parent.get_text(), re.I)
            if loc_m:
                loc = loc_m.group(0)
        if not is_valid_location(loc):
            continue
        full_url   = href if href.startswith("http") else "https://careers.arcb.com" + href
        ok, reason = is_relevant(title)
        if ok:
            jobs.append(make_job(name, title, full_url, "CareersMarketplace",
                                 category="freight", location=loc, match_reason=reason))
    log.info(f"{name}: {len(jobs)} jobs")
    return jobs


# ──────────────────────────────────────────────────────────────────────────────
# TYSON FOODS  (custom site — requests)
# ──────────────────────────────────────────────────────────────────────────────

def scrape_tyson():
    name = "Tyson Foods"
    # Tyson uses a custom careers site. Try the JSON API first, fall back to HTML.
    jobs = []

    # Attempt: SmartRecruiters-style JSON endpoint
    api_url = "https://careers.tysonfoods.com/api/apply/v2/jobs?domain=tysonfoods.com&start=0&num=100&exclude_pid=&pid=&domain=tysonfoods.com&sort_by=relevance"
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
        log.warning(f"{name} API attempt: {e}")

    # Fallback: Playwright on careers page
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
        loc    = ""
        if parent:
            loc_m = re.search(r"\b(AR|OK|MO|KS|Arkansas|Oklahoma|Missouri|Kansas|Remote)\b",
                              parent.get_text(), re.I)
            loc   = loc_m.group(0) if loc_m else ""
        if not is_valid_location(loc):
            continue
        full_url   = href if href.startswith("http") else "https://www.tysonfoods.com" + href
        ok, reason = is_relevant(title)
        if ok:
            jobs.append(make_job(name, title, full_url, "Tyson",
                                 category="freight", location=loc, match_reason=reason))
    log.info(f"{name}: {len(jobs)} jobs (Playwright fallback)")
    return jobs


# ──────────────────────────────────────────────────────────────────────────────
# XPO  (requests)
# ──────────────────────────────────────────────────────────────────────────────

def scrape_xpo():
    name = "XPO"
    # Try their JSON API first
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

    # Fallback: scrape the search page
    url  = "https://jobs.xpo.com/search/?searchby=distance&createNewAlert=false&q=&d=75&lat=35.8&lon=-93.3"
    soup = pw_get_soup(url, wait=5)
    if not soup:
        return jobs
    added = set()
    for a in soup.find_all("a", href=re.compile(r"/job/", re.I)):
        title    = a.get_text(strip=True)
        href     = a["href"]
        if not title or href in added:
            continue
        added.add(href)
        parent = a.find_parent(["li", "div", "tr", "article"])
        loc    = ""
        if parent:
            loc_m = re.search(r"\b(AR|OK|MO|KS|Arkansas|Oklahoma|Missouri|Kansas|Remote)\b",
                              parent.get_text(), re.I)
            loc   = loc_m.group(0) if loc_m else ""
        if not is_valid_location(loc):
            continue
        full_url   = href if href.startswith("http") else "https://jobs.xpo.com" + href
        ok, reason = is_relevant(title)
        if ok:
            jobs.append(make_job(name, title, full_url, "XPO",
                                 category="freight", location=loc, match_reason=reason))
    log.info(f"{name}: {len(jobs)} jobs (HTML fallback)")
    return jobs


# ──────────────────────────────────────────────────────────────────────────────
# ECHO GLOBAL LOGISTICS  (Playwright — JS button-rendered)
# ──────────────────────────────────────────────────────────────────────────────

# Words that must appear in a title for it to be treated as a job listing
_ECHO_JOB_WORDS = re.compile(
    r"\b(coordinator|specialist|representative|analyst|associate|agent|"
    r"manager|advisor|support|service|administrator|assistant|"
    r"recruiter|broker|planner|processor|clerk|trainee|"
    r"brokerage|logistics|operations|sales|billing|claims|"
    r"executive|account|dispatcher|dispatch)\b",
    re.I
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
        # Must link to something that looks like a job posting
        if not any(x in href.lower() for x in ["job", "career", "lever.co", "greenhouse", "workday",
                                                 "position", "req", "apply", "opening"]):
            continue
        # Title must contain at least one job-role word
        if not _ECHO_JOB_WORDS.search(title):
            continue
        # Skip obvious CTAs and nav items
        if any(x in title.lower() for x in ["request", "quote", "learn more", "view all",
                                              "see all", "join our", "login", "apply now",
                                              "home", "about", "contact", "truckload freight",
                                              "less than", "full truckload"]):
            continue
        added.add(href)
        parent = a.find_parent(["li", "div", "section", "article"])
        loc    = ""
        if parent:
            loc_m = re.search(r"\b(AR|OK|MO|KS|Arkansas|Oklahoma|Missouri|Kansas|Remote|Chicago)\b",
                              parent.get_text(), re.I)
            loc   = loc_m.group(0) if loc_m else ""
        if not is_valid_location(loc):
            continue
        full_url   = href if href.startswith("http") else "https://www.echo.com" + href
        ok, reason = is_relevant(title)
        if ok:
            jobs.append(make_job(name, title, full_url, "Echo",
                                 category="freight", location=loc, match_reason=reason))
    log.info(f"{name}: {len(jobs)} jobs")
    return jobs


# ──────────────────────────────────────────────────────────────────────────────
# ARVEST BANK  (Infor CloudSuite — Playwright)
# ──────────────────────────────────────────────────────────────────────────────

def scrape_arvest():
    name = "Arvest Bank"
    url  = (
        "https://css-arvest-prd.inforcloudsuite.com/hcm/Jobs/form/"
        "JobBoard%28ARV,EXTERNAL%29.JobSearchCompositeForm"
        "?navigation=JobBoard%28ARV,EXTERNAL%29.JobSearchCompositeFormNav"
        "&csk.JobBoard=EXTERNAL&csk.showusingxi=true&csk.HROrganization=ARV"
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
        loc    = ""
        if parent:
            loc_m = re.search(
                r"\b(AR|OK|MO|KS|Arkansas|Oklahoma|Missouri|Kansas|Remote"
                r"|Fayetteville|Bentonville|Rogers|Springdale|Fort Smith"
                r"|Tulsa|Oklahoma City|Kansas City|Springfield)\b",
                parent.get_text(), re.I)
            loc = loc_m.group(0) if loc_m else ""
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
# FIRST NATIONAL BANK OF FORT SMITH  (Paylocity — Playwright)
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
    soup = pw_get_soup(base, wait=6)
    if not soup:
        return jobs
    added = set()

    def _parse_page(s):
        for a in s.find_all("a", href=True):
            href  = a["href"]
            title = a.get_text(strip=True)
            if not title or len(title) < 5 or href in added:
                continue
            if not any(x in href.lower() for x in ["/job/", "jobdetails", "careers.regions"]):
                continue
            added.add(href)
            parent = a.find_parent(["li", "div", "tr", "article"])
            loc    = ""
            if parent:
                loc_m = re.search(
                    r"\b(AR|OK|MO|KS|Arkansas|Oklahoma|Missouri|Kansas|Remote"
                    r"|Little Rock|Fort Smith|Fayetteville|Tulsa|Kansas City|St\.? Louis)\b",
                    parent.get_text(), re.I)
                loc = loc_m.group(0) if loc_m else ""
            if not is_valid_location(loc):
                continue
            full_url   = href if href.startswith("http") else "https://careers.regions.com" + href
            ok, reason = is_relevant(title)
            if ok:
                jobs.append(make_job(name, title, full_url, "Regions",
                                     category="banking", location=loc, match_reason=reason))

    _parse_page(soup)

    # Paginate: try pages 2–10
    for page in range(2, 11):
        page_url = f"{base}?pg={page}"
        s = pw_get_soup(page_url, wait=4)
        if not s:
            break
        prev_count = len(jobs)
        _parse_page(s)
        if len(jobs) == prev_count:
            break     # no new jobs → stop paginating
        time.sleep(1)

    log.info(f"{name}: {len(jobs)} jobs")
    return jobs


# ──────────────────────────────────────────────────────────────────────────────
# BANK OF AMERICA  (pre-filtered URL — Playwright)
# ──────────────────────────────────────────────────────────────────────────────

def scrape_bofa():
    name = "Bank of America"
    url  = (
        "https://careers.bankofamerica.com/en-us/job-search"
        "?ref=search&start=0&rows=25&search=getAllJobs"
        "&filters=area%3DAdministration%2Carea%3DCustomer+Service%2Carea%3DOperations+%26+Support"
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
        loc    = ""
        if parent:
            loc_m = re.search(
                r"\b(AR|OK|MO|KS|Arkansas|Oklahoma|Missouri|Kansas|Remote"
                r"|Little Rock|Tulsa|Kansas City|St\.? Louis)\b",
                parent.get_text(), re.I)
            loc = loc_m.group(0) if loc_m else ""
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
# WE WORK REMOTELY  (public HTML — requests, strict remote filter)
# ──────────────────────────────────────────────────────────────────────────────

def _is_good_remote_title(title: str) -> bool:
    """Extra guard for remote boards — reject noise categories."""
    t = title.lower()
    for bad in REMOTE_EXCLUDE_KEYWORDS:
        if bad.strip() in t:
            return False
    return True


def scrape_weworkremotely():
    name = "We Work Remotely"
    urls = [
        "https://weworkremotely.com/categories/remote-customer-service-jobs",
        "https://weworkremotely.com/categories/remote-management-and-finance-jobs",
    ]
    jobs  = []
    added = set()
    for url in urls:
        try:
            r    = requests.get(url, headers=HEADERS, timeout=15)
            soup = BeautifulSoup(r.text, "html.parser")
            for a in soup.find_all("a", href=re.compile(r"/remote-jobs/")):
                href  = a["href"]
                title = a.get_text(strip=True)
                if not title or len(title) < 5 or href in added:
                    continue
                if not _is_good_remote_title(title):
                    continue
                added.add(href)
                full_url   = "https://weworkremotely.com" + href if href.startswith("/") else href
                ok, reason = is_relevant(title)
                if ok:
                    jobs.append(make_job(name, title, full_url, "WWR",
                                         category="remote", location="Remote",
                                         match_reason=reason))
        except Exception as e:
            log.error(f"{name} ({url}): {e}")
        time.sleep(1)
    log.info(f"{name}: {len(jobs)} jobs")
    return jobs


# ──────────────────────────────────────────────────────────────────────────────
# REMOTE.CO  (public HTML — requests, strict remote filter)
# ──────────────────────────────────────────────────────────────────────────────

def scrape_remoteco():
    name = "Remote.co"
    urls = [
        "https://remote.co/remote-jobs/customer-service/",
        "https://remote.co/remote-jobs/administrative/",
    ]
    jobs  = []
    added = set()
    for url in urls:
        try:
            r    = requests.get(url, headers=HEADERS, timeout=15)
            soup = BeautifulSoup(r.text, "html.parser")
            for a in soup.find_all("a", href=re.compile(r"/remote-jobs/")):
                href  = a["href"]
                title = a.get_text(strip=True)
                if not title or len(title) < 5 or href in added:
                    continue
                # Skip category index links
                if re.search(r"/remote-jobs/[^/]+/?$", href) and "/" not in href.split("/remote-jobs/")[1].rstrip("/"):
                    continue
                if not _is_good_remote_title(title):
                    continue
                added.add(href)
                full_url   = "https://remote.co" + href if href.startswith("/") else href
                ok, reason = is_relevant(title)
                if ok:
                    jobs.append(make_job(name, title, full_url, "Remote.co",
                                         category="remote", location="Remote",
                                         match_reason=reason))
        except Exception as e:
            log.error(f"{name} ({url}): {e}")
        time.sleep(1)
    log.info(f"{name}: {len(jobs)} jobs")
    return jobs


# ──────────────────────────────────────────────────────────────────────────────
# NFDA CAREER CENTER  (funeral industry — requests)
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
            loc    = ""
            if parent:
                loc_m = re.search(
                    r"\b(AR|OK|MO|KS|Arkansas|Oklahoma|Missouri|Kansas|Remote|Online|Virtual)\b",
                    parent.get_text(), re.I)
                loc = loc_m.group(0) if loc_m else ""
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


# ──────────────────────────────────────────────────────────────────────────────
# CONNECTING DIRECTORS  (funeral industry — requests)
# ──────────────────────────────────────────────────────────────────────────────

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
            loc    = ""
            if parent:
                loc_m = re.search(
                    r"\b(AR|OK|MO|KS|Arkansas|Oklahoma|Missouri|Kansas|Remote|Online|Virtual)\b",
                    parent.get_text(), re.I)
                loc = loc_m.group(0) if loc_m else ""
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
    all_jobs.extend(scrape_arcbest());          time.sleep(2)
    for s in WORKDAY_SOURCES:
        if s["category"] == "freight":
            all_jobs.extend(scrape_workday(s)); time.sleep(1)
    all_jobs.extend(scrape_tyson());            time.sleep(2)
    all_jobs.extend(scrape_xpo());              time.sleep(2)
    all_jobs.extend(scrape_echo());             time.sleep(2)

    log.info("── Banking ──")
    all_jobs.extend(scrape_arvest());           time.sleep(2)
    for s in WORKDAY_SOURCES:
        if s["category"] == "banking":
            all_jobs.extend(scrape_workday(s)); time.sleep(1)
    all_jobs.extend(scrape_first_national());   time.sleep(2)
    all_jobs.extend(scrape_regions());          time.sleep(2)
    all_jobs.extend(scrape_bofa());             time.sleep(2)

    log.info("── Corporate ──")
    for s in WORKDAY_SOURCES:
        if s["category"] == "corporate":
            all_jobs.extend(scrape_workday(s)); time.sleep(1)

    log.info("── Remote ──")
    all_jobs.extend(scrape_weworkremotely());   time.sleep(1)
    all_jobs.extend(scrape_remoteco());         time.sleep(1)

    log.info("── Funeral / Death care ──")
    all_jobs.extend(scrape_nfda());             time.sleep(2)
    all_jobs.extend(scrape_connecting_directors()); time.sleep(2)

    # Deduplicate by ID
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
    log.info("── Amy's Job Tracker starting ──")
    old_data  = load_jobs()
    new_jobs  = scrape_all()

    # Preserve first_seen dates for existing jobs
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
