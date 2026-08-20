#!/usr/bin/env python3
"""
Indeed Auto-Apply — Playwright + cookies.
Applies to "Indeed Apply" / "Easily apply" jobs automatically.

Prerequisites:
- Indeed account with CV uploaded + name/phone/address filled
- INDEED_COOKIES secret set (from browser session)

Flow:
1. Load Indeed cookies → verify logged in
2. Search for Java/Spring Boot contract jobs with "Indeed Apply"
3. For each job: click Apply → step through wizard → submit
4. Track applied jobs to avoid duplicates
"""

import json
import logging
import os
import re
import time
import random
from datetime import datetime
from pathlib import Path

from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("indeed-auto")

# Config
INDEED_COOKIES = os.environ.get("INDEED_COOKIES", "")
MAX_APPLY = int(os.environ.get("MAX_APPLY", "10"))
HEADLESS = os.environ.get("HEADLESS", "1") == "1"

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
DATA_DIR.mkdir(exist_ok=True)

SCREENSHOTS_DIR = Path(__file__).resolve().parent.parent / "screenshots"
SCREENSHOTS_DIR.mkdir(exist_ok=True)

RESUME_PATH = Path(__file__).resolve().parent.parent / "data" / "resume.pdf"

SEARCH_QUERIES = [
    "Java Spring Boot contract remote",
    "Java developer contract remote",
    "Java microservices contract",
    "Spring Boot backend developer",
    "Senior Java developer remote",
]

# Load from shared config if available
CONFIG_PATH = Path(__file__).resolve().parent.parent / "config" / "shared_skills.json"
if CONFIG_PATH.exists():
    try:
        with open(CONFIG_PATH) as f:
            config = json.load(f)
        SEARCH_QUERIES = config.get("search_terms", {}).get("indeed_auto", SEARCH_QUERIES)
    except Exception:
        pass

SESSION_START = time.time()
SESSION_LIMIT = 12 * 60  # 12 minutes max


def take_screenshot(page, name: str):
    try:
        path = SCREENSHOTS_DIR / f"indeed_{name}_{datetime.now().strftime('%H%M%S')}.png"
        page.screenshot(path=str(path))
    except Exception:
        pass


def load_applied():
    path = DATA_DIR / "applied_indeed_auto.json"
    if path.exists():
        with open(path) as f:
            return json.load(f)
    return {"urls": [], "titles": []}


def save_applied(applied):
    path = DATA_DIR / "applied_indeed_auto.json"
    with open(path, "w") as f:
        json.dump(applied, f)


def is_already_applied(url, title, applied):
    if url in applied.get("urls", []):
        return True
    if title.lower().strip() in [t.lower().strip() for t in applied.get("titles", [])]:
        return True
    return False


def mark_applied(url, title, applied):
    applied.setdefault("urls", []).append(url)
    applied.setdefault("titles", []).append(title)


def inject_cookies(context):
    """Inject Indeed cookies from environment variable."""
    if not INDEED_COOKIES:
        return False

    cookies_to_set = []
    try:
        # Try JSON format first (array of cookie objects)
        cookie_data = json.loads(INDEED_COOKIES)
        if isinstance(cookie_data, list):
            for c in cookie_data:
                if isinstance(c, dict) and c.get("name") and c.get("value"):
                    cookies_to_set.append({
                        "name": c["name"],
                        "value": c["value"],
                        "domain": c.get("domain", ".indeed.com"),
                        "path": c.get("path", "/"),
                    })
    except (json.JSONDecodeError, TypeError):
        # Try semicolon-separated format: name=value; name2=value2
        for pair in INDEED_COOKIES.split(";"):
            pair = pair.strip()
            if "=" in pair:
                name, value = pair.split("=", 1)
                cookies_to_set.append({
                    "name": name.strip(),
                    "value": value.strip(),
                    "domain": ".indeed.com",
                    "path": "/",
                })

    if cookies_to_set:
        context.add_cookies(cookies_to_set)
        logger.info(f"  🍪 Injected {len(cookies_to_set)} Indeed cookies")
        return True
    return False


def verify_logged_in(page) -> bool:
    """Check if we're actually logged into Indeed."""
    page.goto("https://www.indeed.com/", timeout=30000)
    time.sleep(3)

    # Check for logged-in indicators
    try:
        # Look for account menu, profile icon, or signed-in state
        body_text = page.inner_text("body")[:3000].lower()
        logged_in_signals = ["my jobs", "my indeed", "profile", "resume", "sign out", "account"]
        if any(signal in body_text for signal in logged_in_signals):
            logger.info("  ✅ Indeed login verified")
            return True

        # Check if sign-in button is visible (means NOT logged in)
        sign_in = page.locator('a:has-text("Sign in"), button:has-text("Sign in")')
        if sign_in.count() > 0 and sign_in.first.is_visible():
            logger.warning("  ❌ Not logged in — Sign In button visible")
            return False

        # If we can access myjobs page, we're logged in
        page.goto("https://www.indeed.com/myjobs", timeout=15000)
        time.sleep(2)
        if "myjobs" in page.url and "login" not in page.url:
            logger.info("  ✅ Indeed login verified (myjobs accessible)")
            return True

    except Exception as e:
        logger.warning(f"  Login check error: {e}")

    return False


def search_easy_apply_jobs(page, query: str) -> list[dict]:
    """Search Indeed for 'Easily apply' / 'Indeed Apply' jobs."""
    jobs = []
    url = (
        f"https://www.indeed.com/jobs?"
        f"q={query.replace(' ', '+')}&l=Remote&fromage=3&jt=contract"
        f"&sc=0kf%3Aattr(DSQF7)%3B"  # Indeed Apply filter
    )
    logger.info(f"  🔍 Searching: {query}")
    page.goto(url, timeout=30000)
    time.sleep(3)

    # Wait for job cards
    try:
        page.wait_for_selector('[data-testid="jobCard"], .job_seen_beacon, .jobsearch-ResultsList li', timeout=10000)
    except PlaywrightTimeout:
        logger.info(f"    No job cards found")
        return jobs

    # Extract job cards
    cards = page.locator('[data-testid="jobCard"], .job_seen_beacon').all()
    logger.info(f"    Found {len(cards)} job cards")

    for card in cards[:10]:  # Limit per query
        try:
            # Get title and link
            title_el = card.locator('h2 a, a.jcs-JobTitle, [data-testid="job-title"] a').first
            if not title_el.is_visible():
                continue

            title = title_el.inner_text().strip()
            href = title_el.get_attribute("href") or ""
            job_url = f"https://www.indeed.com{href}" if href.startswith("/") else href

            # Check for "Easily apply" badge
            card_text = card.inner_text().lower()
            if "easily apply" not in card_text and "indeed apply" not in card_text:
                continue

            # Get company name
            company = ""
            try:
                company_el = card.locator('[data-testid="company-name"], .companyName, .company').first
                if company_el.is_visible():
                    company = company_el.inner_text().strip()
            except Exception:
                pass

            jobs.append({
                "title": title,
                "company": company,
                "url": job_url,
            })
        except Exception:
            continue

    return jobs


def apply_to_job(page, job: dict) -> str:
    """Apply to a single Indeed job. Returns status string."""
    url = job["url"]
    title = job["title"]

    try:
        page.goto(url, timeout=30000)
        time.sleep(2)

        # Click the Apply button
        apply_btn = None
        for selector in [
            'button:has-text("Apply now")',
            'button:has-text("Apply on company site")',
            '#indeedApplyButton',
            'button[id*="apply"]',
            'a:has-text("Apply now")',
            '.indeed-apply-button',
            'button:has-text("Easily apply")',
        ]:
            try:
                btn = page.locator(selector).first
                if btn.is_visible(timeout=2000):
                    apply_btn = btn
                    break
            except Exception:
                continue

        if not apply_btn:
            return "no_apply_button"

        apply_btn.click()
        time.sleep(3)

        # Handle the Indeed Apply wizard (multi-step)
        max_steps = 5
        for step in range(max_steps):
            page_text = page.inner_text("body")[:2000].lower()

            # Check if application was submitted successfully
            if any(w in page_text for w in ["application submitted", "you've applied", "applied successfully",
                                             "your application has been", "thank you for applying"]):
                logger.info(f"    ✅ APPLIED: {title} @ {job['company']}")
                return "submitted"

            # Check for resume step — select existing resume or upload
            resume_section = page.locator('text=/resume/i, text=/cv/i')
            if resume_section.count() > 0:
                # Try to select "Indeed Resume" (already uploaded)
                try:
                    indeed_resume = page.locator('input[type="radio"][value*="indeed"], label:has-text("Indeed Resume"), [data-testid="resume-selection"]').first
                    if indeed_resume.is_visible(timeout=2000):
                        indeed_resume.click()
                        time.sleep(1)
                except Exception:
                    pass

            # Look for Continue/Next/Submit button
            clicked_next = False
            for btn_text in ["Continue", "Next", "Submit your application", "Submit", "Apply", "Review"]:
                try:
                    btn = page.locator(f'button:has-text("{btn_text}")').first
                    if btn.is_visible(timeout=2000) and btn.is_enabled():
                        btn.click()
                        clicked_next = True
                        time.sleep(2)
                        break
                except Exception:
                    continue

            if not clicked_next:
                # Maybe there are required fields — try to fill them
                # Common Indeed questions
                try:
                    # Years of experience
                    exp_input = page.locator('input[id*="experience"], input[name*="experience"]').first
                    if exp_input.is_visible(timeout=1000):
                        exp_input.fill("10")
                except Exception:
                    pass

                try:
                    # Phone number
                    phone_input = page.locator('input[type="tel"], input[name*="phone"]').first
                    if phone_input.is_visible(timeout=1000) and not phone_input.input_value():
                        phone_input.fill("3472685917")
                except Exception:
                    pass

                # Try Continue again after filling
                for btn_text in ["Continue", "Next", "Submit your application", "Submit"]:
                    try:
                        btn = page.locator(f'button:has-text("{btn_text}")').first
                        if btn.is_visible(timeout=1000) and btn.is_enabled():
                            btn.click()
                            time.sleep(2)
                            break
                    except Exception:
                        continue

            # Check if we hit a blocker
            if "additional information" in page.inner_text("body")[:1000].lower():
                # Skip jobs that ask too many questions
                return "too_many_questions"

        # Final check
        final_text = page.inner_text("body")[:2000].lower()
        if any(w in final_text for w in ["application submitted", "you've applied", "applied", "thank you"]):
            return "submitted"

        return "wizard_incomplete"

    except PlaywrightTimeout:
        return "timeout"
    except Exception as e:
        return f"error: {str(e)[:50]}"


def auto_login_indeed(page) -> bool:
    """Auto-login to Indeed using email + Gmail OTP (no manual cookies needed).
    
    Flow:
    1. Go to Indeed sign-in page
    2. Enter email
    3. Indeed sends verification code to Gmail
    4. Read code from Gmail via IMAP (gmail_otp.py)
    5. Enter code on Indeed
    6. Login complete
    """
    from gmail_otp import read_indeed_otp
    
    try:
        gmail_user = os.environ.get("GMAIL_USER", "bobrikh75@gmail.com")
        
        logger.info("  Step 1: Opening Indeed sign-in page...")
        page.goto("https://secure.indeed.com/auth", timeout=30000)
        time.sleep(3)
        
        # Enter email
        logger.info("  Step 2: Entering email...")
        email_input = page.locator('input[type="email"], input[name="__email"], #ifl-InputFormField-3')
        if email_input.count() == 0:
            # Try alternative selectors
            email_input = page.locator('input[autocomplete="email"], input[name="email"]')
        
        if email_input.count() == 0:
            logger.error("  ❌ Cannot find email input on Indeed login page")
            take_screenshot(page, "login_no_email_field")
            return False
        
        email_input.first.fill(gmail_user)
        time.sleep(1)
        
        # Click submit/continue
        logger.info("  Step 3: Submitting email...")
        submit_btn = page.locator('button[type="submit"], button:has-text("Continue"), button:has-text("Sign in")')
        if submit_btn.count() > 0:
            submit_btn.first.click()
        else:
            email_input.first.press("Enter")
        
        time.sleep(5)
        
        # Check if Indeed asks for verification code
        page_text = page.inner_text("body")[:2000].lower()
        if "verification" in page_text or "code" in page_text or "enter" in page_text:
            logger.info("  Step 4: Waiting for OTP from Gmail...")
            
            # Read OTP from Gmail (polls for up to 60 seconds)
            otp = read_indeed_otp(max_wait_seconds=60, poll_interval=5)
            
            if not otp:
                logger.error("  ❌ Could not read OTP from Gmail")
                take_screenshot(page, "login_no_otp")
                return False
            
            # Enter the OTP
            logger.info(f"  Step 5: Entering OTP: {otp}")
            otp_input = page.locator('input[type="text"], input[name="otp"], input[inputmode="numeric"]')
            if otp_input.count() > 0:
                otp_input.first.fill(otp)
                time.sleep(1)
                
                # Submit OTP
                verify_btn = page.locator('button[type="submit"], button:has-text("Verify"), button:has-text("Continue")')
                if verify_btn.count() > 0:
                    verify_btn.first.click()
                else:
                    otp_input.first.press("Enter")
                
                time.sleep(5)
                
                # Check if login succeeded
                if "myjobs" in page.url or "indeed.com" in page.url and "auth" not in page.url:
                    logger.info("  ✅ Indeed auto-login successful!")
                    return True
        
        # Check if we're already logged in (some flows skip OTP)
        if "auth" not in page.url.lower() and "sign" not in page.url.lower():
            logger.info("  ✅ Indeed login successful (no OTP needed)")
            return True
        
        logger.error("  ❌ Indeed login flow unclear")
        take_screenshot(page, "login_unclear")
        return False
        
    except Exception as e:
        logger.error(f"  ❌ Indeed auto-login error: {str(e)[:100]}")
        take_screenshot(page, "login_error")
        return False


def main():
    logger.info("=" * 60)
    logger.info("INDEED AUTO-APPLY (Playwright + Cookies)")
    logger.info(f"Max applications: {MAX_APPLY}")
    logger.info("=" * 60)

    if not INDEED_COOKIES:
        logger.error("❌ INDEED_COOKIES not set — cannot auto-apply")
        logger.info("  Set INDEED_COOKIES secret with your Indeed session cookies")
        # Save empty results so report doesn't crash
        with open(DATA_DIR / "apply_results_indeed_auto.json", "w") as f:
            json.dump([], f)
        return

    applied_data = load_applied()
    results = []
    total_applied = 0

    with sync_playwright() as p:
        browser = p.firefox.launch(headless=HEADLESS)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:128.0) Gecko/20100101 Firefox/128.0",
            viewport={"width": 1920, "height": 1080},
        )

        # Inject cookies
        if not inject_cookies(context):
            logger.error("❌ Failed to inject cookies")
            browser.close()
            return

        page = context.new_page()

        # Verify login — try cookies first, then auto-login with OTP
        if not verify_logged_in(page):
            logger.info("  🔄 Cookies expired — attempting auto-login with Gmail OTP...")
            login_success = auto_login_indeed(page)
            if not login_success:
                logger.error("❌ Indeed auto-login failed — skipping Indeed auto-apply")
                take_screenshot(page, "login_failed")
                browser.close()
                with open(DATA_DIR / "apply_results_indeed_auto.json", "w") as f:
                    json.dump([], f)
                return

        # Search and apply
        for query in SEARCH_QUERIES:
            if total_applied >= MAX_APPLY:
                break
            if time.time() - SESSION_START > SESSION_LIMIT:
                logger.info("⏰ Session time limit reached")
                break

            jobs = search_easy_apply_jobs(page, query)
            logger.info(f"    {len(jobs)} Easy Apply jobs found")

            for job in jobs:
                if total_applied >= MAX_APPLY:
                    break
                if time.time() - SESSION_START > SESSION_LIMIT:
                    break

                if is_already_applied(job["url"], job["title"], applied_data):
                    logger.info(f"    ⚠️ already_applied: {job['title'][:40]}")
                    continue

                # Random delay (human behavior)
                time.sleep(random.uniform(3, 8))

                status = apply_to_job(page, job)

                result = {
                    "title": job["title"],
                    "company": job["company"],
                    "url": job["url"],
                    "status": status,
                }
                results.append(result)

                if status == "submitted":
                    total_applied += 1
                    mark_applied(job["url"], job["title"], applied_data)
                    logger.info(f"    ✅ APPLIED: {job['title'][:40]} @ {job['company']}")
                else:
                    logger.info(f"    ❌ {status}: {job['title'][:40]}")

                # Take screenshot after each attempt
                take_screenshot(page, f"after_apply_{total_applied}")

        browser.close()

    # Save results
    save_applied(applied_data)
    results_path = DATA_DIR / "apply_results_indeed_auto.json"
    with open(results_path, "w") as f:
        json.dump(results, f, indent=2)

    logger.info(f"\n{'=' * 60}")
    logger.info("INDEED AUTO-APPLY COMPLETE")
    logger.info(f"  ✅ Applied: {total_applied}")
    logger.info(f"  📝 Total attempted: {len(results)}")
    logger.info(f"{'=' * 60}")


if __name__ == "__main__":
    main()
