# Installer le Laboratoire sur ton PC et dans Claude

## 1. Claude Code sur le PC (pour coder et mettre en ligne)
1. Installer les outils : **Git** (git-scm.com), **Python 3.11+** (python.org, cocher « Add to PATH » sous Windows),
   **Node.js 20+** (nodejs.org). Rust est facultatif (seulement pour recompiler `motion.wasm`).
2. Installer **Claude Code** : application de bureau Claude (claude.ai/download, onglet Code) ou en ligne de commande
   (voir code.claude.com/docs, rubrique installation) :
   - Mac / Linux : `curl -fsSL https://claude.ai/install.sh | bash`
   - Windows (PowerShell) : `irm https://claude.ai/install.ps1 | iex`
3. Récupérer le code :
   ```sh
   git clone https://github.com/RamiConstruct/X402
   cd X402
   git checkout claude/ai-live-studio-architecture-2td5sl
   ```
   Sans accès GitHub : `git clone x402.bundle X402` (fichier d'export fourni), puis la même commande `checkout`.
4. Tout installer et vérifier automatiquement :
   - Mac / Linux : `bash tools/installer_pc.sh`
   - Windows : `powershell -ExecutionPolicy Bypass -File tools\installer_pc.ps1`
5. Lancer `claude` dans le dossier : il lit `CLAUDE.md` (mémoire du projet) et reprend avec tout le contexte.

## 2. Les clés (jamais dans la discussion)
Une sauvegarde privée complète est dans ton compte Cloudflare : **Workers KV → coffre-labo →
`sauvegarde-2026-11-03.tgz.b64`** (clés, mots de passe, configuration et données du serveur).
Pour la récupérer sur le PC : copier la valeur dans un fichier `coffre.b64`, puis
`base64 -d coffre.b64 > coffre.tgz && tar xzf coffre.tgz` (le fichier `coffre/LISEZMOI.txt` décrit chaque clé).
Ne mets jamais ce dossier dans le dépôt.

Variables d'environnement à créer (Claude Code sur le web : menu de l'environnement → Edit → Network secrets ;
sur le PC : variables d'environnement du système ou fichier `.env` hors du dépôt) :
`LABO_SSH_KEY`, `OCI_CONFIG_JSON`, `OCI_API_KEY_PEM`, `LABO_TOKEN`, `SENT_TOKEN`, `DAYDREAM_API_KEY`,
plus tard `VAST_API_KEY` / `RUNPOD_API_KEY`, `STRIPE_SECRET_KEY`, `STRIPE_WEBHOOK_SECRET`.
Conseil : régénérer les clés qui sont passées dans la discussion (Daydream, clé SSH) et ne garder que les nouvelles.

## 3. Le projet claude.ai (pour discuter et décider)
Ajouter dans « Project knowledge » : `CLAUDE.md`, `docs/GUIDE_CLAUDE.md`, `docs/SAUVEGARDE.md`, `docs/ai_live_studio/OBJECTIF_1440P_90.md`,
`ETUDE_INSTANTANEITE.md`, `BENCHMARK_ASIE.md`, `PLAN_INVESTISSEMENT.md`, `docs/VISION.md`.
Un projet ne se met pas à jour seul : remplacer les fichiers quand ils changent sur GitHub.
