import assert from "node:assert/strict";
import { test } from "node:test";

import worker, { assetPath } from "./index.js";

const DOMAIN = "laboratory.site";
const SLUGS = ["labo", "x402", "vendeur"];

test("le sous-domaine d'accueil sert la page générale", () => {
  assert.equal(assetPath("projets.laboratory.site", "/", DOMAIN, SLUGS), "/");
});

test("un sous-domaine de projet sert son dossier", () => {
  assert.equal(assetPath("labo.laboratory.site", "/", DOMAIN, SLUGS), "/labo/");
  assert.equal(assetPath("X402.Laboratory.Site.", "/index.html", DOMAIN, SLUGS), "/x402/index.html");
});

test("un sous-domaine inconnu ou un autre domaine ne sont pas réécrits", () => {
  assert.equal(assetPath("inconnu.laboratory.site", "/", DOMAIN, SLUGS), "/");
  assert.equal(assetPath("labo.autre-domaine.org", "/", DOMAIN, SLUGS), "/");
  assert.equal(assetPath("laboratory.site", "/", DOMAIN, SLUGS), "/");
  assert.equal(assetPath("evil-labo.laboratory.site", "/", DOMAIN, SLUGS), "/");
});

test("le Worker refuse les méthodes d'écriture et transmet le chemin réécrit", async () => {
  const seen = [];
  const env = { ASSETS: { fetch: async (req) => { seen.push(new URL(req.url).pathname); return new Response("ok"); } } };
  const post = await worker.fetch(new Request("https://labo.laboratory.site/", { method: "POST" }), env);
  assert.equal(post.status, 405);
  const get = await worker.fetch(new Request("https://labo.laboratory.site/../x"), env);
  assert.equal(get.status, 200);
  assert.deepEqual(seen, ["/labo/x"]); // l'URL normalise « .. » avant la réécriture
});
