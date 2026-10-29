PYTHON ?= python3

.PHONY: test discover compare providers simulate clean

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
