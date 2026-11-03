// Sentinelle du laboratoire (Worker Cloudflare, indépendant du serveur Oracle).
// Toutes les 5 minutes : vérifie AI Live et AI Studio. S'ils sont injoignables 3 fois de suite
// (≥ 10 min) et qu'aucun redémarrage n'a eu lieu depuis 30 min, demande à Oracle de redémarrer
// l'instance (action RESET). Les secrets (clé Oracle, jeton) sont des secrets du Worker.
//
// Accès manuel (jeton requis) : GET /etat (état Oracle + historique), POST /redemarrer.

const SONDES = ["https://live.labotory.site/api/catalog", "https://studio.labotory.site/"];
const ECHECS_AVANT_REDEMARRAGE = 3;
const PAUSE_ENTRE_REDEMARRAGES_MS = 30 * 60 * 1000;

const b64 = (buf) => btoa(String.fromCharCode(...new Uint8Array(buf)));
const pemToDer = (pem) => Uint8Array.from(atob(pem.replace(/-----[^-]+-----/g, "").replace(/\s+/g, "")), (c) => c.charCodeAt(0));

async function ociFetch(env, method, path, bodyObj) {
  const host = `iaas.${env.OCI_REGION}.oraclecloud.com`;
  const target = `/20160918${path}`;
  const date = new Date().toUTCString();
  const headers = { "x-date": date };
  const names = ["x-date", "(request-target)", "host"];
  const lines = [`x-date: ${date}`, `(request-target): ${method.toLowerCase()} ${target}`, `host: ${host}`];
  const body = bodyObj ? new TextEncoder().encode(JSON.stringify(bodyObj)) : new Uint8Array();
  if (method !== "GET") {
    const sha = b64(await crypto.subtle.digest("SHA-256", body));
    Object.assign(headers, { "content-length": String(body.length), "content-type": "application/json", "x-content-sha256": sha });
    names.push("content-length", "content-type", "x-content-sha256");
    lines.push(`content-length: ${body.length}`, "content-type: application/json", `x-content-sha256: ${sha}`);
  }
  const key = await crypto.subtle.importKey("pkcs8", pemToDer(env.OCI_KEY), { name: "RSASSA-PKCS1-v1_5", hash: "SHA-256" }, false, ["sign"]);
  const sig = b64(await crypto.subtle.sign("RSASSA-PKCS1-v1_5", key, new TextEncoder().encode(lines.join("\n"))));
  headers.authorization = `Signature version="1",keyId="${env.OCI_TENANCY}/${env.OCI_USER}/${env.OCI_FINGERPRINT}",algorithm="rsa-sha256",headers="${names.join(" ")}",signature="${sig}"`;
  const r = await fetch(`https://${host}${target}`, { method, headers, body: method === "GET" ? undefined : body });
  const text = await r.text();
  return { status: r.status, data: text ? JSON.parse(text) : {} };
}

async function sonder(url) {
  try {
    const r = await fetch(url, { signal: AbortSignal.timeout(15000), cf: { cacheTtl: 0 } });
    return r.status;
  } catch { return 0; }
}

async function lireEtat(env) { return (await env.SENT.get("etat", "json")) || { echecs: 0, dernierRedemarrage: 0, journal: [] }; }
async function ecrireEtat(env, e) { e.journal = e.journal.slice(-30); await env.SENT.put("etat", JSON.stringify(e)); }

async function redemarrer(env, e, raison) {
  const r = await ociFetch(env, "POST", `/instances/${env.INSTANCE_ID}?action=RESET`);
  e.dernierRedemarrage = Date.now();
  e.journal.push({ t: new Date().toISOString(), evt: "redémarrage", raison, oracle: r.status, etat: r.data.lifecycleState || r.data.code });
  return r;
}

async function verifier(env) {
  const e = await lireEtat(env);
  const codes = await Promise.all(SONDES.map(sonder));
  const enPanne = codes.every((c) => c !== 200);
  e.echecs = enPanne ? e.echecs + 1 : 0;
  e.derniereVerif = { t: new Date().toISOString(), codes };
  if (enPanne) e.journal.push({ t: new Date().toISOString(), evt: "injoignable", codes, echecs: e.echecs });
  if (enPanne && e.echecs >= ECHECS_AVANT_REDEMARRAGE && Date.now() - e.dernierRedemarrage > PAUSE_ENTRE_REDEMARRAGES_MS) {
    await redemarrer(env, e, `injoignable ${e.echecs} fois de suite`);
    e.echecs = 0;
  }
  await ecrireEtat(env, e);
}

// Création de la machine Ampere A1 (offre gratuite) : Oracle manque souvent de place ; on retente
// toutes les 30 minutes jusqu'à réussite, sans jamais créer de doublon (nom « labo-a1 »).
async function tenterA1(env, force = false) {
  const st = (await env.SENT.get("a1", "json")) || { cree: false, essais: 0 };
  if (st.cree) return st;
  if (!force && Date.now() - (st.dernier || 0) < 29 * 60 * 1000) return st;
  st.dernier = Date.now(); st.essais += 1;
  const ex = await ociFetch(env, "GET", `/instances?compartmentId=${env.OCI_TENANCY}&displayName=labo-a1`);
  const vivant = Array.isArray(ex.data) && ex.data.find((i) => !["TERMINATED", "TERMINATING"].includes(i.lifecycleState));
  if (vivant) { Object.assign(st, { cree: true, id: vivant.id, etat: vivant.lifecycleState }); await env.SENT.put("a1", JSON.stringify(st)); return st; }
  const r = await ociFetch(env, "POST", "/instances", {
    availabilityDomain: env.A1_AD, compartmentId: env.OCI_TENANCY, displayName: "labo-a1",
    shape: "VM.Standard.A1.Flex", shapeConfig: { ocpus: 2, memoryInGBs: 12 },
    sourceDetails: { sourceType: "image", imageId: env.A1_IMAGE, bootVolumeSizeInGBs: 100 },
    createVnicDetails: { subnetId: env.A1_SUBNET, assignPublicIp: true },
    metadata: { ssh_authorized_keys: env.SSH_PUB },
  });
  if (r.status < 300) Object.assign(st, { cree: true, id: r.data.id, etat: r.data.lifecycleState, le: new Date().toISOString() });
  else st.derniereErreur = `${r.status} ${r.data.code || ""} ${(r.data.message || "").slice(0, 80)}`;
  await env.SENT.put("a1", JSON.stringify(st));
  return st;
}

function autorise(req, env) {
  const a = new TextEncoder().encode(req.headers.get("authorization") || "");
  const b = new TextEncoder().encode(`Bearer ${env.SENT_TOKEN || ""}`);
  if (!env.SENT_TOKEN || env.SENT_TOKEN.length < 24 || a.length !== b.length) return false;
  let d = 0;
  for (let i = 0; i < a.length; i++) d |= a[i] ^ b[i];
  return d === 0;
}

export default {
  async scheduled(_evt, env, ctx) { ctx.waitUntil(verifier(env)); if (env.A1_IMAGE) ctx.waitUntil(tenterA1(env)); },
  async fetch(req, env) {
    const json = (o, s = 200) => new Response(JSON.stringify(o, null, 2), { status: s, headers: { "content-type": "application/json; charset=utf-8", "cache-control": "no-store" } });
    if (!autorise(req, env)) return json({ erreur: "non autorisé" }, 401);
    const path = new URL(req.url).pathname;
    if (req.method === "GET" && path === "/etat") {
      const oracle = await ociFetch(env, "GET", `/instances/${env.INSTANCE_ID}`);
      return json({ oracle: { http: oracle.status, etat: oracle.data.lifecycleState, nom: oracle.data.displayName }, sentinelle: await lireEtat(env) });
    }
    if (req.method === "POST" && path === "/redemarrer") {
      const e = await lireEtat(env);
      const r = await redemarrer(env, e, "demande manuelle");
      await ecrireEtat(env, e);
      return json({ oracle: r.status, etat: r.data.lifecycleState || r.data });
    }
    if (req.method === "POST" && path === "/verifier") { await verifier(env); return json(await lireEtat(env)); }
    if (path === "/a1") return json(req.method === "POST" ? await tenterA1(env, true) : ((await env.SENT.get("a1", "json")) || {}));
    return json({ erreur: "introuvable" }, 404);
  },
};
