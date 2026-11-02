// Aperçu local : node site/laboratoire/preview.mjs → site/laboratoire/apercu.html (suivi) et apercu-accueil.html
import { readFileSync, writeFileSync } from "node:fs";
import worker, { render, landing } from "./worker.js";
// landing(lang) : une langue de langues/*.json (fr par défaut)
const here = new URL(".", import.meta.url);
const data = JSON.parse(readFileSync(new URL("avancement.json", here), "utf8"));
writeFileSync(new URL("apercu.html", here), render(data));
writeFileSync(new URL("apercu-accueil.html", here), landing());
const env = { LABO: { get: async () => data } };
for (const p of ["/", "/suivi", "/avancement", "/avancement.json", "/x"]) {
  const r = await worker.fetch(new Request("https://labotory.site" + p), env);
  console.log(p, r.status, r.headers.get("content-type") || r.headers.get("location"));
}
