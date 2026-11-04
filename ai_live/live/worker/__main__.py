import argparse
import logging

import uvicorn

from .app import create_worker_app

ap = argparse.ArgumentParser(prog="live.worker")
ap.add_argument("--host", default="127.0.0.1")
ap.add_argument("--port", type=int, default=8890)
a = ap.parse_args()
# Affiche les journaux du worker (résumé des durées par étape, diffusion) dans le terminal.
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
uvicorn.run(create_worker_app(), host=a.host, port=a.port)
