"""Commandes vocales dans les langues du site (hors français, géré par commands.py).

Principe volontairement simple et sûr :
  1. ordres généraux (original, réactiver, annuler, réinitialiser, plus fort, moins fort, autre version) ;
  2. sinon, repérage des personnages / décors / styles du catalogue cités dans la phrase.
Hors français, aucune description libre n'est acceptée : seuls les éléments du catalogue peuvent
être appliqués, ce qui évite qu'un mot non modéré dans une autre langue passe jusqu'au moteur.

Correspondance : texte et mots-clés passent par la même normalisation (scene.norm). Pour le chinois,
le japonais, le coréen, l'arabe et l'hindi (mots collés ou préfixes), recherche par sous-chaîne ;
ailleurs, début de mot (mot entier si le mot-clé fait moins de 5 caractères). Quand deux mots-clés
se chevauchent (« رائد فضاء » contient « فضاء »), le plus long l'emporte.
"""
from __future__ import annotations

import re

from .scene import norm

LANGS = ["en", "es", "pt", "de", "it", "nl", "ar", "tr", "ru", "zh", "ja", "ko", "hi", "id"]
SUBSTRING_LANGS = {"zh", "ja", "ko", "ar", "hi"}
# Langue de la reconnaissance vocale du navigateur (BCP 47)
SPEECH_LANG = {"fr": "fr-FR", "en": "en-US", "es": "es-ES", "pt": "pt-BR", "de": "de-DE", "it": "it-IT", "nl": "nl-NL",
               "ar": "ar-SA", "tr": "tr-TR", "ru": "ru-RU", "zh": "zh-CN", "ja": "ja-JP", "ko": "ko-KR", "hi": "hi-IN", "id": "id-ID"}

G = ["original", "resume", "undo", "reset", "stronger", "weaker", "variant"]

GLOBAL: dict[str, dict[str, list[str]]] = {
    "en": dict(zip(G, [["back to original", "original", "normal", "remove the effect", "stop the effect"],
                       ["resume", "reactivate", "effect back on", "turn the ai on"], ["undo"], ["reset", "start over"],
                       ["stronger", "more intense", "maximum"], ["weaker", "less intense", "softer", "subtler"],
                       ["another version", "other version", "variant", "regenerate"]])),
    "es": dict(zip(G, [["original", "quita el efecto"], ["reactiva", "activa el efecto"], ["deshacer", "deshaz", "anula"],
                       ["reinicia", "empieza de nuevo"], ["mas fuerte", "mas intenso"], ["mas suave", "menos fuerte", "menos intenso"],
                       ["otra version", "variante"]])),
    "pt": dict(zip(G, [["original", "tira o efeito"], ["reative", "reativa", "liga o efeito"], ["desfazer", "desfaz", "anula"],
                       ["reiniciar", "recomecar"], ["mais forte", "mais intenso"], ["mais suave", "menos forte", "menos intenso"],
                       ["outra versao", "variante"]])),
    "de": dict(zip(G, [["original", "effekt aus"], ["reaktivier", "effekt an", "wieder an"], ["ruckgangig"],
                       ["zurucksetzen", "neu starten"], ["starker", "intensiver", "maximal"], ["schwacher", "sanfter", "weniger stark"],
                       ["andere version", "variante"]])),
    "it": dict(zip(G, [["originale", "togli l'effetto"], ["riattiva", "rimetti l'effetto"], ["annulla"],
                       ["ricomincia", "reimposta"], ["piu forte", "piu intenso"], ["piu leggero", "meno forte", "piu delicato"],
                       ["altra versione", "variante"]])),
    "nl": dict(zip(G, [["origineel", "effect uit"], ["weer aan", "heractiveer", "effect aan"], ["ongedaan"],
                       ["opnieuw beginnen", "reset"], ["sterker", "intenser"], ["zwakker", "zachter", "minder sterk"],
                       ["andere versie", "variant"]])),
    "ar": dict(zip(G, [["الأصل", "أوقف التأثير"], ["أعد التأثير", "فعل الذكاء"], ["تراجع", "ألغ"],
                       ["ابدأ من جديد", "إعادة ضبط"], ["أقوى", "أكثر"], ["أخف", "أضعف", "أقل"], ["نسخة أخرى", "نسخة ثانية"]])),
    "tr": dict(zip(G, [["orijinal"], ["efekti ac", "tekrar ac", "yeniden etkinlestir"], ["geri al"],
                       ["sifirla", "bastan basla"], ["daha guclu", "daha fazla"], ["daha hafif", "daha az", "daha yumusak"],
                       ["baska versiyon", "farkli versiyon"]])),
    "ru": dict(zip(G, [["оригинал", "верни как было", "убери эффект"], ["включи эффект", "верни эффект"], ["отмени", "отмена"],
                       ["сброс", "начни заново"], ["сильнее", "интенсивнее", "мощнее"], ["слабее", "мягче", "потише"],
                       ["другой вариант", "другую версию"]])),
    "zh": dict(zip(G, [["原画面", "原图", "恢复原样", "关闭效果", "回到原"], ["重新开启", "打开效果"], ["撤销", "撤回"],
                       ["重置", "重新开始"], ["更强", "强一点", "加强"], ["弱一点", "减弱", "轻一点", "更弱"],
                       ["换一个", "另一个版本", "其他版本"]])),
    "ja": dict(zip(G, [["元に戻", "オリジナル", "効果を消"], ["効果をつけ", "再開"], ["取り消"],
                       ["リセット", "最初から"], ["もっと強", "強く"], ["弱く", "控えめ"], ["別のバージョン", "別バージョン", "違うバージョン"]])),
    "ko": dict(zip(G, [["원본", "원래대로", "효과 꺼"], ["효과 켜", "다시 켜"], ["취소"],
                       ["초기화", "처음부터"], ["더 강하게", "강하게"], ["약하게", "부드럽게"], ["다른 버전", "다른 걸로"]])),
    "hi": dict(zip(G, [["असली", "ओरिजिनल", "इफ़ेक्ट हटाओ"], ["इफ़ेक्ट चालू", "फिर से चालू"], ["पूर्ववत", "वापस लो"],
                       ["रीसेट", "शुरू से"], ["और तेज़", "ज़्यादा", "और ज़ोर"], ["हल्का", "कम करो", "धीमा"],
                       ["दूसरा वर्शन", "दूसरा संस्करण"]])),
    "id": dict(zip(G, [["asli", "matikan efek"], ["nyalakan efek", "aktifkan lagi"], ["batalkan", "urungkan"],
                       ["atur ulang", "mulai dari awal"], ["lebih kuat", "lebih intens"], ["lebih lemah", "lebih halus", "kurangi"],
                       ["versi lain", "variasi"]])),
}

C = ["chevalier", "robot", "pirate", "viking", "astronaute", "samourai", "sorcier", "zombie", "superheros", "dessin_anime"]
D = ["cyberpunk", "medieval", "espace", "jungle", "plage", "hiver", "desert", "sous_marin"]
S = ["anime", "bd", "peinture", "aquarelle", "pixel", "film_noir", "cinema", "pate_a_modeler"]


def _t(chars, decors, styles):
    return {"characters": dict(zip(C, chars)), "decors": dict(zip(D, decors)), "styles": dict(zip(S, styles))}


ITEMS: dict[str, dict[str, dict[str, list[str]]]] = {
    "en": _t([["knight"], ["robot", "android", "cyborg"], ["pirate"], ["viking"], ["astronaut", "spaceman"], ["samurai"],
              ["wizard", "sorcerer", "mage"], ["zombie"], ["superhero"], ["cartoon"]],
             [["cyberpunk", "neon city"], ["medieval", "castle"], ["outer space", "space", "spaceship", "galaxy"], ["jungle", "rainforest"],
              ["beach"], ["winter", "snow"], ["desert", "dunes"], ["underwater", "ocean", "coral"]],
             [["anime", "manga"], ["comic"], ["oil painting", "van gogh", "painting"], ["watercolor", "watercolour"], ["pixel"],
              ["film noir", "black and white"], ["cinematic", "movie"], ["claymation", "plasticine", "clay"]]),
    "es": _t([["caballero"], ["robot", "androide"], ["pirata"], ["vikingo"], ["astronauta"], ["samurai"], ["mago", "hechicero"],
              ["zombi", "zombie"], ["superheroe"], ["dibujo animado", "caricatura"]],
             [["cyberpunk"], ["medieval", "castillo"], ["espacio", "nave espacial", "galaxia"], ["jungla", "selva"], ["playa"],
              ["invierno", "nieve"], ["desierto", "dunas"], ["bajo el agua", "oceano", "arrecife"]],
             [["anime", "manga"], ["comic", "historieta"], ["pintura al oleo", "van gogh", "oleo"], ["acuarela"], ["pixel"],
              ["cine negro", "blanco y negro"], ["cinematografico", "pelicula"], ["plastilina", "claymation"]]),
    "pt": _t([["cavaleiro"], ["robo", "robot", "androide"], ["pirata"], ["viking"], ["astronauta"], ["samurai"], ["mago", "feiticeiro"],
              ["zumbi"], ["super-heroi", "super heroi"], ["desenho animado"]],
             [["cyberpunk"], ["medieval", "castelo"], ["espaco", "galaxia"], ["selva", "floresta tropical"], ["praia"],
              ["inverno", "neve"], ["deserto", "dunas"], ["debaixo d'agua", "oceano", "recife"]],
             [["anime", "manga"], ["quadrinhos", "hq"], ["pintura a oleo", "van gogh"], ["aquarela"], ["pixel"],
              ["filme noir", "preto e branco"], ["cinematografico", "filme"], ["massinha", "claymation"]]),
    "de": _t([["ritter"], ["roboter"], ["pirat"], ["wikinger"], ["astronaut"], ["samurai"], ["zauberer", "magier"], ["zombie"],
              ["superheld"], ["zeichentrick", "cartoon"]],
             [["cyberpunk"], ["mittelalter", "burg"], ["weltraum", "raumschiff", "galaxie"], ["dschungel", "regenwald"], ["strand"],
              ["winter", "schnee"], ["wuste", "dunen"], ["unterwasser", "ozean", "korallen"]],
             [["anime", "manga"], ["comic"], ["olgemalde", "van gogh"], ["aquarell"], ["pixel"], ["film noir", "schwarz-weiss", "schwarzweiss"],
              ["filmisch", "kino"], ["knete", "claymation"]]),
    "it": _t([["cavaliere"], ["robot", "androide"], ["pirata"], ["vichingo"], ["astronauta"], ["samurai"], ["mago", "stregone"],
              ["zombie", "zombi"], ["supereroe"], ["cartone animato"]],
             [["cyberpunk"], ["medievale", "castello"], ["spazio", "astronave", "galassia"], ["giungla"], ["spiaggia"],
              ["inverno", "neve"], ["deserto", "dune"], ["sott'acqua", "sottomarino", "oceano", "corallo"]],
             [["anime", "manga"], ["fumetto"], ["pittura a olio", "van gogh"], ["acquerello"], ["pixel"], ["film noir", "bianco e nero"],
              ["cinematografico"], ["plastilina", "claymation"]]),
    "nl": _t([["ridder"], ["robot"], ["piraat"], ["viking"], ["astronaut"], ["samoerai", "samurai"], ["tovenaar"], ["zombie"],
              ["superheld"], ["tekenfilm"]],
             [["cyberpunk"], ["middeleeuws", "kasteel"], ["ruimte", "ruimteschip"], ["jungle", "regenwoud"], ["strand"],
              ["winter", "sneeuw"], ["woestijn"], ["onderwater", "oceaan", "koraal"]],
             [["anime", "manga"], ["strip"], ["olieverf", "van gogh"], ["aquarel"], ["pixel"], ["film noir", "zwart-wit"],
              ["filmisch"], ["klei", "claymation"]]),
    "ar": _t([["فارس"], ["روبوت"], ["قرصان"], ["فايكنغ", "فايكنج"], ["رائد فضاء"], ["ساموراي"], ["ساحر"], ["زومبي"],
              ["بطل خارق"], ["كرتون", "رسوم متحركة"]],
             [["سايبربانك"], ["قلعة", "القرون الوسطى"], ["فضاء"], ["غابة استوائية", "أدغال"], ["شاطئ"], ["شتاء", "ثلج"], ["صحراء"],
              ["تحت الماء", "محيط", "شعاب مرجانية"]],
             [["أنمي", "انمي", "مانغا"], ["قصص مصورة", "كوميكس"], ["لوحة زيتية", "فان جوخ"], ["ألوان مائية"], ["بكسل"],
              ["فيلم نوار", "أبيض وأسود"], ["سينمائي"], ["صلصال"]]),
    "tr": _t([["sovalye"], ["robot"], ["korsan"], ["viking"], ["astronot"], ["samuray"], ["buyucu"], ["zombi"],
              ["super kahraman"], ["cizgi film"]],
             [["siberpunk", "cyberpunk"], ["ortacag", "kale"], ["uzay"], ["yagmur ormani", "orman"], ["plaj", "sahil"],
              ["kis", "kar"], ["col", "kum tepe"], ["su alti", "okyanus", "mercan"]],
             [["anime", "manga"], ["cizgi roman"], ["yagli boya", "van gogh"], ["suluboya", "sulu boya"], ["piksel"],
              ["kara film", "siyah beyaz"], ["sinematik"], ["oyun hamuru", "hamur"]]),
    "ru": _t([["рыцар"], ["робот"], ["пират"], ["викинг"], ["астронавт", "космонавт"], ["самура"], ["волшебник", "маг"], ["зомби"],
              ["супергеро"], ["мультяш", "мультфильм"]],
             [["киберпанк"], ["средневек", "замок"], ["космос", "космическ"], ["джунгл"], ["пляж"], ["зима", "зимний", "снег"],
              ["пустын"], ["под водой", "океан", "кораллов"]],
             [["аниме", "манга"], ["комикс"], ["живопис", "ван гог"], ["акварел"], ["пиксел"], ["нуар", "черно-бел"],
              ["кинематограф"], ["пластилин"]]),
    "zh": _t([["骑士"], ["机器人"], ["海盗"], ["维京"], ["宇航员"], ["武士"], ["巫师", "魔法师"], ["僵尸"], ["超级英雄"], ["卡通"]],
             [["赛博朋克"], ["中世纪", "城堡"], ["太空", "宇宙"], ["丛林", "雨林"], ["海滩"], ["冬天", "雪"], ["沙漠"], ["海底", "水下", "珊瑚"]],
             [["动漫", "动画风"], ["漫画"], ["油画", "梵高"], ["水彩"], ["像素"], ["黑色电影", "黑白"], ["电影感"], ["黏土", "橡皮泥"]]),
    "ja": _t([["騎士", "ナイト"], ["ロボット"], ["海賊"], ["バイキング", "ヴァイキング"], ["宇宙飛行士"], ["侍", "サムライ"],
              ["魔法使い", "魔術師"], ["ゾンビ"], ["スーパーヒーロー"], ["アニメキャラ", "カートゥーン"]],
             [["サイバーパンク"], ["中世", "城"], ["宇宙"], ["ジャングル"], ["ビーチ", "海辺"], ["冬", "雪"], ["砂漠"], ["海底", "水中", "サンゴ"]],
             [["アニメ"], ["漫画", "コミック"], ["油絵", "ゴッホ"], ["水彩"], ["ドット絵", "ピクセル"], ["フィルムノワール", "白黒"],
              ["映画風", "シネマ"], ["粘土", "クレイ"]]),
    "ko": _t([["기사", "나이트"], ["로봇"], ["해적"], ["바이킹"], ["우주비행사"], ["사무라이"], ["마법사"], ["좀비"], ["슈퍼히어로"],
              ["만화 캐릭터", "카툰"]],
             [["사이버펑크"], ["중세"], ["우주"], ["정글"], ["해변"], ["겨울"], ["사막"], ["바닷속", "수중", "산호"]],
             [["애니메이션", "애니"], ["만화"], ["유화", "고흐"], ["수채화"], ["픽셀"], ["필름 누아르", "흑백"], ["시네마틱", "영화 같은"],
              ["점토", "클레이"]]),
    "hi": _t([["योद्धा", "शूरवीर"], ["रोबोट"], ["समुद्री डाकू"], ["वाइकिंग"], ["अंतरिक्ष यात्री"], ["समुराई"], ["जादूगर"],
              ["ज़ॉम्बी", "जॉम्बी"], ["सुपरहीरो"], ["कार्टून"]],
             [["साइबरपंक"], ["मध्ययुगीन", "किला"], ["अंतरिक्ष"], ["जंगल"], ["समुद्र तट", "बीच"], ["सर्दी", "बर्फ़", "बर्फ"],
              ["रेगिस्तान"], ["पानी के नीचे", "मूंगा"]],
             [["एनीमे", "मंगा"], ["कॉमिक"], ["तैल चित्र", "वैन गॉग"], ["जलरंग"], ["पिक्सेल"], ["फ़िल्म नोयर", "ब्लैक एंड व्हाइट"],
              ["सिनेमाई"], ["मिट्टी", "क्ले"]]),
    "id": _t([["ksatria", "kesatria"], ["robot"], ["bajak laut"], ["viking"], ["astronot"], ["samurai"], ["penyihir"],
              ["zombi", "zombie"], ["pahlawan super"], ["kartun"]],
             [["cyberpunk"], ["abad pertengahan", "kastil"], ["luar angkasa", "antariksa"], ["hutan", "rimba"], ["pantai"],
              ["musim dingin", "salju"], ["gurun"], ["bawah laut", "terumbu"]],
             [["anime", "manga"], ["komik"], ["lukisan minyak", "van gogh"], ["cat air"], ["piksel"], ["film noir", "hitam putih"],
              ["sinematik"], ["tanah liat", "plastisin"]]),
}


def labels() -> dict:
    """Nom affichable de chaque élément du catalogue, par langue (premier mot-clé, majuscule initiale)."""
    return {lang: {cat: {k: (v[0][:1].upper() + v[0][1:]) for k, v in entries.items()} for cat, entries in ITEMS[lang].items()}
            for lang in LANGS}


def _pattern(lang: str, kw: str) -> re.Pattern:
    k = re.escape(norm(kw))
    if lang in SUBSTRING_LANGS:
        return re.compile(k)
    return re.compile(rf"(?<!\w){k}" + ("" if len(norm(kw)) >= 5 else r"(?!\w)"))


_COMPILED: dict[str, dict] = {}


def _compiled(lang: str) -> dict:
    if lang not in _COMPILED:
        glob = {g: [_pattern(lang, p) for p in GLOBAL[lang][g]] for g in G}
        items = [(cat, key, _pattern(lang, kw)) for cat, entries in ITEMS[lang].items() for key, kws in entries.items() for kw in kws]
        _COMPILED[lang] = {"global": glob, "items": items}
    return _COMPILED[lang]


def match_global(lang: str, text: str) -> str | None:
    t = norm(text)
    for g in G:  # ordre important : « original » avant le reste
        if any(p.search(t) for p in _compiled(lang)["global"][g]):
            return g
    return None


def match_items(lang: str, text: str) -> list[tuple[str, str]]:
    """Éléments du catalogue cités, sans chevauchement (le mot-clé le plus long gagne)."""
    t = norm(text)
    found = []
    for cat, key, p in _compiled(lang)["items"]:
        for m in p.finditer(t):
            found.append((m.start(), m.end(), cat, key))
    found.sort(key=lambda x: (-(x[1] - x[0]), x[0]))
    kept, out = [], []
    for s, e, cat, key in found:
        if any(s < ke and ks < e for ks, ke in kept):
            continue
        kept.append((s, e))
        if (cat, key) not in out:
            out.append((cat, key))
    return out
