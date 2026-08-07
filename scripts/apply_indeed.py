#!/usr/bin/env python3
"""
Auto-Apply to Indeed Jobs using SeleniumBase UC (Undetected Chromedriver) mode.
Searches for Java/Spring Boot contract jobs and applies via Easy Apply.

PROVEN: github.com/mdmintz/undetected-testing/blob/master/raw_indeed.py
demonstrates Indeed access from GitHub Actions using SeleniumBase UC + CDP mode.
"""

import json
import logging
import os
import random
import time
from datetime import datetime
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("indeed-apply")

# Config
INDEED_COOKIES = os.environ.get("INDEED_COOKIES", "")
INDEED_EMAIL = os.environ.get("INDEED_EMAIL", "")
INDEED_PASSWORD = os.environ.get("INDEED_PASSWORD", "")
MAX_APPLY = int(os.environ.get("MAX_APPLY", "15"))
HEADLESS = os.environ.get("HEADLESS", "1") == "1"

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
DATA_DIR.mkdir(exist_ok=True)

SCREENSHOTS_DIR = Path(__file__).resolve().parent.parent / "screenshots"
SCREENSHOTS_DIR.mkdir(exist_ok=True)

# Session time limit (25 min — before GitHub Actions 30min timeout)
SESSION_DURATION_LIMIT = 25 * 60

SEARCH_QUERIES = [
    "Java Spring Boot contract remote",
    "Java developer contract C2C remote",
    "Java microservices contract",
    "Spring Boot developer contract",
    "Java backend developer contract remote",
]


# ─── Human-like delays ───────────────────────────────────────────────────────

def human_delay(min_sec=1.5, max_sec=4.0):
    """Wait a random time like a human reading a page."""
    time.sleep(random.uniform(min_sec, max_sec))


def between_applications_delay():
    """Longer delay between job applications to avoid rate limits (15-45s)."""
    delay = random.uniform(15, 45)
    logger.info(f"  ⏳ Waiting {delay:.0f}s before next application...")
    time.sleep(delay)


# ─── Deduplication ────────────────────────────────────────────────────────────

def load_applied() -> dict:
    """Load previously applied job IDs, titles, and URLs — never apply twice."""
    path = DATA_DIR / "applied_indeed.json"
    if path.exists():
        with open(path) as f:
            data = json.load(f)
            if isinstance(data, dict):
                return {
                    "ids": set(data.get("ids", [])),
                    "titles": set(data.get("titles", [])),
                    "urls": set(data.get("urls", [])),
                }
            else:
                return {"ids": set(data), "titles": set(), "urls": set()}
    return {"ids": set(), "titles": set(), "urls": set()}


def save_applied(applied: dict):
    """Save all applied markers."""
    path = DATA_DIR / "applied_indeed.json"
    with open(path, "w") as f:
        json.dump({
            "ids": list(applied.get("ids", set())),
            "titles": list(applied.get("titles", set())),
            "urls": list(applied.get("urls", set())),
        }, f, indent=2)


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


# ─── Screenshots ─────────────────────────────────────────────────────────────

def take_screenshot(sb, name: str):
    """Save a debug screenshot."""
    try:
        path = SCREENSHOTS_DIR / f"{name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
        sb.save_screenshot(str(path))
        logger.info(f"  📸 Screenshot saved: {path.name}")
    except Exception as e:
        logger.warning(f"  Screenshot failed: {e}")


# ─── Cookie Auth ──────────────────────────────────────────────────────────────

def set_indeed_cookies(sb):
    """Set Indeed cookies from INDEED_COOKIES env var after initial navigation."""
    if not INDEED_COOKIES:
        return

    logger.info("  Setting Indeed cookies...")
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

    if cookies_to_set:
        try:
            sb.add_cookies(cookies_to_set)
            logger.info(f"  ✅ Set {len(cookies_to_set)} cookies")
        except Exception as e:
            logger.warning(f"  Cookie setting failed: {e}")


# ─── Login ────────────────────────────────────────────────────────────────────

def login_indeed(sb) -> bool:
    """
    Navigate to Indeed using SeleniumBase UC mode.
    UC mode patches Chromedriver to avoid bot detection.
    CDP mode enables stealth browser interactions.
    """
    logger.info("Navigating to Indeed with SeleniumBase UC + CDP mode...")

    try:
        # First navigation — needed before cookies can be set
        sb.goto("https://www.indeed.com")
        sb.sleep(3)
        sb.solve_captcha()  # Auto-handles any CAPTCHA

        # Set cookies after first navigation
        set_indeed_cookies(sb)

        # Navigate to search page
        sb.goto(
            "https://www.indeed.com/jobs?q=Java+Spring+Boot+contract+remote&l=Remote&fromage=3",
        )
        sb.sleep(3)
        sb.solve_captcha()

        # Check if we got blocked
        page_source = sb.get_page_source().lower()
        if "unusual traffic" in page_source or "blocked" in page_source:
            logger.warning("⚠️ Indeed detected automation — trying again...")
            sb.sleep(5)
            sb.solve_captcha()

        logger.info("✅ Indeed search page loaded successfully")
        take_screenshot(sb, "indeed_loaded")
        return True

    except Exception as e:
        logger.error(f"❌ Indeed navigation failed: {e}")
        take_screenshot(sb, "indeed_failed")
        return False


# ─── Job Search ───────────────────────────────────────────────────────────────

def search_jobs(sb, query: str) -> list:
    """Search Indeed for jobs matching query using SeleniumBase."""
    import re
    jobs = []
    url = (
        f"https://www.indeed.com/jobs?"
        f"q={query.replace(' ', '+')}"
        f"&l=Remote"
        f"&sc=0kf%3Ajt%28contract%29%3B"
        f"&fromage=3"
        f"&sort=date"
    )
    logger.info(f"  Searching: {query}")

    try:
        sb.goto(url)
        sb.sleep(3)
        sb.solve_captcha()
    except Exception as e:
        logger.warning(f"    Page load failed for: {query} — {e}")
        return jobs

    # Wait for job cards to render — try multiple selectors
    page_loaded = False
    for selector in [
        "div.job_seen_beacon",
        "td.resultContent",
        "div[class*='cardOutline']",
        "div[class*='job']",
        "a[data-jk]",
        "div[class*='mosaic']",
        "#mosaic-provider-jobcards",
        "ul.css-zu9cdl",  # Indeed's job list
        "li[class*='css-']",  # React-rendered list items
    ]:
        try:
            sb.wait_for_element_present(selector, timeout=5)
            page_loaded = True
            logger.info(f"    Job cards found with: {selector}")
            break
        except Exception:
            continue

    if not page_loaded:
        # Try waiting for ANY content
        sb.sleep(5)
        page_text = sb.get_page_source()[:500]
        if "job" in page_text.lower() or "result" in page_text.lower():
            page_loaded = True
            logger.info("    Page has content — trying to parse")
        else:
            logger.warning(f"    No results rendered for: {query}")
            take_screenshot(sb, f"no_results_{query[:20]}")
            # Save page source for debugging
            try:
                src = sb.get_page_source()[:2000]
                logger.info(f"    Page source preview: {src[:300]}")
            except Exception:
                pass
            return jobs

    # Parse jobs using BeautifulSoup for reliable extraction
    try:
        soup = sb.get_beautiful_soup()

        # Try multiple selector strategies for Indeed's ever-changing DOM
        title_links = []
        for selector in [
            "h2.jobTitle a",
            "a[data-jk]",
            "h2 a[id^='job']",
            "a[id*='job']",
            "a[href*='/viewjob']",
            "a[href*='jk=']",
            "h2 a",  # Broad fallback
        ]:
            title_links = soup.select(selector)
            if title_links:
                logger.info(f"    Found {len(title_links)} jobs with selector: {selector}")
                break

        if not title_links:
            # Ultra-fallback: find any link containing "viewjob" or "jk=" in href
            all_links = soup.find_all("a", href=True)
            title_links = [a for a in all_links if "/viewjob" in a.get("href", "") or "jk=" in a.get("href", "")]
            if title_links:
                logger.info(f"    Found {len(title_links)} jobs via href fallback")
            else:
                logger.warning(f"    No job links found in page HTML")
                # Log what IS on the page for debugging
                all_h2 = soup.find_all("h2")
                logger.info(f"    H2 tags on page: {[h.get_text(strip=True)[:30] for h in all_h2[:5]]}")
                all_a_count = len(soup.find_all("a"))
                logger.info(f"    Total links on page: {all_a_count}")

        for link in title_links[:15]:
            try:
                title = link.get_text(strip=True)
                href = link.get("href", "")
                job_id = link.get("data-jk", "")

                # Extract job ID from href if not in data-jk
                if not job_id and href:
                    match = re.search(r"jk=([a-f0-9]+)", href)
                    if match:
                        job_id = match.group(1)
                    else:
                        job_id = href[:32]

                if not href.startswith("http"):
                    href = f"https://www.indeed.com{href}"

                # Get company from parent card
                company = "Unknown"
                card = link.find_parent(class_=lambda c: c and ("job_seen_beacon" in c or "resultContent" in c))
                if card:
                    comp_el = card.select_one(
                        "[data-testid='company-name'], span.companyName, span[class*='company']"
                    )
                    if comp_el:
                        company = comp_el.get_text(strip=True)

                if title and job_id:
                    jobs.append({
                        "title": title,
                        "company": company,
                        "job_id": job_id,
                        "url": f"https://www.indeed.com/viewjob?jk={job_id}" if len(job_id) < 20 else href,
                    })
            except Exception:
                continue
    except Exception as e:
        logger.warning(f"  Search parsing error: {e}")

    return jobs


# ─── Apply to Job ─────────────────────────────────────────────────────────────

def apply_to_job(sb, job: dict) -> dict:
    """
    Navigate to job page and attempt to apply via Easy Apply.
    Falls back to 'manual_apply' if blocked or not Easy Apply.
    """
    result = {
        "title": job["title"],
        "company": job["company"],
        "url": job["url"],
        "status": "pending",
        "timestamp": datetime.now().isoformat(),
    }

    try:
        # Navigate to job page
        sb.goto(job["url"])
        sb.sleep(3)
        sb.solve_captcha()

        # Check for login redirect
        current_url = sb.get_current_url().lower()
        if any(x in current_url for x in ["login", "signin", "sign-in", "account/verify"]):
            logger.warning("  ⚠️ Redirected to login — session expired")
            result["status"] = "session_expired"
            result["error"] = "Redirected to login page"
            take_screenshot(sb, "session_expired")
            return result

        # Look for Easy Apply / Apply Now button
        apply_clicked = False
        apply_selectors = [
            "button#indeedApplyButton",
            "button[id*='indeedApply']",
            "button:contains('Apply now')",
            "button:contains('Easy Apply')",
            "a:contains('Apply now')",
            "button.indeed-apply-button",
            "[data-testid='indeedApplyButton']",
        ]

        for selector in apply_selectors:
            try:
                if sb.is_element_present(selector):
                    sb.click(selector)
                    apply_clicked = True
                    logger.info(f"  🖱️ Clicked apply button")
                    sb.sleep(3)
                    sb.solve_captcha()
                    break
            except Exception:
                continue

        if not apply_clicked:
            # No Easy Apply button — save for manual apply
            result["status"] = "manual_apply"
            result["error"] = "No Easy Apply button found"
            logger.info(f"  📧 Saved for email: {job['title']} @ {job['company']}")
            return result

        # Handle the apply flow (multi-step form)
        result = handle_apply_flow(sb, job, result)

    except Exception as e:
        result["status"] = "error"
        result["error"] = str(e)[:200]
        logger.error(f"  ❌ Error: {e}")
        take_screenshot(sb, f"error_{job['job_id'][:8]}")

    return result


def handle_apply_flow(sb, job: dict, result: dict) -> dict:
    """Handle Indeed's multi-step apply form using SeleniumBase."""
    try:
        max_steps = 6
        for step in range(max_steps):
            sb.sleep(2)

            # Check if application was submitted
            page_text = sb.get_page_source().lower()
            if any(x in page_text for x in [
                "application has been submitted",
                "you have applied",
                "successfully applied",
                "thank you for applying",
            ]):
                result["status"] = "submitted"
                logger.info(f"  ✅ APPLIED: {job['title']} @ {job['company']}")
                return result

            # Fill screening questions before advancing
            fill_screening_questions(sb)

            # Look for Continue/Next/Submit button
            advance_clicked = False
            for btn_text in ["Continue", "Next", "Submit your application", "Apply", "Submit", "Review"]:
                try:
                    selector = f"button:contains('{btn_text}')"
                    if sb.is_element_visible(selector):
                        sb.click(selector)
                        advance_clicked = True
                        sb.sleep(2)
                        sb.solve_captcha()
                        break
                except Exception:
                    continue

            if not advance_clicked:
                # Try generic submit-like buttons
                try:
                    if sb.is_element_visible("button[type='submit']"):
                        sb.click("button[type='submit']")
                        sb.sleep(2)
                        sb.solve_captcha()
                        advance_clicked = True
                except Exception:
                    pass

            if not advance_clicked:
                break

        # Final check
        page_text = sb.get_page_source().lower()
        if any(x in page_text for x in ["submitted", "applied", "thank you"]):
            result["status"] = "submitted"
            logger.info(f"  ✅ APPLIED: {job['title']} @ {job['company']}")
        else:
            result["status"] = "incomplete"
            result["error"] = "Could not complete all apply steps"
            take_screenshot(sb, f"incomplete_{job['job_id'][:8]}")

    except Exception as e:
        result["status"] = "error"
        result["error"] = str(e)[:200]
        take_screenshot(sb, f"apply_error_{job['job_id'][:8]}")

    return result


def fill_screening_questions(sb):
    """Try to fill common screening questions on Indeed apply forms."""
    try:
        # Work authorization — click Yes
        try:
            auth_questions = sb.find_elements("fieldset")
            for fieldset in auth_questions:
                text = fieldset.text.lower()
                if "authorized" in text or "legally" in text or "work in" in text:
                    try:
                        yes_label = fieldset.find_element("xpath", ".//label[contains(text(),'Yes')]")
                        yes_label.click()
                    except Exception:
                        pass
                elif "sponsorship" in text or "sponsor" in text:
                    try:
                        no_label = fieldset.find_element("xpath", ".//label[contains(text(),'No')]")
                        no_label.click()
                    except Exception:
                        pass
        except Exception:
            pass

        # Experience years
        try:
            inputs = sb.find_elements("input[type='number']")
            for inp in inputs:
                parent_text = sb.execute_script(
                    "return arguments[0].closest('fieldset, div[role=\"group\"], .ia-BasePage-component')?.textContent || ''",
                    inp,
                ).lower()
                if "experience" in parent_text and "year" in parent_text:
                    sb.execute_script("arguments[0].value = '10'", inp)
                    sb.execute_script("arguments[0].dispatchEvent(new Event('input', {bubbles: true}))", inp)
                elif "salary" in parent_text or "rate" in parent_text or "compensation" in parent_text:
                    sb.execute_script("arguments[0].value = '85'", inp)
                    sb.execute_script("arguments[0].dispatchEvent(new Event('input', {bubbles: true}))", inp)
        except Exception:
            pass

    except Exception:
        pass


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    """Main entry point — SeleniumBase UC mode for Indeed."""
    logger.info("=" * 60)
    logger.info("INDEED AUTO-APPLY AGENT (SeleniumBase UC Mode)")
    logger.info(f"Max applications: {MAX_APPLY}")
    logger.info(f"Headless: {HEADLESS}")
    logger.info("=" * 60)

    if not INDEED_COOKIES:
        logger.warning("⚠️ INDEED_COOKIES not set — running without session cookies")

    applied = load_applied()
    results = []
    applied_count = 0
    session_start = time.time()

    # SeleniumBase UC mode: patches Chromedriver to avoid detection
    # CDP mode: enables stealth browser interactions
    from seleniumbase import SB

    with SB(uc=True, test=True, guest=True, headless2=HEADLESS) as sb:
        sb.activate_cdp_mode()

        # Login / initial navigation
        if not login_indeed(sb):
            logger.error("Failed to access Indeed — aborting")
            return

        # Search across all queries
        all_jobs = []
        for query in SEARCH_QUERIES:
            jobs = search_jobs(sb, query)
            all_jobs.extend(jobs)
            logger.info(f"    Found {len(jobs)} jobs")
            human_delay(2, 5)

        # Deduplicate — NEVER apply to same job twice
        seen = set()
        unique_jobs = []
        for job in all_jobs:
            if job["job_id"] in seen:
                continue
            if is_already_applied(job, applied):
                continue
            seen.add(job["job_id"])
            unique_jobs.append(job)

        logger.info(f"\n{'=' * 60}")
        logger.info(f"Total unique new jobs: {len(unique_jobs)}")
        logger.info(f"Already applied (skipped): {len(all_jobs) - len(unique_jobs)}")
        logger.info(f"{'=' * 60}\n")

        # Apply to jobs
        for job in unique_jobs[:MAX_APPLY]:
            # Check session time limit (25 min)
            if time.time() - session_start > SESSION_DURATION_LIMIT:
                logger.info("⏰ Session time limit reached (25 min) — stopping")
                break

            if applied_count >= MAX_APPLY:
                break

            logger.info(f"\nApplying to: {job['title']} @ {job['company']}")
            human_delay(1, 3)

            result = apply_to_job(sb, job)
            results.append(result)

            if result["status"] == "submitted":
                mark_applied(job, applied)
                applied_count += 1
            elif result["status"] == "manual_apply":
                # Still mark as applied (will be in email report)
                mark_applied(job, applied)
                applied_count += 1
            elif result["status"] == "session_expired":
                logger.error("🛑 Session expired — stopping all applications")
                break
            else:
                logger.info(f"  ⚠️ {result['status']}: {result.get('error', 'unknown')}")

            # Wait 15-45 seconds between applications (avoids rate limiting)
            if applied_count < MAX_APPLY:
                between_applications_delay()

        take_screenshot(sb, "indeed_final")

    # Save results
    save_applied(applied)

    results_path = DATA_DIR / "apply_results_indeed.json"
    with open(results_path, "w") as f:
        json.dump(results, f, indent=2)

    # Summary
    submitted = [r for r in results if r["status"] == "submitted"]
    manual = [r for r in results if r["status"] == "manual_apply"]
    failed = [r for r in results if r["status"] not in ("submitted", "manual_apply")]

    logger.info(f"\n{'=' * 60}")
    logger.info("INDEED APPLY COMPLETE")
    logger.info(f"  ✅ Applied (auto):   {len(submitted)}")
    logger.info(f"  📧 Manual (email):   {len(manual)}")
    logger.info(f"  ❌ Failed:           {len(failed)}")
    logger.info(f"  📊 Total attempted:  {len(results)}")
    logger.info(f"{'=' * 60}")


if __name__ == "__main__":
    main()
