#!/usr/bin/env python3
"""
Indeed Job Finder via ScraperAPI — No browser needed.
Routes requests through residential IPs → Indeed returns full job results.
Jobs saved with clickable Apply URLs → emailed to user for 1-click apply.
"""

import json
import logging
import os
import re
import time
import random
from datetime import datetime
from pathlib import Path

import requests
from bs4 import BeautifulSoup

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("indeed-apply")

# Config
SCRAPER_API_KEY = os.environ.get("SCRAPER_API_KEY", "")
MAX_APPLY = int(os.environ.get("MAX_APPLY", "15"))
SCRAPER_API_URL = "https://api.scraperapi.com/"

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
DATA_DIR.mkdir(exist_ok=True)

SEARCH_QUERIES = [
    "Java Spring Boot contract remote",
    "Java developer contract C2C remote",
    "Java microservices Kafka contract",
    "Spring Boot backend developer contract",
    "Java AWS Kubernetes contract remote",
]

# Load from shared config if available
CONFIG_PATH = Path(__file__).resolve().parent.parent / "config" / "shared_skills.json"
if CONFIG_PATH.exists():
    try:
        with open(CONFIG_PATH) as f:
            config = json.load(f)
        SEARCH_QUERIES = config.get("search_terms", {}).get("indeed", SEARCH_QUERIES)
        logger.info(f"  Loaded {len(SEARCH_QUERIES)} search queries from shared config")
    except Exception:
        pass

SESSION_START = time.time()
SESSION_LIMIT = 25 * 60  # 25 minutes


# ─── Deduplication ────────────────────────────────────────────────────────────

def load_applied():
    path = DATA_DIR / "applied_indeed.json"
    if path.exists():
        with open(path) as f:
            data = json.load(f)
            if isinstance(data, dict):
                return data
            else:
                return {"ids": list(data), "titles": [], "urls": []}
    return {"ids": [], "titles": [], "urls": []}


def save_applied(applied):
    path = DATA_DIR / "applied_indeed.json"
    with open(path, "w") as f:
        json.dump(applied, f)


def is_already_applied(job, applied):
    job_id = job.get("job_id", "")
    title_company = f"{job.get('title', '').lower()}|{job.get('company', '').lower()}"
    url = job.get("url", "")
    if job_id in applied.get("ids", []):
        return True
    if title_company in applied.get("titles", []):
        return True
    if url in applied.get("urls", []):
        return True
    return False


def mark_applied(job, applied):
    applied.setdefault("ids", []).append(job.get("job_id", ""))
    title_company = f"{job.get('title', '').lower()}|{job.get('company', '').lower()}"
    applied.setdefault("titles", []).append(title_company)
    applied.setdefault("urls", []).append(job.get("url", ""))


# ─── ScraperAPI Request ───────────────────────────────────────────────────────

def fetch_indeed_page(query, page=0):
    """Fetch Indeed search page via ScraperAPI (residential proxy)."""
    indeed_url = (
        f"https://www.indeed.com/jobs?"
        f"q={query.replace(' ', '+')}&l=Remote&fromage=3&jt=contract&start={page * 10}"
    )
    params = {
        "api_key": SCRAPER_API_KEY,
        "url": indeed_url,
        "render": "true",
    }
    try:
        resp = requests.get(SCRAPER_API_URL, params=params, timeout=60)
        if resp.status_code == 200:
            return resp.text
        else:
            logger.warning(f"    ScraperAPI returned {resp.status_code}")
            return None
    except Exception as e:
        logger.warning(f"    Request failed: {e}")
        return None


# ─── Parse Jobs ───────────────────────────────────────────────────────────────

def parse_jobs_json(html):
    """Parse jobs from Indeed's embedded JSON (most stable method)."""
    jobs = []
    try:
        match = re.search(
            r'window\.mosaic\.providerData\["mosaic-provider-jobcards"\]\s*=\s*(\{.*?\});\s*</script>',
            html, re.DOTALL
        )
        if not match:
            # Try alternative pattern
            match = re.search(
                r'"mosaic-provider-jobcards":\s*(\{.*?"results"\s*:\s*\[.*?\]\s*\})',
                html, re.DOTALL
            )
        if match:
            data = json.loads(match.group(1))
            results = data.get("metaData", {}).get("mosaicProviderJobCardsModel", {}).get("results", [])
            if not results:
                # Try alternative path
                results = data.get("results", [])
            for r in results:
                jobs.append({
                    "title": r.get("title", "Unknown"),
                    "company": r.get("company", "Unknown"),
                    "location": r.get("formattedLocation", ""),
                    "salary": r.get("salarySnippet", {}).get("text", ""),
                    "job_id": r.get("jobkey", ""),
                    "url": f"https://www.indeed.com/viewjob?jk={r.get('jobkey', '')}",
                })
    except (json.JSONDecodeError, AttributeError) as e:
        logger.debug(f"    JSON parse failed: {e}")
    return jobs


def parse_jobs_html(html):
    """Fallback: parse jobs from HTML using BeautifulSoup."""
    jobs = []
    try:
        soup = BeautifulSoup(html, "html.parser")
        cards = soup.find_all("div", class_="job_seen_beacon")
        if not cards:
            # Try alternative selector
            cards = soup.find_all("li", class_=lambda c: c and "css-" in c and "eu4oa1w0" in c)
        for card in cards:
            title_el = card.select_one("h2.jobTitle span, h2 a span, a.jcs-JobTitle span")
            company_el = card.select_one("[data-testid='company-name'], span.companyName")
            link_el = card.select_one("a[data-jk], h2.jobTitle a, a.jcs-JobTitle")

            title = title_el.get_text(strip=True) if title_el else ""
            company = company_el.get_text(strip=True) if company_el else ""
            job_id = link_el.get("data-jk", "") if link_el else ""
            href = link_el.get("href", "") if link_el else ""

            if not job_id and href:
                m = re.search(r"jk=([a-f0-9]+)", href)
                if m:
                    job_id = m.group(1)

            if title and job_id:
                jobs.append({
                    "title": title,
                    "company": company or "Unknown",
                    "location": "",
                    "salary": "",
                    "job_id": job_id,
                    "url": f"https://www.indeed.com/viewjob?jk={job_id}",
                })
    except Exception as e:
        logger.debug(f"    HTML parse failed: {e}")
    return jobs


# ─── Search ───────────────────────────────────────────────────────────────────

def search_jobs(query):
    """Search Indeed for jobs matching query (up to 3 pages = 30 jobs)."""
    all_jobs = []
    for page in range(3):
        if time.time() - SESSION_START > SESSION_LIMIT:
            logger.info("⏰ Session time limit — stopping search")
            break

        logger.info(f"    Page {page + 1} for: {query}")
        html = fetch_indeed_page(query, page)
        if not html:
            break

        # Try JSON first (more stable), then HTML fallback
        jobs = parse_jobs_json(html)
        if not jobs:
            jobs = parse_jobs_html(html)

        if not jobs:
            logger.info(f"    No jobs found on page {page + 1}")
            break

        all_jobs.extend(jobs)
        logger.info(f"    Found {len(jobs)} jobs on page {page + 1}")

        # Don't fetch more pages if we have enough
        if len(all_jobs) >= MAX_APPLY * 2:
            break

        # Human delay between pages
        time.sleep(random.uniform(2, 4))

    return all_jobs


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    logger.info("=" * 60)
    logger.info("INDEED JOB FINDER (ScraperAPI — No Browser)")
    logger.info(f"Max jobs to process: {MAX_APPLY}")
    logger.info("=" * 60)

    if not SCRAPER_API_KEY:
        logger.error("❌ SCRAPER_API_KEY not set!")
        return

    applied = load_applied()
    results = []
    processed = 0

    # Search all queries
    all_jobs = []
    for query in SEARCH_QUERIES:
        if time.time() - SESSION_START > SESSION_LIMIT:
            break
        logger.info(f"  Searching: {query}")
        jobs = search_jobs(query)
        all_jobs.extend(jobs)
        logger.info(f"    Total so far: {len(all_jobs)}")
        time.sleep(random.uniform(2, 5))

    # Deduplicate
    unique_jobs = []
    seen = set()
    for job in all_jobs:
        if job["job_id"] in seen:
            continue
        if is_already_applied(job, applied):
            continue
        seen.add(job["job_id"])
        unique_jobs.append(job)

    logger.info(f"\n{'=' * 60}")
    logger.info(f"Total found: {len(all_jobs)}")
    logger.info(f"Unique new: {len(unique_jobs)}")
    logger.info(f"Already applied (skipped): {len(all_jobs) - len(unique_jobs)}")
    logger.info(f"{'=' * 60}\n")

    # Process jobs (mark as manual_apply with clickable URLs)
    for job in unique_jobs[:MAX_APPLY]:
        if time.time() - SESSION_START > SESSION_LIMIT:
            break

        result = {
            "title": job["title"],
            "company": job["company"],
            "url": job["url"],
            "status": "manual_apply",
            "error": "Click Easy Apply link in email",
        }
        results.append(result)
        mark_applied(job, applied)
        processed += 1
        logger.info(f"  📧 {job['title']} @ {job['company']} → {job['url']}")

    # Save
    save_applied(applied)

    results_path = DATA_DIR / "apply_results_indeed.json"
    with open(results_path, "w") as f:
        json.dump(results, f, indent=2)

    logger.info(f"\n{'=' * 60}")
    logger.info("INDEED COMPLETE")
    logger.info(f"  📧 Jobs found for email: {processed}")
    logger.info(f"  🔗 Each has a clickable Indeed Easy Apply link")
    logger.info(f"{'=' * 60}")


if __name__ == "__main__":
    main()
