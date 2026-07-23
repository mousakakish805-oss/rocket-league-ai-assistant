# Deploy guide — Rocket League AI Coach

Two parts deploy separately:
- **Backend** → Render (needs a container; it runs a real browser for scraping)
- **Frontend** → Netlify (plain static files)

Do them in this order. Replace every `<PLACEHOLDER>` with your real value.

---

## Step 0 — Push your code to GitHub

Create an empty repo at https://github.com/new (name it `rocket-league-ai-assistant`,
**don't** add a README/.gitignore — you already have them). Then, in this project
folder (PowerShell):

```powershell
git branch -M main
git remote add origin https://github.com/<YOUR-GITHUB-USERNAME>/rocket-league-ai-assistant.git
git push -u origin main
```

If it asks you to log in, use your GitHub account (a browser window opens).

---

## Step 1 — Deploy the backend on Render

1. Go to https://dashboard.render.com → **New +** → **Web Service**.
2. Connect your GitHub and pick the `rocket-league-ai-assistant` repo.
3. Fill in the settings:
   - **Root Directory:** `backend`
   - **Runtime / Language:** `Docker`  (Render auto-detects the `backend/Dockerfile`)
   - **Instance Type:** Starter or higher recommended (the browser needs RAM;
     the free tier can work but is slow and sleeps when idle).
4. **Environment → Add Environment Variable:**

   | Key | Value |
   |-----|-------|
   | `OPENAI_API_KEY` | `sk-<YOUR-OPENAI-KEY>` |
   | `ALLOWED_ORIGINS` | `*`  ← temporary; you'll lock this down in Step 3 |

5. Click **Create Web Service** and wait for the build (first build is slow —
   it installs Chromium + xvfb).
6. When it's live, copy the URL at the top, e.g. `https://rl-coach-api.onrender.com`.
7. Test it: open `https://<YOUR-RENDER-URL>/` in a browser. You should see:
   ```json
   {"message":"Rocket League AI Assistant Backend active!"}
   ```

---

## Step 2 — Deploy the frontend on Netlify

1. Edit `frontend/config.js` and set it to your Render URL from Step 1:

   ```js
   window.RL_COACH_API_BASE = "https://<YOUR-RENDER-URL>";
   ```

2. Save. (Optional: `git add frontend/config.js && git commit -m "point frontend at prod backend" && git push`)
3. Go to https://app.netlify.com/drop and **drag the `frontend` folder** onto the page.
   No build command needed — it's plain static files.
4. Netlify gives you a URL, e.g. `https://rl-coach.netlify.app`. That's your live site.

---

## Step 3 — Lock down CORS (do this once the frontend URL exists)

1. Back in Render → your service → **Environment**, edit `ALLOWED_ORIGINS`:

   ```
   https://<YOUR-NETLIFY-URL>
   ```
   (no trailing slash; comma-separate if you have more than one origin)

2. Save — Render redeploys automatically. Now only your site can call the API.

---

## Step 4 — Set an OpenAI spend cap (important)

Go to https://platform.openai.com/settings/organization/limits and set a hard
monthly budget. The app already rate-limits requests, but a spend cap is what
actually protects you from a surprise bill once it's public.

---

## Done — verify end to end

Open your Netlify URL, type a username, and click **Load profile**:
- If the scrape gets through → real ranks load and the coach analyzes them.
- If Cloudflare blocks it (more likely from Render's datacenter IP) → the
  **manual entry form** appears; enter ranks and the coach works from those.

Either way the app works. If auto-scraping is blocked too often in production,
the next upgrade is a residential proxy in `backend/scraper.py`.

---

## Updating later

Any code change: `git add -A && git commit -m "…" && git push`.
- Render auto-redeploys the backend on push.
- For Netlify drag-and-drop, re-drag the `frontend` folder (or connect the repo
  for auto-deploys).
