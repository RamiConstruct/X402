import argparse

import uvicorn

from .server import create_app

ap = argparse.ArgumentParser(prog="live")
ap.add_argument("--host", default="127.0.0.1")
ap.add_argument("--port", type=int, default=8780)
a = ap.parse_args()
uvicorn.run(create_app(), host=a.host, port=a.port)
