// Aperçu local : node site/laboratoire/preview.mjs → site/laboratoire/apercu.html
import { readFileSync, writeFileSync } from "node:fs";
import worker, { render } from "./worker.js";
const here = new URL(".", import.meta.url);
const data = JSON.parse(readFileSync(new URL("avancement.json", here), "utf8"));
writeFileSync(new URL("apercu.html", here), render(data));
const env = { LABO: { get: async () => data } };
for (const p of ["/", "/avancement.json", "/x"]) {
  const r = await worker.fetch(new Request("https://labotory.site" + p), env);
  console.log(p, r.status, r.headers.get("content-type"));
}
