"use strict";
// Page téléphone : caméra + micro → moteur IA → diffusion directe (RTMP) vers la plateforme.
const $ = (s) => document.querySelector(s);
// Adresses officielles d'envoi (chiffrées quand la plateforme le permet). La clé vient de ton compte.
const PRESETS = {
  youtube: "rtmps://a.rtmps.youtube.com/live2",
  twitch: "rtmps://live.twitch.tv:443/app",
  facebook: "rtmps://live-api-s.facebook.com:443/rtmp",
  restream: "rtmp://live.restream.io/live",
  kick: "", tiktok: "", autre: "",
};
const HINTS = {
  kick: "Stream URL de ton tableau de bord Kick (commence par rtmps://)",
  tiktok: "Fournie par TikTok LIVE Studio (commence par rtmp://)",
  autre: "rtmp://… ou rtmps://…",
};
const HOWTO = {
  youtube: "Clé : YouTube Studio → Créer → Passer au direct → « Clé de flux ». La toute première activation du direct peut demander de vérifier le compte et un délai.",
  twitch: "Clé : tableau de bord Twitch → Paramètres → Stream → « Clé de stream principale ».",
  kick: "Clé et Stream URL : tableau de bord Kick → Paramètres → Stream Key (copie les deux).",
  facebook: "Clé : Facebook → Vidéo en direct (Live Producer) → « Clé de stream » ; active la clé persistante pour la réutiliser.",
  tiktok: "TikTok ne donne la clé de stream qu'à certains comptes (abonnés, pays) : vérifie dans TikTok LIVE Studio.",
  restream: "Clé : tableau de bord Restream → Stream Key. Restream redistribue ton flux vers les chaînes reliées à ton compte (économise ta connexion mobile).",
  autre: "Toute plateforme qui accepte un « encodeur » RTMP/RTMPS : colle l'adresse du serveur et la clé.",
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
const OPTIONS = `<optgroup label="Sans minimum d'abonnés"><option value="youtube">YouTube</option><option value="twitch">Twitch</option><option value="kick">Kick</option><option value="facebook">Facebook</option></optgroup>
<optgroup label="Multidiffusion"><option value="restream">Restream (un flux → 30+ plateformes)</option></optgroup>
<optgroup label="Autres"><option value="autre">Autre serveur (RTMP / RTMPS)</option><option value="tiktok">TikTok LIVE (accès restreint selon le compte)</option></optgroup>`;

function destBlock(d, i) {
  const el = document.createElement("div");
  el.className = "dest";
  el.innerHTML = `<div class="dest-head"><span>Plateforme ${i + 1}</span>${i ? '<button type="button" aria-label="Retirer">×</button>' : ""}</div>
    <select class="d-platform">${OPTIONS}</select><p class="howto"></p>
    <label>Adresse du serveur</label><input class="d-server" inputmode="url" autocapitalize="off" spellcheck="false">
    <label>Clé de stream</label><input class="d-key" type="password" autocapitalize="off" spellcheck="false">`;
  const sel = el.querySelector(".d-platform"), srv = el.querySelector(".d-server");
  sel.value = d.platform || "youtube";
  srv.value = d.server || PRESETS[sel.value] || "";
  el.querySelector(".d-key").value = d.key || "";
  const hint = () => { srv.placeholder = HINTS[sel.value] || PRESETS[sel.value] || ""; el.querySelector(".howto").textContent = HOWTO[sel.value] || ""; };
  sel.addEventListener("change", () => { srv.value = PRESETS[sel.value] || ""; hint(); if (sel.value === "tiktok") $("#format").value = "vertical"; });
  hint();
  el.querySelector(".dest-head button")?.addEventListener("click", () => { el.remove(); renumber(); });
  return el;
}
function renumber() {
  document.querySelectorAll(".dest").forEach((el, i) => (el.querySelector(".dest-head span").textContent = `Plateforme ${i + 1}`));
  $("#add").classList.toggle("hidden", document.querySelectorAll(".dest").length >= 3);
}
function collect() {
  return [...document.querySelectorAll(".dest")].map((el) => ({
    platform: el.querySelector(".d-platform").value, server: el.querySelector(".d-server").value.trim(), key: el.querySelector(".d-key").value.trim() }));
}
$("#add").addEventListener("click", () => { $("#dests").appendChild(destBlock({}, document.querySelectorAll(".dest").length)); renumber(); });
$("#do-bc").addEventListener("change", () => {
  $("#bc").classList.toggle("hidden", !$("#do-bc").checked);
  if ($("#do-bc").checked && !document.querySelector(".dest")) { $("#dests").appendChild(destBlock({}, 0)); renumber(); }
});

async function init() {
  st.catalog = await (await fetch("/api/catalog")).json();
  setIceServers(st.catalog.ice_servers);
  $("#engine").innerHTML = (st.catalog.gpu_rental ? `<option value="cloud">Mon GPU loué</option>` : "") +
    st.catalog.engines.map((e) => `<option value="${esc(e.key)}">${esc(e.name)}</option>`).join("");
  $("#token").value = store.get("token");
  $("#engine").value = store.get("engine") || $("#engine").value;
  $("#mode").innerHTML = (st.catalog.modes || []).map((m) => `<option value="${esc(m.key)}">${esc(m.label)}</option>`).join("");
  $("#mode").value = store.get("mode") || st.catalog.default_mode || "equilibre";
  const hint = () => { const m = (st.catalog.modes || []).find((x) => x.key === $("#mode").value); $("#mode-hint").textContent = m ? m.hint : ""; };
  $("#mode").addEventListener("change", hint); hint();
  $("#format").value = store.get("format") || "horizontal";
  let saved = [];
  try { saved = JSON.parse(store.get("dests") || "[]"); } catch {}
  saved.forEach((d, i) => $("#dests").appendChild(destBlock(d, i)));
  $("#remember-key").checked = saved.some((d) => d.key);
  $("#do-bc").checked = store.get("bc") === "1" && saved.length > 0;
  $("#bc").classList.toggle("hidden", !$("#do-bc").checked);
  renumber();
  $("#chips").innerHTML = st.catalog.characters.slice(0, 8).map((c) => `<button class="chip" data-kind="character" data-key="${esc(c.key)}">${esc(c.label)}</button>`).join("") +
    st.catalog.decors.slice(0, 6).map((c) => `<button class="chip" data-kind="decor" data-key="${esc(c.key)}">${esc(c.label)}</button>`).join("");
  document.querySelectorAll(".chip").forEach((c) => c.addEventListener("click", () => preset(c)));
}

// ------------------------------------------------------------------ démarrage
$("#go").addEventListener("click", async () => {
  $("#err").textContent = ""; $("#go").disabled = true;
  const dests = $("#do-bc").checked ? collect() : [];
  const remember = $("#remember-key").checked;
  store.set("token", $("#token").value); store.set("format", $("#format").value); store.set("engine", $("#engine").value);
  store.set("mode", $("#mode").value);
  store.set("bc", $("#do-bc").checked ? "1" : "");
  store.set("dests", JSON.stringify(dests.map((d) => ({ platform: d.platform, server: d.server, key: remember ? d.key : "" }))));
  try {
    const body = { engine: $("#engine").value, mode: $("#mode").value };
    const tStart = Date.now();
    if (dests.length) body.broadcast = dests.map((d) => ({ platform: d.platform, server_url: d.server, stream_key: d.key, format: $("#format").value }));
    const platform = dests.map((d) => d.platform).join(" + ");
    // Caméra et création du flux IA en parallèle (le moteur commence à se préparer pendant l'ouverture de la caméra).
    const [cam, session] = await Promise.all([
      navigator.mediaDevices.getUserMedia({
        video: videoConstraints({ facingMode: $("#facing").value }),
        audio: { echoCancellation: true, noiseSuppression: true },
      }),
      api("/api/sessions", { method: "POST", body: JSON.stringify(body) }),
    ]);
    st.cam = cam; st.session = session;
    $("#setup").classList.add("hidden"); $("#live").classList.remove("hidden"); document.querySelector(".labnav")?.classList.add("hidden");
    $("#cam").srcObject = st.cam;
    $("#state").textContent = "Connexion au moteur…";
    // Le micro ne part vers le moteur qu'en diffusion directe (inutile en mode essai : il reste pour l'enregistrement local).
    st.pub = await whipPublish(`/api/sessions/${st.session.id}/whip`, st.cam, H(), { audio: !!platform });
    $("#state").textContent = "Chargement de l'IA…";
    $("#ai").addEventListener("playing", () => say(`IA prête en ${((Date.now() - tStart) / 1000).toFixed(1)} s — mode ${st.session.mode_label || ""}`), { once: true });
    st.view = await whepPlay(`/api/sessions/${st.session.id}/whep`, $("#ai"), H());
    $("#state").textContent = platform ? "● EN DIRECT" : "Test (non publié)";
    $("#state").classList.toggle("rec", !!platform);
    st.t0 = Date.now();
    st.timers.push(setInterval(tick, 1000));
    st.timers.push(fpsMeter($("#ai"), (n) => ($("#fps").textContent = `${n} i/s`)));
    st.timers.push(netStats(st.pub, st.view, (s) => {
      const g = netGrade(s), el = $("#net");
      if (!g) return;
      el.classList.remove("hidden"); el.dataset.g = g;
      el.textContent = `Réseau ${g}${s.rtt != null ? ` · ${s.rtt} ms` : ""}`;
      el.title = `envoi ${s.upFps ?? "—"} i/s ${s.res ?? ""} ${s.upKbps ?? "—"} kbit/s · réception ${s.downFps ?? "—"} i/s · pertes ${s.loss ?? 0} % · tampon ${s.bufferMs ?? "—"} ms${s.limit ? " · limité par " + s.limit : ""}`;
    }));
    st.timers.push(setInterval(refresh, 5000));
    try { st.wake = await navigator.wakeLock.request("screen"); } catch {}
    st.recorder = makeRecorder($("#ai"), st.cam.getAudioTracks()[0]);
    say(platform ? `Diffusion vers ${platform} lancée` : "Mode test : rien n'est publié. « ⏺ Essai » pour enregistrer.");
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

// ------------------------------------------------------------------ enregistrement d'essai
$("#rec").addEventListener("click", async () => {
  if (!st.recorder) return;
  if (st.recorder.recording) {
    clearInterval(st.recTimer);
    const r = await st.recorder.stop();
    $("#rec").textContent = "⏺ Essai"; $("#rec").classList.remove("recording"); $("#recpill").classList.add("hidden");
    if (r) say(`Essai enregistré : ${r.name} (${(r.size / 1e6).toFixed(1)} Mo)`);
    return;
  }
  try {
    st.recorder.start();
    $("#rec").textContent = "■ Stop"; $("#rec").classList.add("recording"); $("#recpill").classList.remove("hidden");
    st.recTimer = setInterval(() => { const s = st.recorder.seconds; $("#recpill").textContent = `● ENR ${String(Math.floor(s / 60)).padStart(2, "0")}:${String(s % 60).padStart(2, "0")}`; }, 500);
  } catch (e) { say(e.message); }
});

// ------------------------------------------------------------------ fin
$("#stop").addEventListener("click", async () => {
  if (!confirm("Terminer le live ?")) return;
  try { if (st.session) await api(`/api/sessions/${st.session.id}`, { method: "DELETE" }); } catch {}
  teardown(true);
});
function teardown(back) {
  if (st.recorder && st.recorder.recording) st.recorder.stop();
  clearInterval(st.recTimer); $("#recpill")?.classList.add("hidden"); $("#rec").textContent = "⏺ Essai"; $("#rec").classList.remove("recording");
  st.timers.forEach((t) => clearInterval(t)); st.timers = [];
  try { st.pub && st.pub.close(); st.view && st.view.close(); } catch {}
  st.cam && st.cam.getTracks().forEach((t) => t.stop());
  st.listening = false; try { st.rec && st.rec.stop(); } catch {}
  try { st.wake && st.wake.release(); } catch {}
  if (back) { $("#live").classList.add("hidden"); $("#setup").classList.remove("hidden"); document.querySelector(".labnav")?.classList.remove("hidden"); }
}
init();
