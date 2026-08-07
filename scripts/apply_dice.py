#!/usr/bin/env python3
"""
Auto-Apply to Dice Jobs using Playwright.
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
logger = logging.getLogger("dice-apply")

# Config
DICE_EMAIL = os.environ.get("DICE_EMAIL", "")
DICE_PASSWORD = os.environ.get("DICE_PASSWORD", "")
MAX_APPLY = int(os.environ.get("MAX_APPLY", "20"))
HEADLESS = os.environ.get("HEADLESS", "1") == "1"

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
DATA_DIR.mkdir(exist_ok=True)

SEARCH_QUERIES = [
    "Java Spring Boot contract",
    "Java developer contract remote",
    "Java microservices Kafka contract",
    "Spring Boot backend contract",
    "Java AWS Kubernetes contract",
]


def load_applied():
    """Load previously applied job IDs, titles, and URLs — never apply twice."""
    path = DATA_DIR / "applied_dice.json"
    if path.exists():
        with open(path) as f:
            data = json.load(f)
            if isinstance(data, dict):
                return data
            else:
                return {"ids": set(data), "titles": set(), "urls": set()}
    return {"ids": set(), "titles": set(), "urls": set()}


def save_applied(applied: dict):
    """Save all applied markers."""
    path = DATA_DIR / "applied_dice.json"
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


def login_dice(page):
    """Login to Dice account."""
    logger.info("Logging into Dice...")
    page.goto("https://www.dice.com/dashboard/login")
    time.sleep(2)

    # Enter email
    try:
        email_input = page.wait_for_selector('input[name="email"], input[type="email"]', timeout=5000)
        email_input.fill(DICE_EMAIL)

        # Click continue/next
        page.click('button[type="submit"], button:has-text("Sign In"), button:has-text("Continue")')
        time.sleep(2)

        # Enter password
        pass_input = page.wait_for_selector('input[name="password"], input[type="password"]', timeout=5000)
        pass_input.fill(DICE_PASSWORD)
        page.click('button[type="submit"], button:has-text("Sign In")')
        time.sleep(3)

        # Verify login
        page.wait_for_url("**/dice.com/**", timeout=10000)
        logger.info("✅ Logged into Dice")
        return True

    except PlaywrightTimeout:
        logger.error("❌ Dice login failed")
        return False


def search_jobs(page, query: str) -> list[dict]:
    """Search Dice for contract jobs."""
    jobs = []
    url = f"https://www.dice.com/jobs?q={query.replace(' ', '%20')}&contracttype=CONTRACTOR&radius=0&radiusUnit=mi&page=1&pageSize=20&language=en"
    logger.info(f"  Searching: {query}")
    page.goto(url)
    time.sleep(3)

    try:
        # Dice job cards
        job_cards = page.query_selector_all('dhi-search-card, a[data-cy="card-title-link"]')

        if not job_cards:
            # Try alternative selectors
            job_cards = page.query_selector_all('[data-testid="job-search-result"], .card-title-link')

        for card in job_cards[:15]:
            try:
                # Get job link and title
                link_el = card.query_selector('a[data-cy="card-title-link"], a.card-title-link') or card
                title = link_el.inner_text().strip() if link_el else ""
                href = link_el.get_attribute("href") or ""

                company_el = card.query_selector('[data-cy="card-company"], .card-company a')
                company = company_el.inner_text().strip() if company_el else ""

                if not href.startswith("http"):
                    href = f"https://www.dice.com{href}"

                # Extract job ID from URL
                job_id = href.split("/")[-1] if href else ""

                if title and job_id:
                    jobs.append({
                        "title": title,
                        "company": company,
                        "job_id": job_id,
                        "url": href,
                    })
            except Exception:
                continue

    except Exception as e:
        logger.warning(f"  Search error: {e}")

    return jobs


def apply_to_job(page, job: dict) -> dict:
    """Apply to a Dice job."""
    result = {"title": job["title"], "company": job["company"], "url": job["url"], "status": "unknown", "error": ""}

    try:
        page.goto(job["url"])
        time.sleep(3)

        # Look for "Easy Apply" or "Apply" button
        apply_btn = None
        for selector in [
            'button:has-text("Easy Apply")',
            'button:has-text("Apply")',
            'apply-button-wc',
            'a:has-text("Apply")',
            '#applyButton',
        ]:
            try:
                apply_btn = page.wait_for_selector(selector, timeout=3000)
                if apply_btn and apply_btn.is_visible():
                    break
                apply_btn = None
            except PlaywrightTimeout:
                continue

        if not apply_btn:
            result["status"] = "no_apply_button"
            result["error"] = "No Apply button found"
            return result

        # Check if it's "Easy Apply" (Dice internal) or external
        btn_text = apply_btn.inner_text().lower()
        apply_btn.click()
        time.sleep(3)

        if "easy" in btn_text:
            # Dice Easy Apply — usually 1-click with profile
            result = handle_dice_easy_apply(page, job, result)
        else:
            # May redirect to external site
            current_url = page.url
            if "dice.com" in current_url:
                result = handle_dice_easy_apply(page, job, result)
            else:
                result["status"] = "external_site"
                result["error"] = f"External: {current_url[:50]}"

    except Exception as e:
        result["status"] = "error"
        result["error"] = str(e)[:100]

    return result


def handle_dice_easy_apply(page, job: dict, result: dict) -> dict:
    """Handle Dice's Easy Apply flow."""
    try:
        time.sleep(2)

        # Dice Easy Apply is usually a modal/overlay
        # Check for "Submit" or "Apply" confirmation
        for attempt in range(3):
            # Look for submit button in modal
            submit_btn = None
            for sel in [
                'button:has-text("Submit")',
                'button:has-text("Next")',
                'button:has-text("Apply")',
                'button[type="submit"]',
            ]:
                try:
                    btn = page.query_selector(sel)
                    if btn and btn.is_visible():
                        submit_btn = btn
                        break
                except Exception:
                    continue

            if submit_btn:
                submit_btn.click()
                time.sleep(2)

            # Check if applied
            page_text = page.inner_text("body")[:1000].lower()
            if any(w in page_text for w in ["successfully applied", "application submitted", "thank you for applying", "you have applied"]):
                result["status"] = "submitted"
                logger.info(f"  ✅ APPLIED: {job['title']} @ {job['company']}")
                return result

        # If we got here, check final state
        page_text = page.inner_text("body")[:500].lower()
        if "applied" in page_text or "submitted" in page_text:
            result["status"] = "submitted"
            logger.info(f"  ✅ APPLIED: {job['title']} @ {job['company']}")
        else:
            result["status"] = "incomplete"
            result["error"] = "Could not confirm submission"

    except Exception as e:
        result["status"] = "error"
        result["error"] = str(e)[:100]

    return result


def main():
    """Main entry point."""
    logger.info("=" * 60)
    logger.info("DICE AUTO-APPLY AGENT")
    logger.info(f"Max applications: {MAX_APPLY}")
    logger.info("=" * 60)

    if not DICE_EMAIL or not DICE_PASSWORD:
        logger.error("❌ DICE_EMAIL and DICE_PASSWORD must be set!")
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
        if not login_dice(page):
            browser.close()
            return

        # Search and collect jobs
        all_jobs = []
        for query in SEARCH_QUERIES:
            jobs = search_jobs(page, query)
            all_jobs.extend(jobs)
            logger.info(f"    Found {len(jobs)} jobs")
            human_delay(2, 5)  # Pause between searches

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

        # Apply with human-like behavior
        for job in unique_jobs[:MAX_APPLY]:
            # Check session time limit
            if _time.time() - session_start > SESSION_DURATION_LIMIT:
                logger.info("⏰ Session time limit reached — stopping")
                break

            if applied_count >= MAX_APPLY:
                break

            logger.info(f"\nApplying to: {job['title']} @ {job['company']}")

            # Human-like behavior before applying
            random_scroll(page)
            random_mouse_move(page)
            human_delay(1, 3)

            result = apply_to_job(page, job)
            results.append(result)

            if result["status"] == "submitted":
                mark_applied(job, applied)
                applied_count += 1
            else:
                logger.info(f"  ⚠️ {result['status']}: {result['error']}")

            # CRITICAL: 15-45 second delay between applications
            between_applications_delay()

        browser.close()

    # Save
    save_applied(applied)

    results_path = DATA_DIR / "apply_results_dice.json"
    with open(results_path, "w") as f:
        json.dump(results, f, indent=2)

    # Summary
    submitted = [r for r in results if r["status"] == "submitted"]
    logger.info(f"\n{'='*60}")
    logger.info(f"DICE APPLY COMPLETE")
    logger.info(f"  ✅ Applied: {len(submitted)}")
    logger.info(f"  ❌ Failed:  {len(results) - len(submitted)}")
    logger.info(f"{'='*60}")


if __name__ == "__main__":
    main()
