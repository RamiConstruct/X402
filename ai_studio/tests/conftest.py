from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from studio import media  # noqa: E402
from studio.config import Settings  # noqa: E402
from studio.service import Studio  # noqa: E402


@pytest.fixture
def settings(tmp_path, monkeypatch):
    for k in ("STUDIO_ALLOW_PAID_PROVIDERS", "RUNWAYML_API_SECRET", "FAL_KEY", "STUDIO_PUBLIC_BASE_URL"):
        monkeypatch.delenv(k, raising=False)
    return Settings(data_dir=tmp_path / "data", secret_key="test-secret", dev_mode=True, signup_credits=100,
                    run_worker=False)


@pytest.fixture
def studio(settings):
    return Studio(settings)


@pytest.fixture(scope="session")
def clip(tmp_path_factory) -> Path:
    if not media.available():
        pytest.skip("FFmpeg absent")
    p = tmp_path_factory.mktemp("media") / "clip.mp4"
    media.make_test_clip(p, seconds=4.0)
    return p


@pytest.fixture
def client(settings, studio):
    from fastapi.testclient import TestClient
    from studio.api import create_app
    with TestClient(create_app(settings, studio)) as c:
        yield c
