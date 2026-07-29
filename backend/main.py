import os

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

from scraper import get_player_profile, ScrapeBlockedError, debug_explore
from data_processor import build_manual_profile
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


class CoachRequest(BaseModel):
    platform: str
    username: str
    # The profile the frontend already established (looked up or entered), so
    # the coach doesn't trigger another lookup.
    profile: dict | None = None


class CoachChatRequest(CoachRequest):
    query: str


def _has_ranked_data(profile: dict) -> bool:
    return bool(profile and profile.get("ranked_playlists"))


@app.get("/")
def read_root():
    return {"message": "Rocket League AI Assistant Backend active!"}


@app.post("/api/v1/debug/explore")
@limiter.limit("10/minute")
async def debug_explore_endpoint(request: Request, body: PlayerRequest):
    """Temporary: probe the matches page markup so we can extract recent games."""
    return await debug_explore(body.platform, body.username)


# ---------------------------------------------------------------- lookup ----

@app.post("/api/v1/profile")
@limiter.limit("15/minute")
async def lookup_profile(request: Request, body: PlayerRequest):
    """
    Step 1 of the flow: look up a player's stats (ranks + lifetime totals).
    Costs no AI credits -- the coach is only invoked later, on demand.

    Always returns HTTP 200. `status` is "success" when stats were found, or
    "not_found" when the profile couldn't be loaded, so the frontend can offer
    "search again" / "enter manually".
    """
    try:
        profile = await get_player_profile(body.platform, body.username)
    except ScrapeBlockedError as e:
        return {
            "status": "not_found",
            "reason": "blocked",
            "message": str(e),
            "platform": body.platform,
            "username": body.username,
        }
    except Exception as e:
        return {
            "status": "not_found",
            "reason": "error",
            "message": f"Couldn't load that profile ({e}).",
            "platform": body.platform,
            "username": body.username,
        }

    if not _has_ranked_data(profile):
        return {
            "status": "not_found",
            "reason": "empty",
            "message": "No ranked playlists found for that profile.",
            "platform": body.platform,
            "username": body.username,
        }

    return {
        "status": "success",
        "platform": body.platform,
        "username": body.username,
        "data": profile,
    }


@app.post("/api/v1/profile/manual")
@limiter.limit("30/minute")
async def manual_profile(request: Request, body: ManualProfileRequest):
    """Step 1 (fallback): build a profile from ranks the player typed in."""
    playlists = {name: {"rank": p.rank, "mmr": p.mmr} for name, p in body.playlists.items()}
    profile = build_manual_profile(playlists)

    if not _has_ranked_data(profile):
        raise HTTPException(
            status_code=400,
            detail="No ranks entered. Fill in at least one playlist's rank or MMR.",
        )

    return {
        "status": "success",
        "platform": body.platform,
        "username": body.username,
        "data": profile,
    }


# ----------------------------------------------------------------- coach ----

@app.post("/api/v1/coach/analyze")
@limiter.limit("15/minute")
async def coach_analyze(request: Request, body: CoachRequest):
    """
    Step 2: the player clicked "activate coach". Uses the profile the frontend
    already has; only looks it up again if one wasn't supplied.
    """
    profile = body.profile or {}

    if not _has_ranked_data(profile):
        try:
            profile = await get_player_profile(body.platform, body.username)
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"No profile available ({e}).")

    return {
        "status": "success",
        "platform": body.platform,
        "username": body.username,
        "data": profile,
        "reply": generate_initial_analysis(profile),
    }


@app.post("/api/v1/coach/chat")
@limiter.limit("20/minute")
async def coach_chat(request: Request, body: CoachChatRequest):
    """Step 3: answer a follow-up question grounded in the player's profile."""
    profile = body.profile or {}

    if not _has_ranked_data(profile):
        try:
            profile = await get_player_profile(body.platform, body.username)
        except Exception:
            # The coach handles an empty profile gracefully -- it won't invent
            # ranks; it answers generally or asks for stats.
            profile = profile or {}

    return {
        "status": "success",
        "platform": body.platform,
        "username": body.username,
        "profile": profile,
        "reply": generate_coaching_response(profile, body.query),
    }
