import asyncio
import json
import os
import urllib.parse
import urllib.request

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

# Optional proxy. Cloudflare blocks datacenter IPs (cloud hosts like Render) on
# sight, before it ever inspects the browser -- so on a server the only way to
# scrape successfully is to exit through a RESIDENTIAL IP via a proxy. Set these
# env vars to your proxy provider's endpoint/credentials to enable it. When
# unset, scraping goes direct (works from a residential machine, blocked from a
# datacenter).
PROXY_SERVER = os.getenv("RL_PROXY_SERVER")          # e.g. "http://gate.provider.com:7000"
PROXY_USERNAME = os.getenv("RL_PROXY_USERNAME")
PROXY_PASSWORD = os.getenv("RL_PROXY_PASSWORD")


def _proxy_config():
    """Playwright proxy dict from env, or None if no proxy is configured."""
    if not PROXY_SERVER:
        return None
    cfg = {"server": PROXY_SERVER}
    if PROXY_USERNAME:
        cfg["username"] = PROXY_USERNAME
    if PROXY_PASSWORD:
        cfg["password"] = PROXY_PASSWORD
    return cfg


# ScraperAPI: does the fetch on THEIR infrastructure (residential IPs + Cloudflare
# handling) and returns the rendered HTML. This is what lets a datacenter host
# (Render) scrape successfully -- the request exits from ScraperAPI's trusted IPs,
# not Render's blocked one. Free tier: ~1000 credits/month. Set RL_SCRAPERAPI_KEY
# to enable; leave unset to scrape directly with Playwright.
SCRAPERAPI_KEY = os.getenv("RL_SCRAPERAPI_KEY")
# "premium" (residential) is usually needed for Cloudflare; bump to ultra_premium
# via RL_SCRAPERAPI_LEVEL=ultra if premium still gets blocked.
SCRAPERAPI_LEVEL = os.getenv("RL_SCRAPERAPI_LEVEL", "premium")


def _fetch_via_scraperapi(target_url: str) -> str:
    """Blocking GET through ScraperAPI. Runs in a thread (see caller)."""
    params = {
        "api_key": SCRAPERAPI_KEY,
        "url": target_url,
        "render": "true",          # execute the page's JS (clears CF challenge)
        "country_code": "us",
    }
    if SCRAPERAPI_LEVEL == "ultra":
        params["ultra_premium"] = "true"
    else:
        params["premium"] = "true"

    api_url = "https://api.scraperapi.com/?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(api_url, headers={"User-Agent": "rl-coach/1.0"})
    with urllib.request.urlopen(req, timeout=75) as resp:
        return resp.read().decode("utf-8", errors="replace")


async def _try_scraperapi(target_url: str) -> str | None:
    """Fetch via ScraperAPI if configured and the result looks like a real page.
    Returns HTML on success, or None to signal 'fall back to direct scraping'."""
    if not SCRAPERAPI_KEY:
        return None
    try:
        print("[scrape] via ScraperAPI")
        html = await asyncio.to_thread(_fetch_via_scraperapi, target_url)
    except Exception as e:
        print(f"[scrape] ScraperAPI request failed: {e}")
        return None
    return _accept_api_html(html, "ScraperAPI")


# ZenRows: another scraping API (residential proxies + JS render), often better
# at Cloudflare than ScraperAPI's free tier. Free trial: ~1000 credits. Set
# RL_ZENROWS_KEY to enable; it's tried BEFORE ScraperAPI when both are set.
ZENROWS_KEY = os.getenv("RL_ZENROWS_KEY")


def _fetch_via_zenrows(target_url: str) -> str:
    """Blocking GET through ZenRows. Runs in a thread (see caller)."""
    params = {
        "apikey": ZENROWS_KEY,
        "url": target_url,
        "js_render": "true",       # headless browser (clears CF JS challenge)
        "premium_proxy": "true",   # residential IPs (gets past IP blocks)
        "proxy_country": "us",
        # Tracker is a Vue SPA: the page shell loads first, then the ranks render
        # a moment later. A fixed post-load wait lets the ranks populate. (An
        # element wait_for could hang until timeout, so we use a bounded wait.)
        "wait": "18000",
    }
    api_url = "https://api.zenrows.com/v1/?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(api_url, headers={"User-Agent": "rl-coach/1.0"})
    with urllib.request.urlopen(req, timeout=140) as resp:
        return resp.read().decode("utf-8", errors="replace")


async def _try_zenrows(target_url: str) -> str | None:
    if not ZENROWS_KEY:
        return None
    try:
        print("[scrape] via ZenRows")
        html = await asyncio.to_thread(_fetch_via_zenrows, target_url)
    except Exception as e:
        print(f"[scrape] ZenRows request failed: {e}")
        return None
    return _accept_api_html(html, "ZenRows")


TRACKER_API = "https://api.tracker.gg/api/v2/rocket-league/standard/profile/{platform}/{username}"


def _fetch_via_zenrows_raw(target_url: str, render: bool) -> str:
    """ZenRows GET of an arbitrary URL. render=False for JSON API endpoints."""
    params = {
        "apikey": ZENROWS_KEY,
        "url": target_url,
        "premium_proxy": "true",
        "proxy_country": "us",
    }
    if render:
        params["js_render"] = "true"
    api_url = "https://api.zenrows.com/v1/?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(api_url, headers={"User-Agent": "rl-coach/1.0"})
    with urllib.request.urlopen(req, timeout=90) as resp:
        return resp.read().decode("utf-8", errors="replace")


async def fetch_profile_via_api(platform: str, username: str) -> dict:
    """
    Fetch Tracker's internal JSON API through ZenRows (residential IP + Cloudflare
    handling) and return the raw parsed JSON. This is the reliable server-side
    path: no page rendering, just clean structured data.
    """
    target = TRACKER_API.format(platform=platform, username=username)
    body = await asyncio.to_thread(_fetch_via_zenrows_raw, target, False)
    return json.loads(body)


TRACKER_MATCHES_API = "https://api.tracker.gg/api/v2/rocket-league/standard/matches/{platform}/{username}"


async def debug_explore(platform: str, username: str) -> dict:
    """Temporary: explore the overview (lifetime) stats and matches API shape."""
    out = {}
    try:
        prof = await fetch_profile_via_api(platform, username)
        segs = (prof.get("data") or {}).get("segments") or []
        out["segment_types"] = [s.get("type") for s in segs]
        ov = next((s for s in segs if s.get("type") == "overview"), None)
        if ov:
            stats = ov.get("stats") or {}
            out["overview_stats"] = {
                k: (v.get("displayValue") if isinstance(v, dict) else v)
                for k, v in stats.items()
            }
        else:
            out["overview_note"] = "no overview segment found"
    except Exception as e:
        out["profile_error"] = f"{type(e).__name__}: {e}"

    try:
        murl = TRACKER_MATCHES_API.format(platform=platform, username=username)
        body = await asyncio.to_thread(_fetch_via_zenrows_raw, murl, False)
        mj = json.loads(body)
        out["matches_top_keys"] = list(mj.keys()) if isinstance(mj, dict) else "not-dict"
        mdata = mj.get("data") if isinstance(mj, dict) else None
        out["data_kind"] = type(mdata).__name__
        matches = mdata.get("matches") if isinstance(mdata, dict) else mdata
        out["matches_ok"] = True
        out["match_count"] = len(matches) if isinstance(matches, list) else None
        out["first_match"] = json.dumps(matches[0])[:2000] if matches else None
    except Exception as e:
        out["matches_ok"] = False
        out["matches_error"] = f"{type(e).__name__}: {e}"
    return out


async def get_player_profile(platform: str, username: str) -> dict:
    """
    Returns the parsed player profile dict. When a ZenRows key is configured
    (i.e. on the server) it uses ZenRows -> Tracker's JSON API, which reliably
    gets past Cloudflare. Otherwise it falls back to the direct headful browser
    scrape (works from a residential machine). Raises ScrapeBlockedError when no
    usable data comes back, so callers can fall back to manual entry.
    """
    # Imported here to avoid any import-order coupling at module load.
    from data_processor import parse_player_stats, build_profile_from_api

    if ZENROWS_KEY:
        try:
            api_json = await fetch_profile_via_api(platform, username)
        except Exception as e:
            raise ScrapeBlockedError(f"Profile API fetch failed: {e}")
        profile = build_profile_from_api(api_json)
        if not profile.get("ranked_playlists"):
            raise ScrapeBlockedError("No ranked playlists returned for this profile.")
        return profile

    html = await scrape_rocket_league_stats(platform, username)
    return parse_player_stats(html)


def _accept_api_html(html: str, source: str) -> str | None:
    """Accept scraping-API HTML only if it's the real profile, not a
    challenge/error page. Returns the HTML, or None to signal failure."""
    if any(m in html[:4000].lower() for m in BLOCK_TITLE_MARKERS):
        print(f"[scrape] {source} returned a challenge page")
        return None
    if "ratings-grid" in html or "text-accent" in html:
        return html
    print(f"[scrape] {source} response missing expected profile markup")
    return None


async def scrape_rocket_league_stats(platform: str, username: str, retries: int = 2) -> str:
    """
    Navigates to Rocket League Tracker for a specific platform & username using
    a headful, stealthed browser, waits for the Cloudflare challenge to clear
    and the profile to render, and returns the raw HTML.

    Retries on transient failures. Raises ScrapeBlockedError only when the
    Cloudflare challenge never clears (title stays on the challenge page).
    """
    url = f"https://rocketleague.tracker.network/rocket-league/profile/{platform}/{username}/overview"

    # Preferred path on a server: let a scraping API fetch it from a residential
    # IP (ZenRows first, then ScraperAPI). When either key is configured we rely
    # on them exclusively -- the direct browser scrape below is blocked from
    # datacenter IPs anyway, so falling back to it just burns ~90s before
    # failing. Fail fast to the manual form instead.
    if ZENROWS_KEY or SCRAPERAPI_KEY:
        api_html = await _try_zenrows(url)
        if api_html is None:
            api_html = await _try_scraperapi(url)
        if api_html is not None:
            return api_html
        raise ScrapeBlockedError(
            "Scraping API did not return the profile (Cloudflare, credits, or key "
            "issue -- check the logs). Use manual entry to get coaching."
        )

    last_error = None

    for attempt in range(1, retries + 2):  # e.g. retries=2 -> up to 3 attempts
        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=HEADLESS,
                args=["--disable-blink-features=AutomationControlled"],
            )
            context_opts = dict(
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
                ),
                viewport={"width": 1280, "height": 800},
                locale="en-US",
                timezone_id="America/New_York",
                extra_http_headers={"Accept-Language": "en-US,en;q=0.9"},
            )
            proxy = _proxy_config()
            if proxy:
                context_opts["proxy"] = proxy
            context = await browser.new_context(**context_opts)
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
