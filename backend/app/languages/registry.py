"""Every language Lingo OS can teach, in one place.

A learner adds languages from this catalogue (first run, then Settings → Languages). Adding one downloads what it
needs (a word-splitting model and a dictionary) in the background; the rows of the `languages` table are the
languages this learner has added (`enabled = 1`), in the order they were added.

The catalogue is ordered by number of speakers (native + second language, approximate, Ethnologue 2025).
"""

from __future__ import annotations

from dataclasses import dataclass, field

SPACY_RELEASES = "https://github.com/explosion/spacy-models/releases/download"
WTY = "https://huggingface.co/datasets/daxida/wty-release/resolve/main/latest/dict"


@dataclass(frozen=True)
class Model:
    """A spaCy pipeline downloaded into data/models/<name> (unless it's installed as a Python package)."""

    name: str
    version: str
    size_mb: int

    @property
    def url(self) -> str:
        return f"{SPACY_RELEASES}/{self.name}-{self.version}/{self.name}-{self.version}-py3-none-any.whl"


@dataclass(frozen=True)
class Dictionary:
    """A Yomitan dictionary zip, downloaded into data/dictionaries and imported."""

    file: str
    url: str
    size_mb: int


@dataclass(frozen=True)
class Variant:
    id: str
    label: str
    locale: str  # voice and speech recognition


@dataclass(frozen=True)
class LanguageSpec:
    code: str
    name: str
    native_name: str
    speakers_millions: int
    accent: str
    accent_ink: str
    script: str  # latin | cyrillic | hangul | han | japanese | devanagari | bengali | arabic
    divisor: float  # hours are divided by this to get "Spanish-equivalent hours" (FSI course lengths, English speakers)
    pack: str  # word splitter: de | es | ja | spacy | ko | zh
    variants: tuple[Variant, ...]
    dictionary: Dictionary
    model: Model | None = None  # None: the splitter ships with the app
    writing_mode: str = "horizontal-tb"
    direction: str = "ltr"
    spaced: bool = True  # words separated by spaces
    cased: bool = True  # has upper and lower case
    wiki_page: str | None = None  # Comprehensible Input Wiki page
    level_alt: str | None = None  # a second level scale shown next to CEFR (JLPT for Japanese)
    dictionary_lemmas: bool = False  # the model's lemmas are unreliable: prefer the dictionary's "form of" entries
    names: tuple[str, ...] = field(default=())  # what the language is called in titles ("German", "Deutsch", …)

    @property
    def default_variant(self) -> Variant:
        return self.variants[0]

    def variant(self, variant_id: str | None) -> Variant:
        return next((v for v in self.variants if v.id == variant_id), self.default_variant)


def _wty(code: str, size_mb: int) -> Dictionary:
    return Dictionary(f"wty-{code}-en.zip", f"{WTY}/{code}/en/wty-{code}-en.zip", size_mb)


CATALOG: tuple[LanguageSpec, ...] = (
    LanguageSpec(
        "zh", "Mandarin Chinese", "中文", 1184, "#f87171", "#2a0606", "han", 3.0, "zh",
        (Variant("cn", "Simplified (Mainland China)", "zh-CN"), Variant("tw", "Traditional (Taiwan)", "zh-TW")),
        _wty("zh", 21), Model("zh_core_web_sm", "3.8.0", 49), spaced=False, cased=False, wiki_page="Mandarin_Chinese",
        names=("chinese", "mandarin", "chinesisch", "chino", "chinois", "cinese", "chinês", "китайский", "중국어", "中国語", "中文", "汉语", "漢語", "普通话"),
    ),
    LanguageSpec(
        "hi", "Hindi", "हिन्दी", 609, "#fb923c", "#2a1203", "devanagari", 1.83, "hi",
        (Variant("in", "India", "hi-IN"),), _wty("hi", 5), wiki_page="Hindi", cased=False, dictionary_lemmas=True,
        names=("hindi", "हिन्दी", "हिंदी", "ヒンディー語", "힌디어", "印地语"),
    ),
    LanguageSpec(
        "es", "Spanish", "Español", 558, "#ff8a73", "#2a0f08", "latin", 1.0, "es",
        (Variant("es", "Spain", "es-ES"), Variant("mx", "Mexico", "es-MX")), _wty("es", 21), wiki_page="Spanish",
        names=("spanish", "español", "espanol", "spanisch", "castellano", "espagnol", "spagnolo", "espanhol", "испанский", "스페인어", "スペイン語", "西班牙语"),
    ),
    LanguageSpec(
        "ar", "Arabic", "العربية", 335, "#34d399", "#04241a", "arabic", 3.0, "ar",
        (Variant("msa", "Modern Standard Arabic", "ar-SA"), Variant("eg", "Egyptian Arabic", "ar-EG")), _wty("ar", 13),
        direction="rtl", cased=False, wiki_page="Arabic", dictionary_lemmas=True,
        names=("arabic", "العربية", "arabisch", "árabe", "arabe", "арабский", "아랍어", "アラビア語", "阿拉伯语"),
    ),
    LanguageSpec(
        "fr", "French", "Français", 312, "#60a5fa", "#04162e", "latin", 1.0, "spacy",
        (Variant("fr", "France", "fr-FR"), Variant("ca", "Canada", "fr-CA")), _wty("fr", 11), Model("fr_core_news_sm", "3.8.0", 16),
        wiki_page="French",
        names=("french", "français", "francais", "französisch", "francés", "frances", "francese", "francês", "французский", "프랑스어", "フランス語", "法语"),
    ),
    LanguageSpec(
        "bn", "Bengali", "বাংলা", 284, "#2dd4bf", "#032420", "bengali", 1.83, "bn",
        (Variant("bd", "Bangladesh", "bn-BD"), Variant("in", "India (West Bengal)", "bn-IN")), _wty("bn", 1),
        cased=False, dictionary_lemmas=True, names=("bengali", "bangla", "বাংলা", "ベンガル語", "벵골어", "孟加拉语"),
    ),
    LanguageSpec(
        "pt", "Portuguese", "Português", 267, "#a3e635", "#172204", "latin", 1.0, "spacy",
        (Variant("br", "Brazil", "pt-BR"), Variant("pt", "Portugal", "pt-PT")), _wty("pt", 11), Model("pt_core_news_sm", "3.8.0", 13),
        wiki_page="Portuguese", dictionary_lemmas=True,
        names=("portuguese", "português", "portugues", "portugiesisch", "portugués", "portugais", "portoghese", "португальский", "포르투갈어", "ポルトガル語", "葡萄牙语"),
    ),
    LanguageSpec(
        "ru", "Russian", "Русский", 253, "#c084fc", "#1e0631", "cyrillic", 1.83, "spacy",
        (Variant("ru", "Russia", "ru-RU"),), _wty("ru", 26), Model("ru_core_news_sm", "3.8.0", 15), wiki_page="Russian",
        names=("russian", "русский", "russisch", "ruso", "russe", "russo", "러시아어", "ロシア語", "俄语"),
    ),
    LanguageSpec(
        "de", "German", "Deutsch", 134, "#f5b443", "#1a1300", "latin", 1.33, "de",
        (Variant("de", "Germany", "de-DE"), Variant("at", "Austria", "de-AT"), Variant("ch", "Switzerland", "de-CH")),
        _wty("de", 17), wiki_page="German",
        names=("german", "deutsch", "allemand", "alemán", "aleman", "tedesco", "alemão", "немецкий", "독일어", "ドイツ語", "德语"),
    ),
    LanguageSpec(
        "ja", "Japanese", "日本語", 126, "#a5b4fc", "#0f1330", "japanese", 3.0, "ja",
        (Variant("jp", "Japan", "ja-JP"),),
        Dictionary("jitendex-yomitan.zip", "https://github.com/stephenmk/stephenmk.github.io/releases/latest/download/jitendex-yomitan.zip", 39),
        writing_mode="vertical-rl", spaced=False, cased=False, wiki_page="Japanese", level_alt="jlpt",
        names=("japanese", "japanisch", "japonés", "japones", "japonais", "giapponese", "japonês", "японский", "일본어", "日本語", "nihongo", "にほんご", "日语"),
    ),
    LanguageSpec(
        "ko", "Korean", "한국어", 82, "#f472b6", "#2c0618", "hangul", 3.0, "ko",
        (Variant("kr", "South Korea", "ko-KR"),), _wty("ko", 7), Model("ko_core_news_sm", "3.8.0", 15), cased=False,
        wiki_page="Korean",
        names=("korean", "한국어", "koreanisch", "coreano", "coréen", "coreen", "корейский", "韓国語", "韩语", "hangul"),
    ),
    LanguageSpec(
        "it", "Italian", "Italiano", 68, "#4ade80", "#052310", "latin", 1.0, "spacy",
        (Variant("it", "Italy", "it-IT"),), _wty("it", 17), Model("it_core_news_sm", "3.8.0", 13), wiki_page="Italian",
        dictionary_lemmas=True,
        names=("italian", "italiano", "italienisch", "italien", "итальянский", "이탈리아어", "イタリア語", "意大利语"),
    ),
    LanguageSpec(
        "ro", "Romanian", "Română", 25, "#fde047", "#231d02", "latin", 1.0, "spacy",
        (Variant("ro", "Romania", "ro-RO"),), _wty("ro", 12), Model("ro_core_news_sm", "3.8.0", 13), wiki_page="Romanian",
        dictionary_lemmas=True,
        names=("romanian", "română", "rumänisch", "rumano", "roumain", "rumeno", "romeno", "румынский", "루마니아어", "ルーマニア語", "罗马尼亚语"),
    ),
)

BY_CODE: dict[str, LanguageSpec] = {spec.code: spec for spec in CATALOG}
# Languages whose word splitter is built (the rest are listed as "coming soon").
AVAILABLE = frozenset({"zh", "hi", "es", "ar", "fr", "bn", "pt", "ru", "de", "ja", "ko", "it", "ro"})


def spec(code: str) -> LanguageSpec:
    try:
        return BY_CODE[code]
    except KeyError:
        raise KeyError(f"no language '{code}' in the catalogue") from None


def get(code: str) -> LanguageSpec | None:
    return BY_CODE.get(code)
