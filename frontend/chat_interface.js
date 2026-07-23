// Rocket League AI Coach — frontend logic
// Talks to the FastAPI backend (main.py): /api/v1/coach/chat

const API_BASE = window.RL_COACH_API_BASE || "http://localhost:8000";

// Roughly SSL-ceiling MMR, used only to size the boost-meter fill bars.
const METER_MAX_MMR = 2000;

const els = {
  lookupForm: document.getElementById("lookup-form"),
  platform: document.getElementById("platform"),
  username: document.getElementById("username"),
  lookupBtn: document.getElementById("lookup-btn"),
  profileStatus: document.getElementById("profile-status"),
  rankMeters: document.getElementById("rank-meters"),
  metersList: document.getElementById("meters-list"),
  weaknessNote: document.getElementById("weakness-note"),

  manualToggle: document.getElementById("manual-toggle"),
  manualForm: document.getElementById("manual-form"),
  manualSubmit: document.getElementById("manual-submit"),

  chatThread: document.getElementById("chat-thread"),
  chatForm: document.getElementById("chat-form"),
  chatInput: document.getElementById("chat-input"),
  chatSend: document.getElementById("chat-send"),
};

let currentPlayer = null; // { platform, username }
let currentProfile = null; // established profile dict (scraped or manual)

// ---------- Helpers ----------

function setStatus(message, isError = false) {
  els.profileStatus.textContent = message;
  els.profileStatus.hidden = !message;
  els.profileStatus.classList.toggle("is-error", isError);
}

function setLookupBusy(busy) {
  els.lookupBtn.disabled = busy;
  els.lookupBtn.textContent = busy ? "Loading…" : "Load profile";
  els.platform.disabled = busy;
  els.username.disabled = busy;
}

function setChatEnabled(enabled) {
  els.chatInput.disabled = !enabled;
  els.chatSend.disabled = !enabled;
}

function showManualForm(show) {
  els.manualForm.hidden = !show;
  els.manualToggle.textContent = show
    ? "Hide manual entry"
    : "Enter ranks manually instead";
}

// Shared success path for both the auto-scrape and manual-entry flows: render
// the stat panel, post the coach's opening analysis, remember the profile so
// chat messages don't need to re-fetch it, and unlock the chat box.
function applyProfile(payload) {
  const data = payload.data || {};
  renderMeters(data.ranked_playlists);
  renderWeaknesses(data.identified_weaknesses);

  appendMessage("coach", payload.reply || "Profile loaded -- ask me anything.");

  currentPlayer = { platform: payload.platform, username: payload.username };
  currentProfile = data;
  setChatEnabled(true);
  els.chatInput.focus();
}

function appendMessage(role, text, { pending = false } = {}) {
  const wrap = document.createElement("div");
  wrap.className = `chat-msg chat-msg--${role}${pending ? " chat-msg--pending" : ""}`;

  const roleLabel = document.createElement("span");
  roleLabel.className = "msg-role";
  roleLabel.textContent = role === "coach" ? "COACH" : "YOU";
  wrap.appendChild(roleLabel);

  if (pending) {
    const p = document.createElement("p");
    p.innerHTML = '<span class="typing-dots"><span></span><span></span><span></span></span>';
    wrap.appendChild(p);
  } else {
    const p = document.createElement("p");
    p.textContent = text;
    wrap.appendChild(p);
  }

  els.chatThread.appendChild(wrap);
  els.chatThread.scrollTop = els.chatThread.scrollHeight;
  return wrap;
}

// Short playlist label: "Ranked Doubles 2v2" -> "2v2".
function playlistShort(name) {
  const m = String(name).match(/\d\s*v\s*\d/i);
  if (m) return m[0].replace(/\s/g, "").toLowerCase();
  return String(name).replace(/^Ranked\s+/i, "");
}

// Fallback badge for manually-entered ranks (no icon from the tracker):
// the rank's first letter, or a dash when unranked.
function rankGlyph(rank) {
  const r = (rank || "").trim();
  if (!r || r.toLowerCase() === "unranked") return "–";
  return r.charAt(0).toUpperCase();
}

function renderMeters(rankedPlaylists) {
  els.metersList.innerHTML = "";
  const entries = Object.entries(rankedPlaylists || {});

  if (entries.length === 0) {
    els.rankMeters.hidden = true;
    return;
  }

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

    // Animate fill in on next frame (gives the boost-charge transition).
    requestAnimationFrame(() => {
      card.querySelector(".meter-fill").style.width = pct + "%";
    });
  });

  els.rankMeters.hidden = false;
}

function renderWeaknesses(weaknesses) {
  if (!weaknesses || weaknesses.length === 0) {
    els.weaknessNote.hidden = true;
    return;
  }
  els.weaknessNote.textContent = weaknesses.join(" ");
  els.weaknessNote.hidden = false;
}

function escapeHtml(str) {
  const div = document.createElement("div");
  div.textContent = str;
  return div.innerHTML;
}

// Attribute-safe escaping (also handles quotes) for values dropped into
// src="" / alt="" via innerHTML.
function escapeAttr(str) {
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

// ---------- Profile lookup ----------

async function loadProfile(platform, username) {
  setLookupBusy(true);
  setStatus(`Looking up ${username} on ${platform}…`);
  els.rankMeters.hidden = true;
  els.weaknessNote.hidden = true;
  showManualForm(false);

  const pendingMsg = appendMessage("coach", "", { pending: true });

  try {
    const res = await fetch(`${API_BASE}/api/v1/coach/analyze`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ platform, username }),
    });

    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || `Lookup failed (${res.status})`);
    }

    const payload = await res.json();
    pendingMsg.remove();

    // Auto-lookup was blocked or empty -- fall back to manual entry.
    if (payload.status === "manual_required") {
      setStatus(payload.message || "Auto-lookup unavailable. Enter your ranks below.", true);
      // Pre-fill the platform/username context for the manual submit.
      currentPlayer = { platform, username };
      showManualForm(true);
      els.manualForm.querySelector(".manual-rank")?.focus();
      return;
    }

    applyProfile(payload);
    setStatus(`Loaded ${username} (${platform}). Ask away.`);
  } catch (err) {
    pendingMsg.remove();
    setStatus(err.message || "Couldn't load that profile.", true);
    currentPlayer = null;
    currentProfile = null;
    setChatEnabled(false);
  } finally {
    setLookupBusy(false);
  }
}

els.lookupForm.addEventListener("submit", (e) => {
  e.preventDefault();
  const platform = els.platform.value;
  const username = els.username.value.trim();
  if (!username) return;
  loadProfile(platform, username);
});

// ---------- Manual entry ----------

els.manualToggle.addEventListener("click", () => {
  showManualForm(els.manualForm.hidden);
  if (!els.manualForm.hidden) {
    els.manualForm.querySelector(".manual-rank")?.focus();
  }
});

function collectManualPlaylists() {
  const playlists = {};
  els.manualForm.querySelectorAll(".manual-rank").forEach((rankEl) => {
    const name = rankEl.dataset.playlist;
    const mmrEl = els.manualForm.querySelector(`.manual-mmr[data-playlist="${name}"]`);
    const rank = rankEl.value.trim();
    const mmr = parseInt(mmrEl?.value, 10);
    if (!rank && !mmr) return; // player left this row blank
    playlists[name] = { rank: rank || "Unranked", mmr: Number.isFinite(mmr) ? mmr : 0 };
  });
  return playlists;
}

async function submitManual() {
  const platform = els.platform.value;
  const username = els.username.value.trim() || (currentPlayer && currentPlayer.username) || "player";
  const playlists = collectManualPlaylists();

  if (Object.keys(playlists).length === 0) {
    setStatus("Enter at least one playlist's rank or MMR.", true);
    return;
  }

  els.manualSubmit.disabled = true;
  els.manualSubmit.textContent = "Working…";
  setStatus("Analyzing your ranks…");

  const pendingMsg = appendMessage("coach", "", { pending: true });

  try {
    const res = await fetch(`${API_BASE}/api/v1/coach/analyze_manual`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ platform, username, playlists }),
    });

    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || `Analysis failed (${res.status})`);
    }

    const payload = await res.json();
    pendingMsg.remove();
    applyProfile(payload);
    showManualForm(false);
    setStatus(`Coaching ${username} from your entered ranks. Ask away.`);
  } catch (err) {
    pendingMsg.remove();
    setStatus(err.message || "Couldn't analyze those ranks.", true);
  } finally {
    els.manualSubmit.disabled = false;
    els.manualSubmit.textContent = "Start coaching";
  }
}

els.manualForm.addEventListener("submit", (e) => {
  e.preventDefault();
  submitManual();
});

// ---------- Chat ----------

async function sendMessage(query) {
  if (!currentPlayer) return;

  appendMessage("player", query);
  const pendingMsg = appendMessage("coach", "", { pending: true });

  setChatEnabled(false);

  try {
    const res = await fetch(`${API_BASE}/api/v1/coach/chat`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        platform: currentPlayer.platform,
        username: currentPlayer.username,
        query,
        profile: currentProfile, // reuse established stats; don't re-scrape
      }),
    });

    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || `Coach request failed (${res.status})`);
    }

    const payload = await res.json();
    pendingMsg.remove();
    appendMessage("coach", payload.reply || "No response from coach.");

    // Keep the established profile / panel in sync with what the coach used.
    if (payload.profile && payload.profile.ranked_playlists) {
      currentProfile = payload.profile;
      renderMeters(payload.profile.ranked_playlists);
      renderWeaknesses(payload.profile.identified_weaknesses);
    }
  } catch (err) {
    pendingMsg.remove();
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
