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
DICE_COOKIES = os.environ.get("DICE_COOKIES", "")
DICE_EMAIL = os.environ.get("DICE_EMAIL", "")
DICE_PASSWORD = os.environ.get("DICE_PASSWORD", "")
MAX_APPLY = int(os.environ.get("MAX_APPLY", "15"))
HEADLESS = os.environ.get("HEADLESS", "1") == "1"

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
DATA_DIR.mkdir(exist_ok=True)

SCREENSHOTS_DIR = Path(__file__).resolve().parent.parent / "screenshots"
SCREENSHOTS_DIR.mkdir(exist_ok=True)

SEARCH_QUERIES = [
    "Java Spring Boot contract",
    "Java developer contract remote",
    "Java microservices Kafka contract",
    "Spring Boot backend contract",
    "Java AWS Kubernetes contract",
]

# Load from shared config if available
CONFIG_PATH = Path(__file__).resolve().parent.parent / "config" / "shared_skills.json"
if CONFIG_PATH.exists():
    try:
        import json as _json
        with open(CONFIG_PATH) as f:
            _config = _json.load(f)
        SEARCH_QUERIES = _config.get("search_terms", {}).get("dice", SEARCH_QUERIES)
    except Exception:
        pass

# Multiple selectors for Dice login form (SPA — Next.js, fields may render late)
EMAIL_SELECTORS = [
    'input[name="email"]',
    '#email',
    'input[type="email"]',
    '[data-testid="email-input"]',
    'input[placeholder*="email" i]',
    'input[placeholder*="Email"]',
]

PASSWORD_SELECTORS = [
    'input[name="password"]',
    '#password',
    'input[type="password"]',
    '[data-testid="password-input"]',
    'input[placeholder*="password" i]',
]

SUBMIT_SELECTORS = [
    'button[type="submit"]',
    'button:has-text("Sign In")',
    'button:has-text("Log In")',
    'button:has-text("Continue")',
    '[data-testid="submit-button"]',
    '[data-testid="sign-in-button"]',
]


def take_screenshot(page, name: str):
    """Save a debug screenshot."""
    try:
        path = SCREENSHOTS_DIR / f"{name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
        page.screenshot(path=str(path))
        logger.info(f"  📸 Screenshot saved: {path.name}")
    except Exception as e:
        logger.warning(f"  Screenshot failed: {e}")


def find_element(page, selectors: list, timeout: int = 15000):
    """Try multiple selectors — return the first element found."""
    for selector in selectors:
        try:
            el = page.wait_for_selector(selector, timeout=timeout)
            if el:
                logger.info(f"    Found element with selector: {selector}")
                return el
        except PlaywrightTimeout:
            continue
        except Exception:
            continue
    return None


def click_button(page, selectors: list, timeout: int = 10000):
    """Try multiple selectors to find and click a button."""
    for selector in selectors:
        try:
            btn = page.wait_for_selector(selector, timeout=timeout)
            if btn and btn.is_visible():
                btn.click()
                logger.info(f"    Clicked button with selector: {selector}")
                return True
        except PlaywrightTimeout:
            continue
        except Exception:
            continue
    return False


def check_login_redirect(page) -> bool:
    """Self-healing: detect if page redirected to login (session expired)."""
    url = page.url.lower()
    if "login" in url or "signin" in url or "sign-in" in url:
        logger.error("❌ SELF-HEALING: Detected redirect to login page — session expired!")
        take_screenshot(page, "session_expired")
        return True
    return False


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
    """Login to Dice — uses email/password with multi-selector fallback for SPA form."""
    logger.info("Logging into Dice...")

    if DICE_EMAIL and DICE_PASSWORD:
        logger.info("  Navigating to Dice login page...")
        page.goto("https://www.dice.com/dashboard/login", timeout=60000)
        time.sleep(5)  # Give SPA time to hydrate

        try:
            # Step 1: Find and fill email field
            logger.info("  Looking for email field...")
            email_input = find_element(page, EMAIL_SELECTORS, timeout=15000)
            if not email_input:
                logger.error("❌ Could not find email input field")
                take_screenshot(page, "dice_login_no_email_field")
                # Log page content for debugging
                try:
                    page_html = page.content()[:3000]
                    logger.info(f"  Page URL: {page.url}")
                    logger.info(f"  Page title: {page.title()}")
                except Exception:
                    pass
                return False

            email_input.click()
            time.sleep(0.5)
            email_input.fill(DICE_EMAIL)
            logger.info("  ✅ Email entered")
            time.sleep(2)

            # Step 2: Try to click a "Continue" or "Next" button if there's a two-step flow
            # Some login forms show email first, then password on next screen
            logger.info("  Looking for submit/continue button after email...")
            clicked = click_button(page, SUBMIT_SELECTORS, timeout=5000)
            if clicked:
                logger.info("  Clicked submit after email — checking for password field...")
                time.sleep(5)  # Wait for potential page transition

            # Step 3: Find and fill password field
            logger.info("  Looking for password field...")
            pass_input = find_element(page, PASSWORD_SELECTORS, timeout=15000)
            if not pass_input:
                # Maybe we're already past login (single-step with email only?)
                if "login" not in page.url.lower():
                    logger.info("  ✅ Appears to be logged in after email step")
                    return True
                logger.error("❌ Could not find password input field")
                take_screenshot(page, "dice_login_no_password_field")
                return False

            pass_input.click()
            time.sleep(0.5)
            pass_input.fill(DICE_PASSWORD)
            logger.info("  ✅ Password entered")
            time.sleep(2)

            # Step 4: Click the submit/sign-in button
            logger.info("  Clicking sign-in button...")
            clicked = click_button(page, SUBMIT_SELECTORS, timeout=10000)
            if not clicked:
                # Try pressing Enter as fallback
                logger.info("  No button found — pressing Enter...")
                pass_input.press("Enter")

            # Step 5: Wait for login to complete
            time.sleep(5)

            # Step 6: Navigate to home-feed to verify login
            logger.info("  Verifying login by navigating to home-feed...")
            page.goto("https://www.dice.com/home-feed", timeout=30000)
            time.sleep(3)

            # Check if we're logged in
            current_url = page.url.lower()
            if "login" in current_url or "signin" in current_url:
                logger.error("❌ Dice login failed — redirected back to login page")
                take_screenshot(page, "dice_login_failed_redirect")
                return False

            # Additional check: look for logged-in indicators
            try:
                page_text = page.inner_text("body")[:2000].lower()
                if any(w in page_text for w in ["profile", "job alerts", "my jobs", "home feed", "recommended"]):
                    logger.info("✅ Logged into Dice via email/password (full session)")
                    return True
            except Exception:
                pass

            # If we're on home-feed and not redirected to login, consider it success
            if "home-feed" in page.url or "dashboard" in page.url:
                logger.info("✅ Logged into Dice (URL confirms home-feed/dashboard)")
                return True

            logger.warning("⚠️ Login status unclear — proceeding anyway")
            take_screenshot(page, "dice_login_unclear")
            return True

        except Exception as e:
            logger.error(f"❌ Dice email/password login failed: {e}")
            take_screenshot(page, "dice_login_exception")

    # Fallback: cookies (may only work for search, not wizard)
    if DICE_COOKIES:
        logger.info("  Trying cookie fallback...")
        page.goto("https://www.dice.com/", timeout=60000)
        time.sleep(2)
        cookies_to_set = []
        for cookie_pair in DICE_COOKIES.split(";"):
            cookie_pair = cookie_pair.strip()
            if "=" in cookie_pair:
                name, value = cookie_pair.split("=", 1)
                cookies_to_set.append({
                    "name": name.strip(),
                    "value": value.strip().strip('"'),
                    "domain": ".dice.com",
                    "path": "/",
                })
        page.context.add_cookies(cookies_to_set)
        page.goto("https://www.dice.com/home-feed", timeout=60000)
        time.sleep(3)
        if "home-feed" in page.url or "dashboard" in page.url:
            logger.info("✅ Logged into Dice via cookies (limited session)")
            return True

    logger.error("❌ All Dice login methods failed")
    take_screenshot(page, "dice_login_all_failed")
    return False


def search_jobs(page, query: str) -> list[dict]:
    """Search Dice for contract jobs using their search page with proper wait."""
    jobs = []
    url = f"https://www.dice.com/jobs?q={query.replace(' ', '%20')}&countryCode=US&radius=30&radiusUnit=mi&page=1&pageSize=20&filters.employmentType=CONTRACTS&filters.easyApply=true&language=en"
    logger.info(f"  Searching: {query}")
    page.goto(url)

    # Wait for job cards to render (Dice is a SPA — needs time)
    time.sleep(5)

    # Try to wait for job cards to appear
    try:
        page.wait_for_selector('a[id^="job-card-title-link"]', timeout=10000)
    except PlaywrightTimeout:
        # Try alternative: wait for any job title links
        try:
            page.wait_for_selector('a[href*="/job-detail/"]', timeout=5000)
        except PlaywrightTimeout:
            logger.warning(f"    No job cards found for: {query}")
            return jobs

    # Extract jobs from the rendered page
    try:
        job_links = page.query_selector_all('a[id^="job-card-title-link"], a[href*="/job-detail/"]')

        seen_urls = set()
        for link in job_links[:20]:
            try:
                href = link.get_attribute("href") or ""
                title = link.inner_text().strip()

                if not href or href in seen_urls or not title:
                    continue
                seen_urls.add(href)

                if not href.startswith("http"):
                    href = f"https://www.dice.com{href}"

                # Extract job ID from URL
                job_id = href.split("/")[-1].split("?")[0] if href else ""

                # Try to get company name from nearby elements
                company = ""
                parent = link.evaluate_handle("el => el.closest('[class*=card]') || el.parentElement.parentElement")
                if parent:
                    company_el = parent.query_selector('[data-cy="card-company"] a, a[href*="/company-profile/"]')
                    if company_el:
                        company = company_el.inner_text().strip()

                jobs.append({
                    "title": title,
                    "company": company or "Unknown",
                    "job_id": job_id,
                    "url": href,
                })
            except Exception:
                continue

    except Exception as e:
        logger.warning(f"    Job extraction error: {e}")

    return jobs


def apply_to_job(page, job: dict) -> dict:
    """Apply to a Dice job using the direct wizard URL."""
    result = {"title": job["title"], "company": job["company"], "url": job["url"], "status": "unknown", "error": ""}

    try:
        # Extract job ID from URL (format: /job-detail/<uuid>)
        job_id = job["job_id"]
        if "/" in job_id:
            job_id = job_id.split("/")[-1].split("?")[0]

        # Go DIRECTLY to the application wizard (not the job detail page)
        wizard_url = f"https://www.dice.com/job-applications/{job_id}/wizard"
        logger.info(f"    Opening wizard: {wizard_url}")
        page.goto(wizard_url, timeout=30000)
        time.sleep(4)

        # Self-healing: check if redirected to login
        if check_login_redirect(page):
            result["status"] = "session_expired"
            result["error"] = "Redirected to login — session expired"
            return result

        # Check current state
        current_url = page.url
        page_text = page.inner_text("body")[:2000].lower()

        # Check for "already applied"
        if "already" in page_text and "applied" in page_text:
            result["status"] = "already_applied"
            result["error"] = "Already applied to this job"
            return result

        # Check for errors/redirects
        if "error" in page_text[:200] or "not found" in page_text[:200]:
            result["status"] = "wizard_error"
            result["error"] = "Wizard page not available"
            return result

        # We're on the wizard — look for resume/submit flow
        max_steps = 5
        for step in range(max_steps):
            time.sleep(2)

            # Check if we successfully submitted
            page_text = page.inner_text("body")[:1000].lower()
            if any(w in page_text for w in ["successfully", "submitted", "thank you", "application received", "applied"]):
                result["status"] = "submitted"
                logger.info(f"  ✅ APPLIED: {job['title']} @ {job['company']}")
                return result

            # Self-healing: check for login redirect mid-wizard
            if check_login_redirect(page):
                result["status"] = "session_expired"
                result["error"] = "Session expired during wizard"
                return result

            # Find and click the next/submit button
            clicked = False
            for btn_text in ["Submit", "Next", "Continue", "Submit Application", "Apply", "Review"]:
                try:
                    btn = page.query_selector(f'button:has-text("{btn_text}")')
                    if btn and btn.is_visible():
                        btn.click()
                        clicked = True
                        time.sleep(2)
                        break
                except Exception:
                    continue

            # Also try via JS if regular click didn't work
            if not clicked:
                try:
                    clicked_js = page.evaluate("""
                        () => {
                            const btns = document.querySelectorAll('button, a, [role="button"]');
                            for (const btn of btns) {
                                const text = btn.textContent.toLowerCase().trim();
                                if ((text === 'submit' || text === 'next' || text === 'continue' || 
                                     text.includes('submit') || text.includes('apply')) && 
                                    btn.offsetParent !== null) {
                                    btn.click();
                                    return true;
                                }
                            }
                            return false;
                        }
                    """)
                    if clicked_js:
                        clicked = True
                        time.sleep(2)
                except Exception:
                    pass

            if not clicked:
                break

        # Final check
        page_text = page.inner_text("body")[:1000].lower()
        if any(w in page_text for w in ["successfully", "submitted", "applied", "thank you"]):
            result["status"] = "submitted"
            logger.info(f"  ✅ APPLIED: {job['title']} @ {job['company']}")
        else:
            result["status"] = "incomplete"
            result["error"] = "Could not complete wizard steps"
            take_screenshot(page, f"dice_wizard_incomplete_{job_id[:8]}")

    except Exception as e:
        result["status"] = "error"
        result["error"] = str(e)[:100]
        take_screenshot(page, "dice_apply_exception")

    return result


def main():
    """Main entry point."""
    logger.info("=" * 60)
    logger.info("DICE AUTO-APPLY AGENT")
    logger.info(f"Max applications: {MAX_APPLY}")
    logger.info("=" * 60)

    if not DICE_COOKIES and not DICE_EMAIL:
        logger.error("❌ Either DICE_COOKIES or DICE_EMAIL+DICE_PASSWORD must be set!")
        return

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

            # Self-healing: stop if session expired
            if session_expired:
                logger.error("🛑 Session expired — stopping all applications")
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
            elif result["status"] == "session_expired":
                session_expired = True
                logger.error("🛑 Session expired — stopping early")
                break
            else:
                logger.info(f"  ⚠️ {result['status']}: {result['error']}")

            # CRITICAL: 15-45 second delay between applications
            if not session_expired:
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
    if session_expired:
        logger.info(f"  🛑 Session expired — stopped early")
    logger.info(f"{'='*60}")


if __name__ == "__main__":
    main()
