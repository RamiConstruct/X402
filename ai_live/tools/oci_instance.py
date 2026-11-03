"""Pilote minimal de l'API Oracle Cloud (OCI) : état et redémarrage de l'instance du laboratoire.

Signature des requêtes « HTTP Signatures » d'OCI faite à la main (pas besoin du SDK oci).

Configuration (variables d'environnement ou fichier au format ~/.oci/config, section [DEFAULT]) :
  OCI_USER, OCI_FINGERPRINT, OCI_TENANCY, OCI_REGION, OCI_KEY_FILE (clé privée PEM)
  OCI_CONFIG=<chemin du fichier de config> (facultatif)

Usage :
  python tools/oci_instance.py list                  # instances du compte (racine du compte)
  python tools/oci_instance.py status <ocid>
  python tools/oci_instance.py reboot <ocid>         # SOFTRESET (arrêt propre puis démarrage)
  python tools/oci_instance.py start <ocid>
"""
from __future__ import annotations

import base64
import configparser
import email.utils
import hashlib
import json
import os
import sys
from urllib.parse import urlsplit

import httpx
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding


def load_config() -> dict:
    cfg = {}
    path = os.environ.get("OCI_CONFIG")
    if path and os.path.exists(path):
        cp = configparser.ConfigParser()
        cp.read(path)
        sec = cp["DEFAULT"]
        cfg = {"user": sec.get("user"), "fingerprint": sec.get("fingerprint"), "tenancy": sec.get("tenancy"),
               "region": sec.get("region"), "key_file": sec.get("key_file")}
    for k, env in (("user", "OCI_USER"), ("fingerprint", "OCI_FINGERPRINT"), ("tenancy", "OCI_TENANCY"),
                   ("region", "OCI_REGION"), ("key_file", "OCI_KEY_FILE")):
        cfg[k] = os.environ.get(env) or cfg.get(k)
    missing = [k for k, v in cfg.items() if not v]
    if missing:
        raise SystemExit(f"configuration OCI incomplète : {', '.join(missing)}")
    cfg["key_file"] = os.path.expanduser(cfg["key_file"])
    return cfg


def sign_headers(cfg: dict, method: str, url: str, body: bytes = b"") -> dict:
    """En-têtes signés selon la spécification OCI (draft-cavage-http-signatures-08, rsa-sha256)."""
    u = urlsplit(url)
    path = u.path + (f"?{u.query}" if u.query else "")
    headers = {"date": email.utils.formatdate(usegmt=True), "host": u.netloc}
    names = ["date", "(request-target)", "host"]
    if method.upper() in ("POST", "PUT", "PATCH"):
        headers["content-type"] = "application/json"
        headers["content-length"] = str(len(body))
        headers["x-content-sha256"] = base64.b64encode(hashlib.sha256(body).digest()).decode()
        names += ["content-length", "content-type", "x-content-sha256"]
    lines = []
    for n in names:
        lines.append(f"(request-target): {method.lower()} {path}" if n == "(request-target)" else f"{n}: {headers[n]}")
    key = serialization.load_pem_private_key(open(cfg["key_file"], "rb").read(), password=None)
    sig = base64.b64encode(key.sign("\n".join(lines).encode(), padding.PKCS1v15(), hashes.SHA256())).decode()
    key_id = f"{cfg['tenancy']}/{cfg['user']}/{cfg['fingerprint']}"
    headers["authorization"] = (f'Signature version="1",keyId="{key_id}",algorithm="rsa-sha256",'
                                f'headers="{" ".join(names)}",signature="{sig}"')
    return headers


def call(cfg: dict, method: str, path: str, body: dict | None = None) -> dict | list:
    url = f"https://iaas.{cfg['region']}.oraclecloud.com/20160918{path}"
    data = json.dumps(body).encode() if body is not None else b""
    r = httpx.request(method, url, headers=sign_headers(cfg, method, url, data), content=data or None, timeout=30)
    if r.status_code >= 400:
        raise SystemExit(f"Oracle a refusé ({r.status_code}) : {r.text[:400]}")
    return r.json() if r.content else {}


def main() -> None:
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    cfg = load_config()
    cmd = sys.argv[1]
    if cmd == "list":
        for i in call(cfg, "GET", f"/instances?compartmentId={cfg['tenancy']}"):
            print(i["lifecycleState"], i["displayName"], i["shape"], i["id"])
    elif cmd == "status":
        i = call(cfg, "GET", f"/instances/{sys.argv[2]}")
        print(i["lifecycleState"], i["displayName"], i["shape"])
    elif cmd in ("reboot", "start"):
        action = "SOFTRESET" if cmd == "reboot" else "START"
        i = call(cfg, "POST", f"/instances/{sys.argv[2]}?action={action}")
        print("demandé :", action, "→", i.get("lifecycleState"))
    else:
        raise SystemExit(__doc__)


if __name__ == "__main__":
    main()
