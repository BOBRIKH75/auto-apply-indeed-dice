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
    """Login to Dice — tries cookies first, then email/password fallback."""
    logger.info("Logging into Dice...")

    # Try cookies first
    if DICE_COOKIES:
        page.goto("https://www.dice.com/")
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
        page.goto("https://www.dice.com/home-feed")
        time.sleep(3)
        if "home-feed" in page.url or "dashboard" in page.url:
            logger.info("✅ Logged into Dice via cookies")
            return True

    # Fallback: email + password
    if DICE_EMAIL and DICE_PASSWORD:
        logger.info("  Cookies failed, trying email/password...")
        page.goto("https://www.dice.com/dashboard/login")
        time.sleep(3)
        try:
            email_input = page.wait_for_selector('input[name="email"], input[type="email"]', timeout=5000)
            email_input.fill(DICE_EMAIL)
            page.click('button[type="submit"], button:has-text("Sign In"), button:has-text("Continue")')
            time.sleep(3)
            pass_input = page.wait_for_selector('input[name="password"], input[type="password"]', timeout=5000)
            pass_input.fill(DICE_PASSWORD)
            page.click('button[type="submit"], button:has-text("Sign In")')
            time.sleep(4)
            if "dice.com" in page.url and "login" not in page.url:
                logger.info("✅ Logged into Dice via email/password")
                return True
        except Exception as e:
            logger.warning(f"  Email/password login failed: {e}")

    logger.warning("⚠️ Could not verify Dice login — proceeding anyway")
    return True


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
    """Apply to a Dice job."""
    result = {"title": job["title"], "company": job["company"], "url": job["url"], "status": "unknown", "error": ""}

    try:
        page.goto(job["url"], timeout=30000)
        time.sleep(4)  # Wait for full page load

        # Scroll down to trigger lazy-loaded elements
        page.evaluate("window.scrollTo(0, 300)")
        time.sleep(2)

        # Wait specifically for the apply web component
        try:
            page.wait_for_selector('apply-button-wc, [class*="apply"], button:has-text("Apply")', timeout=8000)
        except PlaywrightTimeout:
            pass  # Continue anyway — try other methods

        # Dice uses various apply button patterns
        apply_btn = None
        for selector in [
            'apply-button-wc',                          # Dice's web component
            'button:has-text("Easy Apply")',
            'button:has-text("Apply Now")',
            'button:has-text("Apply")',
            'a:has-text("Easy Apply")',
            'a:has-text("Apply Now")',
            'a:has-text("Apply")',
            '[data-cy="apply-button"]',
            '#applyButton',
            'dhi-wc-apply-button',                      # Another web component name
            '.btn-apply',
        ]:
            try:
                el = page.query_selector(selector)
                if el and el.is_visible():
                    apply_btn = el
                    break
            except Exception:
                continue

        # Also try clicking inside shadow DOM (Dice uses web components)
        if not apply_btn:
            try:
                # Dice's apply button is inside a web component's shadow DOM
                clicked = page.evaluate("""
                    () => {
                        // Try finding apply-button-wc and clicking inside its shadow
                        const wc = document.querySelector('apply-button-wc, dhi-wc-apply-button');
                        if (wc && wc.shadowRoot) {
                            const btn = wc.shadowRoot.querySelector('button, a');
                            if (btn) { btn.click(); return 'shadow-clicked'; }
                        }
                        
                        // Try all shadow DOMs on the page
                        const allElements = document.querySelectorAll('*');
                        for (const el of allElements) {
                            if (el.shadowRoot) {
                                const btns = el.shadowRoot.querySelectorAll('button, a');
                                for (const btn of btns) {
                                    const text = btn.textContent.toLowerCase();
                                    if (text.includes('apply') && btn.offsetParent !== null) {
                                        btn.click();
                                        return 'shadow-deep-clicked';
                                    }
                                }
                            }
                        }
                        
                        // Last resort: find ANY element with apply text
                        const all = document.querySelectorAll('*');
                        for (const el of all) {
                            if (el.textContent.trim().toLowerCase() === 'easy apply' || 
                                el.textContent.trim().toLowerCase() === 'apply now' ||
                                el.textContent.trim().toLowerCase() === 'apply') {
                                if (el.offsetParent !== null && el.tagName !== 'SPAN') {
                                    el.click();
                                    return 'text-clicked';
                                }
                            }
                        }
                        return null;
                    }
                """)
                if clicked:
                    logger.info(f"    Apply clicked via: {clicked}")
                    time.sleep(3)
                    apply_btn = True
            except Exception as e:
                logger.warning(f"    Shadow DOM search failed: {e}")

        if not apply_btn:
            # Debug: log what buttons ARE on the page
            try:
                all_buttons = page.evaluate("""
                    () => {
                        const btns = document.querySelectorAll('button, a[class*=btn], [role="button"]');
                        return Array.from(btns).slice(0, 10).map(b => ({
                            tag: b.tagName,
                            text: b.textContent.trim().slice(0, 50),
                            visible: b.offsetParent !== null
                        }));
                    }
                """)
                logger.info(f"    DEBUG buttons on page: {json.dumps(all_buttons[:5])}")
            except Exception:
                pass

            result["status"] = "no_apply_button"
            result["error"] = "No Apply button found"
            return result

        # If we found a button element (not already clicked via JS)
        if apply_btn is not True:
            apply_btn.click()
            time.sleep(3)

        # Handle the apply flow
        result = handle_dice_easy_apply(page, job, result)

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

    if not DICE_COOKIES and not DICE_EMAIL:
        logger.error("❌ Either DICE_COOKIES or DICE_EMAIL+DICE_PASSWORD must be set!")
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
