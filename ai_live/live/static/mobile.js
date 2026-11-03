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
  el.innerHTML = `<div class="dest-head"><span>${t("platform", { n: i + 1 })}</span>${i ? '<button type="button" aria-label="Retirer">×</button>' : ""}</div>
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
  document.querySelectorAll(".dest").forEach((el, i) => (el.querySelector(".dest-head span").textContent = t("platform", { n: i + 1 })));
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

// Libellés traduits : modes, puces de personnages/décors (catalogue du serveur, noms par langue).
function label(kind, c) { return ((st.catalog.labels || {})[LANG] || {})[kind]?.[c.key] || c.label; }
function buildModes(selected) {
  $("#mode").innerHTML = `<option value="auto">${esc(t("auto"))}</option>` +
    (st.catalog.modes || []).map((m) => `<option value="${esc(m.key)}">${esc(t("m_" + m.key))}</option>`).join("");
  $("#mode").value = selected || "auto";
  modeHint();
}
function modeHint() { const v = $("#mode").value; $("#mode-hint").textContent = v === "auto" ? t("auto_hint") : t("h_" + v); }
function buildChips() {
  $("#chips").innerHTML = st.catalog.characters.slice(0, 8).map((c) => `<button class="chip" data-kind="character" data-key="${esc(c.key)}">${esc(label("characters", c))}</button>`).join("") +
    st.catalog.decors.slice(0, 6).map((c) => `<button class="chip" data-kind="decor" data-key="${esc(c.key)}">${esc(label("decors", c))}</button>`).join("");
  document.querySelectorAll(".chip").forEach((c) => c.addEventListener("click", () => preset(c)));
}

async function init() {
  st.catalog = await (await fetch("/api/catalog")).json();
  setIceServers(st.catalog.ice_servers);
  $("#engine").innerHTML = (st.catalog.fleet || []).map((f) => `<option value="${esc(f.key)}">${esc(f.name)}</option>`).join("") +
    (st.catalog.gpu_rental ? `<option value="cloud">Mon GPU loué</option>` : "") +
    st.catalog.engines.map((e) => `<option value="${esc(e.key)}">${esc(e.name)}</option>`).join("");
  $("#token").value = store.get("token");
  $("#engine").value = store.get("engine") || $("#engine").value;
  const keep = store.get("mode") || "auto";
  buildModes(keep);
$("#mode").addEventListener("change", modeHint);
  $("#face").checked = store.get("face") === "1";
  const nav = (navigator.language || "fr").slice(0, 2);
  $("#vlang").value = store.get("vlang") || ([...$("#vlang").options].some((o) => o.value === nav) ? nav : "fr");
  $("#refs").checked = store.get("refs") === "1";
  $("#res").value = store.get("res") || "auto";
  $("#fluid").checked = store.get("fluid") !== "0";
  $("#format").value = store.get("format") || "horizontal";
  let saved = [];
  try { saved = JSON.parse(store.get("dests") || "[]"); } catch {}
  saved.forEach((d, i) => $("#dests").appendChild(destBlock(d, i)));
  $("#remember-key").checked = saved.some((d) => d.key);
  $("#do-bc").checked = store.get("bc") === "1" && saved.length > 0;
  $("#bc").classList.toggle("hidden", !$("#do-bc").checked);
  renumber();
  buildChips();
  applyUI($("#vlang").value); modeHint();
  $("#vlang").addEventListener("change", () => { applyUI($("#vlang").value); buildModes($("#mode").value); buildChips(); });
}

// ------------------------------------------------------------------ démarrage
$("#go").addEventListener("click", async () => {
  $("#err").textContent = ""; $("#go").disabled = true;
  const dests = $("#do-bc").checked ? collect() : [];
  const remember = $("#remember-key").checked;
  store.set("token", $("#token").value); store.set("format", $("#format").value); store.set("engine", $("#engine").value);
  store.set("mode", $("#mode").value);
  store.set("face", $("#face").checked ? "1" : "0");
  store.set("vlang", $("#vlang").value);
  store.set("refs", $("#refs").checked ? "1" : "0");
  store.set("res", $("#res").value); store.set("fluid", $("#fluid").checked ? "1" : "0");
  store.set("bc", $("#do-bc").checked ? "1" : "");
  store.set("dests", JSON.stringify(dests.map((d) => ({ platform: d.platform, server: d.server, key: remember ? d.key : "" }))));
  try {
    const tStart = Date.now();
    const auto = $("#mode").value === "auto";
    let mode = $("#mode").value;
    if (auto) { const net = await probeNetwork(); mode = pickInitialMode(net); st.probe = net; }
    const body = { engine: $("#engine").value, mode, references: $("#refs").checked };
    if (dests.length) body.broadcast = dests.map((d) => ({ platform: d.platform, server_url: d.server, stream_key: d.key, format: $("#format").value }));
    const platform = dests.map((d) => d.platform).join(" + ");
    // Caméra et création du flux IA en parallèle (le moteur commence à se préparer pendant l'ouverture de la caméra).
    const [cam, session] = await Promise.all([
      navigator.mediaDevices.getUserMedia({
        video: videoConstraints({ facingMode: $("#facing").value }),
        audio: { echoCancellation: true, noiseSuppression: true },
      }),
      createSession(body),
    ]);
    st.cam = cam; st.session = session;
    $("#setup").classList.add("hidden"); $("#live").classList.remove("hidden"); document.querySelector(".labnav")?.classList.add("hidden");
    $("#cam").srcObject = st.cam;
    $("#state").textContent = t("connecting");
    // Le micro ne part vers le moteur qu'en diffusion directe (inutile en mode essai : il reste pour l'enregistrement local).
    st.pub = await whipPublish(`/api/sessions/${st.session.id}/whip`, st.cam, H(), { audio: !!platform });
    $("#state").textContent = t("loading");
    $("#ai").addEventListener("playing", () => say(t("ready", { s: ((Date.now() - tStart) / 1000).toFixed(1), m: t("m_" + st.session.mode) })), { once: true });
    st.view = await whepPlay(`/api/sessions/${st.session.id}/whep`, $("#ai"), H());
    startRendu();
    $("#state").textContent = platform ? t("live_on") : t("test_state");
    $("#state").classList.toggle("rec", !!platform);
    st.t0 = Date.now();
    st.timers.push(setInterval(tick, 1000));
    st.timers.push(fpsMeter($("#ai"), (n) => ($("#fps").textContent = `${n} ${t("fps")}`)));
    st.tune = auto ? new AutoTune({ mode, allowModeSwitch: !platform }) : null;
    if ($("#face").checked) $("#ai").addEventListener("playing", () => setFace(true), { once: true });
    showMode();
    startNet();
    st.timers.push(setInterval(refresh, 5000));
    try { st.wake = await navigator.wakeLock.request("screen"); } catch {}
    st.recorder = makeRecorder(recSource, st.cam.getAudioTracks()[0]);
    say(platform ? t("bc_started", { p: platform }) : t("test_started"));
  } catch (e) {
    $("#err").textContent = t("failed") + e.message; teardown(false);
  }
  $("#go").disabled = false;
});

// Rendu téléphone (rendu.js) : agrandissement jusqu'en 1080p + prédiction du mouvement.
// Sans WebGL2, on garde simplement la vidéo IA telle quelle.
function startRendu() {
  try { st.rendu && st.rendu.stop(); } catch {}
  st.rendu = null;
  try {
    $("#view").classList.remove("hidden");
    st.rendu = new Rendu({ canvas: $("#view"), ai: $("#ai"), cam: $("#cam"), res: $("#res").value, fluid: $("#fluid").checked, onInfo: showRes });
  } catch (e) { $("#view").classList.add("hidden"); console.warn("rendu téléphone indisponible :", e.message); }
}
function showRes(i) {
  const el = $("#resp"); if (!el) return;
  el.classList.remove("hidden");
  const p = i.short >= 1400 ? "1440p" : i.short >= 1000 ? "1080p" : i.short >= 700 ? "720p" : i.short >= 460 ? "480p" : i.short + "p";
  el.textContent = p + (i.fluid ? ` · ${t("p_fluid")}` : "");
  el.title = i.fluid ? `${t("lag")} ${i.lagMs} ms${i.measured ? "" : " (estimé)"} · ${i.engine === "rust" ? "Rust/WebAssembly" : "JavaScript"}${i.seg ? " · silhouette" : ""}` : "";
}
// Enregistrement : l'image finale (agrandie et lissée) si le rendu tourne, sinon la vidéo IA brute.
function recSource() {
  if (st.rendu) { const tr = st.rendu.stream().getVideoTracks()[0]; return { track: tr, hd: st.rendu.info().short >= 1000, qhd: st.rendu.info().short >= 1400 }; }
  const s = $("#ai").srcObject; return { track: s && s.getVideoTracks()[0] };
}
$("#resp").addEventListener("click", () => {
  if (!st.rendu) return;
  st.rendu.setFluid(!st.rendu.fluid); store.set("fluid", st.rendu.fluid ? "1" : "0"); $("#fluid").checked = st.rendu.fluid;
  showRes(st.rendu.info()); say(st.rendu.fluid ? t("fluid_on") : t("fluid_off"));
});

// Création de session ; avec la flotte, un GPU peut être en démarrage (réponse 503 + ticket) :
// on patiente en réessayant avec le même ticket (la place est gardée), 8 minutes au plus.
async function createSession(body) {
  const t0 = Date.now();
  for (;;) {
    const r = await fetch("/api/sessions", { method: "POST", headers: H({ "Content-Type": "application/json" }), body: JSON.stringify(body) });
    const d = await r.json().catch(() => ({}));
    if (r.ok) return d;
    if (r.status === 503 && d.detail && d.detail.ticket && Date.now() - t0 < 8 * 60_000) {
      body.ticket = d.detail.ticket;
      $("#err").textContent = t("gpu_wait", { s: Math.round((Date.now() - t0) / 1000) });
      await new Promise((res) => setTimeout(res, 1000 * (d.detail.retry_after || 20)));
      continue;
    }
    throw new Error((d.detail && (d.detail.message || d.detail)) || "erreur " + r.status);
  }
}

// Mesures réseau + mode automatique (relancé après chaque reconnexion, car il suit les connexions actives).
function startNet() {
  clearInterval(st.netTimer);
  st.netTimer = netStats(st.pub, st.view, (s) => {
    if (st.rendu) st.rendu.setNet(s);
    const g = netGrade(s), el = $("#net");
    if (g) {
      el.classList.remove("hidden"); el.dataset.g = g;
      el.textContent = `${t("net")} ${t("g_" + g)}${s.rtt != null ? ` · ${s.rtt} ms` : ""}`;
      el.title = `envoi ${s.upFps ?? "—"} i/s ${s.res ?? ""} ${s.upKbps ?? "—"} kbit/s · réception ${s.downFps ?? "—"} i/s · pertes ${s.loss ?? 0} % · tampon ${s.bufferMs ?? "—"} ms${s.limit ? " · limité par " + s.limit : ""}`;
    }
    if (!st.tune || st.switching) return;
    for (const a of st.tune.feed(s)) {
      if (a.type === "bitrate") { applyBitrate(st.pub, a.level); say(a.level === "eco" ? t("net_eco") : t("net_ok")); }
      if (a.type === "mode") switchMode(a.mode);
    }
  });
}

// « Garder mon visage » : une photo de la caméra (512×512) est envoyée au moteur, qui garde tes traits (FaceID).
// Elle reste en mémoire sur le serveur et est effacée quand on désactive ou à la fin de la session.
async function setFace(on) {
  if (!st.session) return;
  if (st.session.mode === "rapide") { say(t("face_rapide")); showFace(); return; }
  try {
    let r;
    if (on) {
      const v = $("#cam"), c = document.createElement("canvas");
      c.width = c.height = 512;
      const s = Math.min(v.videoWidth, v.videoHeight) || 512;
      c.getContext("2d").drawImage(v, (v.videoWidth - s) / 2, (v.videoHeight - s) / 2, s, s, 0, 0, 512, 512);
      const blob = await new Promise((res) => c.toBlob(res, "image/jpeg", 0.88));
      r = await fetch(`/api/sessions/${st.session.id}/face`, { method: "POST", headers: H({ "Content-Type": "image/jpeg" }), body: blob });
    } else {
      r = await fetch(`/api/sessions/${st.session.id}/face`, { method: "DELETE", headers: H() });
    }
    const d = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(d.detail || r.status);
    st.session = d;
    say(on ? t("face_on") : t("face_off"));
  } catch (e) { say("Visage : " + e.message); }
  showFace();
}

function showFace() {
  const b = $("#facep"); if (!b || !st.session) return;
  b.classList.remove("hidden");
  const on = !!st.session.face_locked;
  b.textContent = on ? t("face_pill_on") : t("face_pill_off");
  b.style.borderColor = on ? "#2dd4bf" : "";
}

function showMode() {
  const el = $("#modep"); if (!el || !st.session) return;
  el.classList.remove("hidden");
  el.textContent = (st.tune ? "Auto · " : "") + t("m_" + st.session.mode);
}

// L'IA n'arrive pas à suivre : on recrée le flux dans un mode plus rapide (quelques secondes de coupure).
async function switchMode(mode) {
  st.switching = true;
  try {
    say(t("struggle"));
    st.session = await api(`/api/sessions/${st.session.id}/mode`, { method: "POST", body: JSON.stringify({ mode, reason: "auto" }) });
    try { st.pub && st.pub.close(); st.view && st.view.close(); } catch {}
    st.pub = await whipPublish(`/api/sessions/${st.session.id}/whip`, st.cam, H(), { audio: false });
    st.view = await whepPlay(`/api/sessions/${st.session.id}/whep`, $("#ai"), H());
    showMode(); startNet();
    say(t("mode_auto", { m: t("m_" + st.session.mode) }));
    showFace();
  } catch (e) {
    say(t("mode_fail") + e.message);
    st.tune = null;  // on n'insiste pas
  }
  st.switching = false;
}

function tick() {
  const s = Math.floor((Date.now() - st.t0) / 1000);
  $("#timer").textContent = `${String(Math.floor(s / 60)).padStart(2, "0")}:${String(s % 60).padStart(2, "0")}`;
}
function render(s) {
  st.session = s;
  const sc = s.scene;
  $("#toggle").textContent = sc.bypass ? t("resume") : t("original");
  $("#toggle").className = "big " + (sc.bypass ? "ia" : "orig");
  $("#parody").classList.toggle("hidden", !sc.parody || sc.bypass);
  if (sc.parody_of) $("#parody").textContent = t("parody", { n: sc.parody_of });
  document.querySelectorAll(".chip").forEach((c) => c.classList.toggle("on", (c.dataset.kind === "character" ? sc.character : sc.decor) === c.dataset.key));
  if (s.estimated_cost_usd != null) { $("#cost").classList.remove("hidden"); $("#cost").textContent = `${s.estimated_cost_usd.toFixed(3)} $`; }
  showFace();
  if (s.ended) { say(t("ended") + s.end_reason); teardown(true); }
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
  try { const r = await api(`/api/sessions/${st.session.id}/command`, { method: "POST", body: JSON.stringify({ text, lang: $("#vlang").value }) }); render(r.session); say(r.ok ? (LANG === "fr" ? "✓ " + r.message : t("applied")) : t("refused") + r.message); }
  catch (e) { say(e.message); }
}

// ------------------------------------------------------------------ voix
const Rec = window.SpeechRecognition || window.webkitSpeechRecognition;
$("#mic").addEventListener("click", () => {
  if (!Rec) return say(t("no_speech"));
  if (st.listening) { st.listening = false; try { st.rec.stop(); } catch {} $("#mic").classList.remove("on"); return; }
  const vl = $("#vlang").value;
  st.rec = new Rec(); st.rec.lang = ((st.catalog.voice_langs || []).find((x) => x.code === vl) || {}).speech || "fr-FR"; st.rec.continuous = true;
  st.rec.onresult = (e) => command(e.results[e.results.length - 1][0].transcript.trim());
  st.rec.onend = () => { if (st.listening) try { st.rec.start(); } catch {} };
  st.rec.start(); st.listening = true; $("#mic").classList.add("on"); say(t("listening"));
});

// ------------------------------------------------------------------ enregistrement d'essai
$("#rec").addEventListener("click", async () => {
  if (!st.recorder) return;
  if (st.recorder.recording) {
    clearInterval(st.recTimer);
    const r = await st.recorder.stop();
    $("#rec").textContent = t("rec"); $("#rec").classList.remove("recording"); $("#recpill").classList.add("hidden");
    if (r) say(t("rec_saved", { n: r.name, s: (r.size / 1e6).toFixed(1) }));
    return;
  }
  try {
    st.recorder.start();
    $("#rec").textContent = t("stop_rec"); $("#rec").classList.add("recording"); $("#recpill").classList.remove("hidden");
    st.recTimer = setInterval(() => { const s = st.recorder.seconds; $("#recpill").textContent = `${t("rec_pill")} ${String(Math.floor(s / 60)).padStart(2, "0")}:${String(s % 60).padStart(2, "0")}`; }, 500);
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
  clearInterval(st.recTimer); $("#recpill")?.classList.add("hidden"); $("#rec").textContent = t("rec"); $("#rec").classList.remove("recording");
  st.timers.forEach((t) => clearInterval(t)); st.timers = [];
  clearInterval(st.netTimer); st.tune = null;
  try { st.rendu && st.rendu.stop(); } catch {} st.rendu = null; $("#view").classList.add("hidden"); $("#resp").classList.add("hidden");
  try { st.pub && st.pub.close(); st.view && st.view.close(); } catch {}
  st.cam && st.cam.getTracks().forEach((t) => t.stop());
  st.listening = false; try { st.rec && st.rec.stop(); } catch {}
  try { st.wake && st.wake.release(); } catch {}
  if (back) { $("#live").classList.add("hidden"); $("#setup").classList.remove("hidden"); document.querySelector(".labnav")?.classList.remove("hidden"); }
}
init();

$("#facep").addEventListener("click", () => setFace(!(st.session && st.session.face_locked)));
