"use strict";
// AI Studio — interface (JavaScript sans dépendance).
const $ = (sel) => document.querySelector(sel);
const state = { token: null, account: null, projects: [], project: null, asset: null, quote: null, jobTimer: null };

function loadToken() { try { return localStorage.getItem("studio_token"); } catch { return null; } }
function saveToken(t) { try { t ? localStorage.setItem("studio_token", t) : localStorage.removeItem("studio_token"); } catch {} }

async function api(path, opts = {}) {
  const headers = opts.body instanceof FormData ? {} : { "Content-Type": "application/json" };
  if (state.token) headers.Authorization = "Bearer " + state.token;
  const res = await fetch(path, { ...opts, headers: { ...headers, ...(opts.headers || {}) } });
  if (res.status === 401 && path !== "/api/auth/login") { logout(); throw new Error(t("expired")); }
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(typeof data.detail === "string" ? data.detail : "Erreur " + res.status);
  return data;
}

const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const fmtCredits = (c) => t("n_credits", { n: c });
const fmtUsd = (micro) => (micro / 1e6).toLocaleString("fr-FR", { style: "currency", currency: "USD", minimumFractionDigits: 2, maximumFractionDigits: 4 });
const fmtDate = (iso) => new Date(iso).toLocaleString("fr-FR", { dateStyle: "short", timeStyle: "short" });
const STATUS = new Proxy({}, { get: (_, k) => (["queued", "running", "succeeded", "failed", "canceled"].includes(k) ? t("st_" + k) : undefined) });

// ---------------------------------------------------------------- authentification
function showAuth() { $("#auth").classList.remove("hidden"); $("#app").classList.add("hidden"); }
function showApp() { $("#auth").classList.add("hidden"); $("#app").classList.remove("hidden"); }
function logout() { state.token = null; saveToken(null); showAuth(); }

$("#auth-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const mode = e.submitter?.dataset.mode || "login";
  const f = new FormData(e.target);
  $("#auth-error").textContent = "";
  try {
    const r = await api(`/api/auth/${mode}`, { method: "POST", body: JSON.stringify({ email: f.get("email"), password: f.get("password"), invite: f.get("invite") || "" }) });
    state.token = r.token; saveToken(r.token); await boot();
  } catch (err) { $("#auth-error").textContent = err.message; }
});
$("#logout").addEventListener("click", logout);

async function refreshAccount() {
  state.account = await api("/api/me");
  const held = state.account.credits_held ? ` · ${t("held", { n: state.account.credits_held })}` : "";
  $("#balance").textContent = `${fmtCredits(state.account.credits_available)}${held}`;
  $("#dev-topup").classList.toggle("hidden", !state.account.dev_mode);
}
$("#dev-topup").addEventListener("click", async () => {
  await api("/api/dev/credits", { method: "POST", body: JSON.stringify({ credits: 500 }) });
  refreshAccount();
});

// ---------------------------------------------------------------- onglets
document.querySelectorAll(".tab").forEach((b) => b.addEventListener("click", () => {
  document.querySelectorAll(".tab").forEach((x) => x.classList.toggle("active", x === b));
  document.querySelectorAll(".tab-panel").forEach((p) => p.classList.toggle("hidden", p.id !== "tab-" + b.dataset.tab));
  if (b.dataset.tab === "jobs") renderJobs();
  if (b.dataset.tab === "ledger") renderLedger();
  if (b.dataset.tab === "engines") renderEngines();
}));

// ---------------------------------------------------------------- projets et versions
async function loadProjects(selectRoot, selectAsset) {
  state.projects = await api("/api/projects");
  const ul = $("#projects");
  ul.innerHTML = state.projects.map((p) => `<li data-root="${esc(p.root_id)}"><span>${esc(p.title)}</span><span class="count">${p.versions.length} v.</span></li>`).join("")
    || `<li class="muted small">${t("no_project")}</li>`;
  ul.querySelectorAll("li[data-root]").forEach((li) => li.addEventListener("click", () => selectProject(li.dataset.root)));
  if (selectRoot) selectProject(selectRoot, selectAsset);
}

function selectProject(rootId, assetId) {
  state.project = state.projects.find((p) => p.root_id === rootId);
  if (!state.project) return;
  document.querySelectorAll("#projects li").forEach((li) => li.classList.toggle("active", li.dataset.root === rootId));
  $("#empty").classList.add("hidden"); $("#editor").classList.remove("hidden");
  const v = state.project.versions;
  selectAsset(assetId ? v.find((a) => a.id === assetId) : v[v.length - 1]);
}

function selectAsset(asset) {
  state.asset = asset;
  const player = $("#player");
  player.src = asset.stream_url;
  $("#download").href = asset.download_url;
  $("#asset-meta").textContent = `${asset.width}×${asset.height} · ${asset.duration_s.toFixed(1)} s · ${asset.label}`;
  $("#start").value = 0; $("#end").value = asset.duration_s.toFixed(1); $("#end").max = asset.duration_s;
  updateRange();
  const versions = state.project.versions;
  $("#versions").innerHTML = versions.map((a, i) =>
    `<li data-id="${esc(a.id)}" class="${a.id === asset.id ? "active" : ""}">${i === 0 ? t("original") : esc(a.label)} <span class="muted small">· ${fmtDate(a.created_at)}</span></li>`).join("");
  $("#versions").querySelectorAll("li").forEach((li) => li.addEventListener("click", () => selectAsset(versions.find((a) => a.id === li.dataset.id))));
  const parent = asset.parent_id && versions.find((a) => a.id === asset.parent_id);
  $("#compare").classList.toggle("hidden", !parent);
  $("#compare").dataset.parent = parent ? parent.stream_url : "";
  $("#compare").dataset.self = asset.stream_url;
  document.querySelectorAll("#compare button").forEach((b) => b.classList.toggle("active", b.dataset.view === "after"));
  $("#quote").classList.add("hidden");
}

document.querySelectorAll("#compare button").forEach((b) => b.addEventListener("click", () => {
  const player = $("#player"); const t = player.currentTime;
  player.src = b.dataset.view === "before" ? $("#compare").dataset.parent : $("#compare").dataset.self;
  player.addEventListener("loadedmetadata", () => { player.currentTime = t; }, { once: true });
  document.querySelectorAll("#compare button").forEach((x) => x.classList.toggle("active", x === b));
}));

// ---------------------------------------------------------------- import
$("#file").addEventListener("change", async (e) => {
  const file = e.target.files[0]; if (!file) return;
  const fd = new FormData(); fd.append("file", file);
  $("#upload-status").textContent = t("importing", { f: file.name });
  try {
    const asset = await api("/api/assets", { method: "POST", body: fd });
    $("#upload-status").textContent = t("imported");
    await loadProjects(asset.root_id, asset.id);
  } catch (err) { $("#upload-status").innerHTML = `<span class="error">${esc(err.message)}</span>`; }
  e.target.value = "";
});

// ---------------------------------------------------------------- plage
function updateRange() {
  const d = state.asset?.duration_s || 1;
  const s = Math.max(0, Math.min(+$("#start").value || 0, d));
  const e = Math.max(s, Math.min(+$("#end").value || d, d));
  $("#range-fill").style.left = `${(s / d) * 100}%`;
  $("#range-fill").style.width = `${((e - s) / d) * 100}%`;
}
["#start", "#end"].forEach((id) => $(id).addEventListener("input", updateRange));
$("#mark-in").addEventListener("click", () => { $("#start").value = $("#player").currentTime.toFixed(1); updateRange(); });
$("#mark-out").addEventListener("click", () => { $("#end").value = $("#player").currentTime.toFixed(1); updateRange(); });
$("#whole").addEventListener("click", () => { $("#start").value = 0; $("#end").value = state.asset.duration_s.toFixed(1); updateRange(); });
document.querySelectorAll(".chip").forEach((c) => c.addEventListener("click", () => { $("#prompt").value = c.dataset.prompt || c.textContent; $("#prompt").focus(); }));

// ---------------------------------------------------------------- devis
$("#get-quote").addEventListener("click", async () => {
  const btn = $("#get-quote"); $("#quote-error").textContent = ""; btn.disabled = true;
  try {
    state.quote = await api("/api/quotes", { method: "POST", body: JSON.stringify({
      asset_id: state.asset.id, prompt: $("#prompt").value, start_s: +$("#start").value, end_s: +$("#end").value }) });
    renderQuote();
  } catch (err) { $("#quote-error").textContent = err.message; }
  btn.disabled = false;
});

function renderQuote() {
  const q = state.quote; const el = $("#quote");
  const [s, e] = q.range;
  el.innerHTML = `<div class="range-head"><strong>Devis</strong><span class="muted small">Plage ${s.toFixed(1)}–${e.toFixed(1)} s · valable jusqu'à ${fmtDate(q.expires_at)}</span></div>
    <div class="options">${q.options.map(optionCard).join("")}</div>`;
  el.classList.remove("hidden");
  el.querySelectorAll("button[data-option]").forEach((b) => b.addEventListener("click", () => accept(b.dataset.option, b)));
}

function optionCard(o) {
  if (!o.available) {
    return `<div class="option unavailable"><strong>${esc(o.label)}</strong><span class="muted small">${esc(o.reason)}</span>${excludedList(o.excluded)}</div>`;
  }
  const steps = o.steps.map((st) => `<li>${esc(st.label)} — ${esc(st.engine_name)}${st.prompt ? ` <span class="muted">« ${esc(st.prompt)} »</span>` : ""} · ${st.duration_s.toFixed(1)} s · ${fmtCredits(st.price_credits)}</li>`).join("");
  const enough = state.account.credits_available >= o.total_price_credits;
  return `<div class="option">
    <div class="row" style="margin:0;justify-content:space-between"><strong>${esc(o.label)}</strong>
      ${o.simulated ? `<span class="badge sim">Simulation</span>` : ""}${o.cache_hit ? `<span class="badge ok">Déjà calculé</span>` : ""}</div>
    <div class="price">${fmtCredits(o.total_price_credits)} <span class="muted small">≈ ${fmtUsd(o.total_price_credits * 10000)}</span></div>
    <ul>${steps}</ul>
    <span class="muted small">Durée estimée : ~${Math.ceil(o.eta_s)} s · débit au coût réel, plafonné à ce prix</span>
    ${excludedList(o.excluded)}
    <button class="btn primary" data-option="${esc(o.id)}" ${enough ? "" : "disabled"}>${enough ? t("accept") : t("insufficient")}</button>
  </div>`;
}

function excludedList(ex) {
  if (!ex || !ex.length) return "";
  const uniq = [...new Map(ex.map((x) => [x.engine, x])).values()];
  return `<details><summary>${uniq.length} moteur(s) non retenu(s)</summary><ul>${uniq.map((x) => `<li>${esc(x.engine)} : ${esc(x.reason)}</li>`).join("")}</ul></details>`;
}

async function accept(optionId, btn) {
  btn.disabled = true;
  try {
    const job = await api(`/api/quotes/${state.quote.id}/accept`, { method: "POST", body: JSON.stringify({ option_id: optionId }) });
    $("#quote").classList.add("hidden");
    refreshAccount(); trackJob(job.id);
  } catch (err) { btn.disabled = false; $("#quote-error").textContent = err.message; }
}

// ---------------------------------------------------------------- suivi de tâche
function trackJob(jobId) {
  clearInterval(state.jobTimer);
  const el = $("#job"); el.classList.remove("hidden");
  const tick = async () => {
    const j = await api(`/api/jobs/${jobId}`);
    const done = j.status === "succeeded" || j.status === "failed";
    const badge = j.status === "succeeded" ? "ok" : j.status === "failed" ? "err" : "";
    el.innerHTML = `<div class="status"><strong>${t("processing")}</strong><span class="badge ${badge}">${STATUS[j.status] || j.status}</span>${j.simulated ? `<span class="badge sim">Simulation</span>` : ""}</div>
      ${done ? "" : `<div class="progress"><div></div></div>`}
      <ul class="events">${(j.events || []).map((e) => `<li class="${e.level === "error" ? "error" : ""}">${fmtDate(e.at)} — ${esc(e.message)}</li>`).join("")}</ul>
      ${done ? `<p class="small muted">Réservé ${fmtCredits(j.reserved_credits)} · débité ${fmtCredits(j.charged_credits)}</p>` : ""}`;
    if (done) {
      clearInterval(state.jobTimer); refreshAccount();
      if (j.status === "succeeded") await loadProjects(state.project.root_id, j.output_asset_id);
    }
  };
  tick(); state.jobTimer = setInterval(() => tick().catch(() => {}), 1500);
}

// ---------------------------------------------------------------- tableaux
async function renderJobs() {
  const jobs = await api("/api/jobs");
  $("#jobs-body").innerHTML = jobs.map((j) => `<tr><td>${fmtDate(j.created_at)}</td><td>${STATUS[j.status] || j.status}${j.simulated ? ' <span class="badge sim">sim.</span>' : ""}</td>
    <td>${j.steps.map((s) => esc(s.label)).join(" → ")}</td><td>${j.reserved_credits}</td><td>${j.charged_credits}</td>
    <td>${fmtUsd(j.actual_cost_micro)}</td><td class="small">${esc(j.error || "")}</td></tr>`).join("") || `<tr><td colspan="7" class="muted">${t("no_jobs")}</td></tr>`;
}
async function renderLedger() {
  const rows = await api("/api/ledger");
  const KIND = { grant: "Offert", topup: "Achat", reserve: "Réservation", capture: "Règlement", release: "Remboursement" };
  $("#ledger-body").innerHTML = rows.map((r) => `<tr><td>${fmtDate(r.at)}</td><td>${KIND[r.kind] || r.kind}</td>
    <td style="color:${r.amount_credits < 0 ? "var(--err)" : "var(--ok)"}">${r.amount_credits > 0 ? "+" : ""}${r.amount_credits}</td><td class="small">${esc(r.memo)}</td></tr>`).join("");
}
async function renderEngines() {
  const engines = await api("/api/engines");
  $("#engines").innerHTML = engines.map((e) => `<div class="engine">
    <div class="row" style="margin:0;justify-content:space-between"><strong>${esc(e.name)}</strong>
      <span class="badge ${e.available ? "ok" : "err"}">${e.available ? "Disponible" : "Indisponible"}</span></div>
    <p class="muted small">${esc(e.capabilities.join(", "))}</p>
    <p class="small">${esc(e.pricing.usd_per_unit)} USD / ${e.pricing.unit === "second" ? "seconde" : "tâche"} · marge ×${esc(e.pricing.markup)} · max ${e.max_duration_s} s
      ${e.simulated ? '<span class="badge sim">Simulation</span>' : ""}</p>
    <p class="small muted">Tarif vérifié le : ${esc(e.pricing.verified_on || "non vérifié")} · ${esc(e.pricing.source || "")}</p>
    ${e.available ? "" : `<p class="small error">${esc(e.unavailable_reason)}</p>`}
  </div>`).join("");
}

// ---------------------------------------------------------------- démarrage
async function boot() {
  state.token = state.token || loadToken();
  if (!state.token) return showAuth();
  try { await refreshAccount(); } catch { return showAuth(); }
  showApp(); await loadProjects();
  if (state.projects.length) selectProject(state.projects[0].root_id);
}
boot();

// Langue de l'interface : petit sélecteur discret (écran de connexion et barre du haut).
document.querySelectorAll(".lang-slot").forEach((el) => { el.innerHTML = langPicker(); });
document.querySelectorAll(".lang-pick").forEach((sel) => sel.addEventListener("change", () => {
  applyUI(sel.value);
  if (state.account) refreshAccount().catch(() => {});
}));
applyUI();

// Achat de crédits (Stripe Checkout) — boutons visibles seulement quand le paiement est activé.
async function loadPacks() {
  try {
    const p = await api("/api/billing/packs");
    const box = $("#packs");
    if (!p.enabled) { box.innerHTML = ""; $("#buy-msg").textContent = t("buy_soon"); return; }
    box.innerHTML = p.packs.map((k) => `<button class="btn primary" data-pack="${esc(k.id)}">${esc(t("n_credits", { n: k.credits }))} — ${(k.amount_cents / 100).toFixed(2)} ${esc(k.currency.toUpperCase())}</button>`).join("");
    box.querySelectorAll("button").forEach((b) => b.addEventListener("click", async () => {
      b.disabled = true;
      try { const r = await api("/api/billing/checkout", { method: "POST", body: JSON.stringify({ pack: b.dataset.pack }) }); location.href = r.url; }
      catch (e) { $("#buy-msg").textContent = e.message; b.disabled = false; }
    }));
  } catch {}
}
(() => {
  const q = new URLSearchParams(location.search).get("achat");
  if (q) { setTimeout(() => { const m = $("#buy-msg"); if (m) m.textContent = q === "ok" ? t("bought") : t("buy_cancel"); }, 300); history.replaceState(null, "", location.pathname); }
})();
document.querySelectorAll('[data-tab="ledger"]').forEach((b) => b.addEventListener("click", loadPacks));
