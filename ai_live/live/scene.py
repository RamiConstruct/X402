"""État de scène du live : personnage, décor, style, intensité, bascule original, historique.

Le prompt envoyé au moteur est TOUJOURS reconstruit depuis cet état : une commande
vocale ne modifie qu'un champ, ce qui permet l'annulation et évite les dérives.
"""
from __future__ import annotations

import copy
import re
import unicodedata
from dataclasses import asdict, dataclass, field

# Intensité 1 (léger, garde la structure) → 5 (transformation totale).
# Sur une grille de 50 pas : indice élevé = retouche, indice bas = réécriture (doc Daydream).
STRENGTH_T_INDEX = {1: [38], 2: [30], 3: [22], 4: [14], 5: [8]}
DEFAULT_NEGATIVE = "blurry, low quality, flat, 2d, deformed, extra limbs, text, watermark"

CHARACTERS: dict[str, dict] = {
    "chevalier": {"label": "Chevalier", "keys": ["chevalier", "knight"], "prompt": "medieval knight in shining plate armor"},
    "robot": {"label": "Robot", "keys": ["robot", "androide", "cyborg"], "prompt": "chrome humanoid robot, glowing visor, mechanical details"},
    "pirate": {"label": "Pirate", "keys": ["pirate"], "prompt": "weathered pirate captain with tricorn hat and long coat"},
    "viking": {"label": "Viking", "keys": ["viking"], "prompt": "viking warrior with braided beard and fur cloak"},
    "astronaute": {"label": "Astronaute", "keys": ["astronaute", "cosmonaute", "astronaut"], "prompt": "astronaut in a detailed white space suit"},
    "samourai": {"label": "Samouraï", "keys": ["samourai", "samurai"], "prompt": "samurai in lacquered armor"},
    "sorcier": {"label": "Vieux sorcier", "keys": ["sorcier", "magicien", "wizard"], "prompt": "old wizard with long white beard and starry robe"},
    "zombie": {"label": "Zombie", "keys": ["zombie", "mort-vivant"], "prompt": "cartoon zombie, green skin, funny horror style"},
    "superheros": {"label": "Super-héros", "keys": ["super-heros", "superheros", "super heros", "superhero"], "prompt": "comic book superhero with cape and mask"},
    "dessin_anime": {"label": "Personnage de dessin animé", "keys": ["dessin anime", "cartoon", "pixar", "disney"], "prompt": "3d animated cartoon character, big expressive eyes"},
}

DECORS: dict[str, dict] = {
    "cyberpunk": {"label": "Ville cyberpunk", "keys": ["cyberpunk", "futuriste", "neon"], "prompt": "neon cyberpunk city at night, rain, holograms"},
    "medieval": {"label": "Ville médiévale", "keys": ["medieval", "moyen age", "chateau"], "prompt": "medieval castle town, cobblestone streets"},
    "espace": {"label": "Espace", "keys": ["espace", "station spatiale", "galaxie", "space"], "prompt": "inside a spaceship, stars and planets in the window"},
    "jungle": {"label": "Jungle", "keys": ["jungle", "foret tropicale"], "prompt": "dense tropical jungle, sunbeams"},
    "plage": {"label": "Plage tropicale", "keys": ["plage", "beach"], "prompt": "tropical beach at sunset"},
    "hiver": {"label": "Hiver enneigé", "keys": ["hiver", "neige", "snow"], "prompt": "snowy winter landscape, falling snow"},
    "desert": {"label": "Désert", "keys": ["desert", "sahara", "dunes"], "prompt": "golden desert dunes under a blazing sun"},
    "sous_marin": {"label": "Sous l'océan", "keys": ["sous l'eau", "ocean", "sous-marin", "aquarium"], "prompt": "underwater coral reef, fish, light rays"},
}

STYLES: dict[str, dict] = {
    "anime": {"label": "Anime", "keys": ["anime", "manga"], "prompt": "anime style, cel shading"},
    "bd": {"label": "Bande dessinée", "keys": ["bd", "bande dessinee", "comic"], "prompt": "comic book style, bold ink lines, halftone"},
    "peinture": {"label": "Peinture à l'huile", "keys": ["peinture", "huile", "van gogh", "oil painting"], "prompt": "oil painting, thick brush strokes"},
    "aquarelle": {"label": "Aquarelle", "keys": ["aquarelle", "watercolor"], "prompt": "soft watercolor painting"},
    "pixel": {"label": "Pixel art", "keys": ["pixel", "retro", "8 bit"], "prompt": "pixel art, 16-bit video game"},
    "film_noir": {"label": "Film noir", "keys": ["film noir", "noir et blanc"], "prompt": "black and white film noir, dramatic shadows"},
    "cinema": {"label": "Cinématique", "keys": ["cinema", "cinematique", "film"], "prompt": "cinematic lighting, 35mm film still"},
    "pate_a_modeler": {"label": "Pâte à modeler", "keys": ["pate a modeler", "claymation", "plasticine"], "prompt": "claymation, plasticine stop motion"},
}

# Personnalités publiques : uniquement en CARICATURE non photoréaliste, avec bandeau PARODIE.
PUBLIC_FIGURES = {
    "macron": "Emmanuel Macron", "trump": "Donald Trump", "biden": "Joe Biden", "poutine": "Vladimir Putin",
    "putin": "Vladimir Putin", "zelensky": "Volodymyr Zelensky", "musk": "Elon Musk", "obama": "Barack Obama",
    "le pen": "Marine Le Pen", "melenchon": "Jean-Luc Mélenchon", "mbappe": "Kylian Mbappé", "zidane": "Zinedine Zidane",
    "messi": "Lionel Messi", "ronaldo": "Cristiano Ronaldo", "tebboune": "Abdelmadjid Tebboune",
}
CARICATURE_STYLE = ("satirical caricature, exaggerated cartoon puppet, big head, illustrated, "
                    "non photorealistic, humorous")


def norm(text: str) -> str:
    t = unicodedata.normalize("NFKD", (text or "").lower())
    t = "".join(c for c in t if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", t).strip()


def find_in(catalog: dict[str, dict], text: str) -> str | None:
    t = norm(text)
    for key, item in catalog.items():
        if any(re.search(rf"\b{re.escape(norm(k))}\b", t) for k in item["keys"]):
            return key
    return None


def find_public_figure(text: str) -> str | None:
    t = norm(text)
    for k, name in PUBLIC_FIGURES.items():
        if re.search(rf"\b{re.escape(k)}\b", t):
            return name
    return None


@dataclass
class Scene:
    character: str | None = None       # clé de CHARACTERS
    character_free: str | None = None  # personnage décrit librement
    parody_of: str | None = None       # personnalité publique caricaturée
    decor: str | None = None
    decor_free: str | None = None
    style: str | None = None
    extras: list[str] = field(default_factory=list)
    strength: int = 4
    bypass: bool = False               # True = flux original affiché

    @property
    def parody(self) -> bool:
        return self.parody_of is not None

    def subject(self) -> str:
        if self.parody_of:
            return f"{CARICATURE_STYLE}, caricature of {self.parody_of}"
        if self.character:
            return CHARACTERS[self.character]["prompt"]
        if self.character_free:
            return self.character_free
        return "a person"

    def prompt(self) -> str:
        parts = [self.subject()]
        if self.decor:
            parts.append(DECORS[self.decor]["prompt"])
        elif self.decor_free:
            parts.append(f"background: {self.decor_free}")
        if self.style:
            parts.append(STYLES[self.style]["prompt"])
        parts += self.extras
        parts.append("high quality, detailed")
        return ", ".join(parts)

    def t_index_list(self) -> list[int]:
        return list(STRENGTH_T_INDEX[self.strength])

    def describe(self) -> dict:
        d = asdict(self)
        d.update(parody=self.parody, prompt=self.prompt(), t_index_list=self.t_index_list(),
                 character_label=(CHARACTERS[self.character]["label"] if self.character else
                                  (f"Caricature : {self.parody_of}" if self.parody_of else self.character_free)),
                 decor_label=DECORS[self.decor]["label"] if self.decor else self.decor_free,
                 style_label=STYLES[self.style]["label"] if self.style else None)
        return d


class SceneHistory:
    def __init__(self, scene: Scene | None = None, limit: int = 50) -> None:
        self.current = scene or Scene()
        self._past: list[Scene] = []
        self.limit = limit

    def apply(self, new: Scene) -> None:
        self._past.append(copy.deepcopy(self.current))
        self._past = self._past[-self.limit:]
        self.current = new

    def undo(self) -> bool:
        if not self._past:
            return False
        self.current = self._past.pop()
        return True

    def edit(self) -> Scene:
        return copy.deepcopy(self.current)
