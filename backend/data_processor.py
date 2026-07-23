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
