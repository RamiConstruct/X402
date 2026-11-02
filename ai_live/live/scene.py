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
DEFAULT_NEGATIVE = ("blurry, low quality, lowres, jpeg artifacts, noisy, deformed face, distorted face, "
                    "bad anatomy, extra limbs, extra fingers, mutated hands, text, watermark, logo, frame")
# Finition ajoutée quand aucun style n'est choisi : rendu net et lumineux, stable d'une image à l'autre.
DEFAULT_FINISH = "cinematic lighting, sharp focus, highly detailed"
DEFAULT_SEED = 42  # graine fixe : moins de scintillement entre les images

CHARACTERS: dict[str, dict] = {
    "chevalier": {"label": "Chevalier", "keys": ["chevalier", "knight"], "prompt": "medieval knight in ornate polished plate armor, engraved steel, flowing red cape"},
    "robot": {"label": "Robot", "keys": ["robot", "androide", "cyborg"], "prompt": "sleek chrome humanoid robot, glowing blue visor, intricate mechanical joints"},
    "pirate": {"label": "Pirate", "keys": ["pirate"], "prompt": "weathered pirate captain, tricorn hat, long leather coat, gold earrings"},
    "viking": {"label": "Viking", "keys": ["viking"], "prompt": "fierce viking warrior, braided beard, fur cloak, leather and iron armor"},
    "astronaute": {"label": "Astronaute", "keys": ["astronaute", "cosmonaute", "astronaut"], "prompt": "astronaut in a detailed white space suit, reflective helmet visor, mission patches"},
    "samourai": {"label": "Samouraï", "keys": ["samourai", "samurai"], "prompt": "samurai in red lacquered armor, kabuto helmet, silk cords"},
    "sorcier": {"label": "Vieux sorcier", "keys": ["sorcier", "magicien", "wizard"], "prompt": "wise old wizard, long white beard, deep blue starry robe, glowing staff"},
    "zombie": {"label": "Zombie", "keys": ["zombie", "mort-vivant"], "prompt": "cartoon zombie, green skin, tattered clothes, funny horror style"},
    "superheros": {"label": "Super-héros", "keys": ["super-heros", "superheros", "super heros", "superhero"], "prompt": "comic book superhero, sleek suit with emblem, flowing cape, mask"},
    "dessin_anime": {"label": "Personnage de dessin animé", "keys": ["dessin anime", "cartoon", "pixar", "disney"], "prompt": "3d animated cartoon character, big expressive eyes, soft studio lighting"},
}

DECORS: dict[str, dict] = {
    "cyberpunk": {"label": "Ville cyberpunk", "keys": ["cyberpunk", "futuriste", "neon"], "prompt": "neon cyberpunk city at night, rain-soaked streets, holographic signs, pink and cyan glow"},
    "medieval": {"label": "Ville médiévale", "keys": ["medieval", "moyen age", "chateau"], "prompt": "medieval castle courtyard, stone walls, banners, warm torchlight"},
    "espace": {"label": "Espace", "keys": ["espace", "station spatiale", "galaxie", "space"], "prompt": "inside a spaceship bridge, stars and a giant planet through the window"},
    "jungle": {"label": "Jungle", "keys": ["jungle", "foret tropicale"], "prompt": "lush tropical jungle, giant leaves, golden sunbeams through mist"},
    "plage": {"label": "Plage tropicale", "keys": ["plage", "beach"], "prompt": "tropical beach at golden hour, palm trees, turquoise sea"},
    "hiver": {"label": "Hiver enneigé", "keys": ["hiver", "neige", "snow"], "prompt": "snowy winter forest, falling snowflakes, soft blue light"},
    "desert": {"label": "Désert", "keys": ["desert", "sahara", "dunes"], "prompt": "golden sahara dunes under a blazing sun, heat haze"},
    "sous_marin": {"label": "Sous l'océan", "keys": ["sous l'eau", "ocean", "sous-marin", "aquarium"], "prompt": "underwater coral reef, colorful fish, shimmering light rays"},
}

STYLES: dict[str, dict] = {
    "anime": {"label": "Anime", "keys": ["anime", "manga"], "prompt": "anime style, cel shading, clean line art, studio ghibli colors"},
    "bd": {"label": "Bande dessinée", "keys": ["bd", "bande dessinee", "comic"], "prompt": "comic book style, bold ink lines, halftone dots, flat vivid colors"},
    "peinture": {"label": "Peinture à l'huile", "keys": ["peinture", "huile", "van gogh", "oil painting"], "prompt": "oil painting, thick impasto brush strokes, rich colors"},
    "aquarelle": {"label": "Aquarelle", "keys": ["aquarelle", "watercolor"], "prompt": "soft watercolor painting, paper texture, gentle color bleeding"},
    "pixel": {"label": "Pixel art", "keys": ["pixel", "retro", "8 bit"], "prompt": "pixel art, 16-bit video game sprite style, limited palette"},
    "film_noir": {"label": "Film noir", "keys": ["film noir", "noir et blanc"], "prompt": "black and white film noir, dramatic hard shadows, high contrast"},
    "cinema": {"label": "Cinématique", "keys": ["cinema", "cinematique", "film"], "prompt": "cinematic film still, anamorphic lens, teal and orange grading, 35mm"},
    "pate_a_modeler": {"label": "Pâte à modeler", "keys": ["pate a modeler", "claymation", "plasticine"], "prompt": "claymation, plasticine stop motion, handmade texture"},
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
    seed: int = DEFAULT_SEED           # change avec la commande « autre version »

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
        parts.append(DEFAULT_FINISH if not self.style else "high quality, detailed")
        return ", ".join(parts)

    def t_index_list(self, passes: int = 1) -> list[int]:
        """1 passe = rapide ; 2 passes = 2e retouche plus fine (meilleure qualité, un peu plus lent)."""
        t = STRENGTH_T_INDEX[self.strength][0]
        if passes <= 1:
            return [t]
        return [t, min(45, t + (49 - t) // 2)]

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
