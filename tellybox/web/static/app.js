// Tellybox kid app (KA-1..KA-10). Vanilla ES modules, no build step.
// Routes: #/ (home) and #/show/{id}. Live state via SSE; the sky is the timer.

import { api, subscribe, HttpError } from "./api.js";
import { icons, placeholderTv } from "./icons.js";
import { applySky } from "./sky.js";
import { label as tr, translatePage } from "./i18n.js";

translatePage(); // NF-13: <html lang> and the screen-reader labels in index.html

const $ = (sel, root = document) => root.querySelector(sel);
const view = $("#view");
const nowbar = $("#nowbar");
const skyParts = { body: document.body, sun: $("#sun"), skyEl: $("#sky") };

// ---------- state ----------

let state = {
  tv: "ok",
  now_playing: null,
  sky: { fraction_left: 1, last_five: false, unlimited: false },
  time_up: false,
};
let streamDown = false; // SSE errored and no event since: treat the TV as unreachable
let playBusy = false; // one pick request in flight
let toggleBusy = false; // one pause/resume request in flight
let route = null;
let viewToken = 0;
let cameFromHome = false;

const tvDown = () => streamDown || state.tv !== "ok";

// Distinct, soft colours for placeholders (the API has no show colour).
const SHOW_COLORS = ["#FF9CB6", "#8C7CF0", "#4FC3C9", "#FFB35C", "#B48CE0", "#6FA8FF", "#F08A6C", "#C98CE0"];
const showColor = (id) => SHOW_COLORS[Math.abs(Number(id) || 0) % SHOW_COLORS.length];

// ---------- small DOM helpers ----------

function el(tag, cls, attrs = {}) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  for (const [k, v] of Object.entries(attrs)) e.setAttribute(k, v);
  return e;
}

// 16:9 media box with ink outline; a drawn TV replaces a missing image.
function mediaBox(src, color, cls = "") {
  const box = el("span", `media ${cls}`.trim());
  box.style.setProperty("--c", color);
  const fallback = () => {
    box.classList.add("is-missing");
    box.querySelector("img")?.remove();
    box.insertAdjacentHTML("afterbegin", placeholderTv(color));
  };
  if (!src) {
    fallback();
    return box;
  }
  const img = el("img", "", { alt: "", loading: "lazy", decoding: "async", draggable: "false" });
  img.addEventListener("load", () => box.classList.add("is-loaded"), { once: true });
  img.addEventListener("error", fallback, { once: true });
  img.src = src;
  box.append(img);
  return box;
}

function episodeTile(t, kind) {
  const b = el("button", "tile tile-ep", { type: "button", "aria-label": t.title, "data-ep": String(t.episode_id) });
  const media = mediaBox(t.thumb, showColor(t.show_id));
  b.append(media);
  if (kind === "next") {
    b.append(Object.assign(el("span", "badge"), { innerHTML: icons.next }));
  } else if (t.finished) {
    b.append(Object.assign(el("span", "badge"), { innerHTML: icons.star }));
  } else if (t.progress != null && t.progress > 0) {
    const stripe = el("span", "stripe");
    const fill = el("span");
    fill.style.width = `${Math.max(6, Math.min(100, t.progress * 100))}%`;
    stripe.append(fill);
    media.append(stripe);
  }
  b.append(caption(t.title));
  return b;
}

// KA-10: a short title under the picture, for adults. aria-hidden because the tile's aria-label
// already carries it. Always present (even when empty) so it reserves its two lines and
// tiles in a row line up.
function caption(title) {
  const c = el("span", "caption", { "aria-hidden": "true" });
  c.textContent = title || "";
  return c;
}

function showTile(s) {
  const a = el("a", "tile tile-show", { href: `#/show/${s.show_id}`, "aria-label": s.title, "data-show": String(s.show_id) });
  a.style.setProperty("--c", showColor(s.show_id));
  // The artwork and the card stacked behind it, so they dim together at night.
  const stack = el("span", "stack");
  stack.append(mediaBox(s.artwork, showColor(s.show_id)));
  a.append(stack, caption(s.title));
  return a;
}

// ---------- views ----------

function parseRoute() {
  const m = location.hash.match(/^#\/show\/(\d+)\/?$/);
  if (m) return { name: "show", id: Number(m[1]) };
  return { name: "home" };
}

async function loadView({ keepPlace = false } = {}) {
  const token = ++viewToken;
  const r = route;
  let data;
  try {
    data = r.name === "show" ? await api.show(r.id) : await api.home();
  } catch (err) {
    if (token !== viewToken) return;
    if (err instanceof HttpError && err.status === 404 && r.name === "show") {
      history.replaceState(null, "", "#/"); // show hidden or gone: back home
      onRoute();
      return;
    }
    setTimeout(() => token === viewToken && loadView({ keepPlace }), 3000);
    return;
  }
  if (token !== viewToken) return;

  // Keep scroll positions and focus across live refreshes.
  const scrollTop = view.scrollTop;
  const strip = $(".strip", view);
  const stripLeft = strip ? strip.scrollLeft : 0;
  const focused = document.activeElement && view.contains(document.activeElement) ? document.activeElement : null;
  const focusKey = focused?.dataset.ep ? `[data-ep="${focused.dataset.ep}"]` : focused?.dataset.show ? `[data-show="${focused.dataset.show}"]` : focused?.classList.contains("btn-home") ? ".btn-home" : null;

  const frag = r.name === "show" ? renderShow(data) : renderHome(data);
  view.replaceChildren(frag);
  view.dataset.route = r.name;

  if (keepPlace) {
    view.scrollTop = scrollTop;
    const s = $(".strip", view);
    if (s) s.scrollLeft = stripLeft;
    if (focusKey) $(focusKey, view)?.focus({ preventScroll: true });
  }
  updateLive();
}

function renderHome(data) {
  const frag = document.createDocumentFragment();
  if (data.continue && data.continue.length) {
    const sec = el("section", "row-continue", { "aria-label": tr("Keep watching") });
    const strip = el("div", "strip");
    for (const t of data.continue) strip.append(episodeTile(t, t.kind));
    sec.append(strip);
    frag.append(sec);
  }
  const shows = el("section", "row-shows", { "aria-label": tr("Shows") });
  const grid = el("div", "grid grid-shows");
  for (const s of data.shows || []) grid.append(showTile(s));
  shows.append(grid);
  frag.append(shows);
  return frag;
}

function renderShow(data) {
  const frag = document.createDocumentFragment();
  const head = el("div", "show-head");
  const home = el("button", "round-btn btn-home", { type: "button", "aria-label": tr("Home") });
  home.innerHTML = icons.home;
  head.append(home);
  const art = mediaBox(data.artwork, showColor(data.show_id), "show-art");
  art.setAttribute("role", "img");
  art.setAttribute("aria-label", data.title);
  head.append(art);
  frag.append(head);

  const sec = el("section", "row-episodes", { "aria-label": data.title });
  const grid = el("div", "grid grid-episodes");
  for (const t of data.episodes || []) grid.append(episodeTile(t));
  sec.append(grid);
  frag.append(sec);
  return frag;
}

function onRoute() {
  const prev = route;
  route = parseRoute();
  cameFromHome = route.name === "show" && prev?.name === "home";
  view.scrollTop = 0;
  view.replaceChildren();
  loadView();
  if (prev) view.focus({ preventScroll: true });
}

let refreshTimer = null;
function refreshSoon() {
  clearTimeout(refreshTimer);
  refreshTimer = setTimeout(() => loadView({ keepPlace: true }), 600);
}

// ---------- now-playing bar (KA-6) ----------

const bar = (() => {
  const thumbSlot = el("span", "np-thumb");
  const btn = el("button", "big-btn", { type: "button", "aria-label": tr("Pause") });
  btn.innerHTML = `<span class="big-icon"></span>${icons.spinner}`;
  const idle = el("span", "np-idle", { role: "img", "aria-label": tr("Nothing playing") });
  idle.innerHTML = icons.tvSleepy;
  const offline = el("span", "np-offline", { role: "img", "aria-label": tr("TV not reachable") });
  offline.innerHTML = icons.tvOffline;
  nowbar.append(idle, offline, thumbSlot, btn);
  btn.addEventListener("click", toggle);
  return { thumbSlot, btn, idle, offline, thumbSrc: null, icon: null };
})();

function renderBar() {
  const np = state.now_playing;
  const down = tvDown();
  const mode = down ? "offline" : np ? "playing" : "idle";
  nowbar.dataset.mode = mode;
  bar.idle.hidden = mode !== "idle";
  bar.offline.hidden = mode !== "offline";
  bar.thumbSlot.hidden = mode !== "playing";
  bar.btn.hidden = mode !== "playing";
  if (mode !== "playing") return;

  if (bar.thumbSrc !== np.thumb) {
    bar.thumbSrc = np.thumb;
    const box = mediaBox(np.thumb, showColor(np.show_id));
    box.setAttribute("role", "img");
    box.setAttribute("aria-label", np.title || "");
    bar.thumbSlot.replaceChildren(box);
  } else {
    bar.thumbSlot.firstChild?.setAttribute("aria-label", np.title || "");
  }
  const paused = np.state === "paused";
  const icon = paused ? "play" : "pause";
  if (bar.icon !== icon) {
    bar.icon = icon;
    $(".big-icon", bar.btn).innerHTML = icons[icon];
  }
  bar.btn.setAttribute("aria-label", paused ? tr("Play") : tr("Pause"));
  const busy = toggleBusy || np.state === "loading" || np.state === "buffering";
  bar.btn.classList.toggle("is-busy", busy);
  bar.btn.setAttribute("aria-busy", String(busy));
}

async function toggle() {
  const np = state.now_playing;
  if (toggleBusy || !np || tvDown()) return;
  toggleBusy = true;
  renderBar();
  const r = await (np.state === "paused" ? api.resume() : api.pause());
  toggleBusy = false;
  handleActionResult(r);
  renderBar();
}

// ---------- picks (KA-5, KA-9) ----------

async function pick(tile) {
  if (state.time_up || playBusy) return;
  const id = Number(tile.dataset.ep);
  playBusy = true;
  tile.classList.add("is-pending");
  view.classList.add("is-picking");
  const r = await api.play(id);
  playBusy = false;
  tile.classList.remove("is-pending");
  view.classList.remove("is-picking");
  if (r.status === 404) {
    loadView({ keepPlace: true });
    return;
  }
  handleActionResult(r);
}

function handleActionResult({ status, data }) {
  if (data && typeof data === "object" && "sky" in data) {
    applyState(data);
    return;
  }
  if (status === 409) applyState({ ...state, time_up: true });
  else if (status === 503 || status === 0) applyState({ ...state, tv: "unreachable" });
}

view.addEventListener("click", (e) => {
  const home = e.target.closest(".btn-home");
  if (home) {
    if (cameFromHome) history.back();
    else location.hash = "#/";
    return;
  }
  const tile = e.target.closest(".tile-ep");
  if (tile) {
    pick(tile);
    return;
  }
  const show = e.target.closest(".tile-show");
  if (show && state.time_up) e.preventDefault();
});

// ---------- live state ----------

function updateLive() {
  applySky(state, skyParts);
  renderBar();
  const current = state.now_playing?.episode_id;
  for (const t of view.querySelectorAll(".tile-ep")) {
    t.classList.toggle("is-current", Number(t.dataset.ep) === current);
  }
  // Night: tiles are dimmed and inert (KA-9). The home button keeps working.
  for (const g of view.querySelectorAll(".strip, .grid")) {
    g.inert = !!state.time_up;
    g.setAttribute("aria-disabled", String(!!state.time_up));
  }
  document.body.classList.toggle("tv-down", tvDown());
}

function applyState(next) {
  const prev = state;
  state = next;
  updateLive();
  if (route && (prev.now_playing?.episode_id !== next.now_playing?.episode_id || prev.time_up !== next.time_up)) {
    refreshSoon(); // progress and "continue watching" may have changed
  }
}

// ---------- boot ----------

window.addEventListener("hashchange", onRoute);
document.addEventListener("visibilitychange", () => {
  if (document.visibilityState === "visible" && route) loadView({ keepPlace: true });
});

updateLive();
onRoute();
api.state().then(
  (s) => applyState(s),
  () => {},
);
subscribe({
  onState: (s) => {
    streamDown = false;
    applyState(s);
  },
  onDown: () => {
    streamDown = true;
    updateLive();
  },
});
