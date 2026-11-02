"use strict";
const $ = (s) => document.querySelector(s);
const st = { catalog: null, session: null, cam: null, pubPc: null, viewPc: null, timer: null, poll: null, rec: null, listening: false };

const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
function token() { return $("#token").value || ""; }
function headers(extra = {}) { return { "X-Live-Token": token(), ...extra }; }
function say(text, err = false) { $("#msg").textContent = text; $("#msg").classList.toggle("err", err); }

async function api(path, opts = {}) {
  const r = await fetch(path, { ...opts, headers: headers({ "Content-Type": "application/json", ...(opts.headers || {}) }) });
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(data.detail || "erreur " + r.status);
  return data;
}

// ------------------------------------------------------------ catalogue
async function loadCatalog() {
  st.catalog = await (await fetch("/api/catalog")).json();
  setIceServers(st.catalog.ice_servers);
  $("#token-field").hidden = !st.catalog.access_required;
  $("#engine").innerHTML = (st.catalog.gpu_rental ? `<option value="cloud">Mon GPU loué (Vast.ai / RunPod)</option>` : "") +
    st.catalog.engines.map((e) =>
    `<option value="${esc(e.key)}">${esc(e.name)} — ${esc(e.model)}${e.configured ? "" : " (clé manquante)"}</option>`).join("");
  $("#mode").innerHTML = (st.catalog.modes || []).map((m) => `<option value="${esc(m.key)}" title="${esc(m.hint)}">${esc(m.label)} — ${esc(m.hint)}</option>`).join("");
  $("#mode").value = st.catalog.default_mode || "equilibre";
  setupGpu();
  for (const [kind, id] of [["character", "#characters"], ["decor", "#decors"], ["style", "#styles"]]) {
    const list = st.catalog[kind === "character" ? "characters" : kind + "s"];
    $(id).innerHTML = `<button class="chip" data-kind="${kind}" data-key="" disabled>Aucun</button>` +
      list.map((x) => `<button class="chip" data-kind="${kind}" data-key="${esc(x.key)}" disabled>${esc(x.label)}</button>`).join("");
  }
  document.querySelectorAll(".chip").forEach((c) => c.addEventListener("click", () => preset(c.dataset.kind, c.dataset.key || null)));
}

function enable(on) {
  ["#stop", "#original", "#resume", "#mic", "#rec", "#cmd", "#send", "#copy", "#strength"].forEach((s) => ($(s).disabled = !on));
  document.querySelectorAll(".chip").forEach((c) => (c.disabled = !on));
  $("#start").disabled = on; $("#engine").disabled = on;
}

function render(s) {
  st.session = s;
  const sc = s.scene;
  $("#prompt").textContent = sc.bypass ? "(flux original affiché)" : sc.prompt;
  $("#strength").value = sc.strength; $("#strength-val").textContent = `${sc.strength}/5`;
  $("#ai").style.opacity = sc.bypass ? 0.25 : 1;
  $("#ai-parody").hidden = !sc.parody || sc.bypass;
  $("#ai-parody").textContent = sc.parody_of ? `Parodie IA · ce n'est pas ${sc.parody_of}` : "Parodie · IA";
  document.querySelectorAll(".chip").forEach((c) => {
    const cur = { character: sc.character, decor: sc.decor, style: sc.style }[c.dataset.kind];
    c.classList.toggle("active", (cur || "") === c.dataset.key);
  });
  $("#engine-badge").textContent = s.engine_name;
  $("#cost").textContent = s.estimated_cost_usd != null ? `coût ≈ ${s.estimated_cost_usd.toFixed(3)} $` : "coût : tarif non renseigné";
  $("#log").innerHTML = s.log.slice().reverse().map((l) => `<li>${new Date(l.at * 1000).toLocaleTimeString("fr-FR")} — ${esc(l.message)}</li>`).join("");
  if (s.ended) { say(`Session terminée : ${s.end_reason}`, true); teardown(); }
}

// ------------------------------------------------------------ démarrage
$("#start").addEventListener("click", async () => {
  say("Accès à la caméra…");
  try {
    st.cam = await navigator.mediaDevices.getUserMedia({ video: { width: { ideal: 1280 }, height: { ideal: 720 }, frameRate: { ideal: 30 } }, audio: false });
    $("#cam").srcObject = st.cam;
    say("Création du flux sur le moteur…");
    const s = await api("/api/sessions", { method: "POST", body: JSON.stringify({ engine: $("#engine").value, mode: $("#mode").value }) });
    render(s);
    const tStart = Date.now();
    $("#ai").addEventListener("playing", () => say(`IA prête en ${((Date.now() - tStart) / 1000).toFixed(1)} s (mode ${s.mode_label || "—"})`), { once: true });
    say("Connexion de la caméra au moteur (WHIP)…");
    st.pubPc = await whipPublish(`/api/sessions/${s.id}/whip`, st.cam, headers());
    say("En attente de la sortie IA (premières secondes : chargement du modèle)…");
    st.viewPc = await whepPlay(`/api/sessions/${s.id}/whep`, $("#ai"), headers());
    $("#obs-url").value = location.origin + s.out_url;
    enable(true);
    const t0 = Date.now();
    st.timer = setInterval(() => {
      const sec = Math.floor((Date.now() - t0) / 1000);
      $("#timer").textContent = `${String(Math.floor(sec / 60)).padStart(2, "0")}:${String(sec % 60).padStart(2, "0")}`;
    }, 1000);
    $("#timer").classList.add("live");
    fpsMeter($("#ai"), (n) => ($("#fps").textContent = `${n} i/s`));
    st.poll = setInterval(async () => { try { render(await api(`/api/sessions/${s.id}`)); } catch {} }, 3000);
    st.recorder = makeRecorder($("#ai"), null);
    say("Prêt (mode test). Parle ou clique sur un personnage ; « Enregistrer un essai » garde une vidéo sur ton ordinateur.");
  } catch (e) { say("Échec : " + e.message, true); teardown(); }
});

$("#rec").addEventListener("click", async () => {
  if (!st.recorder) return;
  if (st.recorder.recording) {
    clearInterval(st.recTimer);
    const r = await st.recorder.stop();
    $("#rec").textContent = "⏺ Enregistrer un essai"; $("#rec").classList.remove("rec-on");
    if (r) say(`Essai enregistré : ${r.name} (${(r.size / 1e6).toFixed(1)} Mo)`);
    return;
  }
  try {
    st.recorder.start(); $("#rec").classList.add("rec-on");
    st.recTimer = setInterval(() => ($("#rec").textContent = `■ Arrêter l'enregistrement (${st.recorder.seconds} s)`), 500);
  } catch (e) { say(e.message, true); }
});

function teardown() {
  if (st.recorder && st.recorder.recording) st.recorder.stop();
  clearInterval(st.recTimer);
  clearInterval(st.timer); clearInterval(st.poll);
  try { st.pubPc && st.pubPc.close(); st.viewPc && st.viewPc.close(); } catch {}
  st.cam && st.cam.getTracks().forEach((t) => t.stop());
  stopListening(); enable(false); $("#timer").classList.remove("live");
}

$("#stop").addEventListener("click", async () => {
  if (st.session) { try { render(await api(`/api/sessions/${st.session.id}`, { method: "DELETE" })); } catch {} }
  teardown(); say("Live arrêté.");
});

// ------------------------------------------------------------ actions
async function preset(kind, key) {
  try { render(await api(`/api/sessions/${st.session.id}/preset`, { method: "POST", body: JSON.stringify({ kind, key }) })); say("Appliqué."); }
  catch (e) { say(e.message, true); }
}
async function command(text) {
  if (!text.trim() || !st.session) return;
  try {
    const r = await api(`/api/sessions/${st.session.id}/command`, { method: "POST", body: JSON.stringify({ text }) });
    render(r.session); say((r.ok ? "✓ " : "✗ ") + r.message, !r.ok);
  } catch (e) { say(e.message, true); }
}
async function bypass(on) {
  try { render(await api(`/api/sessions/${st.session.id}/bypass`, { method: "POST", body: JSON.stringify({ on }) })); } catch (e) { say(e.message, true); }
}
$("#original").addEventListener("click", () => bypass(true));
$("#resume").addEventListener("click", () => bypass(false));
$("#send").addEventListener("click", () => { command($("#cmd").value); $("#cmd").value = ""; });
$("#cmd").addEventListener("keydown", (e) => { if (e.key === "Enter") { command($("#cmd").value); $("#cmd").value = ""; } });
$("#strength").addEventListener("change", async (e) => {
  try { render(await api(`/api/sessions/${st.session.id}/strength`, { method: "POST", body: JSON.stringify({ value: +e.target.value }) })); } catch (err) { say(err.message, true); }
});
$("#copy").addEventListener("click", () => { navigator.clipboard.writeText($("#obs-url").value); say("URL copiée : colle-la dans une Source navigateur OBS."); });

// ------------------------------------------------------------ voix (Web Speech API, gratuit, Chrome/Edge)
const Rec = window.SpeechRecognition || window.webkitSpeechRecognition;
function startListening() {
  if (!Rec) return say("Reconnaissance vocale non disponible dans ce navigateur (utilise Chrome ou Edge).", true);
  st.rec = new Rec(); st.rec.lang = "fr-FR"; st.rec.continuous = true; st.rec.interimResults = false;
  st.rec.onresult = (e) => {
    const text = e.results[e.results.length - 1][0].transcript.trim();
    $("#cmd").value = text; command(text);
  };
  st.rec.onend = () => { if (st.listening) try { st.rec.start(); } catch {} };
  st.rec.start(); st.listening = true;
  $("#mic").textContent = "🎙 Écoute vocale : on"; $("#mic").classList.add("on");
}
function stopListening() {
  st.listening = false; try { st.rec && st.rec.stop(); } catch {}
  $("#mic").textContent = "🎙 Écoute vocale : off"; $("#mic").classList.remove("on");
}
$("#mic").addEventListener("click", () => (st.listening ? stopListening() : startListening()));

// ------------------------------------------------------------ GPU à la demande
function setupGpu() {
  if (!st.catalog.gpu_rental) return;
  $("#gpu-box").hidden = false;
  $("#gpu-model").innerHTML = st.catalog.models.map((m) => `<option value="${esc(m.key)}">${esc(m.label)} (≥ ${m.min_vram_gb} Go)</option>`).join("");
  const notes = () => { const m = st.catalog.models.find((x) => x.key === $("#gpu-model").value); $("#gpu-model-notes").textContent = m ? `${m.notes} Estimation : ${m.fps_estimate}.` : ""; };
  $("#gpu-model").addEventListener("change", notes); notes();
  if (!st.catalog.gpu_image_configured) { $("#gpu-warn").hidden = false; $("#gpu-warn").textContent = "LIVE_WORKER_IMAGE n'est pas défini : tu peux comparer les prix, mais pas encore louer (image Docker du worker à publier)."; }
  pollRental();
}

$("#gpu-quote").addEventListener("click", async () => {
  $("#gpu-quote").disabled = true;
  try {
    const q = await api("/api/gpu/quote", { method: "POST", body: JSON.stringify({ model_key: $("#gpu-model").value }) });
    const tb = $("#gpu-offers tbody");
    tb.innerHTML = q.offers.map((o) => `<tr><td>${esc(o.gpu)} · ${o.vram_gb} Go</td><td>${esc(o.provider)}</td><td>${esc(o.location || "—")}</td>
      <td>${o.usd_per_hour.toFixed(3)} $</td><td><b>${o.price_per_min.toFixed(4)} $</b></td>
      <td><button class="btn small" data-offer="${esc(o.key)}">Louer</button></td></tr>`).join("") || `<tr><td colspan="6" class="muted">Aucune offre sous le prix maximal.</td></tr>`;
    $("#gpu-offers").hidden = false;
    tb.querySelectorAll("button[data-offer]").forEach((b) => b.addEventListener("click", () => rent(b.dataset.offer)));
    if (q.errors.length) say("Fournisseur indisponible : " + q.errors.map((e) => e.provider + " (" + e.error + ")").join(", "), true);
  } catch (e) { say(e.message, true); }
  $("#gpu-quote").disabled = false;
});

async function rent(offerKey) {
  if (!confirm("Louer cette machine ? La facturation commence maintenant (libération automatique en cas d'inactivité).")) return;
  try { await api("/api/gpu/rent", { method: "POST", body: JSON.stringify({ offer_key: offerKey, model_key: $("#gpu-model").value }) }); say("Location lancée : démarrage de la machine…"); pollRental(); }
  catch (e) { say(e.message, true); }
}

const RSTATE = { starting: "Démarrage", booting: "Machine en démarrage", warming: "Chargement du modèle", ready: "Prêt", released: "Libéré", failed: "Échec" };
async function pollRental() {
  clearTimeout(st.rentalTimer);
  try {
    const { rental } = await api("/api/gpu/rental");
    const box = $("#gpu-rental");
    if (!rental) { box.hidden = true; return; }
    box.hidden = false;
    const active = !["released", "failed"].includes(rental.state);
    box.innerHTML = `<span class="state ${rental.state === "ready" ? "ready" : ""}">${RSTATE[rental.state] || rental.state}</span>
      <span>${esc(rental.gpu_name)} · ${esc(rental.provider)}</span>
      <span class="muted">${rental.minutes} min · ${rental.cost_usd.toFixed(3)} $ (${rental.usd_per_hour.toFixed(3)} $/h)</span>
      <span class="muted small">${esc(rental.release_reason || rental.detail || "")}</span>
      ${active ? `<button class="btn small danger" id="gpu-release">Libérer le GPU</button>` : ""}`;
    if (active) {
      $("#gpu-release").addEventListener("click", async () => { try { await api("/api/gpu/rental", { method: "DELETE" }); say("GPU libéré."); pollRental(); } catch (e) { say(e.message, true); } });
      if (rental.state === "ready") $("#engine").value = "cloud";
      st.rentalTimer = setTimeout(pollRental, rental.state === "ready" ? 15000 : 4000);
    }
  } catch {}
}

loadCatalog();
