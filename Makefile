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
