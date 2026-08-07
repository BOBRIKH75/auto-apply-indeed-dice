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
INDEED_EMAIL = os.environ.get("INDEED_EMAIL", "")
INDEED_PASSWORD = os.environ.get("INDEED_PASSWORD", "")
MAX_APPLY = int(os.environ.get("MAX_APPLY", "20"))
HEADLESS = os.environ.get("HEADLESS", "1") == "1"
RESUME_PATH = os.environ.get("RESUME_PATH", "config/resume.pdf")

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
DATA_DIR.mkdir(exist_ok=True)

SEARCH_QUERIES = [
    "Java Spring Boot contract remote",
    "Java developer contract C2C remote",
    "Java microservices contract",
    "Spring Boot developer contract",
    "Java backend developer contract remote",
]


def load_applied():
    """Load previously applied job IDs."""
    path = DATA_DIR / "applied_indeed.json"
    if path.exists():
        with open(path) as f:
            return set(json.load(f))
    return set()


def save_applied(applied: set):
    """Save applied job IDs."""
    path = DATA_DIR / "applied_indeed.json"
    with open(path, "w") as f:
        json.dump(list(applied), f)


def login_indeed(page):
    """Login to Indeed account."""
    logger.info("Logging into Indeed...")
    page.goto("https://secure.indeed.com/auth?hl=en_US&co=US&continue=https%3A%2F%2Fwww.indeed.com%2F")
    time.sleep(2)

    # Enter email
    page.fill('input[name="__email"]', INDEED_EMAIL)
    page.click('button[type="submit"]')
    time.sleep(3)

    # Enter password (if password page shows)
    try:
        page.wait_for_selector('input[name="__password"]', timeout=5000)
        page.fill('input[name="__password"]', INDEED_PASSWORD)
        page.click('button[type="submit"]')
        time.sleep(3)
    except PlaywrightTimeout:
        # May use different auth flow (Google, etc)
        logger.warning("Password field not found — may need manual auth or different flow")

    # Verify login
    try:
        page.wait_for_url("**/indeed.com/**", timeout=10000)
        logger.info("✅ Logged into Indeed")
        return True
    except PlaywrightTimeout:
        logger.error("❌ Indeed login failed")
        return False


def search_jobs(page, query: str) -> list[dict]:
    """Search Indeed for jobs matching query."""
    jobs = []
    url = f"https://www.indeed.com/jobs?q={query.replace(' ', '+')}&l=Remote&sc=0kf%3Ajt%28contract%29%3B&fromage=3"
    logger.info(f"  Searching: {query}")
    page.goto(url)
    time.sleep(3)

    try:
        job_cards = page.query_selector_all('div.job_seen_beacon, div.slider_container, a[data-jk]')
        for card in job_cards[:15]:
            try:
                title_el = card.query_selector('h2.jobTitle span, h2 a span')
                company_el = card.query_selector('[data-testid="company-name"], span.companyName')
                link_el = card.query_selector('a[data-jk], h2 a')

                title = title_el.inner_text() if title_el else ""
                company = company_el.inner_text() if company_el else ""
                href = link_el.get_attribute("href") if link_el else ""
                job_id = link_el.get_attribute("data-jk") if link_el else ""

                if not job_id and href:
                    import re
                    match = re.search(r'jk=([a-f0-9]+)', href)
                    job_id = match.group(1) if match else href[:32]

                if title and job_id:
                    jobs.append({
                        "title": title,
                        "company": company,
                        "job_id": job_id,
                        "url": f"https://www.indeed.com/viewjob?jk={job_id}" if job_id else href,
                    })
            except Exception:
                continue
    except Exception as e:
        logger.warning(f"  Search parsing error: {e}")

    return jobs


def apply_to_job(page, job: dict) -> dict:
    """Attempt to apply to a single Indeed job."""
    result = {"title": job["title"], "company": job["company"], "url": job["url"], "status": "unknown", "error": ""}

    try:
        page.goto(job["url"])
        time.sleep(2)

        # Look for "Apply now" or "Easy Apply" button
        apply_btn = None
        for selector in [
            'button:has-text("Apply now")',
            'button:has-text("Apply on company site")',
            'a:has-text("Apply now")',
            '#indeedApplyButton',
            'button[id*="apply"]',
            'a[href*="apply"]',
        ]:
            try:
                apply_btn = page.wait_for_selector(selector, timeout=3000)
                if apply_btn:
                    break
            except PlaywrightTimeout:
                continue

        if not apply_btn:
            result["status"] = "no_apply_button"
            result["error"] = "Could not find Apply button"
            return result

        # Click apply
        apply_btn.click()
        time.sleep(3)

        # Check if it opened Indeed's apply flow or external site
        current_url = page.url

        if "indeed.com" in current_url and ("apply" in current_url or "viewjob" in current_url):
            # Indeed's internal apply flow
            result = handle_indeed_apply_flow(page, job, result)
        else:
            # External company site — can't auto-apply
            result["status"] = "external_site"
            result["error"] = f"Redirected to: {current_url[:50]}"

    except Exception as e:
        result["status"] = "error"
        result["error"] = str(e)[:100]

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

    if not INDEED_EMAIL or not INDEED_PASSWORD:
        logger.error("❌ INDEED_EMAIL and INDEED_PASSWORD must be set!")
        return

    applied = load_applied()
    results = []
    applied_count = 0

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

        # Deduplicate
        seen = set()
        unique_jobs = []
        for job in all_jobs:
            if job["job_id"] not in seen and job["job_id"] not in applied:
                seen.add(job["job_id"])
                unique_jobs.append(job)

        logger.info(f"\n{'='*60}")
        logger.info(f"Total unique new jobs: {len(unique_jobs)}")
        logger.info(f"Already applied: {len(applied)}")
        logger.info(f"{'='*60}\n")

        # Apply to top jobs (with human-like delays)
        for job in unique_jobs[:MAX_APPLY]:
            # Check session time limit
            if _time.time() - session_start > SESSION_DURATION_LIMIT:
                logger.info("⏰ Session time limit reached — stopping to avoid timeout")
                break

            if applied_count >= MAX_APPLY:
                break

            logger.info(f"\nApplying to: {job['title']} @ {job['company']}")

            # Human-like: scroll, move mouse, pause before applying
            random_scroll(page)
            random_mouse_move(page)
            human_delay(1, 3)

            result = apply_to_job(page, job)
            results.append(result)

            if result["status"] == "submitted":
                applied.add(job["job_id"])
                applied_count += 1
            else:
                logger.info(f"  ⚠️ {result['status']}: {result['error']}")

            # CRITICAL: Wait 15-45 seconds between applications (avoids rate limiting)
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
