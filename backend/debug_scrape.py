"""
One-off debug helper: saves the raw rendered HTML for a given profile to disk
so you can inspect the real class names in a browser or editor and confirm/fix
the selectors in data_processor.py against them.

Usage:
    python debug_scrape.py epic Christophr5

Then open debug_output.html in a browser and search for the rank/MMR text
you see on the live site (e.g. "Diamond", "MMR") to find the real class names
Tracker Network is currently using, and update data_processor.py to match.
"""
import asyncio
import sys

from scraper import scrape_rocket_league_stats


async def main():
    if len(sys.argv) != 3:
        print("Usage: python debug_scrape.py <platform> <username>")
        print("  e.g. python debug_scrape.py epic Christophr5")
        sys.exit(1)

    platform, username = sys.argv[1], sys.argv[2]
    print(f"Scraping {platform}/{username}...")

    html = await scrape_rocket_league_stats(platform, username)

    with open("debug_output.html", "w", encoding="utf-8") as f:
        f.write(html)

    print(f"Saved {len(html)} chars to debug_output.html")
    print("Open it in a browser or search it for rank/MMR text to find the real class names.")


if __name__ == "__main__":
    asyncio.run(main())
