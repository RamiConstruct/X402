"""Génère la page de suivi des projets (HTML statique, aucune donnée inventée).

Sources lues à la génération :
* ``site/projets.json`` : registre des projets et de leurs sous-domaines ;
* ``docs/COORDINATION.md`` sur ``origin/main`` (à défaut, la copie locale) ;
* ``git log`` : derniers commits de toutes les branches ;
* les scénarios du laboratoire, rejoués à la génération ;
* ``--avec-tests`` : la suite de tests, exécutée à la génération.

Sorties : ``site/dist/index.html`` (document complet, déployable tel quel sur un
hébergement statique) et ``site/dist/apercu.html`` (contenu seul, pour un aperçu).
La page ne contient ni secret ni identifiant.

Usage : python3 site/build_site.py [--domaine exemple.com] [--avec-tests]
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from html import escape
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from labtrading import BANNER  # noqa: E402
from labtrading.report import SCENARIOS_DIR, load_scenario, run_scenario  # noqa: E402

ETATS = {
    "en_cours": ("En cours", "info"), "en_revue": ("En revue", "warn"),
    "en_attente": ("En attente", "muted"), "termine": ("Terminé", "ok"),
}
STATUTS_LAB = {
    "execute_complet": ("Exécuté (simulé)", "ok"), "execute_apparie_partiel": ("Partiel apparié", "warn"),
    "une_jambe": ("Une seule jambe", "crit"), "non_execute": ("Non exécuté", "muted"),
    "rejete": ("Refusé", "muted"),
}


def git(*args: str) -> str:
    try:
        return subprocess.run(["git", "-C", str(ROOT), *args], capture_output=True, text=True,
                              check=True, timeout=30).stdout
    except (subprocess.SubprocessError, OSError):
        return ""


def coordination() -> dict[str, str]:
    text = git("show", "origin/main:docs/COORDINATION.md")
    if not text:
        path = ROOT / "docs" / "COORDINATION.md"
        text = path.read_text(encoding="utf-8") if path.exists() else ""
    fields = {}
    for key in ("Mission active", "Révision de mission", "État", "Responsable de la prochaine action",
                "Mise à jour UTC", "Version documentaire"):
        match = re.search(rf"^- {re.escape(key)} : (.+)$", text, flags=re.M)
        fields[key] = match.group(1).strip() if match else "inconnu"
    return fields


def commits(limit: int = 12) -> list[dict[str, str]]:
    out = git("log", "--all", f"-{limit}", "--date=format-local:%Y-%m-%d %H:%M",
              "--format=%h%x1f%ad%x1f%an%x1f%s")
    rows = []
    for line in out.splitlines():
        parts = line.split("\x1f")
        if len(parts) == 4:
            rows.append(dict(zip(("sha", "date", "auteur", "sujet"), parts)))
    return rows


def lab_results() -> list[dict[str, object]]:
    rows = []
    for path in sorted(SCENARIOS_DIR.glob("scenario_*.json")):
        data = load_scenario(path)
        result = run_scenario(data)
        rows.append({
            "nom": path.stem.removeprefix("scenario_"), "description": data.get("description", ""),
            "statut": result.status, "ecart": result.gross_spread_unit, "net": result.planned_net,
            "pnl": result.realized_pnl, "exposition": result.open_exposure_base,
            "motif": result.reasons[0] if result.reasons else "aucun refus",
        })
    return rows


def tests() -> dict[str, str] | None:
    proc = subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", "tests", "-t", "."],
                          cwd=ROOT, capture_output=True, text=True, timeout=600)
    ran = re.search(r"Ran (\d+) tests?", proc.stderr)
    return {"nombre": ran.group(1) if ran else "?", "ok": proc.returncode == 0,
            "python": sys.version.split()[0]}


def num(value: object) -> str:
    return "—" if value is None else escape(str(value))


def chip(label: str, tone: str) -> str:
    return f'<span class="chip chip-{tone}">{escape(label)}</span>'


def render(registry: dict, coord: dict, log: list, lab: list, test: dict | None,
           domain: str | None, generated: str) -> tuple[str, str]:
    host = escape(domain) if domain else "votre-domaine"
    cards = []
    for p in registry["projets"]:
        label, tone = ETATS.get(p["etat"], (p["etat"], "muted"))
        missions = ", ".join(p["missions"]) or "aucune"
        blocked = (f'<p class="blocked"><strong>Bloqué par :</strong> {escape(p["bloque_par"])}</p>'
                   if p.get("bloque_par") else "")
        cards.append(f"""
      <article class="project">
        <header><h3>{escape(p["nom"])}</h3>{chip(label, tone)}</header>
        <p class="host">{escape(p["slug"])}.{host}</p>
        <p>{escape(p["resume"])}</p>
        <dl>
          <div><dt>Missions</dt><dd>{escape(missions)}</dd></div>
          <div><dt>Données</dt><dd>{escape(p["donnees"])}</dd></div>
          <div><dt>Argent réel</dt><dd>{"oui" if p["argent_reel"] else "non"}</dd></div>
        </dl>{blocked}
      </article>""")

    lab_rows = []
    for row in lab:
        label, tone = STATUTS_LAB.get(row["statut"], (row["statut"], "muted"))
        lab_rows.append(
            f'<tr><td><span class="scen">{escape(row["nom"])}</span>'
            f'<span class="desc">{escape(row["description"])}</span></td><td>{chip(label, tone)}</td>'
            f'<td class="n">{num(row["ecart"])}</td><td class="n">{num(row["net"])}</td>'
            f'<td class="n">{num(row["pnl"])}</td><td class="n">{num(row["exposition"])}</td>'
            f'<td class="why">{escape(row["motif"])}</td></tr>')

    log_rows = "".join(
        f'<li><code>{escape(c["sha"])}</code><time>{escape(c["date"])}</time>'
        f'<span class="who">{escape("dot" if c["auteur"] != "Claude" else "Claude")}</span>'
        f'<span class="subject">{escape(c["sujet"])}</span></li>' for c in log)

    test_line = ("Tests non exécutés pour cette génération." if test is None else
                 f'{test["nombre"]} tests, {"tous réussis" if test["ok"] else "ÉCHECS"} '
                 f'(Python {escape(test["python"])}).')

    head = f"""<title>Projets {escape(registry["proprietaire"])}</title>
<meta name="claude:viewport-fit-sides" content="cover">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Archivo:wdth,wght@75..100,500..800&family=Public+Sans:wght@400;600&family=IBM+Plex+Mono:wght@400;500&display=swap">
<style>{CSS}</style>"""
    body = f"""
<main>
  <header class="top">
    <p class="eyebrow">Tableau de chantier · {escape(registry["proprietaire"])}</p>
    <h1>Projets en cours</h1>
    <p class="meta">Généré le {escape(generated)} UTC à partir du dépôt RamiConstruct/X402. {escape(test_line)}</p>
  </header>

  <p class="banner">{escape(BANNER)}. Aucun projet ne manipule d'argent réel. Une simulation réussie
  n'est ni un paiement réussi, ni une preuve de rentabilité.</p>

  <section class="coord" aria-labelledby="coord-t">
    <h2 id="coord-t">Coordination dot ↔ Claude</h2>
    <dl>
      <div><dt>Mission active</dt><dd>{escape(coord["Mission active"])} (révision {escape(coord["Révision de mission"])})</dd></div>
      <div><dt>État</dt><dd>{escape(coord["État"])}</dd></div>
      <div><dt>Prochaine action</dt><dd>{escape(coord["Responsable de la prochaine action"])}</dd></div>
      <div><dt>Document</dt><dd>version {escape(coord["Version documentaire"])}, {escape(coord["Mise à jour UTC"])}</dd></div>
    </dl>
  </section>

  <section aria-labelledby="proj-t">
    <h2 id="proj-t">Projets et sous-domaines prévus</h2>
    <div class="projects">{"".join(cards)}
    </div>
  </section>

  <section aria-labelledby="lab-t">
    <h2 id="lab-t">Laboratoire : scénarios rejoués à la génération</h2>
    <p class="lead">Carnets, frais, latences et soldes inventés. Les montants sont en dollars fictifs
    pour un actif fictif (XFIC). « Net planifié » est calculé avant exécution ; le P&amp;L n'est compté
    que pour une paire terminée.</p>
    <div class="table-wrap"><table>
      <thead><tr><th>Scénario</th><th>Statut</th><th class="n">Écart brut / unité</th>
      <th class="n">Net planifié</th><th class="n">P&amp;L simulé</th><th class="n">Exposition</th><th>Motif</th></tr></thead>
      <tbody>{"".join(lab_rows)}</tbody>
    </table></div>
  </section>

  <section aria-labelledby="log-t">
    <h2 id="log-t">Journal des derniers commits</h2>
    <ol class="log">{log_rows}</ol>
  </section>

  <footer>
    <p>{escape(registry["intention"])}</p>
  </footer>
</main>"""
    return head, body


CSS = """
:root {
  /* Plan de chantier : fond béton bleuté, encre ardoise, accent jaune de signalisation sobre. */
  --bg: #eef1f4; --panel: #ffffff; --fg: #1d2630; --muted: #5a6673; --line: #d3d9e0;
  --accent: #b7791f; --ok: #2f7d4f; --warn: #a15c07; --crit: #b42318; --info: #1f5f9e;
  --chip-bg: #e4e9ef;
  --display: "Archivo", "Arial Narrow", system-ui, sans-serif;
  --body: "Public Sans", system-ui, -apple-system, "Segoe UI", sans-serif;
  --mono: "IBM Plex Mono", ui-monospace, "SFMono-Regular", Menlo, monospace;
}
@media (prefers-color-scheme: dark) { :root:not([data-theme="light"]) {
  --bg: #12171d; --panel: #1a2129; --fg: #e3e8ee; --muted: #9aa6b2; --line: #2c3540;
  --accent: #e0a64a; --ok: #5cbf86; --warn: #e3a04f; --crit: #f07a6f; --info: #78aee6;
  --chip-bg: #242d37; color-scheme: dark; } }
:root[data-theme="dark"] {
  --bg: #12171d; --panel: #1a2129; --fg: #e3e8ee; --muted: #9aa6b2; --line: #2c3540;
  --accent: #e0a64a; --ok: #5cbf86; --warn: #e3a04f; --crit: #f07a6f; --info: #78aee6;
  --chip-bg: #242d37; color-scheme: dark; }
body { background: var(--bg); color: var(--fg); font: 15px/1.55 var(--body); }
main { max-width: 1100px; margin: 0 auto; display: grid; gap: 2.25rem;
  padding-block: 2rem 3rem;
  padding-left: max(16px, env(safe-area-inset-left, 0px));
  padding-right: max(16px, env(safe-area-inset-right, 0px)); }
h1, h2, h3 { font-family: var(--display); text-wrap: balance; margin: 0; }
h1 { font-size: clamp(2rem, 5vw, 3rem); font-weight: 800; font-stretch: 80%; letter-spacing: -0.01em; }
h2 { font-size: 1.15rem; font-weight: 700; font-stretch: 85%; text-transform: uppercase;
  letter-spacing: 0.06em; margin-bottom: 0.9rem; border-bottom: 2px solid var(--accent);
  padding-bottom: 0.35rem; }
h3 { font-size: 1.2rem; font-weight: 700; }
p { margin: 0; max-width: 68ch; }
.top { display: grid; gap: 0.4rem; }
.eyebrow { font: 500 0.78rem/1 var(--mono); text-transform: uppercase; letter-spacing: 0.12em; color: var(--accent); }
.meta, .lead { color: var(--muted); }
.lead { margin-bottom: 0.9rem; }
.banner { max-width: none; border: 1px dashed var(--accent); padding: 0.75rem 1rem;
  font-weight: 600; background: var(--panel); }
.coord dl, .project dl { display: grid; gap: 0.5rem 1.5rem; margin: 0; }
.coord dl { grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); }
dt { font: 500 0.72rem/1.2 var(--mono); text-transform: uppercase; letter-spacing: 0.08em; color: var(--muted); }
dd { margin: 0.15rem 0 0; }
.projects { display: grid; gap: 1rem; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); }
.project { background: var(--panel); border: 1px solid var(--line); padding: 1.1rem; display: grid;
  gap: 0.7rem; align-content: start; min-width: 0; }
.project header { display: flex; justify-content: space-between; align-items: baseline; gap: 0.75rem; flex-wrap: wrap; }
.project dl { grid-template-columns: repeat(3, minmax(0, 1fr)); }
.host { font: 500 0.85rem/1.3 var(--mono); color: var(--accent); overflow-wrap: anywhere; }
.blocked { font-size: 0.9rem; color: var(--warn); }
.chip { font: 500 0.72rem/1 var(--mono); text-transform: uppercase; letter-spacing: 0.06em;
  padding: 0.3rem 0.5rem; border-radius: 3px; background: var(--chip-bg); white-space: nowrap; }
.chip-ok { color: var(--ok); } .chip-warn { color: var(--warn); } .chip-crit { color: var(--crit); }
.chip-info { color: var(--info); } .chip-muted { color: var(--muted); }
.table-wrap { overflow-x: auto; background: var(--panel); border: 1px solid var(--line); }
table { border-collapse: collapse; width: 100%; min-width: 760px; font-size: 0.9rem; }
th, td { text-align: left; padding: 0.6rem 0.75rem; border-bottom: 1px solid var(--line); vertical-align: top; }
th { font: 500 0.72rem/1.2 var(--mono); text-transform: uppercase; letter-spacing: 0.06em; color: var(--muted); }
tbody tr:last-child td { border-bottom: 0; }
.n { text-align: right; font-family: var(--mono); font-variant-numeric: tabular-nums; white-space: nowrap; }
.scen { display: block; font-family: var(--mono); font-weight: 500; }
.desc { display: block; color: var(--muted); font-size: 0.82rem; max-width: 34ch; }
.why { color: var(--muted); max-width: 36ch; }
.log { list-style: none; margin: 0; padding: 0; display: grid; gap: 0.1rem; }
.log li { display: grid; grid-template-columns: 5.5rem 9.5rem 3.5rem minmax(0, 1fr); gap: 0.75rem;
  padding: 0.45rem 0; border-bottom: 1px solid var(--line); align-items: baseline; }
.log code, .log time { font: 0.82rem var(--mono); color: var(--muted); font-variant-numeric: tabular-nums; }
.who { font: 500 0.75rem var(--mono); color: var(--accent); }
.subject { min-width: 0; overflow-wrap: anywhere; }
footer { border-top: 1px solid var(--line); padding-top: 1rem; color: var(--muted); font-style: italic; }
@media (max-width: 640px) {
  .log li { grid-template-columns: 1fr 1fr; }
  .subject { grid-column: 1 / -1; }
  .project dl { grid-template-columns: 1fr 1fr; }
}
"""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--domaine", help="nom de domaine pour afficher les sous-domaines prévus")
    parser.add_argument("--avec-tests", action="store_true", help="exécuter la suite de tests")
    args = parser.parse_args(argv)
    registry = json.loads((ROOT / "site" / "projets.json").read_text(encoding="utf-8"))
    generated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")
    head, body = render(registry, coordination(), commits(), lab_results(),
                        tests() if args.avec_tests else None,
                        args.domaine or registry.get("domaine"), generated)
    dist = ROOT / "site" / "dist"
    dist.mkdir(parents=True, exist_ok=True)
    (dist / "index.html").write_text(
        "<!doctype html>\n<html lang=\"fr\">\n<head>\n<meta charset=\"utf-8\">\n"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1, viewport-fit=cover\">\n"
        f"{head}\n</head>\n<body>{body}\n</body>\n</html>\n", encoding="utf-8")
    (dist / "apercu.html").write_text(f"{head}\n{body}\n", encoding="utf-8")
    print(f"Écrit: {dist / 'index.html'}\nÉcrit: {dist / 'apercu.html'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
