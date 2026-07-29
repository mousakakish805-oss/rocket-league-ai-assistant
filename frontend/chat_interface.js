// Rocket League AI Coach -- frontend logic
// Flow: lookup -> (not found -> retry / manual) -> stats dashboard -> coach chat
// Talks to the FastAPI backend: /api/v1/profile, /profile/manual,
// /coach/analyze, /coach/chat

const API_BASE = window.RL_COACH_API_BASE || "http://localhost:8000";

// Roughly SSL-ceiling MMR, used only to size the boost-meter fill bars.
const METER_MAX_MMR = 2000;

const PLATFORM_LABELS = {
  epic: "Epic",
  steam: "Steam",
  psn: "PlayStation",
  xbl: "Xbox",
};

const els = {
  views: {
    lookup: document.getElementById("view-lookup"),
    notfound: document.getElementById("view-notfound"),
    manual: document.getElementById("view-manual"),
    stats: document.getElementById("view-stats"),
    chat: document.getElementById("view-chat"),
  },

  lookupForm: document.getElementById("lookup-form"),
  platform: document.getElementById("platform"),
  username: document.getElementById("username"),
  lookupBtn: document.getElementById("lookup-btn"),
  lookupHint: document.getElementById("lookup-hint"),

  notfoundMessage: document.getElementById("notfound-message"),
  retryBtn: document.getElementById("retry-btn"),
  manualBtn: document.getElementById("manual-btn"),

  manualForm: document.getElementById("manual-form"),
  manualSubmit: document.getElementById("manual-submit"),
  manualBack: document.getElementById("manual-back"),

  statsName: document.getElementById("stats-name"),
  statsMeta: document.getElementById("stats-meta"),
  metersList: document.getElementById("meters-list"),
  lifetimeGrid: document.getElementById("lifetime-grid"),
  lifetimeEmpty: document.getElementById("lifetime-empty"),
  weaknessNote: document.getElementById("weakness-note"),
  activateCoach: document.getElementById("activate-coach"),
  newSearch: document.getElementById("new-search"),

  chatMeta: document.getElementById("chat-meta"),
  backToStats: document.getElementById("back-to-stats"),
  chatThread: document.getElementById("chat-thread"),
  chatForm: document.getElementById("chat-form"),
  chatInput: document.getElementById("chat-input"),
  chatSend: document.getElementById("chat-send"),
};

let currentPlayer = null;  // { platform, username }
let currentProfile = null; // the established profile dict
let coachStarted = false;  // opening analysis already requested?

// ---------- View switching ----------

function showView(name) {
  Object.entries(els.views).forEach(([key, el]) => {
    el.hidden = key !== name;
  });
  window.scrollTo({ top: 0, behavior: "smooth" });
}

// ---------- Helpers ----------

function escapeHtml(str) {
  const div = document.createElement("div");
  div.textContent = str == null ? "" : str;
  return div.innerHTML;
}

function escapeAttr(str) {
  return String(str == null ? "" : str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

// "Ranked Doubles 2v2" -> "2v2"
function playlistShort(name) {
  const m = String(name).match(/\d\s*v\s*\d/i);
  if (m) return m[0].replace(/\s/g, "").toLowerCase();
  return String(name).replace(/^Ranked\s+/i, "");
}

// Fallback badge glyph when no rank icon is available (manual entry).
function rankGlyph(rank) {
  const r = (rank || "").trim();
  if (!r || r.toLowerCase() === "unranked") return "–";
  return r.charAt(0).toUpperCase();
}

function platformLabel(slug) {
  return PLATFORM_LABELS[slug] || slug;
}

// ---------- Rendering: stats dashboard ----------

function renderMeters(rankedPlaylists) {
  els.metersList.innerHTML = "";
  const entries = Object.entries(rankedPlaylists || {});

  entries.forEach(([playlistName, info]) => {
    const mmr = Number(info.mmr) || 0;
    const pct = Math.max(4, Math.min(100, (mmr / METER_MAX_MMR) * 100));
    const peakMmr = Number(info.peak_mmr) || 0;
    const rank = info.rank || "Unranked";

    const badge = info.icon
      ? `<img class="rank-badge" src="${escapeAttr(info.icon)}" alt="${escapeAttr(rank)}" loading="lazy" onerror="this.replaceWith(Object.assign(document.createElement('div'),{className:'rank-badge rank-badge--fallback',textContent:'${escapeAttr(rankGlyph(rank))}'}))">`
      : `<div class="rank-badge rank-badge--fallback">${escapeHtml(rankGlyph(rank))}</div>`;

    const peak =
      peakMmr && peakMmr !== mmr ? `<span class="rank-peak">Peak ${peakMmr}</span>` : "";

    const card = document.createElement("div");
    card.className = "rank-card";
    card.innerHTML = `
      ${badge}
      <div class="rank-info">
        <div class="rank-top">
          <span class="rank-mode">${escapeHtml(playlistShort(playlistName))}</span>
          <span class="rank-name">${escapeHtml(rank)}</span>
        </div>
        <div class="meter-track">
          <div class="meter-fill" style="width:0%"></div>
        </div>
        <div class="rank-bottom">
          <span class="rank-mmr">${mmr ? mmr + " MMR" : "Unranked"}</span>
          ${peak}
        </div>
      </div>
    `;
    els.metersList.appendChild(card);

    // Animate the fill on the next frame (boost-charge transition).
    requestAnimationFrame(() => {
      card.querySelector(".meter-fill").style.width = pct + "%";
    });
  });
}

function renderLifetime(overview) {
  els.lifetimeGrid.innerHTML = "";
  const entries = Object.entries(overview || {});

  if (entries.length === 0) {
    els.lifetimeEmpty.hidden = false;
    return;
  }
  els.lifetimeEmpty.hidden = true;

  entries.forEach(([label, value]) => {
    const tile = document.createElement("div");
    tile.className = "stat-tile";
    tile.innerHTML = `
      <span class="stat-value">${escapeHtml(value)}</span>
      <span class="stat-label">${escapeHtml(label)}</span>
    `;
    els.lifetimeGrid.appendChild(tile);
  });
}

function renderWeaknesses(weaknesses) {
  if (!weaknesses || weaknesses.length === 0) {
    els.weaknessNote.hidden = true;
    return;
  }
  els.weaknessNote.textContent = weaknesses.join(" ");
  els.weaknessNote.hidden = false;
}

function showStats(profile, player) {
  currentProfile = profile;
  currentPlayer = player;
  coachStarted = false;

  els.statsName.textContent = player.username;
  const count = Object.keys(profile.ranked_playlists || {}).length;
  const sourceLabel = profile.source === "manual" ? "entered manually" : "from Tracker";
  els.statsMeta.textContent = `${platformLabel(player.platform)} · ${count} ranked playlist${count === 1 ? "" : "s"} · ${sourceLabel}`;
  els.chatMeta.textContent = `${player.username} · ${platformLabel(player.platform)}`;

  renderMeters(profile.ranked_playlists);
  renderLifetime(profile.overview);
  renderWeaknesses(profile.identified_weaknesses);

  showView("stats");
}

// ---------- Step 1: lookup ----------

function setLookupBusy(busy) {
  els.lookupBtn.disabled = busy;
  els.lookupBtn.textContent = busy ? "Looking up…" : "Continue";
  els.platform.disabled = busy;
  els.username.disabled = busy;
  els.lookupHint.textContent = busy
    ? "Fetching live stats… this can take up to a minute."
    : "First lookup can take up to a minute while the server wakes up.";
}

async function lookupProfile(platform, username) {
  setLookupBusy(true);
  try {
    const res = await fetch(`${API_BASE}/api/v1/profile`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ platform, username }),
    });

    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || `Lookup failed (${res.status})`);
    }

    const payload = await res.json();

    if (payload.status !== "success") {
      els.notfoundMessage.textContent =
        payload.message || "That profile couldn't be loaded.";
      showView("notfound");
      return;
    }

    showStats(payload.data || {}, { platform, username });
  } catch (err) {
    els.notfoundMessage.textContent =
      err.message || "Couldn't reach the server. Check your connection and try again.";
    showView("notfound");
  } finally {
    setLookupBusy(false);
  }
}

els.lookupForm.addEventListener("submit", (e) => {
  e.preventDefault();
  const platform = els.platform.value;
  const username = els.username.value.trim();
  if (!username) return;
  lookupProfile(platform, username);
});

// ---------- Step 1b: not found ----------

els.retryBtn.addEventListener("click", () => {
  showView("lookup");
  els.username.focus();
  els.username.select();
});

els.manualBtn.addEventListener("click", () => {
  showView("manual");
  els.manualForm.querySelector(".manual-rank")?.focus();
});

els.manualBack.addEventListener("click", () => showView("notfound"));

// ---------- Step 1c: manual entry ----------

function collectManualPlaylists() {
  const playlists = {};
  els.manualForm.querySelectorAll(".manual-rank").forEach((rankEl) => {
    const name = rankEl.dataset.playlist;
    const mmrEl = els.manualForm.querySelector(`.manual-mmr[data-playlist="${name}"]`);
    const rank = rankEl.value.trim();
    const mmr = parseInt(mmrEl?.value, 10);
    if (!rank && !mmr) return; // row left blank
    playlists[name] = { rank: rank || "Unranked", mmr: Number.isFinite(mmr) ? mmr : 0 };
  });
  return playlists;
}

els.manualForm.addEventListener("submit", async (e) => {
  e.preventDefault();

  const platform = els.platform.value;
  const username = els.username.value.trim() || "Player";
  const playlists = collectManualPlaylists();

  if (Object.keys(playlists).length === 0) {
    els.notfoundMessage.textContent = "Enter at least one playlist's rank or MMR.";
    showView("notfound");
    return;
  }

  els.manualSubmit.disabled = true;
  els.manualSubmit.textContent = "Working…";

  try {
    const res = await fetch(`${API_BASE}/api/v1/profile/manual`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ platform, username, playlists }),
    });

    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || `Couldn't use those ranks (${res.status})`);
    }

    const payload = await res.json();
    showStats(payload.data || {}, { platform, username });
  } catch (err) {
    els.notfoundMessage.textContent = err.message || "Couldn't use those ranks.";
    showView("notfound");
  } finally {
    els.manualSubmit.disabled = false;
    els.manualSubmit.textContent = "Show my stats";
  }
});

// ---------- Step 2 -> 3: activate coach ----------

els.newSearch.addEventListener("click", () => {
  showView("lookup");
  els.username.focus();
  els.username.select();
});

els.backToStats.addEventListener("click", () => showView("stats"));

function appendMessage(role, text, { pending = false } = {}) {
  const wrap = document.createElement("div");
  wrap.className = `chat-msg chat-msg--${role}${pending ? " chat-msg--pending" : ""}`;

  const roleLabel = document.createElement("span");
  roleLabel.className = "msg-role";
  roleLabel.textContent = role === "coach" ? "COACH" : "YOU";
  wrap.appendChild(roleLabel);

  const p = document.createElement("p");
  if (pending) {
    p.innerHTML = '<span class="typing-dots"><span></span><span></span><span></span></span>';
  } else {
    p.textContent = text;
  }
  wrap.appendChild(p);

  els.chatThread.appendChild(wrap);
  els.chatThread.scrollTop = els.chatThread.scrollHeight;
  return wrap;
}

function setChatEnabled(enabled) {
  els.chatInput.disabled = !enabled;
  els.chatSend.disabled = !enabled;
}

els.activateCoach.addEventListener("click", async () => {
  showView("chat");

  if (coachStarted) {
    els.chatInput.focus();
    return;
  }
  coachStarted = true;

  els.chatThread.innerHTML = "";
  setChatEnabled(false);
  const pending = appendMessage("coach", "", { pending: true });

  try {
    const res = await fetch(`${API_BASE}/api/v1/coach/analyze`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        platform: currentPlayer.platform,
        username: currentPlayer.username,
        profile: currentProfile,
      }),
    });

    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || `Coach failed to start (${res.status})`);
    }

    const payload = await res.json();
    pending.remove();
    appendMessage("coach", payload.reply || "Ask me anything about your game.");
  } catch (err) {
    pending.remove();
    appendMessage("coach", `Couldn't reach the coach: ${err.message}`);
    coachStarted = false; // let them retry
  } finally {
    setChatEnabled(true);
    els.chatInput.focus();
  }
});

// ---------- Step 3: chat ----------

async function sendMessage(query) {
  appendMessage("player", query);
  const pending = appendMessage("coach", "", { pending: true });
  setChatEnabled(false);

  try {
    const res = await fetch(`${API_BASE}/api/v1/coach/chat`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        platform: currentPlayer.platform,
        username: currentPlayer.username,
        query,
        profile: currentProfile,
      }),
    });

    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || `Coach request failed (${res.status})`);
    }

    const payload = await res.json();
    pending.remove();
    appendMessage("coach", payload.reply || "No response from coach.");
  } catch (err) {
    pending.remove();
    appendMessage("coach", `Couldn't reach the coach: ${err.message}`);
  } finally {
    setChatEnabled(true);
    els.chatInput.focus();
  }
}

els.chatForm.addEventListener("submit", (e) => {
  e.preventDefault();
  const query = els.chatInput.value.trim();
  if (!query) return;
  els.chatInput.value = "";
  sendMessage(query);
});
