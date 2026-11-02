from decimal import Decimal

from studio import moderation, quotes
from studio.config import Settings
from studio.engines import Pricing, Registry
from studio.planner import plan


def caps(prompt):
    return [s.capability for s in plan(prompt)]


def test_local_only():
    assert caps("Transforme cette vidéo horizontale en format vertical") == ["format.vertical"]
    assert caps("Passe en noir et blanc puis au ralenti") == ["style.bw", "speed.slow"]


def test_generative_with_local_tail():
    steps = plan("Supprime les voitures et passe en noir et blanc")
    assert [s.capability for s in steps] == ["edit.prompt", "style.bw"]
    assert steps[0].prompt == "Supprime les voitures"


def test_pure_generative_keeps_full_prompt():
    steps = plan("Remplace le ciel par un ciel étoilé et ajoute de la neige")
    assert len(steps) == 1 and steps[0].capability == "edit.prompt"
    assert steps[0].prompt == "Remplace le ciel par un ciel étoilé et ajoute de la neige"


def test_contradiction_last_wins():
    assert caps("tons chauds, puis finalement plus froid") == ["style.cool"]


def test_moderation():
    assert not moderation.check_prompt("rends la personne nue").allowed
    assert moderation.check_prompt("remplace le ciel").allowed


def test_pricing_rounding():
    p = Pricing(unit="second", usd_per_unit=Decimal("0.28"), min_charge_usd=Decimal("0.56"), markup=Decimal("1.8"),
                min_price_credits=1, verified_on=None, source=None)
    assert p.cost_micro(1.0) == 560_000            # minimum de facturation
    assert p.cost_micro(4.2) == 5 * 280_000        # seconde entamée = due
    assert p.price_credits(p.cost_micro(4.2)) == 252  # 1.40 USD × 1.8 = 2.52 USD


def test_routing_excludes_paid_without_permission(tmp_path):
    s = Settings(data_dir=tmp_path, secret_key="x", allow_paid_providers=False)
    reg = Registry.load(s.engines_dir)
    ok, excluded = reg.candidates("edit.prompt", 5, s)
    assert [e.id for e in ok] == ["sim.video_edit"]
    assert any(x["engine"] == "runway.aleph" for x in excluded)


def test_routing_paid_needs_key(tmp_path):
    s = Settings(data_dir=tmp_path, secret_key="x", allow_paid_providers=True, runway_api_key="k")
    reg = Registry.load(s.engines_dir)
    opts = quotes.build_options(plan("remplace le ciel"), reg, s, asset_sha="a", asset_duration=10, start=0, end=5,
                                cache_lookup=lambda k: False)
    # Le simulateur n'est jamais proposé à côté d'un vrai fournisseur ; un seul moteur → une seule option.
    assert len(opts) == 1 and opts[0]["label"] == "Recommandé"
    assert opts[0]["steps"][0]["engine_id"] == "runway.aleph"
    assert not opts[0]["simulated"]


def test_duration_limit(tmp_path):
    s = Settings(data_dir=tmp_path, secret_key="x")
    reg = Registry.load(s.engines_dir)
    ok, excluded = reg.candidates("edit.prompt", 45, s)
    assert ok == [] and any("durée" in x["reason"] for x in excluded)
