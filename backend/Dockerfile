FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Playwright needs its browser binary + OS-level deps installed in the image.
RUN playwright install --with-deps chromium

# xvfb provides a virtual display so the scraper can run a *headful* Chromium
# on a server with no real screen -- headful is what gets past Cloudflare.
# xauth is required by the `xvfb-run` wrapper (without it: "xauth command not found").
RUN apt-get update && apt-get install -y --no-install-recommends xvfb xauth \
    && rm -rf /var/lib/apt/lists/*

COPY . .

# Most hosts (Render, Railway, Fly.io) inject $PORT; default to 8000 for local docker run.
ENV PORT=8000
# xvfb-run wraps uvicorn so any headful browser it launches gets a virtual display.
CMD ["sh", "-c", "xvfb-run -a uvicorn main:app --host 0.0.0.0 --port ${PORT}"]
