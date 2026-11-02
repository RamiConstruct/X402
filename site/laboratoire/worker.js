// « Le Laboratoire » — page publique d'avancement, servie par un Worker Cloudflare sur labotory.site.
// Les données viennent du KV (binding LABO, clé "avancement") : mettre à jour la page = écrire
// un nouveau avancement.json dans le KV, sans redéployer. Page indépendante du serveur Oracle.
// Ne jamais publier de secret, d'IP ni de donnée personnelle : la page est publique.

const ETATS = { en_cours: ["En cours", "run"], termine: ["Terminé", "ok"], en_revue: ["En revue", "rev"], en_attente: ["En attente", "wait"] };
const INFRA = { ok: ["Opérationnel", "ok"], attente: ["À faire", "wait"], panne: ["Panne", "err"] };
const CSS = `:root{--bg:#f6f5f1;--panel:#fff;--text:#18181b;--muted:#5f6068;--line:#e4e2db;--accent:#0f766e;--ok:#15803d;--run:#0f766e;--rev:#7c3aed;--wait:#b45309;--err:#b91c1c;color-scheme:light dark}
@media (prefers-color-scheme:dark){:root{--bg:#0e1013;--panel:#161a1f;--text:#eceef1;--muted:#9aa1ad;--line:#262b33;--accent:#2dd4bf;--ok:#4ade80;--run:#2dd4bf;--rev:#a78bfa;--wait:#fbbf24;--err:#f87171}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font:16px/1.55 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
.wrap{max-width:1080px;margin:0 auto;padding:32px 16px 64px}header{display:flex;justify-content:space-between;align-items:flex-end;gap:16px;flex-wrap:wrap;margin-bottom:28px}
h1{font-size:clamp(30px,5vw,44px);margin:0;letter-spacing:-.02em}h1 span{color:var(--accent)}.intent{color:var(--muted);margin:6px 0 0;max-width:60ch}.upd{font-size:14px;color:var(--muted);white-space:nowrap}
h2{font-size:13px;text-transform:uppercase;letter-spacing:.08em;color:var(--muted);margin:36px 0 12px}.card{background:var(--panel);border:1px solid var(--line);border-radius:14px;padding:20px}
.now{display:grid;grid-template-columns:1.2fr 1fr;gap:16px}@media(max-width:760px){.now{grid-template-columns:1fr}}
.focus{font-size:20px;font-weight:650;margin:0 0 10px}.label{font-size:12px;text-transform:uppercase;letter-spacing:.07em;color:var(--muted);margin:14px 0 6px}
ul{margin:0;padding-left:20px}li{margin:3px 0}.you li::marker{content:"→  ";color:var(--wait)}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(310px,1fr));gap:14px}.proj h3{margin:0;font-size:19px}.proj p{color:var(--muted);margin:6px 0 12px;font-size:15px}
.top{display:flex;justify-content:space-between;align-items:center;gap:10px}.badge{font-size:12px;font-weight:650;padding:3px 10px;border-radius:999px;white-space:nowrap;border:1px solid currentColor}
.ok{color:var(--ok)}.run{color:var(--run)}.rev{color:var(--rev)}.wait{color:var(--wait)}.err{color:var(--err)}
.bar{height:8px;background:var(--line);border-radius:4px;overflow:hidden;margin:4px 0 2px}.bar>div{height:100%;background:var(--accent);border-radius:4px}
.pct{font-size:13px;color:var(--muted)}details{margin-top:10px;font-size:14px}summary{cursor:pointer;color:var(--accent);font-weight:600}.small{font-size:13px;color:var(--muted)}
table{width:100%;border-collapse:collapse;font-size:15px}td,th{text-align:left;padding:10px 12px;border-bottom:1px solid var(--line);vertical-align:top}th{font-size:12px;text-transform:uppercase;letter-spacing:.06em;color:var(--muted)}
.tl{list-style:none;padding:0;margin:0;border-left:2px solid var(--line)}.tl li{position:relative;padding:0 0 14px 18px}.tl li::before{content:"";position:absolute;left:-6px;top:7px;width:10px;height:10px;border-radius:50%;background:var(--accent)}
.tl time{font-size:13px;color:var(--muted);display:block}footer{margin-top:40px;font-size:13px;color:var(--muted)}footer a{color:var(--accent)}
@media(max-width:600px){td,th{padding:8px 6px}.table-wrap{overflow-x:auto}}`;
const ICON = "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'%3E%3Ccircle cx='16' cy='16' r='14' fill='%230f766e'/%3E%3Cpath d='M12 8h8M14 8v7l-5 9h14l-5-9V8' stroke='white' stroke-width='2' fill='none'/%3E%3C/svg%3E";

const e = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const lst = (items, cls = "") => items && items.length ? `<ul class="${cls}">${items.map((i) => `<li>${e(i)}</li>`).join("")}</ul>` : `<p class="small">—</p>`;

export function render(d) {
  const n = d.maintenant || {};
  const projets = (d.projets || []).map((p) => {
    const [lab, cls] = ETATS[p.etat] || [p.etat, "wait"];
    const pct = Number.isFinite(p.avancement) ? Math.max(0, Math.min(100, Math.round(p.avancement))) : null;
    const bar = pct === null ? "" : `<div class="bar" role="progressbar" aria-valuenow="${pct}" aria-valuemin="0" aria-valuemax="100"><div style="width:${pct}%"></div></div><span class="pct">${pct} % (estimation)</span>`;
    const detail = (p.fait?.length || p.pas_encore_teste?.length)
      ? `<details><summary>Détail</summary><div class="label">Fait</div>${lst(p.fait)}${p.pas_encore_teste?.length ? `<div class="label">Pas encore testé en conditions réelles</div>${lst(p.pas_encore_teste)}` : ""}<p class="small">Vérification : ${e(p.tests || "—")}</p></details>` : "";
    return `<article class="card proj"><div class="top"><h3>${e(p.nom)}</h3><span class="badge ${cls}">${e(lab)}</span></div><p>${e(p.resume)}</p>${bar}${detail}</article>`;
  }).join("");
  const infra = (d.infrastructure || []).map((i) => { const [lab, cls] = INFRA[i.etat] || [i.etat, "wait"];
    return `<tr><td>${e(i.element)}</td><td><span class="badge ${cls}">${e(lab)}</span></td><td class="small">${e(i.note)}</td></tr>`; }).join("");
  const journal = (d.journal || []).map((j) => `<li><time datetime="${e(j.date)}">${e(j.date)}</time>${e(j.texte)}</li>`).join("");
  return `<!doctype html><html lang="fr"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Le Laboratoire</title><meta name="description" content="Avancement des projets du laboratoire, mis à jour à chaque étape."><link rel="icon" href="${ICON}"><style>${CSS}</style></head>
<body><style> .labfab{position:fixed;right:max(16px,env(safe-area-inset-right));bottom:max(16px,env(safe-area-inset-bottom));z-index:1000;font:15px/1.3 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif} .labfab summary{list-style:none;width:52px;height:52px;border-radius:50%;background:#0f766e;color:#fff;display:grid;place-items:center;cursor:pointer;box-shadow:0 6px 20px rgba(0,0,0,.35);font-size:22px;user-select:none} .labfab summary::-webkit-details-marker{display:none} .labfab summary:focus-visible{outline:3px solid #5eead4;outline-offset:3px} .labfab[open] summary{background:#134e4a} .labfab nav{position:absolute;right:0;bottom:64px;min-width:230px;background:#101317;border:1px solid #2a313b;border-radius:14px;padding:8px;box-shadow:0 12px 32px rgba(0,0,0,.45)} .labfab .t{display:block;padding:6px 10px 8px;color:#5eead4;font-weight:700;font-size:13px;letter-spacing:.04em} .labfab a{display:block;color:#d6dbe3;text-decoration:none;padding:10px 12px;border-radius:9px} .labfab a:hover,.labfab a:focus-visible{background:#1c2229;color:#fff;outline:none} .labfab a[aria-current="page"]{background:#1f3a37;color:#fff;font-weight:600} .labfab a small{display:block;color:#8b94a3;font-size:12px;margin-top:2px} </style> <details class="labfab"> <summary aria-label="Menu du laboratoire" title="Menu">☰</summary> <nav aria-label="Navigation du laboratoire"> <span class="t">◆ LABORATOIRE</span> <a href="https://labotory.site/" data-k="labo" aria-current="page">Avancement<small>où en est le projet</small></a> <a href="https://live.labotory.site/" data-k="live">AI Live<small>console sur ordinateur</small></a> <a href="https://live.labotory.site/mobile.html" data-k="mobile">AI Live téléphone<small>caméra du téléphone</small></a> <a href="https://studio.labotory.site/" data-k="studio">AI Studio<small>modifier une vidéo</small></a> </nav> </details><div class="wrap"><header><div><h1>Le <span>Laboratoire</span></h1><p class="intent">${e(d.intention)}</p></div><div class="upd">Mis à jour le <time datetime="${e(d.mis_a_jour)}">${e(d.mis_a_jour)}</time></div></header>
<h2>Où on en est</h2><section class="now"><div class="card"><p class="focus">${e(n.focus)}</p><div class="label">Dernière étape franchie</div><p style="margin:0">${e(n.dernier_fait)}</p>
<div class="label">Prochaines étapes</div>${lst(n.prochaines_etapes_claude)}</div><div class="card"><div class="label" style="margin-top:0">En attente de toi</div>${lst(n.en_attente_de_toi, "you")}</div></section>
<h2>Projets</h2><section class="grid">${projets}</section>
<h2>Infrastructure</h2><div class="card table-wrap"><table><thead><tr><th>Élément</th><th>État</th><th>Note</th></tr></thead><tbody>${infra}</tbody></table></div>
<h2>Journal</h2><div class="card"><ul class="tl">${journal}</ul></div>
<footer>Page tenue à jour à chaque étape du projet. Les pourcentages sont des estimations. Aucun secret, identifiant ni donnée personnelle n'est publié ici. · <a href="/avancement.json">données (JSON)</a></footer></div></body></html>`;
}

const SEC = { "x-content-type-options": "nosniff", "referrer-policy": "strict-origin-when-cross-origin",
  "content-security-policy": "default-src 'none'; style-src 'unsafe-inline'; img-src data:; base-uri 'none'; form-action 'none'; frame-ancestors 'none'" };
const FALLBACK = { intention: "", mis_a_jour: "—", maintenant: { focus: "Données d'avancement indisponibles pour le moment." } };

// Mise à jour : PUT /avancement.json avec « Authorization: Bearer <LABO_UPDATE_TOKEN> » (secret du Worker).
async function update(req, env) {
  const auth = req.headers.get("authorization") || "";
  const tok = env.LABO_UPDATE_TOKEN || "";
  const enc = new TextEncoder();
  const a = enc.encode(auth), b = enc.encode(`Bearer ${tok}`);
  let same = tok.length >= 24 && a.length === b.length;
  for (let i = 0; same && i < a.length; i++) same = a[i] === b[i];
  if (!same) return new Response("Non autorisé", { status: 401, headers: SEC });
  const body = await req.text();
  if (body.length > 100_000) return new Response("Trop volumineux", { status: 413, headers: SEC });
  let d;
  try { d = JSON.parse(body); } catch { return new Response("JSON invalide", { status: 400, headers: SEC }); }
  if (!d || typeof d !== "object" || !d.maintenant || !Array.isArray(d.projets) || !Array.isArray(d.journal)) {
    return new Response("Structure invalide (maintenant, projets, journal requis)", { status: 400, headers: SEC });
  }
  await env.LABO.put("avancement", JSON.stringify(d));
  return new Response(JSON.stringify({ ok: true, mis_a_jour: d.mis_a_jour }), { headers: { ...SEC, "content-type": "application/json" } });
}

export default {
  async fetch(req, env) {
    const path = new URL(req.url).pathname;
    if (req.method === "PUT" && path === "/avancement.json") return update(req, env);
    if (req.method !== "GET" && req.method !== "HEAD") return new Response("Méthode non autorisée", { status: 405, headers: SEC });
    const data = (env.LABO && await env.LABO.get("avancement", "json")) || FALLBACK;
    if (path === "/avancement.json") return new Response(JSON.stringify(data, null, 2), { headers: { ...SEC, "content-type": "application/json; charset=utf-8", "cache-control": "public, max-age=30" } });
    if (path === "/" || path === "/index.html") return new Response(render(data), { headers: { ...SEC, "content-type": "text/html; charset=utf-8", "cache-control": "public, max-age=30" } });
    return new Response("Introuvable", { status: 404, headers: SEC });
  },
};
