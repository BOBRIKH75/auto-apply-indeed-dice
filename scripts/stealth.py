"""
Human-like behavior and anti-detection utilities.
Makes Playwright automation look like a real person using a real browser.
"""

import random
import time


# Random delays to mimic human reading/thinking
def human_delay(min_sec=1.5, max_sec=4.0):
    """Wait a random time like a human reading a page."""
    delay = random.uniform(min_sec, max_sec)
    time.sleep(delay)


def short_delay():
    """Quick pause between actions (like clicking to next field)."""
    time.sleep(random.uniform(0.3, 1.2))


def page_load_delay():
    """Wait for page to fully load like a human would."""
    time.sleep(random.uniform(2.0, 5.0))


def between_applications_delay():
    """Longer delay between job applications to avoid rate limits."""
    delay = random.uniform(15, 45)  # 15-45 seconds between applications
    time.sleep(delay)


def human_type(page, selector, text):
    """Type text character by character with random delays like a human."""
    element = page.query_selector(selector)
    if element:
        element.click()
        short_delay()
        # Clear existing text
        element.fill("")
        short_delay()
        # Type with random delays
        for char in text:
            element.type(char, delay=random.randint(50, 200))
        short_delay()


def random_scroll(page):
    """Scroll page randomly like a human browsing."""
    scroll_amount = random.randint(200, 500)
    page.evaluate(f"window.scrollBy(0, {scroll_amount})")
    time.sleep(random.uniform(0.5, 1.5))


def random_mouse_move(page):
    """Move mouse to random position like a human."""
    x = random.randint(100, 800)
    y = random.randint(100, 600)
    page.mouse.move(x, y)
    time.sleep(random.uniform(0.1, 0.3))


def setup_stealth_context(playwright, headless=True):
    """Create a browser context that looks like a real user."""
    browser = playwright.firefox.launch(
        headless=headless,
        # Firefox is less detected than Chromium
    )

    # Randomize viewport slightly (real humans have different screen sizes)
    width = random.choice([1366, 1440, 1536, 1920])
    height = random.choice([768, 900, 864, 1080])

    context = browser.new_context(
        viewport={"width": width, "height": height},
        user_agent=get_random_user_agent(),
        locale="en-US",
        timezone_id="America/Denver",
        geolocation={"latitude": 39.5186, "longitude": -104.7614},  # Parker, CO
        permissions=["geolocation"],
        color_scheme="light",
        java_script_enabled=True,
    )

    # Add stealth scripts to hide automation signals
    context.add_init_script("""
        // Hide webdriver flag
        Object.defineProperty(navigator, 'webdriver', { get: () => false });
        
        // Hide automation flags
        delete window.cdc_adoQpoasnfa76pfcZLmcfl_Array;
        delete window.cdc_adoQpoasnfa76pfcZLmcfl_Promise;
        delete window.cdc_adoQpoasnfa76pfcZLmcfl_Symbol;
        
        // Add plugins (real browsers have plugins)
        Object.defineProperty(navigator, 'plugins', {
            get: () => [1, 2, 3, 4, 5]
        });
        
        // Add languages
        Object.defineProperty(navigator, 'languages', {
            get: () => ['en-US', 'en']
        });
        
        // Hide automation markers
        window.chrome = { runtime: {} };
    """)

    return browser, context


def get_random_user_agent():
    """Return a random real user agent string."""
    agents = [
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Safari/605.1.15",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:128.0) Gecko/20100101 Firefox/128.0",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:128.0) Gecko/20100101 Firefox/128.0",
    ]
    return random.choice(agents)


# Rate limit configuration
MAX_APPLICATIONS_PER_SESSION = 20  # Don't apply to more than 20 per run
MIN_DELAY_BETWEEN_APPS = 15  # Minimum 15 seconds between applications
MAX_DELAY_BETWEEN_APPS = 45  # Maximum 45 seconds between applications
SESSION_DURATION_LIMIT = 25 * 60  # Stop after 25 minutes (before GitHub 30min timeout)
