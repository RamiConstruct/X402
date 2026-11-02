"""Parcours complet : inscription → import → devis → acceptation → traitement → téléchargement."""
import httpx
import pytest

from studio import ledger, media
from studio.engines import Registry
from studio.providers import ProviderError, StepContext
from studio.providers.runway import RunwayAdapter


def auth(client, email="pilote@example.com"):
    r = client.post("/api/auth/register", json={"email": email, "password": "motdepasse-solide"})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


def upload(client, h, clip):
    with clip.open("rb") as f:
        r = client.post("/api/assets", headers=h, files={"file": ("plage.mp4", f, "video/mp4")})
    assert r.status_code == 200, r.text
    return r.json()


def test_full_flow_partial_range(client, studio, clip):
    h = auth(client)
    asset = upload(client, h, clip)
    assert asset["duration_s"] == pytest.approx(4.0, abs=0.2)

    q = client.post("/api/quotes", headers=h, json={"asset_id": asset["id"], "prompt": "Remplace le ciel par une aurore boréale",
                                                    "start_s": 1.0, "end_s": 3.0}).json()
    opt = q["options"][0]
    assert opt["available"] and opt["simulated"]
    assert opt["steps"][0]["duration_s"] == 2.0
    price = opt["total_price_credits"]
    assert price == 101  # 2 s × 0,28 USD = 0,56 USD (minimum) × 1,8 = 1,008 USD → 101 crédits (arrondi supérieur)

    # 100 crédits de bienvenue : insuffisant
    r = client.post(f"/api/quotes/{q['id']}/accept", headers=h, json={"option_id": opt["id"]})
    assert r.status_code == 402
    client.post("/api/dev/credits", headers=h, json={"credits": 500})
    job = client.post(f"/api/quotes/{q['id']}/accept", headers=h, json={"option_id": opt["id"]}).json()
    again = client.post(f"/api/quotes/{q['id']}/accept", headers=h, json={"option_id": opt["id"]}).json()
    assert again["id"] == job["id"]  # double clic = même tâche, une seule réservation
    assert client.get("/api/me", headers=h).json()["credits_held"] == price

    assert studio.process_pending() == 1
    j = client.get(f"/api/jobs/{job['id']}", headers=h).json()
    assert j["status"] == "succeeded", j
    assert j["charged_credits"] == price
    me = client.get("/api/me", headers=h).json()
    assert me["credits_available"] == 600 - price and me["credits_held"] == 0

    out = client.get(f"/api/assets/{j['output_asset_id']}", headers=h).json()
    assert out["parent_id"] == asset["id"] and out["root_id"] == asset["id"]
    assert out["duration_s"] == pytest.approx(asset["duration_s"], abs=0.05)  # segment réintégré : durée totale conservée
    assert (out["width"], out["height"]) == (640, 360)
    dl = client.get(out["download_url"])
    assert dl.status_code == 200 and len(dl.content) > 1000
    assert client.get(out["download_url"].replace("sig=", "sig=0")).status_code == 403

    projects = client.get("/api/projects", headers=h).json()
    assert len(projects) == 1 and len(projects[0]["versions"]) == 2

    # Même demande = résultat en cache, gratuit
    q2 = client.post("/api/quotes", headers=h, json={"asset_id": asset["id"], "prompt": "Remplace le ciel par une aurore boréale",
                                                     "start_s": 1.0, "end_s": 3.0}).json()
    assert q2["options"][0]["cache_hit"] and q2["options"][0]["total_price_credits"] == 0

    with studio.db.session() as s:
        ledger.check_invariants(s)


def test_local_ops_whole_video(client, studio, clip):
    h = auth(client)
    asset = upload(client, h, clip)
    q = client.post("/api/quotes", headers=h, json={"asset_id": asset["id"], "prompt": "format vertical et noir et blanc"}).json()
    opt = q["options"][0]
    assert [s["capability"] for s in opt["steps"]] == ["style.bw", "format.vertical"]
    job = client.post(f"/api/quotes/{q['id']}/accept", headers=h, json={"option_id": opt["id"]}).json()
    studio.process_pending()
    j = client.get(f"/api/jobs/{job['id']}", headers=h).json()
    assert j["status"] == "succeeded", j
    out = client.get(f"/api/assets/{j['output_asset_id']}", headers=h).json()
    assert out["height"] == 360 and out["width"] == 202  # 360 × 9/16 = 202,5 → arrondi pair inférieur


def test_failure_refunds(client, studio, clip):
    h = auth(client)
    asset = upload(client, h, clip)
    client.post("/api/dev/credits", headers=h, json={"credits": 500})
    q = client.post("/api/quotes", headers=h, json={"asset_id": asset["id"], "prompt": "test __echec_simule__"}).json()
    opt = q["options"][0]
    job = client.post(f"/api/quotes/{q['id']}/accept", headers=h, json={"option_id": opt["id"]}).json()
    studio.process_pending()
    j = client.get(f"/api/jobs/{job['id']}", headers=h).json()
    assert j["status"] == "failed" and j["charged_credits"] == 0
    assert client.get("/api/me", headers=h).json()["credits_available"] == 600
    assert any("remboursés" in e["message"] for e in j["events"])


def test_moderation_blocks_before_any_cost(client, clip):
    h = auth(client)
    asset = upload(client, h, clip)
    r = client.post("/api/quotes", headers=h, json={"asset_id": asset["id"], "prompt": "rends cette personne nue"})
    assert r.status_code == 422


def test_isolation_between_users(client, clip):
    h1 = auth(client, "a@example.com")
    asset = upload(client, h1, clip)
    h2 = auth(client, "b@example.com")
    assert client.get(f"/api/assets/{asset['id']}", headers=h2).status_code == 404
    r = client.post("/api/quotes", headers=h2, json={"asset_id": asset["id"], "prompt": "noir et blanc"})
    assert r.status_code == 404


def test_rejects_non_video(client, tmp_path):
    h = auth(client)
    bad = tmp_path / "x.mp4"
    bad.write_bytes(b"pas une video")
    with bad.open("rb") as f:
        r = client.post("/api/assets", headers=h, files={"file": ("x.mp4", f, "video/mp4")})
    assert r.status_code == 400


def test_recover_stale_refunds(client, studio, clip):
    h = auth(client)
    asset = upload(client, h, clip)
    q = client.post("/api/quotes", headers=h, json={"asset_id": asset["id"], "prompt": "noir et blanc"}).json()
    job = client.post(f"/api/quotes/{q['id']}/accept", headers=h, json={"option_id": q["options"][0]["id"]}).json()
    assert studio.claim_next() == job["id"]  # simulé : le serveur plante pendant l'exécution
    assert studio.recover_stale() == 1
    assert client.get(f"/api/jobs/{job['id']}", headers=h).json()["status"] == "failed"
    assert client.get("/api/me", headers=h).json()["credits_available"] == 100


def test_runway_adapter_protocol(tmp_path, settings, clip):
    """Vérifie l'adaptateur Runway contre un serveur simulé (aucun appel réseau réel)."""
    calls = []

    def handler(req: httpx.Request):
        calls.append((req.method, req.url.path))
        if req.method == "POST":
            assert req.headers["Authorization"] == "Bearer k" and "X-Runway-Version" in req.headers
            return httpx.Response(200, json={"id": "task123"})
        if req.url.path.endswith("/v1/tasks/task123"):
            return httpx.Response(200, json={"status": "SUCCEEDED", "output": ["https://cdn.example/out.mp4"]})
        return httpx.Response(404)

    reg = Registry.load(settings.engines_dir)
    adapter = RunwayAdapter(client=httpx.Client(transport=httpx.MockTransport(handler)), sleep=lambda s: None)
    import studio.providers.runway as rw
    rw.download = lambda url, dst: dst.write_bytes(clip.read_bytes())
    out = tmp_path / "o.mp4"
    res = adapter.run(StepContext(engine=reg.get("runway.aleph"), capability="edit.prompt", input_path=clip,
                                  output_path=out, prompt="ciel", duration_s=4.0, idempotency_key="k1", api_key="k"))
    assert res.external_id == "task123" and out.exists()
    assert res.actual_cost_micro == 4 * 280_000
    assert calls[0] == ("POST", "/v1/video_to_video")


def test_runway_adapter_failure(settings, clip, tmp_path):
    def handler(req):
        if req.method == "POST":
            return httpx.Response(200, json={"id": "t"})
        return httpx.Response(200, json={"status": "FAILED", "failure": "contenu refusé"})
    reg = Registry.load(settings.engines_dir)
    adapter = RunwayAdapter(client=httpx.Client(transport=httpx.MockTransport(handler)), sleep=lambda s: None)
    with pytest.raises(ProviderError, match="contenu refusé"):
        adapter.run(StepContext(engine=reg.get("runway.aleph"), capability="edit.prompt", input_path=clip,
                                output_path=tmp_path / "o.mp4", prompt="x", duration_s=2, idempotency_key="k", api_key="k"))


def test_media_probe(clip):
    pr = media.probe(clip)
    assert pr.width == 640 and pr.has_audio
