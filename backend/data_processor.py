from bs4 import BeautifulSoup


def identify_weaknesses(ranked_playlists: dict) -> list:
    """
    Feature engineering: derive coaching-relevant weaknesses from the raw
    playlist ranks/MMR. Shared by both the scraper path (parse_player_stats)
    and the manual-entry path (build_manual_profile) so the AI coach gets the
    same signal regardless of how the numbers arrived.
    """
    weaknesses = []
    playlists = ranked_playlists or {}

    # Gap analysis between 1v1 MMR and 2v2 MMR.
    ones_mmr = next(
        (v["mmr"] for k, v in playlists.items() if "1v1" in k.lower() or "duel" in k.lower()),
        None,
    )
    twos_mmr = next(
        (v["mmr"] for k, v in playlists.items() if "2v2" in k.lower() or "doubles" in k.lower()),
        None,
    )

    if ones_mmr and twos_mmr and (twos_mmr - ones_mmr > 200):
        weaknesses.append(
            "Significant 1v1 MMR gap compared to 2v2. Indicates potential weaknesses in "
            "1v1 shadow defense, kickoffs, and solo kick-off control."
        )

    return weaknesses


def build_manual_profile(playlists: dict) -> dict:
    """
    Builds a profile in the exact same shape parse_player_stats() returns, but
    from stats the player typed in themselves (used when the auto-scrape is
    blocked). `playlists` maps a playlist name to {"rank": str, "mmr": int}.
    """
    ranked = {}
    for name, info in (playlists or {}).items():
        rank = (info.get("rank") or "Unranked").strip() or "Unranked"
        try:
            mmr = int(info.get("mmr") or 0)
        except (ValueError, TypeError):
            mmr = 0
        # Skip rows the player left completely blank.
        if mmr == 0 and rank.lower() == "unranked":
            continue
        ranked[name] = {"rank": rank, "mmr": mmr}

    return {
        "overview": {},
        "ranked_playlists": ranked,
        "identified_weaknesses": identify_weaknesses(ranked),
        "source": "manual",
    }


def build_profile_from_api(api_json: dict) -> dict:
    """
    Builds a profile (same shape as parse_player_stats) from Tracker's internal
    JSON API response -- data.segments[] where each playlist segment carries its
    tier (rank name + icon), current rating (MMR), and peak rating.
    """
    data = (api_json or {}).get("data") or {}
    segments = data.get("segments") or []

    # Lifetime overview stats (wins, goals, goal/shot ratio, assists, saves...).
    overview = {}
    ov_seg = next((s for s in segments if s.get("type") == "overview"), None)
    if ov_seg:
        ov_stats = ov_seg.get("stats") or {}
        wanted = {
            "wins": "Wins",
            "goals": "Goals",
            "assists": "Assists",
            "saves": "Saves",
            "shots": "Shots",
            "goalShotRatio": "Goal/Shot Ratio",
            "mVPs": "MVPs",
            "score": "Score",
        }
        for key, label in wanted.items():
            v = ov_stats.get(key)
            if isinstance(v, dict) and v.get("displayValue") is not None:
                overview[label] = v.get("displayValue")

    ranked = {}
    for seg in segments:
        if seg.get("type") != "playlist":
            continue
        name = (seg.get("metadata") or {}).get("name")
        if not name:
            continue

        stats = seg.get("stats") or {}
        tier_meta = (stats.get("tier") or {}).get("metadata") or {}
        rank = (tier_meta.get("name") or "Unranked").strip() or "Unranked"

        try:
            mmr = int((stats.get("rating") or {}).get("value") or 0)
        except (TypeError, ValueError):
            mmr = 0

        entry = {"rank": rank, "mmr": mmr, "icon": tier_meta.get("iconUrl") or ""}

        peak = (stats.get("peakRating") or {}).get("value")
        if peak is not None:
            try:
                entry["peak_mmr"] = int(peak)
            except (TypeError, ValueError):
                pass

        ranked[name] = entry

    return {
        "overview": overview,
        "ranked_playlists": ranked,
        "identified_weaknesses": identify_weaknesses(ranked),
        "source": "scraped",
    }


def parse_recent_matches(html_content: str, limit: int = 10) -> list:
    """
    Parses the rendered Tracker /matches page into a list of recent games.

    Each match block looks like:
        <div class="match">
          <div class="match__result match__result--victory"></div>
          <div class="match__metadata">
            <div class="match__metadata--result"> Win </div>
            <div class="match__metadata--playlist">Ranked Duel 1v1</div>
          </div>
          <div class="match__rating">
            <img alt="Platinum I">
            <div class="match__rating--value">657</div>
            <div class="match__rating--change up">21</div>
            <div class="match__rating--division">Division I</div>
    Rows whose result isn't Win/Loss (e.g. a "6 Matches" session summary) are
    skipped so the coach only sees actual games.
    """
    soup = BeautifulSoup(html_content, "html.parser")
    matches = []

    for block in soup.find_all("div", class_="match"):
        result_elem = block.find("div", class_="match__metadata--result")
        result = result_elem.get_text(strip=True) if result_elem else ""
        if result.lower() not in ("win", "loss"):
            continue  # session summary row, not a single match

        playlist_elem = block.find("div", class_="match__metadata--playlist")
        playlist = playlist_elem.get_text(strip=True) if playlist_elem else "Unknown"

        entry = {"result": result.title(), "playlist": playlist}

        value_elem = block.find("div", class_="match__rating--value")
        if value_elem:
            try:
                entry["mmr"] = int(value_elem.get_text(strip=True).replace(",", ""))
            except ValueError:
                pass

        change_elem = block.find("div", class_="match__rating--change")
        if change_elem:
            classes = change_elem.get("class") or []
            sign = -1 if "down" in classes else 1
            try:
                entry["mmr_change"] = sign * abs(
                    int(change_elem.get_text(strip=True).replace(",", "").lstrip("+-"))
                )
            except ValueError:
                pass

        img = block.find("img", class_="match__rating--icon")
        if img and img.get("alt"):
            entry["rank"] = img.get("alt").strip()

        matches.append(entry)
        if len(matches) >= limit:
            break

    return matches


def summarize_matches(matches: list) -> str:
    """One-line form summary the coach can reason about (e.g. '6W-4L, +38 MMR')."""
    if not matches:
        return ""
    wins = sum(1 for m in matches if m.get("result") == "Win")
    losses = len(matches) - wins
    net = sum(m.get("mmr_change", 0) for m in matches)
    sign = "+" if net >= 0 else ""
    return f"Last {len(matches)} matches: {wins}W-{losses}L, net {sign}{net} MMR"


def parse_player_stats(html_content: str) -> dict:
    """
    Parses Rocket League Tracker HTML and extracts each playlist's current rank
    and MMR into a clean JSON profile.

    Structure of the live site (as of the current Tracker frontend):
        <h3 class="... text-accent">Ranked Duel 1v1</h3>
        <div class="ratings-grid">
          ... <img class="size-10" alt="Gold II"> ...      <- rank name (alt)
          ... <div class="numbers"><span class="value">534</span></div>  <- MMR
    The FIRST rating column in each grid is the player's *Current* rank (a later
    column is their season Peak), so we take the first rank image / value.
    """
    soup = BeautifulSoup(html_content, "html.parser")

    stats_summary = {
        "overview": {},
        "ranked_playlists": {},
        "identified_weaknesses": [],
        "source": "scraped",
    }

    # Each playlist rank card is an <h3 class="text-accent"> (the playlist name)
    # immediately followed by a .ratings-grid holding the Current/Peak ranks.
    for h3 in soup.find_all("h3"):
        classes = h3.get("class") or []
        if "text-accent" not in classes:
            continue

        playlist_name = h3.get_text(strip=True)
        if not playlist_name:
            continue

        grid = h3.find_next("div", class_="ratings-grid")
        if not grid:
            continue

        # The grid has two columns in DOM order: Current (index 0) then Best/Peak
        # (index 1). Each column has a rank badge <img> (alt = rank name) and a
        # .numbers > .value holding that column's MMR.
        imgs = grid.find_all("img")
        if not imgs:  # not an actual rank card
            continue
        number_values = [
            n.find("span", class_="value")
            for n in grid.find_all("div", class_="numbers")
        ]

        def _mmr(idx):
            if idx < len(number_values) and number_values[idx]:
                try:
                    return int(number_values[idx].get_text(strip=True).replace(",", ""))
                except ValueError:
                    return 0
            return 0

        rank_name = (imgs[0].get("alt") or "Unranked").strip() or "Unranked"
        icon = imgs[0].get("src") or ""

        entry = {
            "rank": rank_name,
            "mmr": _mmr(0),
            "icon": icon,
        }
        # Peak / best-ever rank for this playlist, when present.
        if len(imgs) > 1:
            entry["peak_rank"] = (imgs[1].get("alt") or "").strip()
            entry["peak_mmr"] = _mmr(1)

        stats_summary["ranked_playlists"][playlist_name] = entry

    # Feature engineering: identify performance gaps / weaknesses.
    stats_summary["identified_weaknesses"] = identify_weaknesses(stats_summary["ranked_playlists"])

    return stats_summary
