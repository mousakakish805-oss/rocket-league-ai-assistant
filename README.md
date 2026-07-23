# Rocket League AI Coach

A chat assistant that scrapes a player's Rocket League Tracker profile and gives
coaching advice grounded in their actual ranks/MMR.

- `backend/` — FastAPI + Playwright scraper + OpenAI-powered coach
- `frontend/` — static HTML/CSS/JS chat UI (no build step)

## Run locally

**Backend (macOS / Linux)**
```bash
cd backend
python -m venv .venv && source .venv/bin/activate   # optional but recommended
pip install -r requirements.txt
playwright install chromium
cp .env.example .env   # then fill in OPENAI_API_KEY
export $(cat .env | xargs)   # or use a tool like python-dotenv / direnv
uvicorn main:app --reload
```

**Backend (Windows / PowerShell)**
```powershell
cd backend
python -m venv .venv ; .\.venv\Scripts\Activate.ps1   # optional but recommended
pip install -r requirements.txt
playwright install chromium
copy .env.example .env   # then edit .env and fill in OPENAI_API_KEY
$env:OPENAI_API_KEY = "sk-..."   # set it for this shell (or use python-dotenv)
uvicorn main:app --reload
```

Backend runs at `http://localhost:8000`.

**Frontend**
Just open `frontend/index.html` in a browser. `frontend/config.js` already
points at `http://localhost:8000` by default.

## Deploy

**Backend (needs a real container — Playwright launches a browser):**
1. Push this repo to GitHub.
2. On [Render](https://render.com) or [Railway](https://railway.app): New Web
   Service → connect the repo → set root/Dockerfile path to `backend/`.
3. Add environment variables in the platform's dashboard:
   - `OPENAI_API_KEY`
   - `ALLOWED_ORIGINS` — set this *after* the frontend is deployed, to its URL.
4. Deploy. Note the resulting backend URL (e.g. `https://rl-coach-api.onrender.com`).

**Frontend (any static host):**
1. Deploy the `frontend/` folder to Netlify, Vercel, or Cloudflare Pages
   (drag-and-drop works fine, no build command needed).
2. Edit `frontend/config.js` to set `window.RL_COACH_API_BASE` to your backend
   URL from the step above, then redeploy the frontend.
3. Go back to the backend's env vars and set `ALLOWED_ORIGINS` to your
   frontend's live URL, then redeploy the backend so CORS is locked down.

**Before opening it to real traffic:** set a hard spend cap on your OpenAI
account (Settings → Limits). The built-in rate limit (10 requests/minute/IP)
slows abuse but won't cap total cost on its own.

## How stats get in
The app first tries to **auto-load** a profile by scraping Rocket League
Tracker. That site is behind Cloudflare bot protection, which blocks a plain
headless scraper — so the scraper runs a **headful, stealthed** Chromium and
waits for Cloudflare's challenge to clear, which gets past it (rank + MMR are
then parsed from the rendered page). If the challenge never clears (can happen
on datacenter IPs), the backend returns a `manual_required` signal and the
frontend falls back to a **manual entry form** where the player types their own
ranks/MMR. Either way the numbers flow into the same AI coach, so the app always
works end-to-end. There is no official public Tracker / Psyonix API for
backend username lookups, which is why the scraper + manual fallback is the path.

### Scraper knobs
- Headful is the default (it's what beats Cloudflare). Set
  `RL_SCRAPER_HEADLESS=1` to force headless — faster locally, but usually blocked.
- On a headless server the Dockerfile runs the app under `xvfb-run` so the
  headful browser has a virtual display.

## Notes / known limitations
- The scraper depends on Tracker Network's current HTML structure and their
  Cloudflare protection — the headful+stealth approach gets past it today, but
  Cloudflare is a moving target and success can be lower from datacenter IPs
  (cloud hosts). Scraping may also be against their ToS. The manual-entry
  fallback exists precisely so the app never fully depends on it.
- The coach is single-turn: each message is answered independently, without
  memory of earlier messages in the same chat.
