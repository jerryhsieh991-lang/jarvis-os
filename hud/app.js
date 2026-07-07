/* V.A.U.L.T. front-end — vanilla JS, no build step, no dependencies. */
const $ = (id) => document.getElementById(id);

// ---------- theme + identity from config.json (the reskin seam) ----------
async function applyConfig() {
  const { assistant, theme } = await (await fetch("/api/config")).json();
  const map = {
    "--bg": theme.bg, "--panel": theme.panel, "--edge": theme.panel_edge,
    "--text": theme.text, "--dim": theme.text_dim, "--accent": theme.accent,
    "--accent2": theme.accent_2, "--warn": theme.warn, "--danger": theme.danger,
    "--font": theme.font,
  };
  for (const [k, v] of Object.entries(map)) document.documentElement.style.setProperty(k, v);
  document.title = theme.brand;
  $("brand-name").textContent = theme.brand;
  $("brand-tagline").textContent = assistant.tagline;
  $("logo-glyph").textContent = theme.logo_glyph;
  $("wake-hint").textContent = `say “${assistant.wake_word} …” or type below`;
}

// ---------- state polling ----------
function fmtUptime(sec) {
  const h = Math.floor(sec / 3600), m = Math.floor((sec % 3600) / 60);
  return h ? `${h}h ${m}m` : `${m}m ${sec % 60}s`;
}

async function refreshState() {
  try {
    const s = await (await fetch("/api/state")).json();
    $("m-cpu").textContent = Math.round(s.metrics.cpu);
    $("m-ram").textContent = Math.round(s.metrics.ram);
    const cpu = $("meter-cpu"), ram = $("meter-ram");
    cpu.style.width = `${s.metrics.cpu}%`; ram.style.width = `${s.metrics.ram}%`;
    cpu.classList.toggle("hot", s.metrics.cpu > 80);
    ram.classList.toggle("hot", s.metrics.ram > 80);
    $("m-notes").textContent = s.memory.notes;
    $("m-links").textContent = s.memory.links;
    $("m-uptime").textContent = fmtUptime(s.metrics.uptime_sec);
    $("m-host").textContent = s.metrics.host;

    const dot = $("brain-dot");
    dot.className = "dot " + (s.brain.online ? "online" : "offline");
    $("brain-label").textContent = `brain: ${s.brain.model} ${s.brain.online ? "online" : "offline"}`;

    $("skills").innerHTML = s.skills.map(sk => `
      <div class="skill">
        <div class="name">${sk.name}</div>
        <div class="desc">${sk.description}</div>
        <div class="trig">${sk.triggers.map(t => `<span>${t}</span>`).join("")}</div>
      </div>`).join("");

    if (s.schedule.length) {
      $("schedule").innerHTML = s.schedule.map(item => `<li>${item}</li>`).join("");
    }
  } catch { /* server restarting — keep last values */ }
}

// ---------- live event bus ----------
const ORB_STATES = ["idle", "listening", "thinking", "speaking"];
function setOrb(state) {
  const orb = $("orb");
  orb.className = "orb " + (ORB_STATES.includes(state) ? state : "idle");
  $("orb-state").textContent = state.toUpperCase();
}

function addMsg(kind, text, lane) {
  const feed = $("feed");
  const div = document.createElement("div");
  div.className = `msg ${kind}`;
  div.textContent = text;
  if (lane) {
    const tag = document.createElement("span");
    tag.className = "lane";
    tag.textContent = `[${lane}]`;
    div.appendChild(tag);
  }
  feed.appendChild(div);
  feed.scrollTop = feed.scrollHeight;
  while (feed.children.length > 80) feed.removeChild(feed.firstChild);
}

let ws;
let liveMsg = null; // the assistant bubble currently being streamed into

function startLiveMsg() {
  const feed = $("feed");
  liveMsg = document.createElement("div");
  liveMsg.className = "msg assistant";
  feed.appendChild(liveMsg);
}

function appendLiveMsg(text) {
  if (!liveMsg) startLiveMsg();
  liveMsg.textContent += text;
  const feed = $("feed");
  feed.scrollTop = feed.scrollHeight;
}

function endLiveMsg(lane) {
  if (!liveMsg) return;
  const tag = document.createElement("span");
  tag.className = "lane";
  tag.textContent = `[${lane}]`;
  liveMsg.appendChild(tag);
  liveMsg = null;
}

function connectWS() {
  ws = new WebSocket(`ws://${location.host}/ws`);
  ws.onmessage = (e) => {
    const { kind, payload } = JSON.parse(e.data);
    if (kind === "voice_state") setOrb(payload.state);
    else if (kind === "transcript") addMsg("transcript", `🎙 ${payload.text}`);
    else if (kind === "command") addMsg("user", payload.text);
    else if (kind === "response") addMsg("assistant", payload.text, payload.lane + (payload.saved_to ? " → vault" : ""));
    else if (kind === "response_start") startLiveMsg();
    else if (kind === "response_chunk") appendLiveMsg(payload.text);
    else if (kind === "response_done") endLiveMsg(payload.lane + (payload.saved_to ? " → vault" : ""));
    else if (kind === "wake") addMsg("transcript", "🟢 wake word — listening for command");
    else if (kind === "voice_error") addMsg("transcript", `⚠ mic unavailable: ${payload.detail} (text input still works)`);
  };
  ws.onclose = () => setTimeout(connectWS, 1500);
}

// ---------- command box ----------
$("command-form").addEventListener("submit", (e) => {
  e.preventDefault();
  const input = $("command-input");
  const text = input.value.trim();
  if (!text || !ws || ws.readyState !== 1) return;
  ws.send(JSON.stringify({ command: text, speak: $("speak-toggle").checked }));
  input.value = "";
});

applyConfig();
refreshState();
setInterval(refreshState, 4000);
connectWS();
setOrb("idle");
