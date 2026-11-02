"use strict";
// Page téléphone : caméra + micro → moteur IA → diffusion directe (RTMP) vers la plateforme.
const $ = (s) => document.querySelector(s);
const PRESETS = {
  youtube: "rtmp://a.rtmp.youtube.com/live2",
  twitch: "rtmp://live.twitch.tv/app",
  tiktok: "", kick: "", autre: "",
};
const HINTS = {
  tiktok: "Fournie par TikTok LIVE Studio / paramètres LIVE (commence par rtmp://)",
  kick: "Dans ton tableau de bord Kick → Stream URL (commence par rtmps://)",
  autre: "rtmp://… ou rtmps://…",
};
const st = { session: null, cam: null, pub: null, view: null, t0: 0, timers: [], rec: null, listening: false, wake: null, catalog: null };

const store = {
  get(k) { try { return localStorage.getItem("ailive_" + k) || ""; } catch { return ""; } },
  set(k, v) { try { v ? localStorage.setItem("ailive_" + k, v) : localStorage.removeItem("ailive_" + k); } catch {} },
};
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const H = (extra = {}) => ({ "X-Live-Token": $("#token").value, ...extra });
async function api(path, opts = {}) {
  const r = await fetch(path, { ...opts, headers: H({ "Content-Type": "application/json" }) });
  const d = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(d.detail || "erreur " + r.status);
  return d;
}
const say = (t) => { $("#msg").textContent = t; clearTimeout(say.t); say.t = setTimeout(() => ($("#msg").textContent = ""), 4000); };

// ------------------------------------------------------------------ réglages
async function init() {
  st.catalog = await (await fetch("/api/catalog")).json();
  setIceServers(st.catalog.ice_servers);
  $("#engine").innerHTML = (st.catalog.gpu_rental ? `<option value="cloud">Mon GPU loué</option>` : "") +
    st.catalog.engines.map((e) => `<option value="${esc(e.key)}">${esc(e.name)}</option>`).join("");
  $("#token").value = store.get("token");
  $("#platform").value = store.get("platform");
  $("#server").value = store.get("server");
  $("#key").value = store.get("key");
  $("#remember-key").checked = !!store.get("key");
  $("#format").value = store.get("format") || "vertical";
  $("#engine").value = store.get("engine") || $("#engine").value;
  onPlatform(false);
  $("#chips").innerHTML = st.catalog.characters.slice(0, 8).map((c) => `<button class="chip" data-kind="character" data-key="${esc(c.key)}">${esc(c.label)}</button>`).join("") +
    st.catalog.decors.slice(0, 6).map((c) => `<button class="chip" data-kind="decor" data-key="${esc(c.key)}">${esc(c.label)}</button>`).join("");
  document.querySelectorAll(".chip").forEach((c) => c.addEventListener("click", () => preset(c)));
}
function onPlatform(fill = true) {
  const p = $("#platform").value;
  $("#bc").classList.toggle("hidden", !p);
  if (fill && PRESETS[p]) $("#server").value = PRESETS[p];
  $("#server").placeholder = HINTS[p] || PRESETS[p] || "";
  if (p === "tiktok") $("#format").value = "vertical";
}
$("#platform").addEventListener("change", () => onPlatform(true));

// ------------------------------------------------------------------ démarrage
$("#go").addEventListener("click", async () => {
  $("#err").textContent = ""; $("#go").disabled = true;
  const platform = $("#platform").value;
  store.set("token", $("#token").value); store.set("platform", platform); store.set("server", $("#server").value);
  store.set("format", $("#format").value); store.set("engine", $("#engine").value);
  store.set("key", $("#remember-key").checked ? $("#key").value : "");
  try {
    st.cam = await navigator.mediaDevices.getUserMedia({
      video: { facingMode: $("#facing").value, width: { ideal: 1280 }, height: { ideal: 720 }, frameRate: { ideal: 30 } },
      audio: { echoCancellation: true, noiseSuppression: true },
    });
    const body = { engine: $("#engine").value };
    if (platform) body.broadcast = { platform, server_url: $("#server").value.trim(), stream_key: $("#key").value.trim(), format: $("#format").value };
    st.session = await api("/api/sessions", { method: "POST", body: JSON.stringify(body) });
    $("#setup").classList.add("hidden"); $("#live").classList.remove("hidden");
    $("#cam").srcObject = st.cam;
    $("#state").textContent = "Connexion au moteur…";
    st.pub = await whipPublish(`/api/sessions/${st.session.id}/whip`, st.cam, H());
    $("#state").textContent = "Chargement de l'IA…";
    st.view = await whepPlay(`/api/sessions/${st.session.id}/whep`, $("#ai"), H());
    $("#state").textContent = platform ? "● EN DIRECT" : "Aperçu";
    $("#state").classList.toggle("rec", !!platform);
    st.t0 = Date.now();
    st.timers.push(setInterval(tick, 1000));
    st.timers.push(fpsMeter($("#ai"), (n) => ($("#fps").textContent = `${n} i/s`)));
    st.timers.push(setInterval(refresh, 5000));
    try { st.wake = await navigator.wakeLock.request("screen"); } catch {}
    say(platform ? `Diffusion vers ${platform} lancée` : "Aperçu lancé (pas de diffusion)");
  } catch (e) {
    $("#err").textContent = "Échec : " + e.message; teardown(false);
  }
  $("#go").disabled = false;
});

function tick() {
  const s = Math.floor((Date.now() - st.t0) / 1000);
  $("#timer").textContent = `${String(Math.floor(s / 60)).padStart(2, "0")}:${String(s % 60).padStart(2, "0")}`;
}
function render(s) {
  st.session = s;
  const sc = s.scene;
  $("#toggle").textContent = sc.bypass ? "✦ RÉACTIVER L'IA" : "⟲ ORIGINAL";
  $("#toggle").className = "big " + (sc.bypass ? "ia" : "orig");
  $("#parody").classList.toggle("hidden", !sc.parody || sc.bypass);
  if (sc.parody_of) $("#parody").textContent = `Parodie IA · ce n'est pas ${sc.parody_of}`;
  document.querySelectorAll(".chip").forEach((c) => c.classList.toggle("on", (c.dataset.kind === "character" ? sc.character : sc.decor) === c.dataset.key));
  if (s.estimated_cost_usd != null) { $("#cost").classList.remove("hidden"); $("#cost").textContent = `${s.estimated_cost_usd.toFixed(3)} $`; }
  if (s.ended) { say("Session terminée : " + s.end_reason); teardown(true); }
}
async function refresh() { try { render(await api(`/api/sessions/${st.session.id}`)); } catch {} }

async function preset(chip) {
  try { render(await api(`/api/sessions/${st.session.id}/preset`, { method: "POST", body: JSON.stringify({ kind: chip.dataset.kind, key: chip.dataset.key }) })); say(chip.textContent); }
  catch (e) { say(e.message); }
}
$("#toggle").addEventListener("click", async () => {
  try { render(await api(`/api/sessions/${st.session.id}/bypass`, { method: "POST", body: JSON.stringify({ on: !st.session.scene.bypass }) })); }
  catch (e) { say(e.message); }
});
async function command(text) {
  try { const r = await api(`/api/sessions/${st.session.id}/command`, { method: "POST", body: JSON.stringify({ text }) }); render(r.session); say((r.ok ? "✓ " : "✗ ") + r.message); }
  catch (e) { say(e.message); }
}

// ------------------------------------------------------------------ voix
const Rec = window.SpeechRecognition || window.webkitSpeechRecognition;
$("#mic").addEventListener("click", () => {
  if (!Rec) return say("Reconnaissance vocale indisponible sur ce navigateur (essaie Chrome).");
  if (st.listening) { st.listening = false; try { st.rec.stop(); } catch {} $("#mic").classList.remove("on"); return; }
  st.rec = new Rec(); st.rec.lang = "fr-FR"; st.rec.continuous = true;
  st.rec.onresult = (e) => command(e.results[e.results.length - 1][0].transcript.trim());
  st.rec.onend = () => { if (st.listening) try { st.rec.start(); } catch {} };
  st.rec.start(); st.listening = true; $("#mic").classList.add("on"); say("Je t'écoute : « transforme-moi en chevalier »…");
});

// ------------------------------------------------------------------ fin
$("#stop").addEventListener("click", async () => {
  if (!confirm("Terminer le live ?")) return;
  try { if (st.session) await api(`/api/sessions/${st.session.id}`, { method: "DELETE" }); } catch {}
  teardown(true);
});
function teardown(back) {
  st.timers.forEach((t) => clearInterval(t)); st.timers = [];
  try { st.pub && st.pub.close(); st.view && st.view.close(); } catch {}
  st.cam && st.cam.getTracks().forEach((t) => t.stop());
  st.listening = false; try { st.rec && st.rec.stop(); } catch {}
  try { st.wake && st.wake.release(); } catch {}
  if (back) { $("#live").classList.add("hidden"); $("#setup").classList.remove("hidden"); }
}
init();
