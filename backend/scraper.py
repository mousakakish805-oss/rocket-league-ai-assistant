import asyncio
import os

from playwright.async_api import async_playwright


class ScrapeBlockedError(RuntimeError):
    """Raised when Tracker Network's bot protection actually blocked the request
    (the Cloudflare challenge never cleared), as opposed to a generic scrape
    failure (timeout, bad selector, etc.). Lets callers give the player an
    honest message and fall back to manual stat entry."""
    pass


# Stealth: hide the tell-tale signs that this is an automated browser. Applied
# before any page script runs. This -- combined with a *headful* browser -- is
# what actually gets past Cloudflare's "Just a moment" check that blocks a
# plain headless scraper.
STEALTH_JS = """
Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
Object.defineProperty(navigator, 'languages', {get: () => ['en-US', 'en']});
Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3, 4, 5]});
window.chrome = { runtime: {} };
"""

# Only the *interactive* challenge page carries these in its <title>. Cloudflare
# also injects a challenge-platform <script> into fully-rendered real pages, so
# we must NOT treat that script's mere presence as "blocked" (that was the old
# bug that made every successful scrape look like a block).
BLOCK_TITLE_MARKERS = ("just a moment", "attention required", "access denied")

# Headful is the default because it's what defeats Cloudflare. On a headless
# server (Docker/Render/Railway) run the app under xvfb (see Dockerfile) so a
# headful browser has a virtual display. Set RL_SCRAPER_HEADLESS=1 to force
# headless (faster locally, but far more likely to be blocked).
HEADLESS = os.getenv("RL_SCRAPER_HEADLESS", "0") == "1"


async def scrape_rocket_league_stats(platform: str, username: str, retries: int = 2) -> str:
    """
    Navigates to Rocket League Tracker for a specific platform & username using
    a headful, stealthed browser, waits for the Cloudflare challenge to clear
    and the profile to render, and returns the raw HTML.

    Retries on transient failures. Raises ScrapeBlockedError only when the
    Cloudflare challenge never clears (title stays on the challenge page).
    """
    url = f"https://rocketleague.tracker.network/rocket-league/profile/{platform}/{username}/overview"

    last_error = None

    for attempt in range(1, retries + 2):  # e.g. retries=2 -> up to 3 attempts
        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=HEADLESS,
                args=["--disable-blink-features=AutomationControlled"],
            )
            context = await browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
                ),
                viewport={"width": 1280, "height": 800},
                locale="en-US",
                timezone_id="America/New_York",
                extra_http_headers={"Accept-Language": "en-US,en;q=0.9"},
            )
            await context.add_init_script(STEALTH_JS)
            page = await context.new_page()

            print(f"[scrape {attempt}/{retries + 1}] {url}")
            try:
                await page.goto(url, timeout=45000, wait_until="domcontentloaded")

                # Cloudflare's non-interactive challenge clears itself after a
                # few seconds once the browser looks real. Poll the title until
                # it stops being the challenge page (or we give up).
                title = ""
                for _ in range(8):
                    await page.wait_for_timeout(2500)
                    title = (await page.title()).lower()
                    if not any(m in title for m in BLOCK_TITLE_MARKERS):
                        break

                # Let the profile's ranked data finish rendering.
                await page.wait_for_timeout(2000)

                html_content = await page.content()
                await browser.close()

                title = title.lower()
                if any(m in title for m in BLOCK_TITLE_MARKERS):
                    raise ScrapeBlockedError(
                        "Tracker Network's Cloudflare challenge did not clear for this "
                        "request. This can happen on datacenter IPs; try again, run the "
                        "scraper from a residential IP, or use manual stat entry."
                    )

                return html_content

            except ScrapeBlockedError:
                # Browser was already closed on the success path before the block
                # check raised; close again defensively (no-op if already closed).
                try:
                    await browser.close()
                except Exception:
                    pass
                if attempt <= retries:
                    await asyncio.sleep(1.5 * attempt)
                    continue
                raise
            except Exception as e:
                try:
                    await browser.close()
                except Exception:
                    pass
                last_error = e
                if attempt <= retries:
                    await asyncio.sleep(1.5 * attempt)
                    continue
                raise RuntimeError(f"Failed to scrape player profile: {str(last_error)}")

    raise RuntimeError(f"Failed to scrape player profile: {str(last_error)}")


if __name__ == "__main__":
    import sys
    plat = sys.argv[1] if len(sys.argv) > 1 else "epic"
    user = sys.argv[2] if len(sys.argv) > 2 else "sample_user"
    html = asyncio.run(scrape_rocket_league_stats(plat, user))
    print("Scraping completed. HTML length:", len(html))
