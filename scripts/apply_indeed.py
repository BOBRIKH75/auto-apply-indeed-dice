#!/usr/bin/env python3
"""
Auto-Apply to Indeed Jobs using Playwright.
Searches for Java/Spring Boot contract jobs and applies via Easy Apply.
"""

import json
import logging
import os
import time
from datetime import datetime
from pathlib import Path

from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("indeed-apply")

# Config
INDEED_COOKIES = os.environ.get("INDEED_COOKIES", "")
MAX_APPLY = int(os.environ.get("MAX_APPLY", "15"))
HEADLESS = os.environ.get("HEADLESS", "1") == "1"

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
DATA_DIR.mkdir(exist_ok=True)

SCREENSHOTS_DIR = Path(__file__).resolve().parent.parent / "screenshots"
SCREENSHOTS_DIR.mkdir(exist_ok=True)

SEARCH_QUERIES = [
    "Java Spring Boot contract remote",
    "Java developer contract C2C remote",
    "Java microservices contract",
    "Spring Boot developer contract",
    "Java backend developer contract remote",
]


def take_screenshot(page, name: str):
    """Save a debug screenshot."""
    try:
        path = SCREENSHOTS_DIR / f"{name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
        page.screenshot(path=str(path))
        logger.info(f"  📸 Screenshot saved: {path.name}")
    except Exception as e:
        logger.warning(f"  Screenshot failed: {e}")


def check_login_redirect(page) -> bool:
    """Self-healing: detect if page redirected to login (session expired)."""
    url = page.url.lower()
    if any(x in url for x in ["login", "signin", "sign-in", "account/verify"]):
        logger.error("❌ SELF-HEALING: Detected redirect to login page — session expired!")
        take_screenshot(page, "indeed_session_expired")
        return True
    return False


def load_applied():
    """Load previously applied job IDs, titles, and URLs — never apply twice."""
    path = DATA_DIR / "applied_indeed.json"
    if path.exists():
        with open(path) as f:
            data = json.load(f)
            # Support both old format (list of IDs) and new format (dict)
            if isinstance(data, dict):
                return data
            else:
                return {"ids": set(data), "titles": set(), "urls": set()}
    return {"ids": set(), "titles": set(), "urls": set()}


def save_applied(applied: dict):
    """Save all applied markers."""
    path = DATA_DIR / "applied_indeed.json"
    # Convert sets to lists for JSON
    with open(path, "w") as f:
        json.dump({
            "ids": list(applied.get("ids", set())),
            "titles": list(applied.get("titles", set())),
            "urls": list(applied.get("urls", set())),
        }, f)


def is_already_applied(job: dict, applied: dict) -> bool:
    """Check ALL ways a job could be a duplicate."""
    job_id = job.get("job_id", "")
    title_company = f"{job.get('title', '').lower().strip()}|{job.get('company', '').lower().strip()}"
    url = job.get("url", "")

    if job_id in applied.get("ids", set()):
        return True
    if title_company in applied.get("titles", set()):
        return True
    if url in applied.get("urls", set()):
        return True
    return False


def mark_applied(job: dict, applied: dict):
    """Mark a job as applied in all tracking sets."""
    applied.setdefault("ids", set()).add(job.get("job_id", ""))
    title_company = f"{job.get('title', '').lower().strip()}|{job.get('company', '').lower().strip()}"
    applied.setdefault("titles", set()).add(title_company)
    applied.setdefault("urls", set()).add(job.get("url", ""))


def login_indeed(page):
    """
    Indeed blocks headless browsers aggressively (fingerprint + IP detection).
    Cookie auth doesn't work from GitHub Actions IPs.
    
    Strategy: Use Indeed's PUBLIC search (no login needed for searching).
    Save job URLs with 'Easy Apply' → email them for manual 1-click apply.
    """
    logger.info("Indeed mode: SEARCH-ONLY (Indeed blocks headless auto-apply)")
    logger.info("  Will find jobs and save Easy Apply links for your email")
    
    # Set cookies anyway — might help with search results
    if INDEED_COOKIES:
        cookies_to_set = []
        for cookie_pair in INDEED_COOKIES.split(";"):
            cookie_pair = cookie_pair.strip()
            if "=" in cookie_pair:
                name, value = cookie_pair.split("=", 1)
                cookies_to_set.append({
                    "name": name.strip(),
                    "value": value.strip().strip('"'),
                    "domain": ".indeed.com",
                    "path": "/",
                })
        page.context.add_cookies(cookies_to_set)
    
    # Navigate to Indeed search (public, no auth needed)
    try:
        page.goto("https://www.indeed.com/jobs?q=Java+Spring+Boot+contract+remote&l=Remote&fromage=3", 
                  wait_until="domcontentloaded", timeout=30000)
        time.sleep(3)
        logger.info("✅ Indeed search page loaded")
        return True
    except Exception:
        logger.warning("  Indeed search timed out, trying without filters...")
        try:
            page.goto("https://www.indeed.com/jobs?q=Java+developer+contract", 
                      wait_until="domcontentloaded", timeout=30000)
            time.sleep(3)
            return True
        except Exception as e:
            logger.error(f"❌ Indeed completely blocked: {e}")
            return False


def search_jobs(page, query: str) -> list[dict]:
    """Search Indeed for jobs matching query."""
    jobs = []
    url = f"https://www.indeed.com/jobs?q={query.replace(' ', '+')}&l=Remote&sc=0kf%3Ajt%28contract%29%3B&fromage=3&sort=date"
    logger.info(f"  Searching: {query}")
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=30000)
    except Exception:
        logger.warning(f"    Page load timeout for: {query}")
        return jobs
    time.sleep(4)

    # Wait for job cards to render
    try:
        page.wait_for_selector('div.job_seen_beacon, td.resultContent, div[class*="cardOutline"]', timeout=10000)
    except PlaywrightTimeout:
        logger.warning(f"    No results rendered for: {query}")
        return jobs

    try:
        # Get all job title links
        title_links = page.query_selector_all('h2.jobTitle a, a[data-jk], h2 a[id^="job"]')

        for link in title_links[:15]:
            try:
                title = link.inner_text().strip()
                href = link.get_attribute("href") or ""
                job_id = link.get_attribute("data-jk") or ""

                # Extract job ID from href if not in data-jk
                if not job_id and href:
                    import re
                    match = re.search(r'jk=([a-f0-9]+)', href)
                    if match:
                        job_id = match.group(1)
                    else:
                        job_id = href[:32]

                if not href.startswith("http"):
                    href = f"https://www.indeed.com{href}"

                # Get company from nearby element
                company = ""
                parent = link.evaluate_handle("el => el.closest('.job_seen_beacon') || el.closest('.resultContent') || el.closest('td')")
                if parent:
                    comp_el = parent.query_selector('[data-testid="company-name"], span.companyName, span[class*="company"]')
                    if comp_el:
                        company = comp_el.inner_text().strip()

                if title and job_id:
                    jobs.append({
                        "title": title,
                        "company": company or "Unknown",
                        "job_id": job_id,
                        "url": f"https://www.indeed.com/viewjob?jk={job_id}" if len(job_id) < 20 else href,
                    })
            except Exception:
                continue
    except Exception as e:
        logger.warning(f"  Search parsing error: {e}")

    return jobs


def apply_to_job(page, job: dict) -> dict:
    """
    Indeed blocks headless auto-apply (fingerprint + IP detection).
    Instead: mark job as 'manual_apply' — these get emailed with clickable links.
    User opens email → clicks 'Easy Apply' → done in 5 seconds (logged in on phone/laptop).
    """
    result = {
        "title": job["title"], 
        "company": job["company"], 
        "url": job["url"], 
        "status": "manual_apply",
        "error": "Indeed requires manual 1-click apply from email"
    }
    logger.info(f"  📧 Saved for email: {job['title']} @ {job['company']}")
    return result


def handle_indeed_apply_flow(page, job: dict, result: dict) -> dict:
    """Handle Indeed's multi-step apply form."""
    try:
        # Indeed apply forms have multiple steps
        # Step 1: Contact info (usually pre-filled if logged in)
        # Step 2: Resume (already on profile)
        # Step 3: Screening questions
        # Step 4: Review & Submit

        max_steps = 5
        for step in range(max_steps):
            time.sleep(2)

            # Check if we're done (confirmation page)
            if page.query_selector('div:has-text("Your application has been submitted")'):
                result["status"] = "submitted"
                logger.info(f"  ✅ APPLIED: {job['title']} @ {job['company']}")
                return result

            # Check for "Continue" or "Next" button
            continue_btn = None
            for btn_text in ["Continue", "Next", "Submit your application", "Apply", "Submit"]:
                try:
                    btn = page.query_selector(f'button:has-text("{btn_text}")')
                    if btn and btn.is_visible():
                        continue_btn = btn
                        break
                except Exception:
                    continue

            if continue_btn:
                # Before clicking, try to fill any required fields
                fill_screening_questions(page)
                continue_btn.click()
                time.sleep(2)
            else:
                # No more buttons — might be stuck
                break

        # Check final status
        page_text = page.inner_text("body")[:500].lower()
        if "submitted" in page_text or "applied" in page_text or "thank you" in page_text:
            result["status"] = "submitted"
            logger.info(f"  ✅ APPLIED: {job['title']} @ {job['company']}")
        else:
            result["status"] = "incomplete"
            result["error"] = "Could not complete all steps"

    except Exception as e:
        result["status"] = "error"
        result["error"] = str(e)[:100]

    return result


def fill_screening_questions(page):
    """Try to fill common screening questions on Indeed apply forms."""
    try:
        # Work authorization
        for q in page.query_selector_all('fieldset, div[role="group"]'):
            text = q.inner_text().lower()
            if "authorized" in text or "legally" in text or "work in" in text:
                yes_radio = q.query_selector('input[value="Yes"], label:has-text("Yes")')
                if yes_radio:
                    yes_radio.click()

            elif "sponsorship" in text or "sponsor" in text:
                no_radio = q.query_selector('input[value="No"], label:has-text("No")')
                if no_radio:
                    no_radio.click()

            elif "experience" in text and "year" in text:
                # Fill years of experience
                input_field = q.query_selector('input[type="number"], input[type="text"]')
                if input_field:
                    input_field.fill("10")

            elif "salary" in text or "rate" in text or "compensation" in text:
                input_field = q.query_selector('input[type="number"], input[type="text"]')
                if input_field:
                    input_field.fill("85")

    except Exception:
        pass


def main():
    """Main entry point."""
    logger.info("=" * 60)
    logger.info("INDEED AUTO-APPLY AGENT")
    logger.info(f"Max applications: {MAX_APPLY}")
    logger.info("=" * 60)

    if not INDEED_COOKIES:
        logger.warning("⚠️ INDEED_COOKIES not set — running in search-only mode anyway")
        # Can still search public Indeed without login

    applied = load_applied()
    results = []
    applied_count = 0
    session_expired = False

    with sync_playwright() as p:
        # Use stealth browser (Firefox + anti-detection)
        from stealth import setup_stealth_context, human_delay, page_load_delay, between_applications_delay, random_scroll, random_mouse_move, SESSION_DURATION_LIMIT
        import time as _time
        session_start = _time.time()

        browser, context = setup_stealth_context(p, headless=HEADLESS)
        page = context.new_page()

        # Login
        if not login_indeed(page):
            browser.close()
            return

        # Search and apply
        all_jobs = []
        for query in SEARCH_QUERIES:
            jobs = search_jobs(page, query)
            all_jobs.extend(jobs)
            logger.info(f"    Found {len(jobs)} jobs")
            human_delay(2, 5)  # Pause between searches like a human

        # Deduplicate — NEVER apply to same job twice (checks ID + title + URL)
        seen = set()
        unique_jobs = []
        for job in all_jobs:
            if job["job_id"] in seen:
                continue
            if is_already_applied(job, applied):
                continue
            seen.add(job["job_id"])
            unique_jobs.append(job)

        logger.info(f"\n{'='*60}")
        logger.info(f"Total unique new jobs: {len(unique_jobs)}")
        logger.info(f"Already applied (skipped): {len(all_jobs) - len(unique_jobs)}")
        logger.info(f"{'='*60}\n")

        # Apply to top jobs (with human-like delays)
        for job in unique_jobs[:MAX_APPLY]:
            # Check session time limit
            if _time.time() - session_start > SESSION_DURATION_LIMIT:
                logger.info("⏰ Session time limit reached — stopping to avoid timeout")
                break

            if applied_count >= MAX_APPLY:
                break

            # Self-healing: stop if session expired
            if session_expired:
                logger.error("🛑 Session expired — stopping all applications")
                break

            logger.info(f"\nApplying to: {job['title']} @ {job['company']}")

            # Human-like: scroll, move mouse, pause before applying
            random_scroll(page)
            random_mouse_move(page)
            human_delay(1, 3)

            result = apply_to_job(page, job)
            results.append(result)

            if result["status"] == "submitted":
                mark_applied(job, applied)
                applied_count += 1
            elif result["status"] == "session_expired":
                session_expired = True
                logger.error("🛑 Session expired — stopping early")
                break
            else:
                logger.info(f"  ⚠️ {result['status']}: {result['error']}")

            # CRITICAL: Wait 15-45 seconds between applications (avoids rate limiting)
            if not session_expired:
                between_applications_delay()

        browser.close()

    # Save results
    save_applied(applied)

    results_path = DATA_DIR / "apply_results_indeed.json"
    with open(results_path, "w") as f:
        json.dump(results, f, indent=2)

    # Summary
    submitted = [r for r in results if r["status"] == "submitted"]
    failed = [r for r in results if r["status"] != "submitted"]

    logger.info(f"\n{'='*60}")
    logger.info(f"INDEED APPLY COMPLETE")
    logger.info(f"  ✅ Applied: {len(submitted)}")
    logger.info(f"  ❌ Failed:  {len(failed)}")
    logger.info(f"  📊 Total attempted: {len(results)}")
    logger.info(f"{'='*60}")


if __name__ == "__main__":
    main()
