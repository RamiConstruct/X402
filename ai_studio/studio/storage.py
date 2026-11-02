"""Stockage de fichiers adressé par clé. Implémentation locale ; une implémentation
S3/R2 (URLs présignées, upload multipart direct navigateur → bucket) suivra la même interface."""
from __future__ import annotations

import hashlib
import shutil
from pathlib import Path


class LocalStorage:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def path(self, key: str) -> Path:
        p = (self.root / key).resolve()
        if self.root.resolve() not in p.parents:
            raise ValueError("clé de stockage invalide")
        return p

    def put_file(self, key: str, src: Path) -> None:
        dst = self.path(key)
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, dst)

    def exists(self, key: str) -> bool:
        return self.path(key).exists()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()
