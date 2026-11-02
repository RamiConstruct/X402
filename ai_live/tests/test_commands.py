from live.commands import apply_command, set_preset
from live.scene import SceneHistory


def run(*texts):
    h = SceneHistory()
    results = [apply_command(h, t) for t in texts]
    return h, results


def test_character_known_and_free():
    h, r = run("Transforme-moi en chevalier")
    assert r[0].ok and h.current.character == "chevalier"
    assert "plate armor" in h.current.prompt()
    h, r = run("deviens un dragon rouge")
    assert h.current.character is None and h.current.character_free == "dragon rouge"


def test_decor_style_weather_combine():
    h, _ = run("transforme-moi en robot", "change le décor en ville cyberpunk", "style anime", "ajoute de la neige")
    s = h.current
    assert (s.character, s.decor, s.style) == ("robot", "cyberpunk", "anime")
    assert "heavy snowfall" in s.extras
    p = s.prompt()
    assert "robot" in p and "cyberpunk" in p and "anime" in p


def test_revert_resume_undo():
    h, r = run("transforme-moi en pirate", "retour à l'original")
    assert h.current.bypass and h.current.character == "pirate"  # la scène est conservée
    apply_command(h, "remets l'effet")
    assert not h.current.bypass
    apply_command(h, "annule")
    assert h.current.bypass
    apply_command(h, "annule")
    apply_command(h, "annule")
    assert h.current.character is None


def test_strength():
    h, _ = run("plus fort", "plus fort", "plus fort")
    assert h.current.strength == 5 and h.current.t_index_list() == [8]
    apply_command(h, "plus subtil")
    assert h.current.strength == 4


def test_public_figure_becomes_labelled_caricature():
    h, r = run("Transforme-moi en Emmanuel Macron")
    s = h.current
    assert r[0].ok and s.parody and s.parody_of == "Emmanuel Macron"
    assert "caricature" in s.prompt() and "non photorealistic" in s.prompt()
    assert "PARODIE" in r[0].message
    apply_command(h, "transforme-moi en viking")
    assert not h.current.parody  # changer de personnage retire la parodie


def test_blocked():
    h, r = run("rends-moi nu")
    assert not r[0].ok and r[0].blocked == "contenu sexuel"
    assert h.current.prompt().startswith("a person")


def test_single_words_and_unknown():
    h, r = run("cyberpunk")
    assert h.current.decor == "cyberpunk"
    h, r = run("blablabla incompréhensible")
    assert not r[0].ok


def test_remove_weather():
    h, _ = run("ajoute de la neige", "ajoute de la pluie", "enlève la neige")
    assert h.current.extras == ["rain falling"]


def test_preset():
    h = SceneHistory()
    assert set_preset(h, "style", "pixel").ok and h.current.style == "pixel"
    assert not set_preset(h, "style", "inconnu").ok


def test_compound_command():
    h, r = run("transforme-moi en chevalier et décor cyberpunk, style anime")
    s = h.current
    assert r[0].ok and (s.character, s.decor, s.style) == ("chevalier", "cyberpunk", "anime")
    h, r = run("style film noir et blanc")
    assert h.current.style == "film_noir"
    h, r = run("transforme-moi en pirate et rends-moi nu")
    assert not r[0].ok and r[0].blocked
    assert h.current.character is None  # rien n'est appliqué partiellement
