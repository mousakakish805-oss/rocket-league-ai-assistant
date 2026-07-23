import os
from openai import OpenAI

from prompts import (
    COACH_SYSTEM_PROMPT,
    build_user_message,
    build_empty_profile_notice,
    build_initial_analysis_message,
)

# Lazily create the OpenAI client on first use rather than at import. If
# OPENAI_API_KEY is missing/blank, the OpenAI() constructor raises -- doing that
# at import time would crash the ENTIRE backend on startup (so even scraping and
# manual entry would go down). Lazy init keeps the server booting; only the coach
# calls fail, and they fail gracefully with a message (see the try/except below).
_client = None


def _get_client() -> OpenAI:
    global _client
    if _client is None:
        _client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    return _client


MODEL = "gpt-4o"


def _profile_is_empty(player_profile: dict) -> bool:
    return not player_profile or not any(
        player_profile.get(key) for key in ("overview", "ranked_playlists", "identified_weaknesses")
    )


def generate_coaching_response(player_profile: dict, query: str) -> str:
    """
    Generates a personalized Rocket League coaching response using OpenAI,
    incorporating the player's scraped profile stats and enforcing strict game boundaries.
    """
    user_message = (
        build_empty_profile_notice(query)
        if _profile_is_empty(player_profile)
        else build_user_message(player_profile, query)
    )

    try:
        response = _get_client().chat.completions.create(
            model=MODEL,
            messages=[
                {"role": "system", "content": COACH_SYSTEM_PROMPT},
                {"role": "user", "content": user_message},
            ],
            temperature=0.4,
            max_tokens=600,
        )
        return response.choices[0].message.content
    except Exception as e:
        return f"Error communicating with AI coach: {str(e)}"


def generate_initial_analysis(player_profile: dict) -> str:
    """
    Generates an unprompted opening analysis covering every ranked playlist
    in the player's profile, called right after a profile loads (before the
    player has asked anything).
    """
    user_message = build_initial_analysis_message(player_profile)

    try:
        response = _get_client().chat.completions.create(
            model=MODEL,
            messages=[
                {"role": "system", "content": COACH_SYSTEM_PROMPT},
                {"role": "user", "content": user_message},
            ],
            temperature=0.4,
            max_tokens=700,
        )
        return response.choices[0].message.content
    except Exception as e:
        return f"Error communicating with AI coach: {str(e)}"
