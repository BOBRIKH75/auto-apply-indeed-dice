#!/usr/bin/env python3
"""
Refresh login cookies by logging in with email/password.
Saves new cookies to data/ for the workflow to update GitHub secrets.
"""

import json
import logging
import os
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("refresh-cookies")

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
DATA_DIR.mkdir(exist_ok=True)


def refresh_dice_cookies():
    """Login to Dice with email/password and export fresh cookies."""
    email = os.environ.get("DICE_EMAIL", "")
    password = os.environ.get("DICE_PASSWORD", "")

    if not email or not password:
        logger.error("❌ DICE_EMAIL and DICE_PASSWORD required for cookie refresh")
        return False

    logger.info("Refreshing Dice cookies...")

    with sync_playwright() as p:
        browser = p.firefox.launch(headless=True)
        context = browser.new_context(
            viewport={"width": 1280, "height": 800},
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:128.0) Gecko/20100101 Firefox/128.0",
        )
        page = context.new_page()

        # Login to Dice
        page.goto("https://www.dice.com/dashboard/login")
        time.sleep(3)

        try:
            # Enter email
            email_input = page.wait_for_selector('input[name="email"], input[type="email"]', timeout=10000)
            email_input.fill(email)
            page.click('button[type="submit"], button:has-text("Sign In"), button:has-text("Continue")')
            time.sleep(3)

            # Enter password
            pass_input = page.wait_for_selector('input[name="password"], input[type="password"]', timeout=10000)
            pass_input.fill(password)
            page.click('button[type="submit"], button:has-text("Sign In")')
            time.sleep(5)

            # Check if logged in
            if "login" not in page.url.lower():
                logger.info("✅ Dice login successful")

                # Extract cookies
                cookies = context.cookies()
                # Filter to dice.com cookies
                dice_cookies = [c for c in cookies if "dice.com" in c.get("domain", "")]

                # Build cookie string
                cookie_str = "; ".join(f"{c['name']}={c['value']}" for c in dice_cookies)

                # Save to file
                cookie_path = DATA_DIR / "dice_cookies_new.txt"
                with open(cookie_path, "w") as f:
                    f.write(cookie_str)

                logger.info(f"  Saved {len(dice_cookies)} cookies to {cookie_path}")
                browser.close()
                return True
            else:
                logger.error("❌ Dice login failed — still on login page")
                browser.close()
                return False

        except Exception as e:
            logger.error(f"❌ Dice cookie refresh failed: {e}")
            browser.close()
            return False


def refresh_indeed_cookies():
    """
    Indeed uses Google OAuth — can't refresh automatically.
    User must manually update INDEED_COOKIES when they expire.
    This function logs a reminder.
    """
    logger.info("ℹ️ Indeed uses Google OAuth — cookies must be refreshed manually")
    logger.info("  To refresh: login to Indeed in Chrome → run extract script → update secret")
    logger.info("  Cookies typically last 2-4 weeks")


if __name__ == "__main__":
    logger.info("=" * 60)
    logger.info("COOKIE REFRESH")
    logger.info("=" * 60)

    refresh_dice_cookies()
    refresh_indeed_cookies()
