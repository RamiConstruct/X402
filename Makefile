PYTHON ?= python3

.PHONY: test discover compare providers simulate clean studio-install studio-test studio-run live-install live-test live-run

test:
	$(PYTHON) -m unittest discover -s tests -t . -v

discover:
	$(PYTHON) -m atelier_x402 discover --out sorties

compare:
	$(PYTHON) -m atelier_x402 compare

providers:
	$(PYTHON) -m atelier_x402 providers

simulate:
	$(PYTHON) -m atelier_x402 simulate-x402 --all

clean:
	rm -rf sorties
	find . -name __pycache__ -type d -prune -exec rm -rf {} +

# --- AI STUDIO (pilote A) ---
studio-install:
	cd ai_studio && python3 -m venv .venv && .venv/bin/pip install -e '.[dev]'

studio-test:
	cd ai_studio && .venv/bin/python -m pytest -q

studio-run:
	cd ai_studio && .venv/bin/python -m studio serve

# --- AI LIVE (pilote B) ---
live-install:
	cd ai_live && python3 -m venv .venv && .venv/bin/pip install -e '.[dev]'

live-test:
	cd ai_live && .venv/bin/python -m pytest -q

live-run:
	cd ai_live && .venv/bin/python -m live

# --- QUALITÉ (outils GitHub figés, lancés via uvx : rien à installer) ---
# Détail et licences : .claude/kit/KIT.md
RUFF        = uvx --quiet ruff@0.17.5
SHELLCHECK  = uvx --quiet --from shellcheck-py==0.11.0.1 shellcheck
SECRETS     = uvx --quiet --from detect-secrets==1.5.0 detect-secrets-hook
PIP_AUDIT   = uvx --quiet pip-audit@2.10.1
SEMGREP     = uvx --quiet semgrep@1.185.0

.PHONY: lint shell secrets audit semgrep check scan

lint:
	$(RUFF) check .

shell:
	git ls-files '*.sh' | grep -v '^\.claude/skills/' | xargs $(SHELLCHECK) --severity=warning

# Échoue seulement sur un secret potentiel absent de .secrets.baseline.
secrets:
	git ls-files -z | grep -zv '^\.claude/' | xargs -0 $(SECRETS) --baseline .secrets.baseline

# Failles connues dans les dépendances des deux pilotes (réseau requis).
audit:
	@for p in ai_studio ai_live; do \
		echo "== $$p"; t=$$(mktemp); \
		uv pip compile --quiet --universal $$p/pyproject.toml --extra dev -o $$t >/dev/null \
		&& $(PIP_AUDIT) --disable-pip --no-deps -r $$t; rc=$$?; rm -f $$t; [ $$rc -eq 0 ] || exit $$rc; \
	done

# Analyse de sécurité du code (réseau requis pour télécharger les règles).
semgrep:
	$(SEMGREP) scan --config p/python --config p/secrets --metrics off --error --quiet \
		--exclude .claude --exclude fixtures --exclude tests .

# Rapide, hors ligne une fois les outils en cache : à lancer avant chaque commit.
check: lint shell secrets test

# Plus lent, en ligne : à lancer avant une mise en production.
scan: audit semgrep
