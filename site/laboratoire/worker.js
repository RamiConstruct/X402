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

// labnav:start (généré par site/nav/apply_nav.py depuis site/nav/nav.html — ne pas modifier à la main)
const NAV_HTML = "<style>.labnav{position:sticky;top:0;z-index:1000;background:rgba(13,17,23,.94);-webkit-backdrop-filter:blur(10px);backdrop-filter:blur(10px);border-bottom:1px solid #232a33;color:#e6e9ee;font:15px/1.3 system-ui,-apple-system,\"Segoe UI\",Roboto,sans-serif}.labnav .in{max-width:1180px;margin:0 auto;padding:0 16px;min-height:56px;display:flex;align-items:center;justify-content:space-between;gap:12px}.labnav .b{color:#fff;font-weight:800;text-decoration:none;display:flex;align-items:center;gap:8px;white-space:nowrap}.labnav .b i{color:#2dd4bf;font-style:normal}.labnav input{position:absolute;width:1px;height:1px;opacity:0;margin:0;pointer-events:none}.labnav label{display:none;margin:0;cursor:pointer;padding:8px 12px;border:1px solid #2f3742;border-radius:10px;color:#e6e9ee;font-size:15px;user-select:none}.labnav input:focus-visible+label{outline:3px solid #5eead4;outline-offset:2px}.labnav input:checked+label{background:#1c2229}.labnav ul{list-style:none;margin:0;padding:0;display:flex;align-items:center;gap:2px}.labnav li{margin:0}.labnav a.l{display:block;color:#c3cad4;text-decoration:none;padding:8px 12px;border-radius:9px}.labnav a.l:hover,.labnav a.l:focus-visible{background:#1c2229;color:#fff;outline:none}.labnav a.l[aria-current=\"page\"]{background:#1f3a37;color:#fff;font-weight:600}.labnav a.cta{background:#0f766e;color:#fff;font-weight:700;margin-left:6px}.labnav a.cta:hover,.labnav a.cta:focus-visible{background:#115e59}@media (max-width:860px){.labnav label{display:block}.labnav ul{display:none;position:absolute;left:0;right:0;top:100%;flex-direction:column;align-items:stretch;gap:2px;background:#0d1117;border-bottom:1px solid #232a33;padding:8px 12px 14px;box-shadow:0 14px 30px rgba(0,0,0,.4)}.labnav input:checked~ul{display:flex}.labnav a.l{padding:13px 12px}.labnav a.cta{margin:6px 0 0;text-align:center}}</style><nav class=\"labnav\" aria-label=\"Menu du site\"><div class=\"in\"><a class=\"b\" href=\"https://labotory.site/\"><i>◆</i> Le Laboratoire</a><input type=\"checkbox\" id=\"labnav-t\" aria-label=\"Ouvrir ou fermer le menu\"><label for=\"labnav-t\" aria-hidden=\"true\">☰ Menu</label><ul><li><a class=\"l\" data-k=\"accueil\" href=\"https://labotory.site/\">Accueil</a></li><li><a class=\"l\" data-k=\"live\" href=\"https://live.labotory.site/\">AI Live</a></li><li><a class=\"l\" data-k=\"mobile\" href=\"https://live.labotory.site/mobile.html\">AI Live téléphone</a></li><li><a class=\"l\" data-k=\"studio\" href=\"https://studio.labotory.site/\">AI Studio</a></li><li><a class=\"l\" data-k=\"suivi\" href=\"https://labotory.site/suivi\">Suivi</a></li><li><a class=\"l cta\" data-k=\"attente\" href=\"https://labotory.site/#attente\">Liste d'attente</a></li></ul></div></nav>";
// labnav:end
const nav = (k) => NAV_HTML.replace(`data-k="${k}" `, `data-k="${k}" aria-current="page" `);

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
<title>Suivi du projet · Le Laboratoire</title><meta name="robots" content="noindex"><meta name="description" content="Suivi interne de l'avancement des projets."><link rel="icon" href="${ICON}"><style>${CSS}</style></head>
<body>${nav("suivi")}<div class="wrap"><header><div><h1>Suivi du <span>projet</span></h1><p class="intent">${e(d.intention)}</p></div><div class="upd">Mis à jour le <time datetime="${e(d.mis_a_jour)}">${e(d.mis_a_jour)}</time></div></header>
<h2>Où on en est</h2><section class="now"><div class="card"><p class="focus">${e(n.focus)}</p><div class="label">Dernière étape franchie</div><p style="margin:0">${e(n.dernier_fait)}</p>
<div class="label">Prochaines étapes</div>${lst(n.prochaines_etapes_claude)}</div><div class="card"><div class="label" style="margin-top:0">En attente de toi</div>${lst(n.en_attente_de_toi, "you")}</div></section>
<h2>Projets</h2><section class="grid">${projets}</section>
<h2>Infrastructure</h2><div class="card table-wrap"><table><thead><tr><th>Élément</th><th>État</th><th>Note</th></tr></thead><tbody>${infra}</tbody></table></div>
<h2>Journal</h2><div class="card"><ul class="tl">${journal}</ul></div>
<footer>Page tenue à jour à chaque étape du projet. Les pourcentages sont des estimations. Aucun secret, identifiant ni donnée personnelle n'est publié ici. · <a href="/avancement.json">données (JSON)</a></footer></div></body></html>`;
}

// ─── Page d'accueil commerciale ───────────────────────────────────────────────
const LCSS = `:root{--bg:#f7f6f2;--panel:#fff;--text:#16171a;--muted:#5d6068;--line:#e3e1da;--accent:#0f766e;--accent2:#7c3aed;--soft:#e6f4f1;color-scheme:light dark}
@media (prefers-color-scheme:dark){:root{--bg:#0c0e11;--panel:#14181d;--text:#eceef1;--muted:#9aa1ad;--line:#242a32;--accent:#2dd4bf;--accent2:#a78bfa;--soft:#10231f}}
*{box-sizing:border-box}html{scroll-behavior:smooth}body{margin:0;background:var(--bg);color:var(--text);font:17px/1.6 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
a{color:var(--accent)}.w{max-width:1120px;margin:0 auto;padding:0 16px}section{padding:72px 0}h2{font-size:clamp(26px,4vw,38px);line-height:1.15;letter-spacing:-.02em;margin:0 0 12px}
.lead{color:var(--muted);font-size:clamp(17px,2.2vw,20px);max-width:62ch;margin:0 0 28px}.eyebrow{font-size:13px;font-weight:700;letter-spacing:.09em;text-transform:uppercase;color:var(--accent);margin:0 0 10px}
.hero{background:radial-gradient(1200px 500px at 85% -10%,rgba(45,212,191,.22),transparent 60%),radial-gradient(900px 500px at -10% 10%,rgba(124,58,237,.16),transparent 60%);padding:64px 0 72px}
.hero .w{display:grid;grid-template-columns:1.1fr .9fr;gap:48px;align-items:center}@media(max-width:880px){.hero .w{grid-template-columns:1fr;gap:36px}}
h1{font-size:clamp(36px,6.4vw,64px);line-height:1.04;letter-spacing:-.035em;margin:0 0 18px}h1 em{font-style:normal;color:var(--accent)}
.beta{display:inline-block;font-size:13px;font-weight:700;padding:5px 12px;border-radius:999px;background:var(--soft);color:var(--accent);margin-bottom:18px;border:1px solid color-mix(in srgb,var(--accent) 30%,transparent)}
.btns{display:flex;gap:12px;flex-wrap:wrap}.btn{display:inline-block;text-decoration:none;font-weight:700;padding:14px 22px;border-radius:12px;border:1px solid var(--line);color:var(--text);background:var(--panel)}
.btn.p{background:#0f766e;border-color:#0f766e;color:#fff}.btn.p:hover{background:#115e59}.btn:hover{border-color:var(--accent)}.note{font-size:14px;color:var(--muted);margin-top:14px}
.phone{position:relative;margin:0 auto;width:min(300px,78vw);aspect-ratio:9/18;border-radius:38px;background:#0b0d10;border:10px solid #1d2229;box-shadow:0 30px 70px rgba(0,0,0,.35);overflow:hidden}
.scr{position:absolute;inset:0;background:linear-gradient(160deg,#1e1b4b 0%,#7c3aed 38%,#db2777 66%,#f59e0b 100%)}.scr::after{content:"";position:absolute;inset:0;background:radial-gradient(60% 30% at 50% 42%,rgba(255,255,255,.35),transparent 70%)}
.half{position:absolute;inset:0 50% 0 0;background:linear-gradient(160deg,#3f4651,#1f242b);border-right:2px solid #fff}.half span,.scr span{position:absolute;top:14px;font-size:11px;font-weight:700;color:#fff;background:#0009;padding:3px 8px;border-radius:6px;z-index:2}.half span{left:12px}.scr>span{right:12px}
.who{position:absolute;left:50%;top:38%;transform:translate(-50%,-50%);width:42%;aspect-ratio:1/1.3;border-radius:50% 50% 42% 42%;background:#0004;z-index:1}
.say{position:absolute;left:12px;right:12px;bottom:84px;z-index:3;background:#fffffff0;color:#111;border-radius:14px;padding:10px 12px;font-size:14px;font-weight:600;box-shadow:0 8px 20px #0005}.say small{display:block;color:#6b7280;font-weight:500;font-size:11px}
.ctl{position:absolute;left:10px;right:10px;bottom:14px;z-index:3;display:grid;grid-template-columns:1fr 1fr 1fr;gap:6px}.ctl b{font-size:11px;color:#fff;text-align:center;padding:10px 0;border-radius:10px;background:#ffffff26}.ctl b:first-child{background:#7c3aed}
.grid3{display:grid;grid-template-columns:repeat(3,1fr);gap:16px}.grid2{display:grid;grid-template-columns:repeat(2,1fr);gap:20px}@media(max-width:820px){.grid3,.grid2{grid-template-columns:1fr}}
.card{background:var(--panel);border:1px solid var(--line);border-radius:18px;padding:24px}.card h3{margin:0 0 8px;font-size:20px}.card p{margin:0;color:var(--muted)}
.prod{padding:30px}.prod .tag{font-size:12px;font-weight:800;letter-spacing:.1em;color:var(--accent2)}.prod h3{font-size:28px;margin:6px 0 10px;letter-spacing:-.02em}.prod ul{margin:16px 0 22px;padding:0;list-style:none}.prod li{padding:7px 0 7px 28px;position:relative;border-top:1px solid var(--line)}.prod li::before{content:"✓";position:absolute;left:4px;color:var(--accent);font-weight:800}
.num{width:38px;height:38px;border-radius:50%;display:grid;place-items:center;font-weight:800;background:var(--soft);color:var(--accent);margin-bottom:12px}
.ex{display:flex;flex-wrap:wrap;gap:10px}.ex span{background:var(--panel);border:1px solid var(--line);border-radius:999px;padding:9px 16px;font-size:15px}
.plats{display:flex;flex-wrap:wrap;gap:12px}.plats span{font-weight:700;padding:12px 20px;border-radius:12px;background:var(--panel);border:1px solid var(--line)}
.alt{background:var(--panel);border-top:1px solid var(--line);border-bottom:1px solid var(--line)}
.faq details{background:var(--bg);border:1px solid var(--line);border-radius:14px;padding:16px 20px;margin-bottom:10px}.faq summary{cursor:pointer;font-weight:700}.faq details p{margin:10px 0 0;color:var(--muted)}
.final{text-align:center}.final .lead{margin:0 auto 26px}.final .btns{justify-content:center}
.wl{max-width:640px;margin:0 auto}.wl form{display:grid;gap:14px;text-align:left;margin-top:8px}.wl label{display:grid;gap:6px;font-weight:600;font-size:15px}
.wl input[type=email],.wl select{font:inherit;color:var(--text);background:var(--bg);border:1px solid var(--line);border-radius:12px;padding:13px 14px;width:100%}
.wl input:focus-visible,.wl select:focus-visible{outline:3px solid color-mix(in srgb,var(--accent) 45%,transparent);border-color:var(--accent)}
.wl .two{display:grid;grid-template-columns:1fr 1fr;gap:14px}@media(max-width:600px){.wl .two{grid-template-columns:1fr}}
.wl .ok{display:flex;gap:10px;align-items:flex-start;font-weight:400;font-size:14px;color:var(--muted)}.wl .ok input{margin-top:4px;width:18px;height:18px;flex:none}
.wl button{font:inherit;font-weight:700;border:0;border-radius:12px;padding:15px 22px;background:#0f766e;color:#fff;cursor:pointer}.wl button:hover{background:#115e59}
.hp{position:absolute;left:-9999px;width:1px;height:1px;overflow:hidden}.msgbox{padding:14px 16px;border-radius:12px;margin:0 0 16px;font-weight:600}.msgbox.good{background:var(--soft);color:var(--accent)}.msgbox.bad{background:color-mix(in srgb,#dc2626 14%,transparent);color:#dc2626}
footer{border-top:1px solid var(--line);padding:28px 0 40px;font-size:14px;color:var(--muted)}footer .w{display:flex;justify-content:space-between;gap:16px;flex-wrap:wrap}footer a{color:var(--muted)}`;

export function landing(etat = "") {
  const box = etat === "merci" ? `<p class="msgbox good" role="status">Merci, tu es sur la liste ! On te prévient dès que ton accès est prêt.</p>`
    : etat === "erreur" ? `<p class="msgbox bad" role="alert">Adresse e-mail invalide ou case non cochée. Réessaie.</p>` : "";
  return `<!doctype html><html lang="fr"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>AI Live & AI Studio — transforme ta vidéo par la voix</title>
<meta name="description" content="AI Live transforme ton live en temps réel, à la voix : personnage, décor, style. AI Studio modifie tes vidéos en décrivant ce que tu veux. Prix affiché avant chaque usage.">
<meta property="og:title" content="AI Live & AI Studio — transforme ta vidéo par la voix"><meta property="og:description" content="Ton live transformé en direct par l'IA, à la voix. Tes vidéos modifiées en une phrase."><meta property="og:type" content="website">
<link rel="icon" href="${ICON}"><style>${LCSS}</style></head><body>${nav("accueil")}
<main>
<section class="hero"><div class="w"><div>
<span class="beta">Bêta privée · accès sur invitation</span>
<h1>Dis-le.<br>Ton live <em>se transforme</em>.</h1>
<p class="lead">AI Live transforme ta caméra en direct, juste avec ta voix : deviens un chevalier, passe dans un décor cyberpunk, change de style en une phrase. Tu reviens à l'image réelle d'un seul geste.</p>
<div class="btns"><a class="btn p" href="#attente">Rejoindre la liste d'attente</a><a class="btn" href="#produits">Voir les outils</a></div>
<p class="note">Fonctionne depuis un téléphone ou un ordinateur. Aucune carte graphique à acheter.</p>
</div>
<div class="phone" role="img" aria-label="Aperçu : à gauche l'image réelle, à droite l'image transformée par l'IA après la commande vocale « transforme-moi en chevalier »">
<div class="scr"><span>IA</span></div><div class="half"><span>Réel</span></div><div class="who"></div>
<div class="say"><small>🎙 commande vocale</small>« Transforme-moi en chevalier, décor château »</div>
<div class="ctl"><b>🎙 Voix</b><b>⟲ Original</b><b>⏺ Essai</b></div>
</div></div></section>

<section><div class="w">
<p class="eyebrow">Pourquoi c'est différent</p><h2>La créativité d'un studio, la simplicité d'une phrase</h2>
<p class="lead">Pas de logiciel compliqué ni de matériel coûteux. Tu parles, l'IA s'occupe du reste, et tu sais toujours ce que tu paies.</p>
<div class="grid3">
<div class="card"><h3>🎙 Piloté à la voix</h3><p>« Plus fort », « ajoute de la neige », « style anime ». Les commandes se combinent, en français, pendant que tu filmes.</p></div>
<div class="card"><h3>⚡ Pensé pour le direct</h3><p>L'image est transformée en continu, et le bouton « Original » rend la vraie caméra instantanément.</p></div>
<div class="card"><h3>💶 Prix connu d'avance</h3><p>Tu paies à l'usage. Le tarif est affiché avant de commencer, sans abonnement imposé ni surprise.</p></div>
</div></div></section>

<section class="alt" id="produits"><div class="w">
<p class="eyebrow">Deux outils</p><h2>Pour le direct et pour tes vidéos</h2>
<div class="grid2" style="margin-top:28px">
<article class="card prod" id="live"><span class="tag">AI LIVE</span><h3>Ton live transformé, en temps réel</h3><p>La caméra de ton téléphone ou de ton ordinateur passe par l'IA avant d'arriver à tes spectateurs.</p>
<ul><li>Personnages, décors et styles en un mot ou à la voix</li><li>Retour à l'image réelle en un geste</li><li>Diffusion vers YouTube, Twitch, Kick et Facebook, jusqu'à 3 à la fois</li><li>Formats horizontal, vertical et carré</li><li>Mode essai : enregistre-toi sans rien publier</li></ul>
<a class="btn p" href="https://live.labotory.site/mobile.html">Ouvrir AI Live</a></article>
<article class="card prod" id="studio"><span class="tag">AI STUDIO</span><h3>Tes vidéos modifiées en une phrase</h3><p>Importe une vidéo, décris le changement : l'IA prépare un devis, puis fait le travail.</p>
<ul><li>« Remplace le ciel par un coucher de soleil »</li><li>Changer d'univers, de saison ou d'ambiance</li><li>Recadrer en vertical pour les formats courts</li><li>Ne modifier qu'un passage précis, sans payer le reste</li><li>Devis avant chaque traitement, remboursé en cas d'échec</li></ul>
<a class="btn p" href="https://studio.labotory.site/">Ouvrir AI Studio</a></article>
</div></div></section>

<section><div class="w">
<p class="eyebrow">Comment ça marche</p><h2>Trois étapes, et tu es en direct</h2>
<div class="grid3" style="margin-top:28px">
<div class="card"><div class="num">1</div><h3>Ouvre AI Live</h3><p>Depuis ton téléphone ou ton ordinateur. Tu choisis la caméra, l'IA démarre.</p></div>
<div class="card"><div class="num">2</div><h3>Parle</h3><p>Dis ce que tu veux devenir. Change d'avis quand tu veux, l'image suit.</p></div>
<div class="card"><div class="num">3</div><h3>Diffuse</h3><p>Fais un essai, puis envoie le résultat sur tes plateformes avec ta clé de diffusion, ou via OBS.</p></div>
</div>
<h3 style="margin:40px 0 14px">Exemples de commandes</h3>
<div class="ex"><span>« transforme-moi en chevalier »</span><span>« décor cyberpunk »</span><span>« style anime »</span><span>« ajoute de la neige »</span><span>« plus fort »</span><span>« reviens à l'original »</span></div>
</div></section>

<section class="alt"><div class="w">
<p class="eyebrow">Plateformes</p><h2>Diffuse là où est ton public</h2>
<p class="lead">On commence par les plateformes ouvertes à tous, sans nombre minimum d'abonnés. D'autres arriveront ensuite.</p>
<div class="plats"><span>YouTube</span><span>Twitch</span><span>Kick</span><span>Facebook</span><span>+ via Restream</span></div>
</div></section>

<section><div class="w">
<p class="eyebrow">Pour qui</p><h2>Fait pour celles et ceux qui créent</h2>
<div class="grid3" style="margin-top:28px">
<div class="card"><h3>Streamers IRL</h3><p>Change d'univers en marchant dans la rue, sans PC ni montage.</p></div>
<div class="card"><h3>Créateurs de contenu</h3><p>Des formats originaux pour tes shorts et tes vidéos, en une phrase.</p></div>
<div class="card"><h3>Humour & animation</h3><p>Personnages, déguisements, ambiances : de quoi surprendre ta communauté à chaque live.</p></div>
</div></div></section>

<section class="alt"><div class="w grid2" style="align-items:center">
<div><p class="eyebrow">Créer sans tromper</p><h2>Une IA créative, et responsable</h2>
<p class="lead" style="margin:0">Personne ne peut prendre de façon réaliste l'apparence d'une vraie personne sans son accord. Les parodies de personnalités sont des caricatures, toujours signalées par un bandeau « Parodie IA ». Les contenus sexuels, violents ou haineux sont bloqués.</p></div>
<div class="card"><h3>Ta vie privée</h3><p>Tes clés de diffusion restent sur ton appareil si tu le choisis, et ne s'affichent jamais en clair. En mode essai, rien n'est publié.</p></div>
</div></section>

<section class="faq"><div class="w">
<p class="eyebrow">Questions fréquentes</p><h2>Tout ce qu'il faut savoir</h2>
<details><summary>Faut-il un ordinateur puissant ?</summary><p>Non. Le calcul se fait sur des cartes graphiques en ligne, louées seulement pendant ton utilisation. Un téléphone récent suffit.</p></details>
<details><summary>Combien ça coûte ?</summary><p>Tu paies à l'usage : à la minute pour AI Live selon le modèle choisi, sur devis pour AI Studio. Le prix est toujours affiché avant de commencer.</p></details>
<details><summary>Sur quelles plateformes puis-je diffuser ?</summary><p>YouTube, Twitch, Kick et Facebook pour commencer, jusqu'à trois en même temps, ou toute plateforme qui accepte une diffusion RTMP (par exemple via Restream ou OBS).</p></details>
<details><summary>Puis-je essayer sans rien publier ?</summary><p>Oui. Le mode essai affiche la transformation sur ton écran et te permet d'enregistrer des tests. Rien ne part en ligne tant que tu ne lances pas la diffusion.</p></details>
<details><summary>Est-ce disponible maintenant ?</summary><p>Les deux outils sont en bêta privée et s'ouvrent progressivement, sur invitation. <a href="#attente">Inscris-toi sur la liste d'attente</a> pour être prévenu.</p></details>
</div></section>

<section class="alt final" id="attente"><div class="w wl">
<p class="eyebrow">Liste d'attente</p>
<h2>Sois parmi les premiers à essayer</h2>
<p class="lead">Laisse ton e-mail : on ouvre les accès petit à petit, et on te prévient dès que c'est ton tour.</p>
${box}
<form method="post" action="/liste-attente#attente">
<label>Ton e-mail<input type="email" name="email" required maxlength="200" autocomplete="email" placeholder="toi@exemple.com"></label>
<div class="two">
<label>Tu es plutôt…<select name="profil"><option value="streamer">Streamer</option><option value="createur">Créateur de vidéos</option><option value="entreprise">Entreprise / agence</option><option value="curieux">Curieux</option></select></label>
<label>Ce qui t'intéresse<select name="interet"><option value="les_deux">Les deux</option><option value="live">AI Live</option><option value="studio">AI Studio</option></select></label>
</div>
<div class="hp" aria-hidden="true"><label>Ne pas remplir<input type="text" name="site" tabindex="-1" autocomplete="off"></label></div>
<label class="ok"><input type="checkbox" name="accord" value="oui" required><span>J'accepte d'être contacté par e-mail au sujet de l'accès à AI Live et AI Studio. Mon adresse ne sert qu'à ça, n'est jamais revendue, et je peux demander sa suppression à tout moment en répondant à un e-mail reçu.</span></label>
<button type="submit">Rejoindre la liste d'attente</button>
</form>
</div></section>
</main>
<footer><div class="w"><span>© ${new Date().getUTCFullYear()} Le Laboratoire · AI Live & AI Studio</span><span><a href="#produits">Produits</a> · <a href="#attente">Liste d'attente</a> · <a href="/suivi">Suivi du projet</a></span></div></footer>
</body></html>`;
}

const SEC = { "x-content-type-options": "nosniff", "referrer-policy": "strict-origin-when-cross-origin",
  "content-security-policy": "default-src 'none'; style-src 'unsafe-inline'; img-src data:; base-uri 'none'; form-action 'self'; frame-ancestors 'none'" };
const FALLBACK = { intention: "", mis_a_jour: "—", maintenant: { focus: "Données d'avancement indisponibles pour le moment." } };

function autorise(req, env) {
  const auth = req.headers.get("authorization") || "";
  const tok = env.LABO_UPDATE_TOKEN || "";
  const enc = new TextEncoder();
  const a = enc.encode(auth), b = enc.encode(`Bearer ${tok}`);
  let same = tok.length >= 24 && a.length === b.length;
  for (let i = 0; same && i < a.length; i++) same = a[i] === b[i];
  return same;
}

// Liste d'attente : POST /liste-attente (formulaire). Stockée dans le KV (clé « attente:<sha256 e-mail> »),
// jamais affichée publiquement. Lecture : GET /liste-attente.json avec le même jeton que la mise à jour.
const PROFILS = ["streamer", "createur", "entreprise", "curieux"], INTERETS = ["les_deux", "live", "studio"];
const back = (req, etat) => new Response(null, { status: 303, headers: { ...SEC, location: new URL(`/?${etat}#attente`, req.url).toString() } });
async function inscrire(req, env) {
  const origin = req.headers.get("origin");
  if (origin && origin !== new URL(req.url).origin) return new Response("Origine refusée", { status: 403, headers: SEC });
  const body = await req.text();
  if (body.length > 4000) return new Response("Trop volumineux", { status: 413, headers: SEC });
  const f = new URLSearchParams(body);
  if (f.get("site")) return back(req, "merci"); // pot de miel : robot
  const email = (f.get("email") || "").trim().toLowerCase();
  if (email.length > 200 || !/^[^\s@<>]+@[^\s@<>]+\.[^\s@<>]{2,}$/.test(email) || f.get("accord") !== "oui") return back(req, "erreur");
  const profil = PROFILS.includes(f.get("profil")) ? f.get("profil") : "curieux";
  const interet = INTERETS.includes(f.get("interet")) ? f.get("interet") : "les_deux";
  const h = [...new Uint8Array(await crypto.subtle.digest("SHA-256", new TextEncoder().encode(email)))].map((x) => x.toString(16).padStart(2, "0")).join("");
  const key = `attente:${h}`;
  const deja = await env.LABO.get(key, "json");
  const rec = { email, profil, interet, accord: true, inscrit_le: deja?.inscrit_le || new Date().toISOString(), maj_le: new Date().toISOString(), pays: req.cf?.country || null };
  await env.LABO.put(key, JSON.stringify(rec), { metadata: { inscrit_le: rec.inscrit_le } });
  return back(req, "merci");
}
async function exporter(req, env) {
  if (!autorise(req, env)) return new Response("Non autorisé", { status: 401, headers: SEC });
  const out = []; let cursor;
  do {
    const r = await env.LABO.list({ prefix: "attente:", cursor });
    for (const k of r.keys) { const v = await env.LABO.get(k.name, "json"); if (v) out.push(v); }
    cursor = r.list_complete ? null : r.cursor;
  } while (cursor);
  out.sort((a, b) => a.inscrit_le.localeCompare(b.inscrit_le));
  return new Response(JSON.stringify({ total: out.length, inscrits: out }, null, 2), { headers: { ...SEC, "content-type": "application/json; charset=utf-8", "cache-control": "no-store" } });
}

// Mise à jour : PUT /avancement.json avec « Authorization: Bearer <LABO_UPDATE_TOKEN> » (secret du Worker).
async function update(req, env) {
  if (!autorise(req, env)) return new Response("Non autorisé", { status: 401, headers: SEC });
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
    if (req.method === "POST" && path === "/liste-attente") return inscrire(req, env);
    if (path === "/liste-attente.json") return exporter(req, env);
    if (req.method !== "GET" && req.method !== "HEAD") return new Response("Méthode non autorisée", { status: 405, headers: SEC });
    const html = { ...SEC, "content-type": "text/html; charset=utf-8", "cache-control": "public, max-age=60" };
    if (path === "/" || path === "/index.html") {
      const q = new URL(req.url).searchParams, etat = q.has("merci") ? "merci" : q.has("erreur") ? "erreur" : "";
      return new Response(landing(etat), { headers: etat ? { ...html, "cache-control": "no-store", "x-robots-tag": "noindex" } : html });
    }
    if (path === "/avancement" || path === "/suivi/") return Response.redirect(new URL("/suivi", req.url).toString(), 301);
    const data = (env.LABO && await env.LABO.get("avancement", "json")) || FALLBACK;
    if (path === "/suivi") return new Response(render(data), { headers: { ...html, "cache-control": "public, max-age=30", "x-robots-tag": "noindex" } });
    if (path === "/avancement.json") return new Response(JSON.stringify(data, null, 2), { headers: { ...SEC, "content-type": "application/json; charset=utf-8", "cache-control": "public, max-age=30" } });
    return new Response("Introuvable", { status: 404, headers: SEC });
  },
};
