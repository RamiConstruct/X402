// Worker de la page de suivi : sert les fichiers statiques de site/dist.
// projets.<domaine> -> /           (page générale)
// <slug>.<domaine>  -> /<slug>/    (page d'un projet du registre)
// Tout autre hôte reçoit la page générale. Aucune donnée n'est collectée.
import { DOMAIN, HOME, SLUGS } from "./projets.generated.js";

export function assetPath(hostname, pathname, domain = DOMAIN, slugs = SLUGS) {
  const host = hostname.toLowerCase().replace(/\.$/, "");
  const suffix = `.${domain}`;
  if (!host.endsWith(suffix)) return pathname;
  const sub = host.slice(0, -suffix.length);
  if (sub === HOME || !slugs.includes(sub)) return pathname;
  return `/${sub}${pathname}`;
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    if (request.method !== "GET" && request.method !== "HEAD") {
      return new Response("Méthode non autorisée", { status: 405, headers: { Allow: "GET, HEAD" } });
    }
    url.pathname = assetPath(url.hostname, url.pathname);
    return env.ASSETS.fetch(new Request(url, request));
  },
};
