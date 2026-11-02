import argparse

import uvicorn

from .app import create_worker_app

ap = argparse.ArgumentParser(prog="live.worker")
ap.add_argument("--host", default="127.0.0.1")
ap.add_argument("--port", type=int, default=8890)
a = ap.parse_args()
uvicorn.run(create_worker_app(), host=a.host, port=a.port)
