// Assemble les traductions (langues/*.json) en un module pour le Worker : node site/laboratoire/build_langues.mjs
// Vérifie que chaque langue a exactement la même structure que le français (aucun texte manquant).
import { readdirSync, readFileSync, writeFileSync } from "node:fs";

const dir = new URL("./langues/", import.meta.url);
const ORDER = ["fr", "en", "es", "pt", "de", "it", "nl", "ar", "tr", "ru", "zh", "ja", "ko", "hi", "id"];
const files = readdirSync(dir).filter((f) => f.endsWith(".json")).map((f) => f.slice(0, -5));
const codes = [...ORDER.filter((c) => files.includes(c)), ...files.filter((c) => !ORDER.includes(c)).sort()];
const langs = Object.fromEntries(codes.map((c) => [c, JSON.parse(readFileSync(new URL(`${c}.json`, dir), "utf8"))]));

function shape(v) {
  if (Array.isArray(v)) return v.map(shape);
  if (v && typeof v === "object") return Object.fromEntries(Object.keys(v).sort().map((k) => [k, shape(v[k])]));
  return typeof v;
}
const ref = JSON.stringify(shape(langs.fr));
const errors = [];
for (const [c, t] of Object.entries(langs)) {
  if (JSON.stringify(shape(t)) !== ref) errors.push(`${c} : structure différente du français`);
  if (!["ltr", "rtl"].includes(t.dir)) errors.push(`${c} : dir invalide`);
  const faqLast = t.faq.items.at(-1)[1];
  if (!faqLast.includes("{link}") || !faqLast.includes("{/link}")) errors.push(`${c} : lien {link} manquant dans la FAQ`);
  if (/<(?!br>|em>|\/em>)/.test(t.h1)) errors.push(`${c} : balise non autorisée dans h1`);
}
if (errors.length) { console.error(errors.join("\n")); process.exit(1); }

writeFileSync(new URL("./langues.js", import.meta.url),
  "// Généré par build_langues.mjs depuis langues/*.json — ne pas modifier à la main.\n" +
  `export const LANGS = ${JSON.stringify(langs)};\n`);
console.log(`${codes.length} langues : ${codes.join(", ")}`);
