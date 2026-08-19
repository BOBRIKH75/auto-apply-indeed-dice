#!/usr/bin/env python3
"""
Indeed Job Finder — FREE via python-jobspy (no API key needed).
Falls back to ScraperAPI if jobspy fails.

python-jobspy scrapes Indeed/LinkedIn/Glassdoor/ZipRecruiter directly.
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

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("indeed-apply")

# Config
SCRAPER_API_KEY = os.environ.get("SCRAPER_API_KEY", "")
MAX_APPLY = int(os.environ.get("MAX_APPLY", "15"))

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
DATA_DIR.mkdir(exist_ok=True)

SEARCH_QUERIES = [
    "Java Spring Boot contract remote",
    "Java developer contract C2C remote",
    "Java microservices Kafka contract",
    "Spring Boot backend developer contract",
    "Java AWS Kubernetes contract remote",
    "Senior Java developer remote contract",
    "Java backend engineer C2C",
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
SESSION_LIMIT = 12 * 60  # 12 minutes (jobspy is faster than ScraperAPI)


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


# ─── Job Search via python-jobspy (FREE — no API key) ─────────────────────────

def search_jobs_jobspy(query):
    """Search Indeed via python-jobspy (free, direct scraping)."""
    try:
        from jobspy import scrape_jobs
        jobs = scrape_jobs(
            site_name=["indeed"],
            search_term=query,
            location="USA",
            results_wanted=20,
            hours_old=72,  # Last 3 days
            job_type="contract",
            is_remote=True,
        )
        results = []
        for _, row in jobs.iterrows():
            job_url = str(row.get("job_url", ""))
            if not job_url or job_url == "nan":
                continue
            job_id = ""
            m = re.search(r"jk=([a-f0-9]+)", job_url)
            if m:
                job_id = m.group(1)
            elif "viewjob" in job_url:
                m = re.search(r"/([a-f0-9]{16,})", job_url)
                if m:
                    job_id = m.group(1)
            else:
                job_id = str(hash(job_url))[-12:]

            results.append({
                "title": str(row.get("title", "Unknown")),
                "company": str(row.get("company", "Unknown")),
                "location": str(row.get("location", "")),
                "salary": str(row.get("min_amount", "")) if row.get("min_amount") else "",
                "job_id": job_id,
                "url": job_url,
            })
        return results
    except Exception as e:
        logger.warning(f"    python-jobspy error: {e}")
        return []


def search_jobs_scraperapi(query):
    """Fallback: Search Indeed via ScraperAPI (paid, residential proxy)."""
    if not SCRAPER_API_KEY:
        return []
    try:
        import requests
        indeed_url = (
            f"https://www.indeed.com/jobs?"
            f"q={query.replace(' ', '+')}&l=Remote&fromage=3&jt=contract&start=0"
        )
        params = {
            "api_key": SCRAPER_API_KEY,
            "url": indeed_url,
            "render": "true",
        }
        resp = requests.get("https://api.scraperapi.com/", params=params, timeout=60)
        if resp.status_code != 200:
            logger.warning(f"    ScraperAPI returned {resp.status_code}")
            return []
        # Parse JSON from response
        from bs4 import BeautifulSoup
        match = re.search(
            r'window\.mosaic\.providerData\["mosaic-provider-jobcards"\]\s*=\s*(\{.*?\});\s*</script>',
            resp.text, re.DOTALL
        )
        if match:
            data = json.loads(match.group(1))
            results_data = data.get("metaData", {}).get("mosaicProviderJobCardsModel", {}).get("results", [])
            return [{
                "title": r.get("title", "Unknown"),
                "company": r.get("company", "Unknown"),
                "location": r.get("formattedLocation", ""),
                "salary": r.get("salarySnippet", {}).get("text", ""),
                "job_id": r.get("jobkey", ""),
                "url": f"https://www.indeed.com/viewjob?jk={r.get('jobkey', '')}",
            } for r in results_data]
        return []
    except Exception as e:
        logger.warning(f"    ScraperAPI error: {e}")
        return []


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    logger.info("=" * 60)
    logger.info("INDEED JOB FINDER (python-jobspy FREE + ScraperAPI fallback)")
    logger.info(f"Max jobs to process: {MAX_APPLY}")
    logger.info("=" * 60)

    applied = load_applied()
    results = []
    processed = 0

    # Search all queries using python-jobspy (FREE)
    all_jobs = []
    for query in SEARCH_QUERIES:
        if time.time() - SESSION_START > SESSION_LIMIT:
            break
        logger.info(f"  🔍 Searching: {query}")
        
        # Primary: python-jobspy (free, no API key)
        jobs = search_jobs_jobspy(query)
        if jobs:
            all_jobs.extend(jobs)
            logger.info(f"    ✅ jobspy found {len(jobs)} jobs")
        else:
            # Fallback: ScraperAPI (if key is set and has credits)
            jobs = search_jobs_scraperapi(query)
            if jobs:
                all_jobs.extend(jobs)
                logger.info(f"    ✅ ScraperAPI found {len(jobs)} jobs")
            else:
                logger.info(f"    ⚠️  No results from jobspy or ScraperAPI")
        
        logger.info(f"    Total so far: {len(all_jobs)}")
        time.sleep(random.uniform(1, 3))

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
