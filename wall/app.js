/* Home hub wall screen (1280 x 800, an Android tablet on the wall).
   Everything shown comes from the hub: GET /api/state, then the /api/events WebSocket.
   Every control sends POST /api/action (see CONTRACT.md). No frameworks, no outside requests. */
(function () {
"use strict";

const stage = document.getElementById("stage");
const $ = (s) => stage.querySelector(s);
const $$ = (s) => Array.from(stage.querySelectorAll(s));

// ---------- icons (24 x 24 line icons) ----------
const I = {
  snow: '<path d="M12 2v20M3.3 7l17.4 10M3.3 17L20.7 7M9 4l3 2 3-2M9 20l3-2 3 2"/>',
  sun: '<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M2 12h2M20 12h2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/>',
  fan: '<circle cx="12" cy="12" r="2"/><path d="M12 10c0-4 1-7 4-7s3 4-2 7M14 12c4 0 7 1 7 4s-4 3-7-2M12 14c0 4-1 7-4 7s-3-4 2-7M10 12c-4 0-7-1-7-4s4-3 7 2"/>',
  drop: '<path d="M12 3s7 7.5 7 12a7 7 0 0 1-14 0c0-4.5 7-12 7-12z"/>',
  auto: '<path d="M4 12a8 8 0 0 1 14-5.3M20 12a8 8 0 0 1-14 5.3M18 3v4h-4M6 21v-4h4"/>',
  speaker: '<rect x="6" y="2" width="12" height="20" rx="3"/><circle cx="12" cy="14.5" r="3.5"/><circle cx="12" cy="6.5" r="1"/>',
  tv: '<rect x="2" y="4" width="20" height="13" rx="2"/><path d="M8 21h8"/>',
  frame: '<rect x="3" y="4" width="18" height="14" rx="1.5"/><path d="M6 15l4-4 3 3 2-2 3 3"/><path d="M8 21h8"/>',
  power: '<path d="M12 3v8M6.3 6.3a8 8 0 1 0 11.4 0"/>',
  pause: '<rect x="6" y="4" width="4" height="16" rx="1"/><rect x="14" y="4" width="4" height="16" rx="1"/>',
  play: '<path d="M7 4l13 8-13 8z"/>',
  next: '<path d="M4 5l9 7-9 7zM13 5l9 7-9 7z"/>',
  prev: '<path d="M20 5l-9 7 9 7zM11 5l-9 7 9 7z"/>',
  room: '<path d="M3 11l9-7 9 7v9a1 1 0 0 1-1 1h-5v-6h-6v6H4a1 1 0 0 1-1-1z"/>',
  group: '<path d="M10 14a4 4 0 0 0 5.7 0l3-3a4 4 0 0 0-5.7-5.7l-1 1M14 10a4 4 0 0 0-5.7 0l-3 3a4 4 0 0 0 5.7 5.7l1-1"/>',
  chev: '<path d="M9 5l7 7-7 7"/>',
  close: '<path d="M6 6l12 12M18 6L6 18"/>',
  plus: '<path d="M12 5v14M5 12h14"/>',
  remote: '<rect x="7" y="2.5" width="10" height="19" rx="3"/><circle cx="12" cy="8" r="2"/><path d="M10 13.5h4M10 16.5h4"/>',
  back: '<path d="M9 6l-5 5 5 5"/><path d="M4 11h11a5 5 0 0 1 0 10h-3"/>',
  playpause: '<path d="M3 5l9 7-9 7z"/><path d="M15 5v14M20 5v14"/>',
  check: '<path d="M5 12.5l4.5 4.5L19 7.5"/>',
  mute: '<path d="M4 9h4l5-4v14l-5-4H4z"/><path d="M17 9l4 6M21 9l-4 6"/>',
  gear: '<circle cx="12" cy="12" r="3.2"/><path d="M12 2.5v2.6M12 18.9v2.6M2.5 12h2.6M18.9 12h2.6M5.3 5.3l1.8 1.8M16.9 16.9l1.8 1.8M5.3 18.7l1.8-1.8M16.9 7.1l1.8-1.8"/><circle cx="12" cy="12" r="7"/>',
  mic: '<rect x="9" y="2.5" width="6" height="12" rx="3"/><path d="M5.5 11a6.5 6.5 0 0 0 13 0M12 17.5V21M8.5 21h7"/>',
  kbd: '<rect x="2.5" y="6" width="19" height="12" rx="2.5"/><path d="M6 10h.01M9 10h.01M12 10h.01M15 10h.01M18 10h.01M6.5 14h11"/>',
  warn: '<path d="M12 3.5l9.5 16.5h-19z"/><path d="M12 10v4.5M12 17.5h.01"/>',
  note: '<path d="M9 18V5l11-2v13"/><circle cx="6.5" cy="18" r="2.5"/><circle cx="17.5" cy="16" r="2.5"/>',
  thermo: '<path d="M14 14.8V4.5a2 2 0 0 0-4 0v10.3a4 4 0 1 0 4 0z"/><path d="M12 9v7"/>',
  heart: '<path d="M12 20.5s-8-5-8-11a4.6 4.6 0 0 1 8-3 4.6 4.6 0 0 1 8 3c0 6-8 11-8 11z"/>',
  spark: '<path d="M12 3l1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8zM18.5 15l.8 2.2 2.2.8-2.2.8-.8 2.2-.8-2.2-2.2-.8 2.2-.8z"/>',
  shuffle: '<path d="M3 7h3.5c2.5 0 4 1.5 5.5 4s3 4 5.5 4H21M3 17h3.5c2.5 0 4-1.5 5.5-4M15 7h2.5M17.5 7H21M18 4l3 3-3 3M18 12l3 3-3 3"/>',
  search: '<circle cx="11" cy="11" r="6.5"/><path d="M16 16l5 5"/>',
  link: '<path d="M10 14a4 4 0 0 0 5.7 0l3-3a4 4 0 0 0-5.7-5.7l-1 1M14 10a4 4 0 0 0-5.7 0l-3 3a4 4 0 0 0 5.7 5.7l1-1"/>',
};
const svg = (n) => `<svg viewBox="0 0 24 24">${I[n]}</svg>`;
const lineIcon = (n, size) => `<svg viewBox="0 0 24 24" style="width:${size}px;height:${size}px;stroke:currentColor;fill:none;stroke-width:2;vertical-align:-2px">${I[n]}</svg>`;
const esc = (v) => String(v == null ? "" : v).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const clone = (o) => (o == null ? o : JSON.parse(JSON.stringify(o)));
const cap = (s) => (s ? s[0].toUpperCase() + s.slice(1) : "");

// ---------- the hub address and key ----------
const params = new URLSearchParams(location.search);
// Served by the hub: always that hub. ?hub= is only for a copy opened from disk (file://), so a link such
// as http://<hub>/?hub=http://evil.example can never send this screen's key to another computer.
const SERVED = /^https?:$/.test(location.protocol);
const HUB = (SERVED ? location.origin : (params.get("hub") || "")).replace(/\/+$/, "");
const WS_URL = () => HUB.replace(/^http/, "ws") + "/api/events?key=" + encodeURIComponent(KEY);
let KEY = (function readKey() {
  const m = location.hash.match(/[#&]key=([^&]+)/);
  if (m) {
    const k = decodeURIComponent(m[1]);
    try { localStorage.setItem("hub.key", k); } catch (e) { /* private mode */ }
    history.replaceState(null, "", location.pathname + location.search);   // the key does not stay in the address
    return k;
  }
  try { return localStorage.getItem("hub.key") || ""; } catch (e) { return ""; }
})();
const auth = () => ({ Authorization: "Bearer " + KEY });

// ---------- state ----------
const savedLook = (() => { try { return JSON.parse(localStorage.getItem("hub.look")) || {}; } catch (e) { return {}; } })();
const S = {
  look: { layout: ["a", "b", "c"].includes(savedLook.layout) ? savedLook.layout : "a",
          scene: ["mountain", "night"].includes(savedLook.scene) ? savedLook.scene : "mountain" },
  server: null,       // the last state the hub sent
  view: null,         // server state plus the changes still on their way (optimistic)
  conn: "connecting", // connecting | online | offline | nokey
  open: null, openSrc: null,
  dragging: false,
  posBase: null,      // song position and when the hub said so
};
let pending = [];
let opSeq = 0;

function setServer(st) {
  if (!st || typeof st !== "object") return;
  S.server = st;
  const now = st.speakers && st.speakers.now;
  S.posBase = now && now.position != null ? { pos: now.position, at: Date.now(), playing: !!now.playing } : null;
  recompute();
}
function recompute() {
  const v = clone(S.server);
  if (v) pending.forEach((op) => { try { optimistic(v, op.action, op.args); } catch (e) { /* the hub answer decides */ } });
  S.view = v;
}

// what the screen shows at once, before the hub has answered (the hub answer always wins)
function optimistic(v, action, a) {
  const ac = v.aircon, sp = v.speakers, tvs = v.tvs;
  const zone = (id) => ac.zones.find((z) => z.id === id);
  const tv = () => tvs.devices.find((t) => t.id === a.tv);
  switch (action) {
    case "aircon.power": ac.power = a.on; break;
    case "aircon.set_temp": ac.set = a.value; break;
    case "aircon.nudge": ac.set = Math.max(16, Math.min(30, ac.set + a.delta)); break;
    case "aircon.mode": ac.mode = a.mode; ac.power = true; break;
    case "aircon.fan": ac.fan = a.speed; break;
    case "aircon.zone": { const z = zone(a.zone); z.on = a.on; z.open = a.on ? (z.open || 100) : 0; break; }
    case "aircon.zones_all": ac.zones.forEach((z) => { z.on = a.on; z.open = a.on ? (z.open || 100) : 0; }); break;
    case "music.play": if (sp.now) sp.now.playing = true; break;
    case "music.pause": if (sp.now) sp.now.playing = false; break;
    case "music.speakers":
      if (sp.now) sp.now.on = a.speakers.slice();
      sp.devices.forEach((d) => { d.in_use = a.speakers.includes(d.id); });
      break;
    case "speakers.volume":
      sp.devices.forEach((d) => { if (d.id === a.speaker || (a.speaker === "all" && d.in_use)) d.volume = a.value; });
      break;
    case "tv.power": { const t = tv(); if (a.on) { if (t.power !== "on") t.waking = true; } else { t.power = "off"; t.waking = false; } break; }
    case "tv.volume": { const t = tv(); t.volume = Math.max(0, Math.min(100, (t.volume || 0) + a.delta)); t.muted = false; break; }
    case "tv.mute": tv().muted = a.muted; break;
    case "tv.launch": tv().app = a.app; break;
    case "tv.art_mode": tv().art_mode = a.on; break;
    default: break;
  }
}

// ---------- reading the state ----------
const MODES = { cool: ["Cool", "Cooling", "snow", "cool"], heat: ["Heat", "Heating", "sun", "heat"], fan: ["Fan", "Fan", "fan", "cool"],
                dry: ["Dry", "Drying", "drop", "cool"], auto: ["Auto", "Auto", "auto", "cool"] };
const AC = () => (S.view ? S.view.aircon : undefined);
const SP = () => (S.view ? S.view.speakers : undefined);
const TV = () => (S.view ? S.view.tvs : undefined);
const mode = (ac) => MODES[ac.mode] || MODES.auto;
const zones = (ac) => ac.zones || [];
const zonesOn = (ac) => zones(ac).filter((z) => z.on).length;
const acTint = (ac) => (ac.power ? mode(ac)[3] : "off");
const acStatus = (ac) => (ac.power ? `${mode(ac)[1]} · ${zonesOn(ac)} of ${zones(ac).length} rooms` : "Off");
const fmtT = (t) => (t == null ? "–" : String(Math.round(t * 10) / 10));
const spDevices = (sp) => sp.devices || [];
const spName = (sp, id) => (spDevices(sp).find((d) => d.id === id) || { name: id }).name;
const nowOf = (sp) => (sp && sp.now) || null;
const playing = (sp) => !!(nowOf(sp) && nowOf(sp).playing);
const groupText = (sp) => { const n = nowOf(sp); return n && n.on && n.on.length ? n.on.map((id) => spName(sp, id)).join(" + ") : "No speaker picked"; };
const tvList = (tvs) => tvs.devices || [];
const tvShort = (t) => t.name.replace(/^The /, "").replace(/ Room$/, "");
const tvIcon = (t) => (t.kind === "samsung" || t.art_mode != null ? "frame" : "tv");
const tvKind = (t) => (t.kind === "samsung" ? "Samsung" : t.kind === "android" ? "Android TV" : "");
const tvState = (t) => (t.waking ? "Waking up…" : t.power === "on" ? "On" + (t.app ? " · " + t.app : "") : t.art_mode ? "Art mode" : "Off");
const tvsOn = (tvs) => tvList(tvs).filter((t) => t.power === "on").length;
const mmss = (s) => `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, "0")}`;
function posNow() {
  const n = nowOf(SP()); if (!n || !S.posBase) return null;
  let p = S.posBase.pos + (S.posBase.playing ? (Date.now() - S.posBase.at) / 1000 : 0);
  if (n.duration) p = Math.min(p, n.duration);
  return p;
}
const progPct = () => { const n = nowOf(SP()), p = posNow(); return n && n.duration && p != null ? (p / n.duration) * 100 : 0; };
function artBg(n) {
  const grad = "linear-gradient(140deg,#f6d365 0%,#fda085 45%,#8e44ad 100%)";
  if (n && typeof n.art === "string" && /^(https?:|data:image\/)/.test(n.art)) return `background-image:url('${esc(n.art.replace(/["'\\()\s<>]/g, encodeURIComponent))}'),${grad}`;
  return `background-image:${grad}`;
}
const down = (title, sub) => `<div class="down"><div class="ic">${svg("warn")}</div><div class="col grow"><div class="title" style="font-size:19px">${esc(title)}</div>
  <div class="hint">${esc(sub || "The hub keeps trying. Check it is plugged in.")}</div></div></div>`;
const waitCard = (label) => `<div class="label">${label}</div><div class="wait" style="margin-top:auto">Connecting to the hub…</div>`;

// ---------- shared pieces ----------
function insideChip(pad) {
  const ac = AC();
  if (!ac || !ac.available || ac.inside == null) return "";
  return `<div class="card row" data-chip style="padding:${pad || "12px 20px 12px 14px"};gap:14px;border-radius:22px">
    <div class="ic ${acTint(ac) === "off" ? "off" : acTint(ac)}">${svg("thermo")}</div>
    <div class="col"><div class="row" style="gap:10px"><span style="font-size:28px;font-weight:600">${fmtT(ac.inside)}°</span><span class="sub" style="color:#fff">Inside</span></div>
    <div class="sub">${HOME.place ? esc(HOME.place) + " · " : ""}${ac.power ? `${mode(ac)[1]} to ${ac.set}°` : "Aircon off"}</div></div></div>`;
}
function who(label) {
  if (!PEOPLE.length) return "";
  const btn = (n) => `<button class="person ${ME.name === n ? "here" : ""}" data-action="person" data-arg="${esc(n)}" data-src="p-${esc(n)}"><div class="face ${faceTint(n)}">${esc(n[0])}</div>${esc(n)}</button>`;
  return `<div class="who">${label ? '<span class="sub" style="margin-right:6px;text-shadow:0 1px 6px rgba(0,0,0,.4)">Tap your name</span>' : ""}
    ${PEOPLE.map(btn).join("")}</div>`;
}
// On the wall tablet, the AirTouch app is one tap away: a button next to the gear in every layout.
const gear = () => (window.HubAndroid ? `<button class="gear airtouch" data-do="airtouch" aria-label="Open the AirTouch app">${svg("fan")}</button>` : "") +
  `<button class="gear" data-open="settings" data-src="gear" aria-label="Look settings">${svg("gear")}</button>`;
const micBtn = (style) => `<button class="mic" id="mic" data-src="mic" aria-label="Hold to talk" style="${style || ""}"><span class="lvl"></span>${svg("mic")}</button>`;
const NATIVE = !!window.HubAndroid;   // inside the wall tablet's own app (tablet/), which records the voice itself
const kbdBtn = () => `<button class="kbd" data-open="ask" data-src="kbd" aria-label="Type a question">${svg("kbd")}</button>`;
const playBtn = (extra, cls) => `<button class="btn round fill ${playing(SP()) ? "white" : ""} ${cls || ""}" data-do="playPause" aria-label="${playing(SP()) ? "Pause" : "Play"}" style="${extra || ""}">${svg(playing(SP()) ? "pause" : "play")}</button>`;
const powerBtn = (doName, on, color, tv, busy) => `<button class="btn round ${on ? color : ""} ${busy ? "busy" : ""}" data-do="${doName}" ${tv ? `data-tv="${esc(tv)}"` : ""} aria-label="Power">${svg("power")}</button>`;
const prog = (h) => `<div class="vol grow" ${h ? `style="height:${h}px"` : ""}><i data-prog style="width:${progPct()}%"></i></div>`;

// ---------- layout A: lock screen and dock ----------
function acCardA() {
  const ac = AC();
  if (!S.view) return `<div class="card col" style="flex:1.05;padding:20px 22px">${waitCard("Aircon")}</div>`;
  if (!ac) return "";
  if (!ac.available) return `<div class="card col" data-card="aircon" style="flex:1.05;padding:20px 22px;justify-content:center">${down("Aircon not answering")}</div>`;
  return `<div class="card ${ac.power ? "on" : ""} col" data-card="aircon" data-open="aircon" data-src="a-aircon" style="flex:1.05;padding:20px 22px">
      <div class="row"><div class="ic ${acTint(ac)}">${svg(mode(ac)[2])}</div>
        <div class="col grow"><div class="title">Aircon</div><div class="sub">${acStatus(ac)}</div></div>
        ${powerBtn("acPower", ac.power, acTint(ac))}</div>
      <div class="row grow" style="justify-content:space-between;margin-top:6px">
        <button class="btn" data-do="nudge" data-arg="-1" aria-label="Cooler">−</button><div class="big" data-set style="font-size:72px">${ac.set}°</div><button class="btn" data-do="nudge" data-arg="1" aria-label="Warmer">+</button></div>
    </div>`;
}
// ---------- one tap music ----------
const linkedSp = (sp) => !!(sp && sp.spotify && sp.spotify.linked);
const pickList = (sp) => (S.pick && S.pick.length ? S.pick : (nowOf(sp) && nowOf(sp).on) || ["lounge-room"]);
function goBtn(sp, big) {
  const last = sp.spotify.last;
  return `<button class="go ${S.starting ? "busy" : ""}" data-do="musicStart" data-arg="recent" aria-label="Play music now" style="${big ? "" : "height:68px"}">
    <span class="goic">${svg("play")}</span>
    <span class="col" style="text-align:left;min-width:0"><b>${S.starting ? "Starting…" : "Play music"}</b><small class="ellip">${esc(last || "Liked Songs")}</small></span></button>`;
}
const plBtns = (sp) => `<button class="lst" data-do="musicStart" data-arg="liked">Liked Songs</button>` +
  (sp.spotify.playlists || []).slice(0, 3).map((p) => `<button class="lst" data-do="musicStart" data-arg="playlist:${esc(p.id)}"><span class="ellip">${esc(p.name)}</span></button>`).join("");
function quickMusic(sp) {
  if (!linkedSp(sp)) return "";
  const spk = spDevices(sp), on = pickList(sp);
  const chips = spk.map((d) => `<button class="pill ${on.includes(d.id) ? "sel" : ""}" data-do="pickSpk" data-arg="${esc(d.id)}" ${d.available ? "" : "disabled"} style="height:48px">${esc(d.name)}</button>`).join("");
  return `<div class="label" style="margin-top:4px">Play on</div>
    <div class="row" style="gap:10px;flex-wrap:wrap">${chips}</div>
    ${goBtn(sp, true)}
    <div class="lists">${plBtns(sp)}</div>`;
}
function musicCardA() {
  const sp = SP();
  if (!S.view) return `<div class="card col" style="flex:1.08;padding:20px 22px">${waitCard("Music")}</div>`;
  if (!sp) return "";
  if (!sp.available) return `<div class="card col" data-card="music" style="flex:1.08;padding:20px 22px;justify-content:center">${down("Speakers not answering")}</div>`;
  const n = nowOf(sp);
  if (!n) {
    return `<div class="card col" data-card="music" data-open="music" data-src="a-music" style="flex:1.08;padding:20px 22px">
      <div class="row"><div class="art empty">${svg("note")}</div>
        <div class="col grow"><div class="title">Nothing playing</div><div class="sub">${spDevices(sp).length} speakers ready</div></div>${spIcon(34)}</div>
      ${linkedSp(sp) ? `<div style="margin-top:auto">${goBtn(sp, false)}</div>` : `<div class="hint" style="margin-top:auto">Start Spotify on a phone and pick a ceiling speaker. It shows up here.</div>`}</div>`;
  }
  return `<div class="card col" data-card="music" data-open="music" data-src="a-music" style="flex:1.08;padding:20px 22px">
      <div class="row"><div class="art" style="${artBg(n)}"></div>
        <div class="col grow"><div class="title ellip">${esc(n.title)}</div><div class="sub ellip">${esc(n.artist)}</div>
        <div class="sub ellip" style="margin-top:2px">${lineIcon("group", 15)} ${esc(groupText(sp))}</div></div>${spIcon(34)}</div>
      <div class="row grow" style="gap:14px;margin-top:10px">
        ${playBtn()}<button class="btn round fill" data-do="next" aria-label="Next song">${svg("next")}</button>${prog()}</div>
    </div>`;
}
function tvCardA() {
  const tvs = TV();
  if (!S.view) return `<div class="card col" style="flex:1.12;padding:20px 22px">${waitCard("TVs")}</div>`;
  if (!tvs) return "";
  if (!tvs.available) return `<div class="card col" data-card="tvs" style="flex:1.12;padding:20px 22px;justify-content:center">${down("TVs not answering")}</div>`;
  const mini = tvList(tvs).map((t) => {
    const on = t.power === "on";
    return `<div class="${on ? "card on" : ""} col" style="flex:1;min-width:0;padding:12px 10px;border-radius:20px;box-shadow:none;${on ? "" : "background:rgba(255,255,255,.12)"}">
      <div class="ic ${on ? "green" : "off"}">${t.waking ? '<span class="spin" style="margin:0"></span>' : svg(tvIcon(t))}</div>
      <div class="title ellip" style="font-size:16px;margin-top:auto">${esc(tvShort(t))}</div>
      <div class="sub ellip" style="font-size:14px">${t.waking ? "Waking…" : on ? "On" : t.art_mode ? "Art mode" : "Off"}</div></div>`;
  }).join("");
  return `<div class="card col" data-card="tvs" data-open="tvs" data-src="a-tvs" style="flex:1.12;padding:20px 22px">
      <div class="label" style="margin-bottom:12px">TVs</div>
      <div class="row grow" style="gap:12px;align-items:stretch">${mini}</div></div>`;
}
function layoutA() {
  return `
  <div style="position:absolute;left:24px;top:24px">${insideChip()}</div>
  <div class="row" style="position:absolute;right:24px;top:24px;gap:10px">${who(true)}${gear()}</div>
  <div class="row" style="position:absolute;left:24px;right:24px;bottom:24px;gap:16px;align-items:stretch;height:212px">
    ${acCardA()}${musicCardA()}${tvCardA()}
    <div class="card talk col" style="width:112px;flex:none;padding:16px 0;border-radius:28px">
      ${micBtn()}<div class="sub" style="font-size:13px;margin-top:-4px">Hold to talk</div>${kbdBtn()}</div>
  </div>`;
}

// ---------- layout B: clock left, controls right ----------
function layoutB() {
  const ac = AC(), sp = SP(), tvs = TV();
  let acCard = "", music = "", tvCard = "";
  if (!S.view) {
    acCard = `<div class="card col" style="padding:20px 22px;height:300px">${waitCard("Aircon")}</div>`;
    music = `<div class="card col" style="padding:18px 22px;height:192px">${waitCard("Music")}</div>`;
    tvCard = `<div class="card col" style="padding:14px 22px;flex:1">${waitCard("TVs")}</div>`;
  } else {
    if (ac && !ac.available) acCard = `<div class="card col" data-card="aircon" style="padding:20px 22px;height:300px;justify-content:center">${down("Aircon not answering")}</div>`;
    else if (ac) {
      const pills = Object.entries(MODES).map(([k, m]) => `<button class="pill ${ac.mode === k ? "sel" + (k === "heat" ? " heat" : "") : ""}" data-do="acMode" data-arg="${k}" style="height:44px;padding:0 15px">${m[0]}</button>`).join("");
      const onRooms = zones(ac).filter((z) => z.on).map((z) => esc(z.name)).join(", ") || "No rooms on";
      acCard = `<div class="card ${ac.power ? "on" : ""} col" data-card="aircon" data-open="aircon" data-src="b-aircon" style="padding:20px 22px;height:300px">
      <div class="row"><div class="ic ${acTint(ac)}">${svg(mode(ac)[2])}</div><div class="col grow"><div class="title">Aircon</div><div class="sub">${ac.power ? mode(ac)[1] : "Off"}${ac.inside != null ? ` · Inside ${fmtT(ac.inside)}°` : ""}</div></div>
        ${powerBtn("acPower", ac.power, acTint(ac))}</div>
      <div class="row" style="justify-content:space-between;margin:14px 0 12px"><button class="btn" data-do="nudge" data-arg="-1" aria-label="Cooler">−</button><div class="big" data-set style="font-size:76px">${ac.set}°</div><button class="btn" data-do="nudge" data-arg="1" aria-label="Warmer">+</button></div>
      <div class="row" style="gap:7px">${pills}</div>
      <div class="row" style="margin-top:auto;border-top:1px solid ${ac.power ? "rgba(0,0,0,.08)" : "rgba(255,255,255,.14)"};padding-top:12px">
        <div class="col grow"><div style="font-size:16px;font-weight:600">${zonesOn(ac)} of ${zones(ac).length} rooms on</div><div class="sub ellip" style="font-size:14px">${onRooms}</div></div>
        <div class="sub row" style="gap:2px;font-weight:600">Rooms ${lineIcon("chev", 18)}</div></div></div>`;
    }
    if (sp && !sp.available) music = `<div class="card col" data-card="music" style="padding:18px 22px;height:192px;justify-content:center">${down("Speakers not answering")}</div>`;
    else if (sp && !nowOf(sp)) {
      music = `<div class="card col" data-card="music" data-open="music" data-src="b-music" style="padding:18px 22px;height:192px">
      <div class="row"><div class="art empty">${svg("note")}</div><div class="col grow"><div class="title">Nothing playing</div><div class="sub">${spDevices(sp).length} speakers ready</div></div>${spIcon(34)}</div>
      ${linkedSp(sp) ? `<div style="margin-top:auto">${goBtn(sp, false)}</div>` : `<div class="hint" style="margin-top:auto">Start Spotify on a phone and pick a ceiling speaker. It shows up here.</div>`}</div>`;
    } else if (sp) {
      const n = nowOf(sp);
      music = `<div class="card col" data-card="music" data-open="music" data-src="b-music" style="padding:18px 22px;height:192px">
      <div class="row"><div class="art" style="${artBg(n)}"></div><div class="col grow"><div class="title ellip">${esc(n.title)}</div><div class="sub ellip">${esc(n.artist)} · ${esc(groupText(sp))}</div></div>${spIcon(34)}</div>
      <div class="row" style="gap:12px;margin-top:auto">${playBtn()}<button class="btn round fill" data-do="next" aria-label="Next song">${svg("next")}</button>
        ${prog()}<div class="btn round">${svg("group")}</div></div></div>`;
    }
    if (tvs && !tvs.available) tvCard = `<div class="card col" data-card="tvs" style="padding:14px 22px;flex:1;justify-content:center">${down("TVs not answering")}</div>`;
    else if (tvs) {
      const rows = tvList(tvs).map((t) => `<div class="row" style="height:56px"><div class="ic ${t.power === "on" ? "green" : "off"}">${t.waking ? '<span class="spin" style="margin:0"></span>' : svg(tvIcon(t))}</div>
      <div class="col grow"><div class="title" style="font-size:19px">${esc(t.name)}</div><div class="sub ellip" style="font-size:15px">${esc(tvState(t))}</div></div>
      ${powerBtn("tvPower", t.power === "on", "green", t.id, t.waking)}</div>`).join("");
      tvCard = `<div class="card col" data-card="tvs" data-open="tvs" data-src="b-tvs" style="padding:14px 22px;flex:1;justify-content:space-between">${rows}</div>`;
    }
  }
  return `
  <div style="position:absolute;left:48px;bottom:40px" class="col">
    <div class="row" style="gap:14px;align-items:center">${insideChip()}<div class="talk">${micBtn()}${kbdBtn()}</div></div>
    <div class="row" style="margin-top:16px;gap:10px">${who(true)}${gear()}</div></div>
  <div class="col" style="position:absolute;right:24px;top:24px;bottom:24px;width:440px;gap:16px">${acCard}${music}${tvCard}</div>`;
}

// ---------- layout C: Apple Home style grid ----------
function tile(o) {
  const ic = `<div class="ic ${o.on ? o.color : "off"}" style="width:40px;height:40px">${o.spin ? '<span class="spin" style="margin:0"></span>' : svg(o.icon)}</div>`;
  const attrs = o.open ? `data-open="${o.open}" data-src="${esc(o.src)}"` : o.do ? `data-do="${o.do}" ${o.arg != null ? `data-arg="${esc(o.arg)}"` : ""} ${o.tv ? `data-tv="${esc(o.tv)}"` : ""} role="button"` : "";
  return `<div class="card ${o.on ? "on" : ""} col" ${attrs} style="grid-column:span ${o.wide ? 2 : 1};padding:10px 12px;border-radius:20px;box-shadow:none;cursor:pointer;min-width:0">
    <div class="row" style="justify-content:space-between">${ic}${o.extra || ""}</div>
    <div style="margin-top:auto;font-size:16px;font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">${esc(o.name)}</div><div class="sub ellip" style="font-size:14px">${esc(o.status)}</div></div>`;
}
function layoutC() {
  const ac = AC(), sp = SP(), tvs = TV();
  const pill = (open, icon, color, text, sel) => `<button class="pill" data-open="${open}" data-src="c-pill-${open}" style="height:48px;padding:0 18px 0 8px;${sel ? "background:rgba(255,255,255,.86);color:#111" : "backdrop-filter:blur(20px);-webkit-backdrop-filter:blur(20px)"}">
    <span class="ic ${color}" style="width:34px;height:34px">${svg(icon)}</span>${esc(text)}</button>`;
  const downPill = (icon, text) => `<div class="pill" style="height:48px;padding:0 18px 0 8px;backdrop-filter:blur(20px);-webkit-backdrop-filter:blur(20px)"><span class="ic" style="width:34px;height:34px;background:rgba(255,159,10,.3);color:#ffcf7a">${svg("warn")}</span>${esc(text)}</div>`;
  const small = (d, arg, t, label) => `<button class="btn hit8" data-do="${d}" data-arg="${arg}" aria-label="${label}" style="height:40px;min-width:40px;padding:0;font-size:22px">${t}</button>`;
  const head = (t) => `<div style="grid-column:1/-1;font-size:17px;font-weight:700;margin:4px 0 -4px 4px;text-shadow:0 1px 6px rgba(0,0,0,.45)">${t}</div>`;
  let pills = "", climate = "", media = "";
  if (!S.view) {
    climate = `<div class="card" style="grid-column:1/-1;padding:16px 20px;border-radius:20px"><div class="wait">Connecting to the hub…</div></div>`;
  } else {
    if (ac && !ac.available) { pills += downPill("warn", "Aircon not answering"); climate = `<div class="card" data-card="aircon" style="grid-column:1/-1;padding:14px 18px;border-radius:20px">${down("Aircon not answering")}</div>`; }
    else if (ac) {
      pills += pill("aircon", mode(ac)[2], acTint(ac), `Climate · ${ac.power ? ac.set + "°" : "Off"}`, ac.power);
      climate = tile({ name: `Aircon · ${ac.power ? mode(ac)[0] + " " + ac.set + "°" : "Off"}`, status: acStatus(ac), icon: mode(ac)[2], on: ac.power,
                       color: acTint(ac), wide: true, open: "aircon", src: "c-aircon",
                       extra: `<div class="row" style="gap:8px">${small("nudge", -1, "−", "Cooler")}${small("nudge", 1, "+", "Warmer")}</div>` });
      climate += zones(ac).map((z) => tile({ name: z.name, status: `${fmtT(z.temp)}°${z.on ? " · On" : ""}`, icon: "room", on: z.on, color: "cool", do: "zone", arg: z.id })).join("");
    }
    if (sp && !sp.available) { pills += downPill("warn", "Speakers not answering"); media += `<div class="card" data-card="music" style="grid-column:span 4;padding:14px 18px;border-radius:20px">${down("Speakers not answering")}</div>`; }
    else if (sp) {
      const n = nowOf(sp);
      pills += pill("music", "speaker", n ? "warm" : "off", n ? `Speakers · ${playing(sp) ? n.on.length + " playing" : "Paused"}` : "Speakers · Nothing playing");
      media += spDevices(sp).map((d, i) => {
        const inUse = n && n.on.includes(d.id);
        const status = !d.available ? "Not answering" : inUse ? `${i === 0 ? n.title + " · " : ""}${n.playing ? "Playing" : "Paused"}` : "Not playing";
        return tile({ name: d.name, status, icon: "speaker", on: inUse && n.playing, color: "warm", wide: i === 0, open: "music", src: "c-spk-" + d.id,
                      extra: i === 0 && n ? `<button class="btn round fill hit8" data-do="playPause" aria-label="${n.playing ? "Pause" : "Play"}" style="height:40px;min-width:40px;width:40px;background:#111;color:#fff">${svg(n.playing ? "pause" : "play")}</button>` : "" });
      }).join("");
    }
    if (tvs && !tvs.available) { pills += downPill("warn", "TVs not answering"); media += `<div class="card" data-card="tvs" style="grid-column:span 3;padding:14px 18px;border-radius:20px">${down("TVs not answering")}</div>`; }
    else if (tvs) {
      pills += pill("tvs", "tv", tvsOn(tvs) ? "green" : "off", `TVs · ${tvsOn(tvs)} on`);
      media += tvList(tvs).map((t) => tile({ name: t.name, status: tvState(t), icon: tvIcon(t), on: t.power === "on", spin: t.waking, color: "green", do: "tvPower", tv: t.id })).join("");
    }
  }
  return `
  <div style="position:absolute;left:24px;top:24px">${insideChip("8px 16px 8px 10px")}</div>
  <div class="row" style="position:absolute;right:24px;top:24px;gap:10px">${who(false)}${gear()}</div>
  <div class="row" style="position:absolute;left:24px;bottom:318px;gap:10px;align-items:flex-end">${pills}</div>
  <div class="talk" style="position:absolute;right:24px;bottom:318px">${kbdBtn()}${micBtn()}</div>
  <div style="position:absolute;left:24px;right:24px;bottom:24px;display:grid;grid-template-columns:repeat(9,minmax(0,1fr));grid-template-rows:auto 100px auto 100px;gap:10px">
    ${head("Climate")}${climate}${head("Speakers and TVs")}${media}</div>`;
}

// ---------- the expanded sheets ----------
function sheetAircon() {
  const ac = AC();
  if (!ac || !ac.available) return `<div style="padding-right:76px"><h2>Aircon</h2></div><div style="margin-top:30px">${down("Aircon not answering")}</div>`;
  const pills = Object.entries(MODES).map(([k, m]) => `<button class="pill ${ac.mode === k ? "sel" + (k === "heat" ? " heat" : "") : ""}" data-do="acMode" data-arg="${k}">${lineIcon(m[2], 18)} ${m[0]}</button>`).join("");
  const speeds = (ac.fan_speeds && ac.fan_speeds.length ? ac.fan_speeds : []);
  const fans = speeds.map((f) => `<button class="pill ${ac.fan === f ? "sel" : ""}" data-do="acFan" data-arg="${esc(f)}">${esc(cap(f))}</button>`).join("");
  const rooms = zones(ac).map((z) => `<button class="room ${z.on ? "on" : ""}" data-do="zone" data-arg="${esc(z.id)}">
      <div class="ic ${z.on ? "cool" : "off"}" style="width:40px;height:40px">${svg("room")}</div>
      <div class="tp" style="right:16px;top:12px">${fmtT(z.temp)}°</div>
      <div class="nm">${esc(z.name)}</div><div class="st">${z.on ? (z.open > 0 && z.open < 100 ? `On · ${z.open}% open` : "On") : "Off"}</div></button>`).join("");
  return `
  <div class="row" style="padding-right:76px"><div class="ic ${acTint(ac)}" style="width:52px;height:52px">${svg(mode(ac)[2])}</div>
    <div class="col grow"><h2>Aircon</h2><div class="sub">${ac.power ? mode(ac)[1] : "Off"}${ac.inside != null ? ` · Inside ${fmtT(ac.inside)}°` : ""}${HOME.place ? " · " + esc(HOME.place) : ""}</div></div>
    <button class="pill" data-do="acPower" style="height:56px;padding:0 22px;${ac.power ? "background:var(--cool);color:#fff" : ""}">${lineIcon("power", 22)} ${ac.power ? "On" : "Off"}</button></div>
  <div class="row" style="align-items:flex-start;gap:40px;margin-top:30px">
    <div class="col" style="width:400px;gap:12px">
      <div class="label">Set to</div>
      <div class="row" style="justify-content:space-between"><button class="btn" data-do="setTemp" data-arg="-1" aria-label="Cooler" style="height:72px;min-width:72px;font-size:32px">−</button>
        <div class="big" data-set style="font-size:110px;font-weight:200">${ac.set}°</div>
        <button class="btn" data-do="setTemp" data-arg="1" aria-label="Warmer" style="height:72px;min-width:72px;font-size:32px">+</button></div>
      <div class="label" style="margin-top:14px">Mode</div><div class="seg">${pills}</div>
      ${fans ? `<div class="label" style="margin-top:14px">Fan speed</div><div class="seg">${fans}</div>` : ""}
    </div>
    <div class="col grow" style="gap:14px">
      <div class="row"><div class="col grow"><div class="label">Rooms</div><div style="font-size:20px;font-weight:600;margin-top:2px">${zonesOn(ac)} of ${zones(ac).length} on</div></div>
        <button class="pill" data-do="zonesAll" data-arg="on">All on</button><button class="pill" data-do="zonesAll" data-arg="off">All off</button></div>
      <div class="rooms">${rooms}</div>
      <div class="sub" style="font-size:14px">Tap a room to open or close its vent.</div>
    </div>
  </div>`;
}
function spkRows(sp, n) {
  return spDevices(sp).map((d) => {
    const inUse = !!(n && n.on.includes(d.id));
    const status = !d.available ? "Not answering" : d.muted ? "Muted" : inUse ? (n.playing ? "Playing" : "Paused") : "Not playing";
    const vol = d.volume == null ? 0 : d.volume;
    const tick = n ? `<button class="tick" data-do="spkGroup" data-arg="${esc(d.id)}" aria-label="Play in ${esc(d.name)}" ${d.available ? "" : "disabled"}
          style="width:56px;height:56px;display:grid;place-items:center;flex:none;margin:-11px -6px"><span class="check ${inUse ? "on" : ""}">${svg("check")}</span></button>` : "";
    const name = `<div class="col" style="width:170px;flex:none;text-align:left"><div style="font-size:19px;font-weight:600">${esc(d.name)}</div>
        <div class="sub" style="font-size:14px">${status}</div></div>`;
    return `<div class="spk" data-spk="${esc(d.id)}" style="${d.available ? "" : "opacity:.55"}">${tick}
      ${n ? `<button data-do="spkGroup" data-arg="${esc(d.id)}" style="flex:none;min-height:56px;margin:-10px 0" ${d.available ? "" : "disabled"}>${name}</button>` : name}
      <div class="ic ${inUse && n.playing ? "warm" : "off"}" style="width:36px;height:36px">${svg("speaker")}</div>
      <input type="range" min="0" max="100" value="${vol}" data-vol="${esc(d.id)}" aria-label="${esc(d.name)} volume" style="--p:${vol}%" ${d.available ? "" : "disabled"}>
      <span class="sub" data-vol-label style="width:34px;text-align:right;font-size:15px">${vol}</span>
    </div>`;
  }).join("");
}
function spotifyNote(sp) {
  if (!sp.spotify || sp.spotify.linked) return "";
  return `<div class="notice">${svg("link")}<span>Spotify is not linked yet. Link Spotify on the iMac so the hub can move songs and find music.</span></div>`;
}
// ---------- the Spotify music view ----------
// Spotify's own icon and logo, unaltered (wall/assets/SOURCE.txt). The icon is always 21px or bigger, the logo always 70px or wider.
const SP_ICON = "assets/spotify-icon-green.svg", SP_LOGO = "assets/spotify-logo-green.svg";
const spLogo = (h) => `<img class="splogo" src="${SP_LOGO}" alt="Spotify" style="height:${h}px">`;
const spIcon = (px) => `<img class="spicon" src="${SP_ICON}" alt="Spotify" style="width:${px}px;height:${px}px">`;
const M = { tab: "home", lib: null, loading: false, err: null, q: "", res: null, searching: false, pickMain: false, seq: 0, timer: null };
const okImg = (u) => typeof u === "string" && /^https:\/\/[a-z0-9.-]+\.(scdn\.co|spotifycdn\.com)\//i.test(u);
const imgDiv = (u, cls, inner) => `<div class="${cls}" ${okImg(u) ? `style="background-image:url('${esc(u.replace(/["'\\()\s<>]/g, encodeURIComponent))}')"` : ""}>${inner || ""}</div>`;
const MTABS = [["home", "Home"], ["search", "Search"], ["playlists", "Playlists"], ["speakers", "Speakers"]];
const mTabs = () => MTABS.map(([k, t]) => `<button class="pill ${M.tab === k ? "sel" : ""}" data-do="mTab" data-arg="${k}" style="height:56px;padding:0 24px;font-size:18px">${t}</button>`).join("");
async function hubGet(path) {
  try {
    const r = await fetch(HUB + path, { headers: auth() });
    let b = null; try { b = await r.json(); } catch (e) { /* not JSON */ }
    if (r.status === 401) { needKey(true); return null; }
    return { ok: r.ok && !!(b && b.ok), status: r.status, body: b };
  } catch (e) { return { ok: false, status: 0, body: null }; }
}
async function loadLib(fresh) {
  if (!linkedSp(SP())) return;
  M.loading = !M.lib; M.err = null; renderBrowse();
  const r = await hubGet("/api/music/library" + (fresh ? "?fresh=1" : ""));
  M.loading = false;
  if (r && r.ok) M.lib = r.body.library; else M.err = r ? errorText(r.status, r.body) : "The hub needs its key.";
  renderBrowse();
}
function musicOpened() { M.tab = "home"; M.q = ""; M.res = null; M.pickMain = false; loadLib(true); }
async function doSearch() {
  const q = M.q.trim(), seq = ++M.seq;
  if (!q) { M.res = null; M.searching = false; renderBrowse(); return; }
  M.searching = true; renderBrowse();
  const r = await hubGet("/api/music/search?q=" + encodeURIComponent(q));
  if (seq !== M.seq) return;
  M.searching = false;
  M.res = r && r.ok ? r.body.results : { error: r ? errorText(r.status, r.body) : "The hub needs its key." };
  renderBrowse();
}
function renderBrowse() {
  const b = $("[data-mbrowse]"); if (!b || S.open !== "music") return;
  b.innerHTML = mBrowse();
  const t = $("[data-mtabs]"); if (t) t.innerHTML = mTabs();
  const bar = $("[data-msearchbar]"); if (bar) bar.style.display = M.tab === "search" ? "flex" : "none";
}
const mRow = (it, what) => `<button class="mrow" data-do="mPlayUri" data-arg="${esc(it.uri)}">${imgDiv(it.image, "mimg" + (what === "Artist" ? " round" : ""))}
  <span class="col" style="min-width:0;text-align:left"><b class="ellip">${esc(it.name)}</b><small class="ellip">${esc(it.sub || what)}</small></span></button>`;
function mHome(sp) {
  const lib = M.lib;
  if (!lib) return M.err ? `<div class="notice">${svg("warn")}<span>${esc(M.err)}</span></div>` : `<div class="wait">Loading your Spotify…</div>`;
  const main = lib.playlists.find((p) => p.id === lib.main);
  const recent = lib.recent || [];
  const tile = (arg, art, name, sub) => `<button class="mtile" data-do="musicStart" data-arg="${arg}">${art}<span class="col" style="min-width:0;text-align:left"><b class="ellip">${esc(name)}</b><small class="ellip">${esc(sub)}</small></span></button>`;
  const tiles = [
    tile("liked", `<div class="mimg tile liked">${lineIcon("heart", 40)}</div>`, "Liked Songs", "Your saved songs"),
    main ? tile("main", imgDiv(main.image, "mimg tile"), main.name, "Your main playlist") : "",
    lib.discover ? tile("discover", `<div class="mimg tile disc">${lineIcon("spark", 40)}</div>`, "Discover Weekly", "Made for you, every Monday") : "",
    recent.length || (sp.spotify && sp.spotify.last) ? tile("recent", imgDiv(recent[0] && recent[0].image, "mimg tile"), "Recently played", (sp.spotify && sp.spotify.last) || recent[0].name) : "",
  ].join("");
  return `<div class="mtiles">${tiles}</div>
    <div class="row" style="margin:16px 0 8px"><div class="label grow">Recently played songs</div>
      <button class="pill" data-do="mPickMain" style="height:48px">Change main playlist</button></div>
    <div class="mrows">${recent.slice(0, 8).map((t) => mRow(t, "Song")).join("") || '<div class="hint">Nothing played lately. Search for a song, or pick a playlist.</div>'}</div>`;
}
function mSearch() {
  const r = M.res;
  if (M.searching && !r) return `<div class="wait">Searching…</div>`;
  if (!M.q.trim()) return `<div class="hint" style="font-size:18px;padding:8px 4px">Type a song, an artist, an album or a playlist. Tap anything to play it.</div>`;
  if (!r) return "";
  if (r.error) return `<div class="notice">${svg("warn")}<span>${esc(r.error)}</span></div>`;
  const sec = (title, list, what) => list.length ? `<div class="label" style="margin:14px 0 8px">${title}</div><div class="mrows">${list.map((i) => mRow(i, what)).join("")}</div>` : "";
  const all = sec("Songs", r.tracks, "Song") + sec("Artists", r.artists, "Artist") + sec("Albums", r.albums, "Album") + sec("Playlists", r.playlists, "Playlist");
  return all || `<div class="hint" style="font-size:18px;padding:8px 4px">Spotify found nothing for “${esc(M.q.trim())}”.</div>`;
}
function mPlaylists() {
  const lib = M.lib;
  if (!lib) return M.err ? `<div class="notice">${svg("warn")}<span>${esc(M.err)}</span></div>` : `<div class="wait">Loading your playlists…</div>`;
  const head = M.pickMain ? `<div class="notice" style="margin-bottom:12px">${svg("check")}<span class="grow">Tap the playlist you want as your main one.</span>
      <button class="pill" data-do="mPickMain" style="height:44px">Cancel</button></div>` : "";
  const cards = lib.playlists.map((p) => `<button class="mcard ${p.id === lib.main ? "isMain" : ""}" data-do="${M.pickMain ? "mSetMain" : "musicStart"}" data-arg="${M.pickMain ? esc(p.id) : "playlist:" + esc(p.id)}">
      ${imgDiv(p.image, "mcov", p.id === lib.main ? '<span class="mbadge">Main</span>' : "")}<b class="ellip">${esc(p.name)}</b></button>`).join("");
  return head + (cards ? `<div class="mgrid">${cards}</div>` : `<div class="hint">There are no playlists in his Spotify yet.</div>`) +
    (!M.pickMain ? `<div class="row" style="margin-top:12px"><button class="pill" data-do="mPickMain">Change main playlist</button></div>` : "");
}
function mBrowse() {
  const sp = SP();
  if (M.tab === "search") return mSearch();
  if (M.tab === "playlists") return mPlaylists();
  if (M.tab === "speakers") return `<div class="col" style="gap:10px">${spkRows(sp, nowOf(sp))}</div>`;
  return mHome(sp);
}
function mNow(sp) {
  const n = nowOf(sp);
  if (!n) {
    return `<div class="bigart empty">${spIcon(110)}</div>
      <div><div style="font-size:28px;font-weight:700">Nothing playing</div>
      <div class="hint" style="font-size:17px;margin-top:6px">Tap Liked Songs, a playlist or a search result. It plays on the speakers picked below.</div></div>`;
  }
  const inUse = spDevices(sp).filter((d) => n.on.includes(d.id));
  const allVol = inUse.length ? Math.round(inUse.reduce((a, d) => a + (d.volume || 0), 0) / inUse.length) : 0;
  const p = posNow();
  return `<div class="bigart" style="${artBg(n)}"></div>
    <div><div style="font-size:26px;font-weight:700" class="ellip">${esc(n.title)}</div><div class="sub ellip" style="font-size:18px">${esc(n.artist)}</div></div>
    ${n.duration ? `<div>${prog(8)}<div class="row sub" style="justify-content:space-between;font-size:14px;margin-top:6px"><span data-pos>${p != null ? mmss(p) : ""}</span><span>${mmss(n.duration)}</span></div></div>` : ""}
    <div class="row" style="justify-content:center;gap:10px">
      ${linkedSp(sp) ? `<button class="btn round ${n.shuffle ? "green" : "fill"}" data-do="shuffle" aria-label="Shuffle ${n.shuffle ? "on" : "off"}" style="width:56px;height:56px">${svg("shuffle")}</button>` : ""}
      <button class="btn round fill" data-do="prev" aria-label="Previous song" style="width:60px;height:60px">${svg("prev")}</button>
      <button class="btn round fill white" data-do="playPause" aria-label="${n.playing ? "Pause" : "Play"}" style="width:80px;height:80px;border-radius:40px">${svg(n.playing ? "pause" : "play")}</button>
      <button class="btn round fill" data-do="next" aria-label="Next song" style="width:60px;height:60px">${svg("next")}</button></div>
    <div class="row"><span class="ic off" style="width:30px;height:30px;flex:none">${svg("speaker")}</span><input type="range" min="0" max="100" value="${allVol}" data-vol="all" aria-label="Volume" style="--p:${allVol}%"></div>`;
}
function mPlayOn(sp) {
  const n = nowOf(sp), on = n ? n.on : pickList(sp);
  return `<span class="label" style="flex:none">Play on</span>` + spDevices(sp).map((d) =>
    `<button class="pill ${on.includes(d.id) ? "sel" : ""}" data-do="chipSpk" data-arg="${esc(d.id)}" ${d.available ? "" : "disabled"} style="height:52px;font-size:17px">${esc(d.name)}</button>`).join("");
}
function sheetMusic() {
  const sp = SP();
  if (!sp || !sp.available) return `<div style="padding-right:76px"><h2>Music</h2></div><div style="margin-top:30px">${down("Speakers not answering")}</div>`;
  const linked = linkedSp(sp);
  if (!linked) {                                      // Cast only: the controls and speakers, and a note about linking
    const n = nowOf(sp);
    return `<div class="row mroot" data-mroot="0" style="align-items:flex-start;gap:32px;height:100%">
      <div class="col mleft" style="width:300px;gap:14px">${mNow(sp)}</div>
      <div class="col grow" style="min-width:0;gap:14px;padding-right:76px">${spLogo(36)}${spotifyNote(sp)}
        <div class="label" style="margin-top:6px">${n ? "Speakers · tick to play there" : "Speakers"}</div><div class="col" style="gap:10px">${spkRows(sp, n)}</div></div></div>`;
  }
  return `<div class="row mroot" data-mroot="1" style="align-items:flex-start;gap:32px;height:100%">
    <div class="col mleft" data-mnow style="width:300px;gap:14px">${mNow(sp)}</div>
    <div class="col grow" style="min-width:0;height:100%;gap:12px">
      <div class="row" style="padding-right:76px;height:40px">${spLogo(34)}</div>
      <div class="row" data-mtabs style="gap:10px">${mTabs()}</div>
      <div class="msearchbar" data-msearchbar style="display:${M.tab === "search" ? "flex" : "none"}">${lineIcon("search", 26)}
        <input id="msearch" type="text" value="${esc(M.q)}" placeholder="Songs, artists, albums, playlists" enterkeyhint="search" autocomplete="off" autocapitalize="off" spellcheck="false" aria-label="Search Spotify" maxlength="120">
        <button class="btn round" data-do="mClear" aria-label="Clear search" style="width:44px;height:44px;min-width:44px">${svg("close")}</button></div>
      <div class="mbrowse grow" data-mbrowse>${mBrowse()}</div>
      <div class="row mplayon" data-mplayon style="gap:10px;flex-wrap:nowrap">${mPlayOn(sp)}</div>
    </div></div>`;
}
// A TV app's logo (tvlogos.js, drawn in the button's own colour), or its name as a wordmark when there is none.
function tvAppMark(name) {
  const L = (window.TV_LOGOS || {})[name];
  if (L) {     // 26px tall, wide wordmarks capped at 88px wide
    const [x, y, w, h] = L.box, ht = Math.min(26, 88 * h / w), wd = ht * w / h;
    return `<svg viewBox="${x} ${y} ${w} ${h}" width="${wd.toFixed(1)}" height="${ht.toFixed(1)}" fill="currentColor" aria-hidden="true"><path d="${esc(L.d)}"/></svg>`;
  }
  const F = (window.TV_LOGO_FILES || {})[name];
  if (F) {     // a logo file: its shape only, as a mask filled with the button's colour
    const ht = Math.min(F.h || 26, 88 / F.ratio), wd = ht * F.ratio, u = `url(${esc(F.src)})`;
    return `<span class="tvmask" aria-hidden="true" style="width:${wd.toFixed(1)}px;height:${ht.toFixed(1)}px;-webkit-mask-image:${u};mask-image:${u}"></span>`;
  }
  return `<span class="tvword" aria-hidden="true">${esc(name)}</span>`;
}
// Each TV's own list of services (the ones signed in there), kept on this tablet. No list yet: all of them.
const TVL = (() => { try { const v = JSON.parse(localStorage.getItem("hub.tvapps")); return v && typeof v === "object" ? v : {}; } catch (e) { return {}; } })();
let tvEdit = null;                          // the TV whose list is being changed (the + button)
function saveTvl() { try { localStorage.setItem("hub.tvapps", JSON.stringify(TVL)); } catch (e) { /* private mode */ } }
function tvShown(tv, all) { const l = TVL[tv]; return Array.isArray(l) ? l.filter((a) => all.includes(a)) : all.slice(); }
// The list to change: the saved one as it is (a service the hub has not listed yet must not drop out of it).
function tvListFor(tv) { const l = TVL[tv]; return Array.isArray(l) ? l.slice() : ((TV() || {}).apps || []).slice(); }
const tvPill = (a, tv, doName, sel) => `<button class="pill tvapp ${sel ? "sel" : ""}" data-do="${doName}" data-tv="${esc(tv)}" data-arg="${esc(a)}" aria-label="${esc(a)}" title="${esc(a)}">${tvAppMark(a)}</button>`;
function tvEditBox(t, all) {
  const shown = tvShown(t.id, all), rest = all.filter((a) => !shown.includes(a));
  return `<div class="col" style="gap:10px">
      <div class="sub" style="font-size:14px">On this TV's panel. Drag to change the order, tap one to take it off.</div>
      <div class="row tvorder" style="gap:8px 6px;flex-wrap:wrap">${shown.map((a) => tvPill(a, t.id, "tvAppHide")).join("") || `<div class="sub">None yet.</div>`}</div>
      <div class="sub" style="font-size:14px;margin-top:6px">Add a service. It opens on the TV so you can sign in there.</div>
      <div class="row" style="gap:8px 6px;flex-wrap:wrap">${rest.map((a) => tvPill(a, t.id, "tvAppAdd")).join("") || `<div class="sub">Every service is on the panel.</div>`}</div>
      <div class="row" style="margin-top:4px"><button class="pill sel" data-do="tvEdit" data-tv="${esc(t.id)}" style="height:48px;padding:0 24px">Done</button></div>
    </div>`;
}
// The remote (the remote button on a TV card): arrows and OK, Back, Home, rewind, play/pause, fast forward.
let tvRemote = null;
function tvRemoteBox(t) {
  const k = (key, label, inner, cls) => `<button class="rk ${cls || ""}" data-do="tvKey" data-tv="${esc(t.id)}" data-arg="${key}" aria-label="${label}">${inner}</button>`;
  return `<div class="remote">
      <div class="dpad">
        ${k("up", "Up", svg("chev"), "up")}${k("left", "Left", svg("chev"), "left")}${k("ok", "OK", "OK", "ok")}${k("right", "Right", svg("chev"), "right")}${k("down", "Down", svg("chev"), "down")}
      </div>
      <div class="row rrow">${k("back", "Back", svg("back"))}${k("home", "Home", svg("room"))}</div>
      <div class="row rrow">${k("rewind", "Rewind", svg("prev"))}${k("play_pause", "Play or pause", svg("playpause"))}${k("fast_forward", "Fast forward", svg("next"))}</div>
    </div>`;
}
function sheetTvs() {
  const tvs = TV();
  if (!tvs || !tvs.available) return `<div style="padding-right:76px"><h2>TVs</h2></div><div style="margin-top:30px">${down("TVs not answering")}</div>`;
  const list = tvList(tvs);
  const anyArt = list.some((t) => t.art_mode != null);
  const cards = list.map((t) => {
    const on = t.power === "on";
    const scr = t.waking ? `<div class="screen waking"><span><span class="spin"></span>Waking up…</span></div>`
      : on ? `<div class="screen on">${esc(t.app || "On")}</div>` : t.art_mode ? `<div class="screen artmode">Art mode</div>` : `<div class="screen">Off</div>`;
    const all = tvs.apps || [], editing = tvEdit === t.id, remote = tvRemote === t.id && on;
    const apps = tvShown(t.id, all).map((a) => tvPill(a, t.id, "tvApp", on && t.app === a)).join("") +
      `<button class="pill tvapp tvadd" data-do="tvEdit" data-tv="${esc(t.id)}" aria-label="Add or remove services" title="Add or remove services">${svg("plus")}</button>`;
    const art = t.art_mode != null ? `<div class="row"><div class="grow" style="font-size:17px;font-weight:600">Art mode when off</div>
        <button class="sw ${t.art_mode ? "on" : ""}" data-do="frameArt" data-tv="${esc(t.id)}" aria-label="Art mode"></button></div>`
      : anyArt ? '<div style="height:38px"></div>' : "";
    const dim = on ? "" : "opacity:.4;pointer-events:none";
    return `<div class="tvcard ${on ? "on" : ""}" data-tvcard="${esc(t.id)}">
      <div class="row"><div class="col grow" style="min-width:0"><div style="font-size:22px;font-weight:700" class="ellip">${esc(t.name)}</div><div class="sub" style="font-size:14px">${esc(tvKind(t))}</div></div>
        <button class="btn round ${remote ? "white" : ""}" data-do="tvRemote" data-tv="${esc(t.id)}" aria-label="${remote ? "Close the remote" : "Remote"}" title="Remote" style="width:64px;height:64px;${on ? "" : "opacity:.4;pointer-events:none"}">${svg("remote")}</button>
        <button class="btn round ${on ? "green" : ""} ${t.waking ? "busy" : ""}" data-do="tvPower" data-tv="${esc(t.id)}" aria-label="Power" style="width:64px;height:64px">${svg("power")}</button></div>
      ${remote ? tvRemoteBox(t) : editing ? tvEditBox(t, all) : `${scr}
      <div class="row" style="gap:8px 6px;flex-wrap:wrap;${dim}">${apps}</div>`}
      <div class="row" style="gap:10px;margin-top:auto;${dim}">
        <button class="btn" data-do="tvVol" data-tv="${esc(t.id)}" data-arg="-1" aria-label="Volume down">−</button>
        <div class="grow" style="text-align:center;font-size:22px;font-weight:600">${t.muted ? "Muted" : t.volume != null ? "Volume " + t.volume : "Volume"}</div>
        <button class="btn" data-do="tvVol" data-tv="${esc(t.id)}" data-arg="1" aria-label="Volume up">+</button>
        <button class="btn round ${t.muted ? "white" : ""}" data-do="tvMute" data-tv="${esc(t.id)}" aria-label="Mute">${svg("mute")}</button></div>
      ${art}</div>`;
  }).join("");
  return `<div class="row" style="padding-right:76px;margin-bottom:22px"><div class="col grow"><h2>TVs</h2>
    <div class="sub">${tvsOn(tvs)} of ${list.length} on</div></div></div><div class="tvs" style="grid-template-columns:repeat(${Math.max(1, list.length)},1fr)">${cards}</div>`;
}
function sheetSettings() {
  const lay = { a: ["Lock screen and dock", "Big clock, 3 cards at the bottom"], b: ["Clock left, controls right", "Aircon, music and TVs always open"],
                c: ["Home grid", "A tile for every room, speaker and TV"] };
  const marks = { a: '<b style="left:8%;right:8%;bottom:8%;height:24%"></b><b style="left:34%;width:32%;top:22%;height:22%;background:rgba(255,255,255,.4)"></b>',
                  b: '<b style="right:4%;width:34%;top:6%;bottom:6%"></b><b style="left:6%;width:38%;top:30%;height:24%;background:rgba(255,255,255,.4)"></b>',
                  c: '<b style="left:4%;right:4%;bottom:6%;height:36%"></b><b style="left:38%;width:24%;top:10%;height:16%;background:rgba(255,255,255,.4)"></b>' };
  const sc = S.look.scene;
  const layouts = Object.entries(lay).map(([k, [n, d]]) => `<button class="choice ${S.look.layout === k ? "sel" : ""}" data-action="setLayout" data-arg="${k}">
      <div class="thumb" style="background-image:url(scenes/${sc}/photo.jpg)">${marks[k]}</div><div class="nm">${k.toUpperCase()} · ${n}</div><div class="ds">${d}</div></button>`).join("");
  const scenes = [["mountain", "Snowy mountain", "Daytime peak over a lake"], ["night", "Night lake", "Our own dark mountain and glowing sky"]]
    .map(([k, n, d]) => `<button class="choice ${sc === k ? "sel" : ""}" data-action="setScene" data-arg="${k}">
      <div class="thumb" style="height:150px;background-image:url(scenes/${k}/thumb.jpg)"></div><div class="nm">${n}</div><div class="ds">${d}</div></button>`).join("");
  return `<div style="padding-right:76px"><h2>Look</h2><div class="sub">These only change the look. Device and account settings stay on the iMac.</div></div>
    <div class="label" style="margin:22px 0 10px">Layout</div><div class="choices" style="grid-template-columns:repeat(3,1fr)">${layouts}</div>
    <div class="label" style="margin:22px 0 10px">Scene</div><div class="choices" style="grid-template-columns:repeat(2,1fr);width:66%">${scenes}</div>`;
}
const EXAMPLES = ["Make the lounge warmer", "Turn on the living room TV", "Pause the music", "Close all the vents"];
function sheetAsk() {
  return `<div style="padding-right:76px"><h2>Ask the house</h2><div class="sub">Type it the way you would say it.</div></div>
    <form class="askform" data-form="ask" style="margin-top:24px" autocomplete="off">
      <input id="askText" type="text" maxlength="500" placeholder="Make the lounge warmer" enterkeyhint="send" aria-label="Your question">
      <button class="btn white" type="submit" style="height:64px;padding:0 28px;font-size:20px;font-weight:600">Ask</button></form>
    <div class="label" style="margin:22px 0 10px">For example</div>
    <div class="seg">${EXAMPLES.map((e) => `<button class="pill" data-action="askFill" data-arg="${esc(e)}">${esc(e)}</button>`).join("")}</div>`;
}
let lastAnswer = null;
function sheetAnswer() {
  const a = lastAnswer;
  if (!a || a.thinking) {
    return `<div class="ans"><div class="label">${a && a.typed ? "You asked" : "Listening done"}</div>
      ${a && a.typed ? `<div class="heard">“${esc(a.typed)}”</div>` : ""}
      <div class="reply dots" style="margin-top:8px"><i></i><i></i><i></i></div><div class="sub">Thinking…</div></div>`;
  }
  const heard = a.heard ? `<div><div class="label">You said</div><div class="heard" data-heard>“${esc(a.heard)}”</div></div>` : "";
  const reply = a.ok ? (a.reply || "Done.") : (a.error || "The hub couldn't answer that.");
  const acts = (a.actions || []).map((x) => `<div class="act ${x.ok ? "ok" : "bad"}"><span class="mk">${x.ok ? "✓" : "✕"}</span>
      <div class="col"><span>${esc(describe(x.action, x.args || {}))}</span>${!x.ok && x.error ? `<span class="why">${esc(x.error)}</span>` : ""}</div></div>`).join("");
  return `<div class="ans" data-answer>${heard}<div class="reply" data-reply style="padding-right:60px">${esc(reply)}</div>
      ${acts ? `<div class="acts">${acts}</div>` : ""}
      <div class="foot" data-foot>${a.kept ? "Stays open. Tap ✕ to close." : "Closes by itself in 8 seconds. Tap here to keep it open."}</div></div>`;
}
const ANS_RECT = { left: 200, top: 120, width: 880, height: 500 };
const ASK_RECT = { left: 200, top: 40, width: 880, height: 400 };
// ---------- personal view: one person's card (event titles and times only, no PIN) ----------
// Opened by a name tap, or by Face ID on the tablet (the tablet's app sends a name, never a picture).
// The names and the place name come from the hub's config.json ("people", "place") through GET /api/home.
let PEOPLE = [];
const HOME = { place: "" };
const faceTint = (n) => (PEOPLE.indexOf(n) % 2 ? "a" : "j");
const ME = { name: null, how: null, card: null, loading: false, error: null, closeTimer: null };
const FACE = { native: false, camera: "off", enrolled: [], enrol: null, forgetArm: null, who: null };
const greet = (n) => { const h = new Date().getHours(); return `${h < 12 ? "Good morning" : h < 18 ? "Good afternoon" : "Good evening"}, ${n}`; };
function dayLabel(d) {
  const t = new Date(); t.setHours(0, 0, 0, 0);
  const x = new Date(d); x.setHours(0, 0, 0, 0);
  const diff = Math.round((x - t) / 86400000);
  return diff <= 0 ? "Today" : diff === 1 ? "Tomorrow" : x.toLocaleDateString("en-AU", { weekday: "long", day: "numeric", month: "short" }).replace(",", "");
}
const hhmm = (d) => d.toLocaleTimeString("en-AU", { hour: "numeric", minute: "2-digit" }).replace(/\s?([ap])\.?m\.?/i, (m, a) => a.toLowerCase() + "m");
function personEvents() {
  const c = ME.card, cal = c && c.calendar;
  if (ME.loading && !c) return `<div class="sub" style="margin-top:12px">Loading…</div>`;
  if (ME.error) return `<div class="sub" style="margin-top:12px">${esc(ME.error)}</div>`;
  if (!cal) return "";
  const live = cal.sources.filter((s) => s.connected);
  if (!live.length) return `<div class="me-empty"><div style="font-size:20px;font-weight:600">No calendar connected yet</div>
    <div class="sub" style="margin-top:6px">It is set up on the iMac. Nobody needs to type a password here.</div></div>`;
  if (!cal.events.length) return `<div class="me-empty"><div style="font-size:20px;font-weight:600">Nothing on in the next ${cal.days} days</div></div>`;
  let last = "", rows = "";
  cal.events.forEach((e) => {
    const d = new Date(e.start), day = dayLabel(d);
    if (day !== last) { rows += `<div class="label" style="margin:${last ? 16 : 4}px 0 8px">${esc(day)}</div>`; last = day; }
    rows += `<div class="me-ev"><div class="me-t">${e.allDay ? "All day" : esc(hhmm(d))}</div><div class="ellip" style="font-size:19px;font-weight:600;min-width:0">${esc(e.title)}</div></div>`;
  });
  if (cal.more) rows += `<div class="sub" style="margin-top:10px">and ${cal.more} more</div>`;
  return `<div class="me-list">${rows}</div>`;
}
function faceBox(n) {
  if (!FACE.native) return `<div class="sub">Face ID works on the wall tablet.</div>`;
  const en = FACE.enrol && FACE.enrol.name === n ? FACE.enrol : null;
  const kept = `<div class="sub" style="font-size:14px;margin-top:8px">Only numbers that describe your face are kept on this tablet. No photo is taken or kept.</div>`;
  if (en && (en.state === "looking" || en.state === "progress")) {
    const pct = Math.round(100 * (en.got || 0) / (en.need || 8));
    return `<div style="font-size:18px;font-weight:600">Look at the screen and keep still</div>
      <div class="me-bar"><b style="width:${pct}%"></b></div>
      <div class="row" style="justify-content:space-between;margin-top:10px"><span class="sub">${en.got || 0} of ${en.need || 8}</span>
      <button class="pill" data-action="faceCancel">Cancel</button></div>`;
  }
  const msg = en && en.state === "failed" && en.msg ? `<div class="me-warn">${esc(en.msg)}</div>` : "";
  if (FACE.camera === "none") return `<div style="font-size:18px;font-weight:600">Face ID is off</div><div class="sub" style="margin-top:6px">The tablet's camera has stopped answering. It comes back when the tablet restarts. Tapping your name still works.</div>`;
  if (FACE.camera === "denied" && !FACE.enrolled.includes(n)) return `<div style="font-size:18px;font-weight:600">Face ID needs the camera</div>${msg}
    <button class="btn white" data-action="faceEnrol" data-arg="${esc(n)}" style="margin-top:12px;font-size:17px;font-weight:600">Set up face</button>${kept}`;
  if (FACE.enrolled.includes(n)) {
    const armed = FACE.forgetArm === n;
    return `<div style="font-size:18px;font-weight:600">Face ID is on for ${esc(n)}</div>${msg}
      <button class="btn ${armed ? "heat" : ""}" data-action="faceForget" data-arg="${esc(n)}" style="margin-top:12px;font-size:17px;font-weight:600;background:${armed ? "" : "rgba(255,255,255,.14)"}">${armed ? "Tap again to forget" : "Forget my face"}</button>${kept}`;
  }
  return `<div style="font-size:18px;font-weight:600">Set up Face ID</div>${msg}
    <div class="sub" style="margin-top:6px">Stand about an arm's length away and look at the screen for a few seconds.</div>
    <button class="btn white" data-action="faceEnrol" data-arg="${esc(n)}" style="margin-top:12px;font-size:17px;font-weight:600">Set up face for ${esc(n)}</button>${kept}`;
}
function sheetPerson() {
  const n = ME.name || PEOPLE[0] || "", other = PEOPLE.length > 1 ? PEOPLE[(PEOPLE.indexOf(n) + 1) % PEOPLE.length] : null;
  const c = ME.card, srcs = c && c.calendar ? c.calendar.sources : [];
  const srcLine = srcs.length ? "Calendars: " + srcs.map((s) => `${esc(s.name)}${s.connected ? (s.note ? ` (${esc(s.note)})` : "") : " · not connected"}`).join(" · ") : "";
  const slot = (title, s) => `<div class="me-slot"><div style="font-size:18px;font-weight:600">${title}</div><div class="sub" style="margin-top:4px">${esc((s && s.note) || "Not connected yet")}</div></div>`;
  return `<div class="row" style="padding-right:76px;gap:18px;align-items:center">
      <div class="face ${faceTint(n)}" style="width:72px;height:72px;font-size:28px">${esc(n.slice(0, 1))}</div>
      <div class="col grow"><h2>${esc(greet(n))}</h2><div class="sub">${ME.how === "face" ? "Recognised by Face ID" : "Your own view"} · event titles only</div></div>
      ${other ? `<button class="pill" data-action="person" data-arg="${esc(other)}">I'm ${esc(other)}</button>` : ""}</div>
    <div class="row" style="gap:28px;margin-top:22px;align-items:stretch;height:584px">
      <div class="col" style="flex:1.45;min-width:0">
        <div class="label">Next ${c && c.calendar ? c.calendar.days : 7} days</div>
        ${personEvents()}
        ${srcLine ? `<div class="sub" style="font-size:14px;margin-top:auto;padding-top:10px">${srcLine}</div>` : ""}
      </div>
      <div class="col" style="flex:1;gap:14px;min-width:0">
        <div class="me-slot">${faceBox(n)}</div>
        ${slot("Ring doorbell", c && c.ring)}
        ${slot("Parcels", c && c.parcels)}
      </div></div>`;
}

const SHEETS = {
  person: { fn: sheetPerson, tone: "dark", live: true },
  aircon: { fn: sheetAircon, tone: "light", live: true }, music: { fn: sheetMusic, tone: "dark", live: true },
  tvs: { fn: sheetTvs, tone: "dark", live: true }, settings: { fn: sheetSettings, tone: "dark", live: true },
  ask: { fn: sheetAsk, tone: "dark", rect: ASK_RECT }, answer: { fn: sheetAnswer, tone: "dark", rect: ANS_RECT },
};

// plain words for an action the Ask ran
function describe(action, a) {
  const st = S.view || {};
  const zn = (id) => ((st.aircon && zones(st.aircon).find((z) => z.id === id)) || { name: id }).name;
  const tn = (id) => ((st.tvs && tvList(st.tvs).find((t) => t.id === id)) || { name: id }).name;
  const sn = (id) => (id === "all" ? "All speakers" : st.speakers ? spName(st.speakers, id) : id);
  const onOff = (v) => (v ? "on" : "off");
  switch (action) {
    case "aircon.power": return `Aircon ${onOff(a.on)}`;
    case "aircon.set_temp": return `Aircon set to ${a.value}°`;
    case "aircon.nudge": return `Aircon ${Math.abs(a.delta)}° ${a.delta > 0 ? "warmer" : "cooler"}`;
    case "aircon.mode": return `Aircon to ${MODES[a.mode] ? MODES[a.mode][0] : a.mode}`;
    case "aircon.fan": return `Fan speed ${cap(a.speed)}`;
    case "aircon.zone": return `${zn(a.zone)} vent ${a.on ? "open" : "closed"}`;
    case "aircon.zones_all": return `Every room's vent ${a.on ? "open" : "closed"}`;
    case "music.play": return "Music playing";
    case "music.pause": return "Music paused";
    case "music.next": return "Next song";
    case "music.previous": return "Previous song";
    case "music.speakers": return `Music on ${(a.speakers || []).map(sn).join(" + ")}`;
    case "music.search_play": return `Playing “${a.query}”${a.speakers ? " on " + a.speakers.map(sn).join(" + ") : ""}`;
    case "speakers.volume": return `${sn(a.speaker)} volume ${a.value}`;
    case "tv.power": return `${tn(a.tv)} TV ${onOff(a.on)}`;
    case "tv.volume": return `${tn(a.tv)} TV volume ${a.delta > 0 ? "up" : "down"} ${Math.abs(a.delta)}`;
    case "tv.mute": return `${tn(a.tv)} TV ${a.muted ? "muted" : "unmuted"}`;
    case "tv.launch": return `${a.app} on the ${tn(a.tv)} TV`;
    case "tv.play": return `Playing “${a.title}” on the ${tn(a.tv)} TV`;
    case "tv.art_mode": return `Art mode ${onOff(a.on)}`;
    default: return String(action || "Something");
  }
}

// ---------- rendering ----------
const NOTES = { mountain: "", night: "" };   // no on screen credit: the scenes are our own (the owner, 11 Nov 2026)
function renderScene() {
  const { layout: l, scene: sc } = S.look;
  const p = window.SCENES[sc][l];
  $("#scene").innerHTML = `<svg class="scene" viewBox="0 0 1280 800" preserveAspectRatio="xMidYMid slice">
    <defs><pattern id="glass" patternUnits="userSpaceOnUse" width="1280" height="800"><image href="scenes/${sc}/glass.jpg" width="1280" height="800"/></pattern>
      <filter id="shadow" x="-10%" y="-10%" width="120%" height="140%"><feDropShadow dx="0" dy="3" stdDeviation="6" flood-color="#000" flood-opacity=".28"/></filter></defs>
    <image href="scenes/${sc}/photo.jpg" width="1280" height="800"/>
    <text class="date" id="date" x="${p.dateX}" y="${p.dateY}" text-anchor="${p.anchor}"></text>
    <text class="t" id="clock" x="${p.x}" y="${p.y}" text-anchor="${p.anchor}" font-size="${p.size}"></text>
    <image href="scenes/${sc}/fg.webp" width="1280" height="800"/></svg>`;
  const sh = { a: [320, 0.38], b: [360, 0.42], c: [560, 0.5] }[l];
  $("#shade").style.cssText = `height:${sh[0]}px;background:linear-gradient(to top, rgba(0,0,0,${sh[1]}), rgba(0,0,0,0))`;
  $("#note").textContent = NOTES[sc];
  stage.dataset.layout = l; stage.dataset.scene = sc;
  tick();
}
function renderUI() {
  if (REC.held) return;                               // never redraw the mic while it is held
  $("#ui").innerHTML = { a: layoutA, b: layoutB, c: layoutC }[S.look.layout]();
  if (S.open && S.openSrc) { const el = $(`[data-src="${CSS.escape(S.openSrc)}"]`); if (el) el.style.visibility = "hidden"; }
}
function renderSheet() {
  const sh = $(".sheet .full");
  if (!sh || !S.open || $(".sheet").dataset.closing) return;
  if (!SHEETS[S.open].live || S.dragging) return;     // no redraw while a slider is held
  if (S.open === "music") {                           // keep the search box and the lists steady: redraw only the live parts
    const sp = SP(), root = sh.querySelector("[data-mroot]");
    if (root && sp && sp.available && root.dataset.mroot === (linkedSp(sp) ? "1" : "0")) {
      if (root.dataset.mroot === "1") {
        sh.querySelector("[data-mnow]").innerHTML = mNow(sp);
        sh.querySelector("[data-mplayon]").innerHTML = mPlayOn(sp);
        if (M.tab === "speakers") sh.querySelector("[data-mbrowse]").innerHTML = mBrowse();
      } else sh.innerHTML = SHEETS.music.fn();
      return;
    }
  }
  sh.innerHTML = SHEETS[S.open].fn();
}
function render(sheetToo = true) {
  stage.classList.toggle("offline", S.conn === "offline");
  stage.classList.toggle("nohub", S.conn === "connecting" || S.conn === "nokey");
  renderUI();
  if (sheetToo) renderSheet();
}

function tick() {
  const d = new Date();
  const c = $("#clock"), dt = $("#date");
  // only touch the page when the text really changed, so the big clock is not repainted every second
  const ct = `${d.getHours() % 12 || 12}:${String(d.getMinutes()).padStart(2, "0")}`;
  if (c && c.textContent !== ct) c.textContent = ct;
  const dtt = d.toLocaleDateString("en-AU", { weekday: "long", day: "numeric", month: "long" }).replace(",", "");
  if (dt && dt.textContent !== dtt) dt.textContent = dtt;
}

// ---------- the expand and close animation (from the prototype) ----------
let scale = 1;
const FULL = { left: 40, top: 40, width: 1200, height: 720 };
function rectIn(el) {
  const s = stage.getBoundingClientRect(), r = el.getBoundingClientRect();
  return { left: (r.left - s.left) / scale, top: (r.top - s.top) / scale, width: r.width / scale, height: r.height / scale };
}
const px = (r) => ({ left: r.left + "px", top: r.top + "px", width: r.width + "px", height: r.height + "px" });
function miniOf(el, r) {
  const m = el.cloneNode(true);
  m.classList.add("mini");
  m.removeAttribute("id");
  [m, ...m.querySelectorAll("*")].forEach((n) => ["data-action", "data-do", "data-open", "data-src", "data-prog", "data-pos", "id"].forEach((a) => n.removeAttribute(a)));
  Object.assign(m.style, { width: r.width + "px", height: r.height + "px", background: "transparent", border: "0",
                           boxShadow: "none", backdropFilter: "none", webkitBackdropFilter: "none", visibility: "visible", transform: "none" });
  return m;
}
// Lighter mode (the wall tablet): the card grows to the sheet with a transform (compositor) instead of animating
// left/top/width/height every frame, which relaid out and repainted the whole sheet on a slow chip.
const LIGHT = document.documentElement.classList.contains("lighter");
const xf = (r, t) => `translate(${r.left - t.left}px, ${r.top - t.top}px) scale(${r.width / t.width}, ${r.height / t.height})`;
function radiusOf(el) { return parseFloat(getComputedStyle(el).borderTopLeftRadius) || 28; }

function openSheet(name, el) {
  if (S.open || !el) return;
  const spec = SHEETS[name], target = spec.rect || FULL;
  const r = rectIn(el), rad = Math.min(radiusOf(el), r.height / 2);
  const startBg = getComputedStyle(el).backgroundColor;
  S.open = name; S.openSrc = el.dataset.src;
  const back = document.createElement("div"); back.className = "backdrop"; back.dataset.action = "close";
  const sh = document.createElement("div"); sh.className = "sheet " + spec.tone; sh.dataset.sheet = name;
  Object.assign(sh.style, px(r), { borderRadius: rad + "px" });
  const mini = miniOf(el, r);
  const full = document.createElement("div"); full.className = "full"; full.innerHTML = spec.fn();
  Object.assign(full.style, { width: target.width + "px", height: target.height + "px" });
  const close = document.createElement("button"); close.className = "btn round close"; close.dataset.action = "close"; close.setAttribute("aria-label", "Close"); close.innerHTML = svg("close");
  close.style.opacity = 0;
  sh.append(mini, full, close); stage.append(back, sh);
  el.style.visibility = "hidden";
  stage.classList.add("sheet-open");
  const endBg = getComputedStyle(sh).backgroundColor;
  const opts = { duration: 560, easing: "cubic-bezier(.32,.72,0,1)", fill: "forwards" };
  if (LIGHT) {
    Object.assign(sh.style, px(target), { borderRadius: "34px", transformOrigin: "0 0", willChange: "transform" });
    mini.style.display = "none";
    sh.animate([{ transform: xf(r, target), backgroundColor: startBg }, { transform: "none", backgroundColor: endBg }], { ...opts, duration: 380 });
    full.animate([{ opacity: 0 }, { opacity: 1 }], { duration: 200, delay: 170, fill: "forwards" });
  } else {
  sh.animate([{ ...px(r), borderRadius: rad + "px", backgroundColor: startBg }, { ...px(target), borderRadius: "34px", backgroundColor: endBg }], opts);
  mini.animate([{ opacity: 1 }, { opacity: 0 }], { duration: 160, fill: "forwards" });
  full.animate([{ opacity: 0, transform: "translateY(14px) scale(.985)" }, { opacity: 1, transform: "none" }], { duration: 380, delay: 130, easing: "cubic-bezier(.2,.8,.2,1)", fill: "forwards" });
  }
  close.animate([{ opacity: 0 }, { opacity: 1 }], { duration: 300, delay: 240, fill: "forwards" });
  if (name === "music") musicOpened();
  if (name === "ask") setTimeout(() => { const i = $("#askText"); if (i && S.open === "ask") i.focus(); }, 420);
}
function swapSheet(name) {                            // the ask sheet turns into the answer, in place
  const sh = $(".sheet"); if (!sh || sh.dataset.closing) return false;
  S.open = name; sh.dataset.sheet = name;
  const full = sh.querySelector(".full"), target = SHEETS[name].rect || FULL;
  full.innerHTML = SHEETS[name].fn();
  sh.getAnimations().forEach((a) => a.finish());
  const cur = rectIn(sh);
  sh.getAnimations().forEach((a) => a.cancel()); Object.assign(sh.style, px(cur), { borderRadius: "34px" });
  Object.assign(full.style, { width: target.width + "px", height: target.height + "px" });
  sh.animate([px(cur), px(target)], { duration: 420, easing: "cubic-bezier(.32,.72,0,1)", fill: "forwards" });
  return true;
}
function closeSheet() {
  const sh = $(".sheet"); if (!sh || sh.dataset.closing) return;
  sh.dataset.closing = "1";
  if (S.open === "person") personGone();
  clearTimeout(answerTimer);
  const src = S.openSrc;
  stage.classList.remove("sheet-open");
  if (document.activeElement && sh.contains(document.activeElement)) document.activeElement.blur();
  renderUI();                                         // the card under the sheet now shows the new state
  const el = $(`[data-src="${CSS.escape(src)}"]`) || $('[data-src="gear"]');
  el.style.visibility = "hidden";
  const r = rectIn(el), rad = Math.min(radiusOf(el), r.height / 2);
  const endBg = getComputedStyle(el).backgroundColor;
  const full = sh.querySelector(".full"), close = sh.querySelector(".close");
  const mini = miniOf(el, r); sh.querySelector(".mini").replaceWith(mini); mini.style.opacity = 0;
  const cur = rectIn(sh);
  if (LIGHT) {
    const lay = { left: sh.offsetLeft, top: sh.offsetTop, width: sh.offsetWidth, height: sh.offsetHeight };
    const bgNow = getComputedStyle(sh).backgroundColor;
    sh.getAnimations().forEach((a) => a.cancel()); Object.assign(sh.style, px(lay), { transformOrigin: "0 0", willChange: "transform" });
    mini.style.display = "none";
    [full, close].forEach((n) => { n.getAnimations().forEach((a) => a.cancel()); n.animate([{ opacity: 1 }, { opacity: 0 }], { duration: 120, fill: "forwards" }); });
    const a2 = sh.animate([{ transform: xf(cur, lay), backgroundColor: bgNow }, { transform: xf(r, lay), backgroundColor: endBg }], { duration: 320, delay: 60, easing: "cubic-bezier(.32,.72,0,1)", fill: "forwards" });
    a2.onfinish = () => {
      S.open = null; S.openSrc = null;
      sh.remove(); const b = $(".backdrop"); if (b) b.remove();
      const now = $(`[data-src="${CSS.escape(src)}"]`) || el;
      now.style.visibility = "";
      render();
    };
    return;
  }
  sh.getAnimations().forEach((a) => a.cancel()); Object.assign(sh.style, px(cur));
  [full, close].forEach((n) => { n.getAnimations().forEach((a) => a.cancel()); n.animate([{ opacity: 1 }, { opacity: 0 }], { duration: 160, fill: "forwards" }); });
  mini.animate([{ opacity: 0 }, { opacity: 1 }], { duration: 220, delay: 220, fill: "forwards" });
  const anim = sh.animate([{ ...px(cur), borderRadius: "34px", backgroundColor: getComputedStyle(sh).backgroundColor },
                           { ...px(r), borderRadius: rad + "px", backgroundColor: endBg }],
                          { duration: 480, easing: "cubic-bezier(.32,.72,0,1)", fill: "forwards" });
  anim.onfinish = () => {
    S.open = null; S.openSrc = null;
    sh.remove(); const b = $(".backdrop"); if (b) b.remove();
    const now = $(`[data-src="${CSS.escape(src)}"]`) || el;
    now.style.visibility = "";
    render();
  };
}

// ---------- toast and banner ----------
let toastTimer;
function toast(t, ms) {
  const n = $("#toast"); n.textContent = t; n.classList.add("show");
  clearTimeout(toastTimer); toastTimer = setTimeout(() => n.classList.remove("show"), ms || 3200);
}
let bannerTimer;
function banner() {
  const b = $("#banner");
  if (S.conn !== "offline") { clearTimeout(bannerTimer); bannerTimer = null; b.classList.remove("show"); return; }
  const secs = Math.max(0, Math.ceil((retryAt - Date.now()) / 1000));
  b.innerHTML = `<span class="dot"></span><span>Can't reach the hub</span><span class="sub">${retryAt && secs > 0 ? `Trying again in ${secs} s` : "Trying again…"}</span>`;
  if (!b.classList.contains("show") && !bannerTimer) bannerTimer = setTimeout(() => { bannerTimer = null; if (S.conn === "offline") b.classList.add("show"); }, 900);
}

// ---------- talking to the hub ----------
let ws = null, pingTimer = null, pongTimer = null, retryTimer = null, retryAt = 0, backoff = 1000;
function setConn(c) { if (S.conn !== c) { S.conn = c; render(); } banner(); }

async function connect() {
  clearTimeout(retryTimer); retryAt = 0;
  if (!KEY) return needKey(false);
  if (!HUB) return hubLost();
  let res;
  try { res = await fetch(HUB + "/api/state", { headers: auth(), cache: "no-store" }); } catch (e) { return hubLost(); }
  if (res.status === 401) return needKey(true);
  let body = null;
  try { body = await res.json(); } catch (e) { /* not JSON */ }
  if (!res.ok || !body || !body.ok) return hubLost();
  setServer(body.state);
  openSocket();
  loadHome();
}
async function loadHome() {                 // names and place: shown once they arrive, never required
  try {
    const res = await fetch(HUB + "/api/home", { headers: auth(), cache: "no-store" });
    const b = res.ok ? await res.json() : null;
    if (!b || !b.ok) return;
    PEOPLE = Array.isArray(b.people) ? b.people.filter((x) => typeof x === "string" && x).slice(0, 8) : [];
    HOME.place = typeof b.place === "string" ? b.place : "";
    render();
  } catch (e) { /* an older hub: no names, no place */ }
}
function openSocket() {
  dropSocket();
  let sock;
  try { sock = new WebSocket(WS_URL()); } catch (e) { return hubLost(); }
  ws = sock;
  sock.onopen = () => {
    backoff = 1000; setConn("online"); render();
    checkWallFiles();                         // the hub may have been restarted with new wall files
    pingTimer = setInterval(() => {
      if (sock.readyState !== 1) return;
      sock.send(JSON.stringify({ type: "ping" }));
      clearTimeout(pongTimer); pongTimer = setTimeout(() => { if (ws === sock) hubLost(); }, 10000);
    }, 25000);
  };
  sock.onmessage = (e) => {
    let m; try { m = JSON.parse(e.data); } catch (err) { return; }
    if (m.type === "state") { setServer(m.state); render(); } else if (m.type === "pong") clearTimeout(pongTimer);
  };
  sock.onclose = () => { if (ws === sock) hubLost(); };
}
function dropSocket() {
  clearInterval(pingTimer); clearTimeout(pongTimer);
  if (ws) { const s = ws; ws = null; s.onclose = null; s.onmessage = null; try { s.close(); } catch (e) { /* gone */ } }
}
function hubLost() {
  dropSocket();
  if (S.conn === "nokey") return;
  pending = []; recompute();
  clearTimeout(retryTimer);
  retryAt = Date.now() + backoff;
  retryTimer = setTimeout(connect, backoff);
  backoff = Math.min(backoff * 2, 15000);
  setConn("offline");
}
setInterval(() => { if (S.conn === "offline") banner(); }, 1000);

// ---------- new wall files: reload ----------
// The tablet keeps this page open for days. Every few minutes (and when the hub comes back) the page, its
// scripts and its styles are asked for their ETag; when one changed, the page reloads itself, but only while
// nobody is using it (no sheet open, not recording). The key is kept in localStorage, so a reload keeps it.
const WALL_FILES = [location.origin + location.pathname,
  ...[...document.querySelectorAll("script[src], link[rel=stylesheet]")].map((e) => e.src || e.href)];
let wallMark = null, wallNew = false;
async function wallFingerprint() {
  const parts = await Promise.all(WALL_FILES.map(async (u) => {
    const r = await fetch(u, { method: "HEAD", cache: "no-store" });
    if (!r.ok) throw new Error("not ok");
    return (r.headers.get("ETag") || "") + "|" + (r.headers.get("Last-Modified") || "") + "|" + (r.headers.get("Content-Length") || "");
  }));
  return parts.join(" ");
}
async function checkWallFiles() {
  if (!wallNew) {
    let f;
    try { f = await wallFingerprint(); } catch (e) { return; }      // the hub is away: try again later
    if (wallMark === null) { wallMark = f; return; }
    wallNew = f !== wallMark;
  }
  if (wallNew && !S.open && !REC.rec && !REC.held && S.conn === "online") location.reload();
}
checkWallFiles();
setInterval(checkWallFiles, 5 * 60 * 1000);
setInterval(() => { if (wallNew) checkWallFiles(); }, 15 * 1000);  // waiting for nobody to be using it

function needKey(wrong) {
  dropSocket(); clearTimeout(retryTimer);
  if (S.open) { const sh = $(".sheet"), b = $(".backdrop"); if (sh) sh.remove(); if (b) b.remove(); S.open = null; S.openSrc = null; stage.classList.remove("sheet-open"); }
  setConn("nokey");
  let p = $(".keypanel");
  if (!p) { p = document.createElement("div"); p.className = "keypanel"; stage.append(p); }
  const where = HUB || "http://<the iMac>:8790";
  p.innerHTML = `<div class="box">
    <h2>This screen needs its hub key</h2>
    <p>${wrong ? "The key this screen has did not work. " : ""}Open this screen once with its key at the end of the address:<br><code>${esc(where)}/#key=…</code></p>
    <p>The wall key is in <code>~/.home-hub/keys.json</code> on the iMac. You can also paste it here.</p>
    <form class="askform" data-form="key" autocomplete="off"><input id="keyText" type="text" placeholder="Paste the key" aria-label="Hub key" autocapitalize="off" spellcheck="false">
      <button class="btn white" type="submit" style="height:64px;padding:0 24px;font-size:19px;font-weight:600">Use key</button></form></div>`;
}
function useKey(k) {
  k = (k || "").trim(); if (!k) return;
  KEY = k;
  try { localStorage.setItem("hub.key", k); } catch (e) { /* private mode */ }
  const p = $(".keypanel"); if (p) p.remove();
  S.conn = "connecting"; render(); connect();
}

// every control goes through here: show it at once, send it, and let the hub's answer win
const queues = {};
function act(action, args) {
  if (S.conn !== "online") return Promise.resolve();
  const op = { id: ++opSeq, action, args };
  pending.push(op); recompute(); render();
  const q = action.startsWith("aircon") ? "aircon" : action.startsWith("tv") ? "tvs" : "speakers";
  return (queues[q] = (queues[q] || Promise.resolve()).then(() => post(op)));
}
// TV volume: quick taps on + or - are added up and sent as one change (the number moves at once), so the
// TV is not asked once per tap and the number does not jump about while the answers come back.
const volTaps = {};                 // tv -> { op, timer }
function tvVolTap(tv, d) {
  if (S.conn !== "online" || !d) return;
  let v = volTaps[tv];
  if (!v) { v = volTaps[tv] = { op: { id: ++opSeq, action: "tv.volume", args: { tv, delta: 0 } } }; pending.push(v.op); }
  v.op.args.delta = Math.max(-10, Math.min(10, v.op.args.delta + d));
  recompute(); render();
  clearTimeout(v.timer);
  v.timer = setTimeout(() => {
    delete volTaps[tv];
    if (!v.op.args.delta || S.conn !== "online") { settle(v.op, null); return; }
    queues.tvs = (queues.tvs || Promise.resolve()).then(() => post(v.op));
  }, 350);
}
// A remote button: sent in order, and nothing on the screen is redrawn (a press changes nothing shown, and
// redrawing under a finger loses the next tap).
function tvKeyPress(tv, key) {
  if (S.conn !== "online") return;
  queues.tvs = (queues.tvs || Promise.resolve()).then(async () => {
    try {
      const res = await fetch(HUB + "/api/action", { method: "POST", headers: { ...auth(), "Content-Type": "application/json" },
                                                    body: JSON.stringify({ action: "tv.key", args: { tv, key } }) });
      if (res.status === 401) { needKey(true); return; }
      if (!res.ok) { let b = null; try { b = await res.json(); } catch (e) { /* not JSON */ } toast(errorText(res.status, b), 4200); }
    } catch (e) { toast("Couldn't reach the hub. Nothing changed."); }
  });
}
function settle(op, state) {
  pending = pending.filter((o) => o !== op);
  if (state) setServer(state); else recompute();
  render();
}
async function post(op) {
  let res, body = null;
  try {
    res = await fetch(HUB + "/api/action", { method: "POST", headers: { ...auth(), "Content-Type": "application/json" },
                                              body: JSON.stringify({ action: op.action, args: op.args }) });
    try { body = await res.json(); } catch (e) { body = null; }
  } catch (e) {
    settle(op, null); toast("Couldn't reach the hub. Nothing changed."); return;
  }
  if (res.status === 401) { settle(op, null); needKey(true); return; }
  if (res.ok && body && body.ok) { settle(op, body.state || null); return; }
  settle(op, null);
  toast(errorText(res.status, body), 4200);
}
function errorText(status, body) {
  if (status === 409 && body && body.needs === "spotify") return "Link Spotify on the iMac to do this";
  if (body && body.error) return body.error;
  return "The hub couldn't do that. Try again.";
}

// the controls, by name
const DO = {
  airtouch: () => { try { window.HubAndroid.openAirTouch(); } catch (e) { toast("The AirTouch app did not open."); } },
  acPower: () => act("aircon.power", { on: !AC().power }),
  nudge: (d) => act("aircon.nudge", { delta: Number(d) }),
  setTemp: (d) => { const v = Math.max(16, Math.min(30, AC().set + Number(d))); if (v !== AC().set) act("aircon.set_temp", { value: v }); },
  acMode: (m) => act("aircon.mode", { mode: m }),
  acFan: (f) => act("aircon.fan", { speed: f }),
  zone: (id) => { const z = zones(AC()).find((x) => x.id === id); if (z) act("aircon.zone", { zone: id, on: !z.on }); },
  zonesAll: (v) => act("aircon.zones_all", { on: v === "on" }),
  playPause: () => act(playing(SP()) ? "music.pause" : "music.play", {}),
  musicStart: (arg) => {
    const sp = SP(); if (!sp || S.starting) return;
    const [what, id] = String(arg || "recent").split(":");
    const args = { what, speakers: pickList(sp) };
    if (what === "playlist") args.playlist = id;
    S.starting = true; render();
    act("music.start", args).finally(() => { S.starting = false; render(); });
  },
  mTab: (k) => { M.tab = k; M.pickMain = false; renderBrowse(); if (k === "search") setTimeout(() => { const i = $("#msearch"); if (i && !M.q) i.focus(); }, 60); },
  mPlayUri: (uri) => {
    const sp = SP(); if (!sp || S.starting) return;
    S.starting = true; render();
    act("music.start", { what: "uri", uri, speakers: pickList(sp) }).finally(() => { S.starting = false; render(); });
  },
  mClear: () => { M.q = ""; M.res = null; M.seq++; const i = $("#msearch"); if (i) { i.value = ""; i.focus(); } renderBrowse(); },
  mPickMain: () => { M.pickMain = !M.pickMain; M.tab = "playlists"; renderBrowse(); },
  mSetMain: async (id) => {
    try {
      const r = await fetch(HUB + "/api/music/main", { method: "POST", headers: { ...auth(), "Content-Type": "application/json" }, body: JSON.stringify({ playlist: id }) });
      let b = null; try { b = await r.json(); } catch (e) { /* not JSON */ }
      if (r.ok && b && b.ok) { M.lib = b.library; M.pickMain = false; renderBrowse(); toast("Main playlist changed."); }
      else toast(errorText(r.status, b), 4200);
    } catch (e) { toast("Couldn't reach the hub. Nothing changed."); }
  },
  chipSpk: (id) => (nowOf(SP()) ? DO.spkGroup(id) : DO.pickSpk(id)),
  shuffle: async () => {
    const n = nowOf(SP()); if (!n) return;
    try {
      const r = await fetch(HUB + "/api/music/shuffle", { method: "POST", headers: { ...auth(), "Content-Type": "application/json" }, body: JSON.stringify({ on: !n.shuffle }) });
      let b = null; try { b = await r.json(); } catch (e) { /* not JSON */ }
      if (r.ok && b && b.ok && b.state) { setServer(b.state); render(); } else toast(errorText(r.status, b), 4200);
    } catch (e) { toast("Couldn't reach the hub. Nothing changed."); }
  },
  pickSpk: (id) => {
    const cur = pickList(SP()).slice();
    const next = cur.includes(id) ? cur.filter((x) => x !== id) : cur.concat(id);
    if (!next.length) { toast("Pick at least one speaker."); return; }
    S.pick = next; render();
  },
  next: () => act("music.next", {}),
  prev: () => act("music.previous", {}),
  spkGroup: (id) => {
    const n = nowOf(SP()); if (!n) return;
    const list = n.on.includes(id) ? n.on.filter((x) => x !== id) : spDevices(SP()).map((d) => d.id).filter((x) => x === id || n.on.includes(x));
    if (!list.length) { toast("Keep at least one speaker playing. Pause the music to stop it."); return; }
    act("music.speakers", { speakers: list });
  },
  tvPower: (_, tv) => { const t = tvList(TV()).find((x) => x.id === tv); if (t) act("tv.power", { tv, on: !(t.power === "on" || t.waking) }); },
  tvApp: (app, tv) => act("tv.launch", { tv, app }),
  tvEdit: (_, tv) => { tvEdit = tvEdit === tv ? null : tv; if (tvEdit) tvRemote = null; renderSheet(); },
  tvRemote: (_, tv) => { tvRemote = tvRemote === tv ? null : tv; if (tvRemote) tvEdit = null; renderSheet(); },
  tvKey: (key, tv) => tvKeyPress(tv, key),
  tvAppHide: (app, tv) => { TVL[tv] = tvListFor(tv).filter((a) => a !== app); saveTvl(); renderSheet(); },
  tvAppAdd: (app, tv) => {
    const l = tvListFor(tv); if (!l.includes(app)) l.push(app);
    TVL[tv] = l; saveTvl(); renderSheet();
    const t = tvList(TV()).find((x) => x.id === tv);
    if (t && t.power === "on") { act("tv.launch", { tv, app }); toast(`Opening ${app} on the ${t.name} TV. Sign in there.`, 4500); }
    else toast(`${app} is on the panel. Turn the TV on and open it to sign in.`, 4500);
  },
  tvVol: (d, tv) => tvVolTap(tv, Number(d)),
  tvMute: (_, tv) => { const t = tvList(TV()).find((x) => x.id === tv); if (t) act("tv.mute", { tv, muted: !t.muted }); },
  frameArt: (_, tv) => { const t = tvList(TV()).find((x) => x.id === (tv || "frame")); if (t) act("tv.art_mode", { tv: t.id, on: !t.art_mode }); },
};

// ---------- local actions (no hub) ----------
function saveLook() { try { localStorage.setItem("hub.look", JSON.stringify(S.look)); } catch (e) { /* private mode */ } }
const LOCAL = {
  close: () => closeSheet(),
  setLayout: (l) => { S.look.layout = l; saveLook(); renderScene(); render(); },
  setScene: (s) => { S.look.scene = s; saveLook(); renderScene(); render(); },
  person: (n) => openPerson(n, "tap"),
  faceEnrol: (n) => {
    if (!window.HubAndroid || !window.HubAndroid.faceEnrol) return;
    FACE.forgetArm = null;
    const r = window.HubAndroid.faceEnrol(n);
    if (r === "ok" || r === "asking") { FACE.enrol = { name: n, state: "looking", got: 0, need: 8 }; renderSheet(); }
  },
  faceCancel: () => { try { window.HubAndroid.faceCancel(); } catch (e) { /* not on the tablet */ } },
  faceForget: (n) => {
    if (FACE.forgetArm !== n) {                       // first tap arms it, a second tap within 5 s forgets
      FACE.forgetArm = n; renderSheet();
      setTimeout(() => { if (FACE.forgetArm === n) { FACE.forgetArm = null; renderSheet(); } }, 5000);
      return;
    }
    FACE.forgetArm = null;
    try { window.HubAndroid.faceForget(n); } catch (e) { /* not on the tablet */ }
  },
  askFill: (t) => { const i = $("#askText"); if (i) { i.value = t; i.focus(); } },
};
// ---------- drag to reorder a TV's services (in the + editor; a tap still takes one off) ----------
let tvDrag = null, swallowClick = false;
stage.addEventListener("pointerdown", (e) => {
  const p = e.target.closest && e.target.closest(".tvorder [data-do=tvAppHide]");
  if (!p || e.button > 0) return;
  tvDrag = { el: p, box: p.parentElement, id: e.pointerId, x0: e.clientX, y0: e.clientY, moving: false };
});
stage.addEventListener("pointermove", (e) => {
  const d = tvDrag; if (!d || e.pointerId !== d.id) return;
  const dx = e.clientX - d.x0, dy = e.clientY - d.y0;
  if (!d.moving) {
    if (Math.hypot(dx, dy) < 10) return;
    d.moving = true; d.el.classList.add("dragging");
    try { d.el.setPointerCapture(e.pointerId); } catch (err) { /* already gone */ }
  }
  const r = d.el.getBoundingClientRect(), k = r.width / (d.el.offsetWidth || 1) || 1;   // the stage is scaled
  d.el.style.transform = `translate(${dx / k}px, ${dy / k}px) scale(1.08)`;
  // the pill under the finger (by centre) is where it would go
  const others = [...d.box.querySelectorAll("[data-do=tvAppHide]")].filter((x) => x !== d.el);
  let best = null, bestD = Infinity;
  for (const o of others) {
    const b = o.getBoundingClientRect(), dd = Math.hypot(b.left + b.width / 2 - e.clientX, b.top + b.height / 2 - e.clientY);
    if (dd < bestD) { bestD = dd; best = o; }
  }
  others.forEach((o) => o.classList.toggle("droptarget", o === best));
  d.target = best ? { arg: best.dataset.arg, after: e.clientX > best.getBoundingClientRect().left + best.getBoundingClientRect().width / 2 } : null;
});
function endTvDrag(e, cancel) {
  const d = tvDrag; if (!d || e.pointerId !== d.id) return;
  tvDrag = null;
  if (!d.moving) return;                      // a tap: the click takes it off as before
  swallowClick = true; setTimeout(() => { swallowClick = false; }, 400);
  const tv = d.el.dataset.tv, app = d.el.dataset.arg;
  if (!cancel && d.target) {
    const l = tvListFor(tv).filter((a) => a !== app);
    const i = l.indexOf(d.target.arg);
    l.splice(i + (d.target.after ? 1 : 0), 0, app);
    TVL[tv] = l; saveTvl();
  }
  renderSheet();
}
stage.addEventListener("pointerup", (e) => endTvDrag(e, false));
stage.addEventListener("pointercancel", (e) => endTvDrag(e, true));
stage.addEventListener("click", (e) => { if (swallowClick) { swallowClick = false; e.stopPropagation(); e.preventDefault(); } }, true);

stage.addEventListener("click", (e) => {
  if (e.target.closest(".mic")) return;
  const d = e.target.closest("[data-do]");
  if (d && stage.contains(d)) {
    if (d.disabled) return;
    const fn = DO[d.dataset.do]; if (fn) fn(d.dataset.arg, d.dataset.tv);
    return;
  }
  const a = e.target.closest("[data-action]");
  if (a && stage.contains(a)) { LOCAL[a.dataset.action](a.dataset.arg); return; }
  const o = e.target.closest("[data-open]");
  if (o && !S.open && !o.closest(".sheet")) openSheet(o.dataset.open, o);
});
stage.addEventListener("submit", (e) => {
  e.preventDefault();
  const f = e.target;
  if (f.dataset.form === "key") useKey(f.querySelector("input").value);
  if (f.dataset.form === "ask") { const t = f.querySelector("input").value.trim(); if (t) askText(t); }
});
// volume sliders: move freely, send when let go
stage.addEventListener("pointerdown", (e) => {
  if (e.target.matches && e.target.matches("input[type=range]")) S.dragging = true;
  const sh = e.target.closest && e.target.closest('.sheet[data-sheet="answer"]');
  if (sh && lastAnswer && !lastAnswer.thinking && !lastAnswer.kept && !e.target.closest(".close")) {
    lastAnswer.kept = true; clearTimeout(answerTimer);
    const f = sh.querySelector("[data-foot]"); if (f) f.textContent = "Stays open. Tap ✕ to close.";
  }
});
stage.addEventListener("input", (e) => {
  if (e.target.id === "msearch") { M.q = e.target.value; clearTimeout(M.timer); M.timer = setTimeout(doSearch, 380); return; }
  const t = e.target; if (!t.dataset || t.dataset.vol == null) return;
  t.style.setProperty("--p", t.value + "%");
  const lab = t.parentNode.querySelector("[data-vol-label]"); if (lab) lab.textContent = t.value;
});
stage.addEventListener("change", (e) => {
  const t = e.target; if (!t.dataset || t.dataset.vol == null) return;
  S.dragging = false;
  act("speakers.volume", { speaker: t.dataset.vol, value: Number(t.value) });
});
document.addEventListener("pointerup", () => { if (S.dragging) setTimeout(() => { S.dragging = false; renderSheet(); }, 50); });
document.addEventListener("keydown", (e) => { if (e.key === "Escape") closeSheet(); });

// ---------- ask: typed and spoken ----------
let answerTimer = null;
function showAnswer(body) {
  lastAnswer = { ok: !!(body && body.ok), heard: body && body.heard, reply: body && body.reply, error: body && body.error,
                 actions: (body && Array.isArray(body.actions)) ? body.actions : [], kept: false };
  if (S.open !== "answer") {                          // closed while thinking: say it briefly instead
    if (!S.open) toast(lastAnswer.ok ? (lastAnswer.reply || "Done.") : (lastAnswer.error || "The hub couldn't answer that."), 5000);
    return;
  }
  const full = $(".sheet .full"); if (full) full.innerHTML = sheetAnswer();
  clearTimeout(answerTimer);
  answerTimer = setTimeout(() => { if (S.open === "answer" && lastAnswer && !lastAnswer.kept) closeSheet(); }, 8000);
}
async function askSend(url, init) {
  try {
    const res = await fetch(HUB + url, init);
    if (res.status === 401) { needKey(true); return null; }
    let body = null; try { body = await res.json(); } catch (e) { /* not JSON */ }
    return body || { ok: false, error: "The hub sent an answer this screen can't read." };
  } catch (e) { return { ok: false, error: "Couldn't reach the hub. Try again in a moment." }; }
}
async function askText(text) {
  lastAnswer = { thinking: true, typed: text };
  if (S.open === "ask") swapSheet("answer"); else if (!S.open) openSheet("answer", $('[data-src="kbd"]'));
  const body = await askSend("/api/ask", { method: "POST", headers: { ...auth(), "Content-Type": "application/json" }, body: JSON.stringify({ text, source: "wall" }) });
  if (body) showAnswer(body);
}
async function askAudio(blob, mime) {
  lastAnswer = { thinking: true };
  if (!S.open) openSheet("answer", $("#mic"));
  const body = await askSend("/api/ask/audio?source=wall", { method: "POST", headers: { ...auth(), "Content-Type": mime }, body: blob });
  if (body) showAnswer(body);
}

// hold to talk. The microphone is only open while the button is held.
const REC = { held: false, t0: 0, stream: null, rec: null, chunks: [], maxTimer: null, tickTimer: null, cancel: false, ctx: null, raf: 0 };
const MIN_MS = 400, MAX_MS = 15000;
function pickMime() {
  const opts = ["audio/webm;codecs=opus", "audio/webm", "audio/ogg;codecs=opus", "audio/mp4"];
  for (const m of opts) { try { if (window.MediaRecorder && MediaRecorder.isTypeSupported(m)) return m; } catch (e) { /* old */ } }
  return "";
}
function tip(html, ms) {
  let t = $("#tip");
  if (!t) { t = document.createElement("div"); t.id = "tip"; t.className = "listen-tip"; stage.append(t); }
  const mic = $("#mic"); const r = mic ? rectIn(mic) : { left: 600, top: 600, width: 76, height: 76 };
  const cx = Math.max(140, Math.min(1280 - 140, r.left + r.width / 2));
  Object.assign(t.style, { left: cx + "px", top: Math.max(16, r.top - 66) + "px" });
  t.innerHTML = html; t.hidden = false;
  clearTimeout(t._h); if (ms) t._h = setTimeout(() => { t.hidden = true; }, ms);
}
const hideTip = () => { const t = $("#tip"); if (t) t.hidden = true; };
function micLook(on) { const m = $("#mic"); if (m) m.classList.toggle("listening", on); }
function micDown(e) {
  const mic = e.target.closest && e.target.closest(".mic");
  if (!mic || S.open || S.conn !== "online" || REC.held || REC.rec) return;
  e.preventDefault();
  try { mic.setPointerCapture(e.pointerId); } catch (err) { /* fine */ }
  REC.held = true; REC.t0 = performance.now(); REC.cancel = false;
  micLook(true);
  tip(`<span class="rec"></span>Listening…<span class="secs" data-secs>0:00</span>`);
  REC.tickTimer = setInterval(() => { const s = $("[data-secs]"); if (s) s.textContent = mmss((performance.now() - REC.t0) / 1000); }, 250);
  if (NATIVE) { nativeStart(); return; }
  if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia || !window.MediaRecorder) { micFail("unavailable"); return; }
  navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true } }).then((stream) => {
    if (!REC.held) { stream.getTracks().forEach((t) => t.stop()); return; }  // let go before the mic was ready
    REC.stream = stream; REC.chunks = [];
    const mime = pickMime();
    let rec;
    try { rec = mime ? new MediaRecorder(stream, { mimeType: mime }) : new MediaRecorder(stream); } catch (err) { micFail("unavailable"); return; }
    REC.rec = rec;
    rec.ondataavailable = (ev) => { if (ev.data && ev.data.size) REC.chunks.push(ev.data); };
    rec.onstop = recDone;
    rec.start(250);
    REC.maxTimer = setTimeout(() => { if (REC.held) release(true); }, MAX_MS);
    meter(stream);
  }).catch((err) => micFail(err && (err.name === "NotAllowedError" || err.name === "SecurityError") ? "denied" : "unavailable"));
}
// The wall tablet's app records with Android's own recorder (a web page opened by network address
// may not use the microphone). It hands the recording back as base64 through __hubNativeAudio.
function nativeStart() {
  let r = "error";
  try { r = window.HubAndroid.startRecording(); } catch (e) { /* old app */ }
  if (r !== "ok") { micFail(r === "denied" ? "denied" : "unavailable"); return; }
  REC.rec = {
    state: "recording", mimeType: "audio/mp4",
    stop() {
      if (this.state === "inactive") return;
      this.state = "inactive";
      if (REC.cancel) { try { window.HubAndroid.cancelRecording(); } catch (e) { /* gone */ } recDone(); return; }
      try { window.HubAndroid.stopRecording(); } catch (e) { nativeFailed(); }
    },
  };
  REC.maxTimer = setTimeout(() => { if (REC.held) release(true); }, MAX_MS);
}
function nativeFailed(msg) {
  REC.rec = null; stopMic(); render(false);
  toast(msg || "The microphone did not work. Tap the keyboard to type instead.", 5000);
}
window.__hubNativeAudio = (b64, mime) => {
  REC.rec = null; stopMic(); render(false);
  if (!b64) { toast("I didn't hear anything. Hold the button while you talk.", 4000); return; }
  const bin = atob(b64); const u = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) u[i] = bin.charCodeAt(i);
  askAudio(new Blob([u], { type: mime || "audio/mp4" }), mime || "audio/mp4");
};
window.__hubNativeAudioError = (msg) => nativeFailed(msg);
function meter(stream) {
  try {
    const Ctx = window.AudioContext || window.webkitAudioContext; if (!Ctx) return;
    const ctx = new Ctx(); REC.ctx = ctx;
    const an = ctx.createAnalyser(); an.fftSize = 512;
    ctx.createMediaStreamSource(stream).connect(an);
    const buf = new Uint8Array(an.fftSize);
    const loop = () => {
      if (!REC.ctx) return;
      an.getByteTimeDomainData(buf);
      let sum = 0; for (let i = 0; i < buf.length; i++) { const v = (buf[i] - 128) / 128; sum += v * v; }
      const lvl = Math.min(1, Math.sqrt(sum / buf.length) * 4);
      const l = $("#mic .lvl"); if (l) l.style.transform = `scale(${1 + lvl * 0.45})`;
      REC.raf = requestAnimationFrame(loop);
    };
    loop();
  } catch (e) { /* the rings still show it is listening */ }
}
function stopMic() {
  clearTimeout(REC.maxTimer); clearInterval(REC.tickTimer);
  if (REC.stream) REC.stream.getTracks().forEach((t) => t.stop());
  REC.stream = null;
  if (REC.ctx) { try { REC.ctx.close(); } catch (e) { /* closed */ } REC.ctx = null; }
  cancelAnimationFrame(REC.raf);
}
function release(force) {
  if (!REC.held) return;
  REC.held = false;
  micLook(false);
  const heldFor = performance.now() - REC.t0;
  if ((heldFor < MIN_MS && !force) || !REC.rec) {
    REC.cancel = true;
    if (REC.rec && REC.rec.state !== "inactive") REC.rec.stop(); else { stopMic(); REC.rec = null; }
    tip("Hold to talk", 1800);
    render(false);
    return;
  }
  hideTip();
  REC.cancel = false;
  if (REC.rec.state !== "inactive") REC.rec.stop();
}
function recDone() {
  const rec = REC.rec; REC.rec = null;
  stopMic();
  render(false);
  if (REC.cancel) return;
  const mime = ((rec && rec.mimeType) || "audio/webm").split(";")[0];
  const blob = new Blob(REC.chunks, { type: mime }); REC.chunks = [];
  askAudio(blob, mime);
}
function micFail(kind) {
  REC.held = false; REC.cancel = true; stopMic(); REC.rec = null; micLook(false); hideTip();
  render(false);
  toast(kind === "denied" ? "The microphone is not allowed on this screen. Tap the keyboard to type instead."
                          : "There is no microphone on this screen. Tap the keyboard to type instead.", 5000);
}
stage.addEventListener("pointerdown", micDown);
["pointerup", "pointercancel"].forEach((ev) => document.addEventListener(ev, () => { if (REC.held) release(false); }));
stage.addEventListener("contextmenu", (e) => { if (e.target.closest(".mic")) e.preventDefault(); });
document.addEventListener("visibilitychange", () => {          // screen off or app hidden: drop the recording, send nothing
  if (!document.hidden || !REC.held) return;
  REC.held = false; REC.cancel = true; micLook(false); hideTip();
  if (REC.rec && REC.rec.state !== "inactive") REC.rec.stop(); else { stopMic(); REC.rec = null; }
});

// ---------- personal view: open, keep, close ----------
const TAP_IDLE = 60000;      // a tapped view goes back to shared after 60 s with no touch (PLAN-NOTES)
const FACE_GONE = 10000;     // a face view closes 10 s after Face ID stops seeing the person
let lastTouch = 0, idleTimer = null;
function presence(who, how) {
  if (S.conn !== "online") return;
  fetch(HUB + "/api/presence", { method: "POST", headers: { ...auth(), "Content-Type": "application/json" },
                                  body: JSON.stringify({ who, how }) }).catch(() => { /* the card still works */ });
}
async function loadCard(n) {
  ME.loading = true; ME.error = null; renderSheet();
  try {
    const res = await fetch(HUB + "/api/personal/" + encodeURIComponent(n), { headers: auth(), cache: "no-store" });
    if (res.status === 401) { needKey(true); return; }
    const body = await res.json();
    if (ME.name !== n) return;
    if (body && body.ok) ME.card = body.card; else ME.error = (body && body.error) || "Your card didn't load.";
  } catch (e) { if (ME.name === n) ME.error = "Couldn't reach the hub for your card."; }
  if (ME.name === n) { ME.loading = false; renderSheet(); }
}
function openPerson(n, how) {
  if (!PEOPLE.includes(n)) return;
  if (S.open && S.open !== "person") return;          // never cover a sheet someone is using
  clearTimeout(ME.closeTimer); ME.closeTimer = null;
  const same = ME.name === n;
  ME.how = how;
  if (how === "tap") lastTouch = Date.now();
  if (!same) { ME.name = n; ME.card = null; ME.error = null; if (FACE.enrol && FACE.enrol.name !== n && FACE.enrol.state === "failed") FACE.enrol = null; }
  presence(n, how);
  if (!same || !ME.card) loadCard(n);
  if (S.open === "person") { renderSheet(); renderUI(); }
  else { const el = $(`[data-src="p-${n}"]`); if (el) { openSheet("person", el); renderUI(); } }
  armIdle();
}
function personGone() {                       // the person sheet is closing, whatever closed it
  clearTimeout(ME.closeTimer); clearTimeout(idleTimer); ME.closeTimer = idleTimer = null;
  if (ME.name) presence(null, ME.how || "tap");
  ME.name = null; ME.how = null; ME.card = null; ME.error = null; FACE.forgetArm = null;
  if (FACE.enrol && FACE.enrol.state !== "looking" && FACE.enrol.state !== "progress") FACE.enrol = null;
}
function enrolling() { return FACE.enrol && (FACE.enrol.state === "looking" || FACE.enrol.state === "progress"); }
function armIdle() {
  clearTimeout(idleTimer);
  if (S.open !== "person") return;
  idleTimer = setTimeout(() => {
    if (S.open !== "person") return;
    if (enrolling() || Date.now() - lastTouch < TAP_IDLE) { armIdle(); return; }
    if (ME.how === "face" && FACE.who === ME.name) { armIdle(); return; }   // still standing there
    closeSheet();
  }, 5000);
}
stage.addEventListener("pointerdown", () => {
  lastTouch = Date.now();
  if (S.open === "person" && ME.how === "face") { ME.how = "tap"; clearTimeout(ME.closeTimer); ME.closeTimer = null; }
}, true);
// events from the tablet's Face ID (tablet/src/.../FaceEngine.java): names and progress only
window.__hubFace = (e) => {
  if (!e || typeof e !== "object") return;
  FACE.native = true;
  if (e.type === "status") {
    FACE.camera = e.camera || "off"; FACE.enrolled = Array.isArray(e.enrolled) ? e.enrolled : [];
    FACE.who = e.who || null;
  } else if (e.type === "who") {
    FACE.who = e.who || null;
    if (e.who) {
      if (!S.open || S.open === "person") {
        if (ME.name && ME.name !== e.who && Date.now() - lastTouch < 10000) { /* someone is using the view: leave it */ }
        else openPerson(e.who, ME.name === e.who && ME.how === "tap" ? "tap" : "face");
      }
    } else if (S.open === "person" && ME.how === "face" && !enrolling()) {
      clearTimeout(ME.closeTimer);
      ME.closeTimer = setTimeout(() => {
        if (S.open === "person" && ME.how === "face" && !FACE.who && Date.now() - lastTouch >= FACE_GONE) closeSheet();
      }, FACE_GONE);
    }
  } else if (e.type === "enrol") {
    FACE.enrol = e;
    if (e.state === "done") { if (!FACE.enrolled.includes(e.name)) FACE.enrolled.push(e.name); toast(`Face ID is set up for ${e.name}.`, 4000); }
    if (e.state === "cancelled") FACE.enrol = null;
    if (e.state === "busy") { FACE.enrol = null; toast(e.msg || "Try again in a moment.", 4000); }
  } else if (e.type === "forgot") {
    FACE.enrolled = FACE.enrolled.filter((x) => x !== e.name);
    toast(`${e.name}'s face is forgotten. Nothing about it is kept.`, 4500);
  }
  if (S.open === "person") renderSheet();
};
if (window.HubAndroid && window.HubAndroid.faceStatus) { try { window.__hubFace(JSON.parse(window.HubAndroid.faceStatus())); } catch (e) { /* older app */ } }

// ---------- clock, song progress, fit to the window ----------
setInterval(() => {
  tick();
  if (playing(SP())) {
    const w = progPct() + "%", p = posNow();
    $$("[data-prog]").forEach((n) => (n.style.width = w));
    if (p != null) $$("[data-pos]").forEach((n) => (n.textContent = mmss(p)));
  }
}, 1000);
function fit() {
  scale = Math.min(1, window.innerWidth / 1280, window.innerHeight / 800);
  stage.style.transform = scale < 1 ? `scale(${scale})` : "";
}
window.addEventListener("resize", fit);
fit(); renderScene(); render();
connect();

// for the tests and for checking from the iMac
window.__wall = { S, get pending() { return pending.length; }, get conn() { return S.conn; } };
})();
