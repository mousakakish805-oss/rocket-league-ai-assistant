import os

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

from scraper import scrape_rocket_league_stats, ScrapeBlockedError, debug_scrape_zenrows
from data_processor import parse_player_stats, build_manual_profile
from ai_coach import generate_coaching_response, generate_initial_analysis

app = FastAPI(title="Rocket League AI Assistant API")

# ---- CORS ----
# In production, set ALLOWED_ORIGINS to your deployed frontend's URL(s),
# comma-separated, e.g. "https://rlcoach.yourdomain.com". Defaults to "*"
# for local development only -- do NOT leave this as "*" in production,
# since it lets any site call your API (and burn your OpenAI credits).
allowed_origins_env = os.getenv("ALLOWED_ORIGINS", "*")
allowed_origins = (
    ["*"] if allowed_origins_env == "*" else [o.strip() for o in allowed_origins_env.split(",")]
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

# ---- Rate limiting ----
# Protects your OpenAI (and scraping) budget from being drained by anonymous
# traffic once this is public. Tune the limits to your expected usage.
limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)


class PlayerRequest(BaseModel):
    platform: str  # epic, psn, xbl, steam
    username: str


class ManualPlaylist(BaseModel):
    rank: str = "Unranked"
    mmr: int = 0


class ManualProfileRequest(BaseModel):
    platform: str
    username: str
    # e.g. {"Ranked Duel 1v1": {"rank": "Diamond II", "mmr": 950}, ...}
    playlists: dict[str, ManualPlaylist]


class CoachChatRequest(BaseModel):
    platform: str
    username: str
    query: str
    # The already-established profile (from a successful scrape or manual
    # entry). Sent by the frontend so we DON'T re-scrape on every message --
    # that was both wasteful and a fast way to get Cloudflare-blocked.
    profile: dict | None = None


def _has_ranked_data(profile: dict) -> bool:
    return bool(profile and profile.get("ranked_playlists"))


@app.get("/")
def read_root():
    return {"message": "Rocket League AI Assistant Backend active!"}


@app.post("/api/v1/debug/scrape")
@limiter.limit("10/minute")
async def debug_scrape(request: Request, body: PlayerRequest):
    """Temporary diagnostic: shows exactly what the ZenRows fetch returns."""
    return await debug_scrape_zenrows(body.platform, body.username)


@app.post("/api/v1/stats/scrape")
@limiter.limit("10/minute")
async def get_player_stats(request: Request, body: PlayerRequest):
    try:
        raw_html = await scrape_rocket_league_stats(body.platform, body.username)
        parsed_data = parse_player_stats(raw_html)

        return {
            "status": "success",
            "platform": body.platform,
            "username": body.username,
            "data": parsed_data,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/v1/coach/analyze")
@limiter.limit("10/minute")
async def coach_analyze(request: Request, body: PlayerRequest):
    """
    Tries to auto-load the player's profile by scraping Tracker Network. If the
    scrape is blocked (Cloudflare) or comes back empty, this returns a
    `status: "manual_required"` signal (HTTP 200) instead of an error, so the
    frontend can fall back to asking the player to type their ranks in.
    """
    try:
        raw_html = await scrape_rocket_league_stats(body.platform, body.username)
        parsed_data = parse_player_stats(raw_html)
    except ScrapeBlockedError:
        return {
            "status": "manual_required",
            "reason": "blocked",
            "message": (
                "The tracker site blocked the automatic lookup (bot protection). "
                "Enter your ranks manually to get coaching."
            ),
            "platform": body.platform,
            "username": body.username,
        }
    except Exception as e:
        return {
            "status": "manual_required",
            "reason": "error",
            "message": f"Couldn't auto-load stats ({e}). Enter your ranks manually to continue.",
            "platform": body.platform,
            "username": body.username,
        }

    if not _has_ranked_data(parsed_data):
        return {
            "status": "manual_required",
            "reason": "empty",
            "message": (
                "Auto-load didn't find any ranked playlists for that profile. "
                "Enter your ranks manually to get coaching."
            ),
            "platform": body.platform,
            "username": body.username,
        }

    reply = generate_initial_analysis(parsed_data)

    return {
        "status": "success",
        "source": "scraped",
        "platform": body.platform,
        "username": body.username,
        "data": parsed_data,
        "reply": reply,
    }


@app.post("/api/v1/coach/analyze_manual")
@limiter.limit("20/minute")
async def coach_analyze_manual(request: Request, body: ManualProfileRequest):
    """
    Builds a profile from ranks the player typed in themselves (the reliable
    fallback when scraping is blocked) and returns the same opening analysis.
    """
    playlists = {name: {"rank": p.rank, "mmr": p.mmr} for name, p in body.playlists.items()}
    profile = build_manual_profile(playlists)

    if not _has_ranked_data(profile):
        raise HTTPException(
            status_code=400,
            detail="No ranks entered. Fill in at least one playlist's rank or MMR.",
        )

    reply = generate_initial_analysis(profile)

    return {
        "status": "success",
        "source": "manual",
        "platform": body.platform,
        "username": body.username,
        "data": profile,
        "reply": reply,
    }


@app.post("/api/v1/coach/chat")
@limiter.limit("20/minute")
async def coach_chat(request: Request, body: CoachChatRequest):
    """
    Answers the player's question grounded in their profile. Prefers the profile
    the frontend already established (scraped once, or manually entered); only
    falls back to a best-effort scrape if none was provided.
    """
    parsed_data = body.profile or {}

    if not _has_ranked_data(parsed_data):
        try:
            raw_html = await scrape_rocket_league_stats(body.platform, body.username)
            parsed_data = parse_player_stats(raw_html)
        except Exception:
            # Blocked / failed -- the coach handles an empty profile gracefully
            # (it won't invent ranks; it answers generally or asks for stats).
            parsed_data = parsed_data or {}

    reply = generate_coaching_response(parsed_data, body.query)

    return {
        "status": "success",
        "platform": body.platform,
        "username": body.username,
        "profile": parsed_data,
        "reply": reply,
    }
