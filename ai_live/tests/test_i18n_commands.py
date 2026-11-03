"""Commandes vocales dans les 15 langues du site."""
import pytest

from live.commands import apply_command
from live.i18n_commands import GLOBAL, ITEMS, LANGS
from live.scene import CHARACTERS, DECORS, STYLES, SceneHistory

CASES = [
    ("en", "turn me into a knight", "character", "chevalier"),
    ("en", "cyberpunk background", "decor", "cyberpunk"),
    ("es", "conviérteme en caballero", "character", "chevalier"),
    ("es", "estilo anime", "style", "anime"),
    ("pt", "me transforme em pirata", "character", "pirate"),
    ("de", "mach mich zum Ritter", "character", "chevalier"),
    ("de", "Kulisse Weltraum", "decor", "espace"),
    ("it", "trasformami in un samurai", "character", "samourai"),
    ("nl", "maak me een robot", "character", "robot"),
    ("ar", "حوّلني إلى فارس", "character", "chevalier"),
    ("ar", "خلفية صحراء", "decor", "desert"),
    ("tr", "beni şövalyeye dönüştür", "character", "chevalier"),
    ("ru", "сделай меня рыцарем", "character", "chevalier"),
    ("ru", "в стиле аниме", "style", "anime"),
    ("zh", "把我变成骑士", "character", "chevalier"),
    ("zh", "赛博朋克背景", "decor", "cyberpunk"),
    ("ja", "騎士にして", "character", "chevalier"),
    ("ja", "アニメ風に", "style", "anime"),
    ("ko", "나를 기사로 바꿔 줘", "character", "chevalier"),
    ("hi", "मुझे योद्धा बना दो", "character", "chevalier"),
    ("id", "ubah aku jadi ksatria", "character", "chevalier"),
]


@pytest.mark.parametrize("lang,text,field,key", CASES)
def test_items(lang, text, field, key):
    h = SceneHistory()
    r = apply_command(h, text, lang=lang)
    assert r.ok, (lang, text, r.message)
    assert getattr(h.current, field) == key


@pytest.mark.parametrize("lang,stronger,original", [
    ("en", "stronger", "back to original"), ("es", "más fuerte", "vuelve al original"),
    ("de", "stärker", "zurück zum Original"), ("ar", "أقوى", "عُد إلى الأصل"),
    ("zh", "更强一点", "回到原画面"), ("ja", "もっと強く", "元に戻して"), ("ru", "сильнее", "верни оригинал"),
])
def test_global_commands(lang, stronger, original):
    h = SceneHistory()
    assert apply_command(h, stronger, lang=lang).ok and h.current.strength == 5
    assert apply_command(h, original, lang=lang).ok and h.current.bypass is True


def test_combined_and_unknown():
    h = SceneHistory()
    r = apply_command(h, "turn me into a viking, snowy winter background", lang="en")
    assert r.ok and h.current.character == "viking" and h.current.decor == "hiver"
    before = h.current
    r = apply_command(h, "make me look like my neighbour", lang="en")
    assert not r.ok and h.current == before  # hors catalogue : refusé hors français (pas de texte libre non modéré)


def test_tables_complete():
    for lang in LANGS:
        assert set(GLOBAL[lang]) >= {"original", "resume", "undo", "stronger", "weaker", "variant"}, lang
        for cat, keys in (("characters", CHARACTERS), ("decors", DECORS), ("styles", STYLES)):
            missing = [k for k in keys if not ITEMS[lang][cat].get(k)]
            assert not missing, (lang, cat, missing)


def test_french_unchanged():
    h = SceneHistory()
    assert apply_command(h, "transforme-moi en chevalier", lang="fr").ok and h.current.character == "chevalier"
