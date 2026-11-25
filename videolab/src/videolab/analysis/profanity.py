"""Küfür algılama (TR + EN). Türkçe ekleri, yazım varyasyonlarını ve uzatmaları (siiiktir) ele alır.
Sözlük kullanıcı tarafından düzenlenebilir (JSON). Eşleşme kelime-kökü + ek mantığıyla yapılır."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

# Ö/Ü/Ş/Ç/Ğ katlanır; ı ile i AYRI tutulur ki "sıkıntı" gibi masum kelimeler "sik" ile karışmasın.
_FOLD = str.maketrans({"ö": "o", "ü": "u", "ş": "s", "ç": "c", "ğ": "g", "â": "a", "î": "i", "û": "u"})
_LEET = str.maketrans({"@": "a", "0": "o", "$": "s", "3": "e", "1": "i", "!": "i", "*": "", "-": "", "_": ""})


_DIAC = set("öüşçğ")


def normalize(word: str, fold: bool = True) -> str:
    w = word.replace("İ", "i").replace("I", "ı").lower()   # Türkçe büyük/küçük harf kuralı
    if fold:
        w = w.translate(_FOLD)
    w = w.translate(_LEET)
    w = re.sub(r"[^a-zıöüşçğ]", "", w)
    return re.sub(r"(.)\1{2,}", r"\1", w)                    # "siiiiktir" -> "siktir" (3+ tekrar)


# Türkçe çekim/yapım ekleri (kök + ek eşleşmesi için; bilinçli olarak kısıtlı)
_TR_SUFFIX = re.compile(
    r"^(?:nun|nin|nın|na|ne|ni|nı|nu|nda|nde|nden|ndan|yla|yle|ya|ye|yi|yı|yu|ler|lar|i|ı|u|e|a|in|ın|un|un|im|ım|um|iz|ız|si|sı|su|nin|nın|yi|yı|ye|ya|de|da|den|dan|te|ta|ten|tan|le|la|ymis|ymış|"
    r"ci|cı|cu|cu|lik|lık|luk|luk|im|ım|sin|sın|siniz|sınız|ti|tı|di|dı|ir|ır|er|ar|ecek|acak|ip|ıp|erek|arak|ma|me|mek|mak|"
    r"tir|tır|ti|tı|miş|mış|mus|mis|yor|iyor|ıyor|uyor)+$")


@dataclass
class Entry:
    stem: str
    lang: str = "tr"
    suffixes: bool = True          # False: yalnızca tam eşleşme (veya çoğul -s/-es/-ing/-ed)
    enabled: bool = True


DEFAULT_ENTRIES = [
    # Türkçe
    Entry("amk"), Entry("aq", suffixes=False), Entry("amq"), Entry("orospu"), Entry("orospuç"),
    Entry("siktir"), Entry("sikerim"), Entry("sikeyim"), Entry("sikik"), Entry("sikim"),
    Entry("yarrak"), Entry("yarak", suffixes=False), Entry("piç"), Entry("göt"), Entry("götün"),
    Entry("ibne"), Entry("pezevenk"), Entry("amina"), Entry("amcık"), Entry("gavat"),
    Entry("şerefsiz"), Entry("puşt"), Entry("mal", suffixes=False),
    # İngilizce
    Entry("fuck", "en", False), Entry("fucking", "en", False), Entry("fucker", "en", False),
    Entry("shit", "en", False), Entry("bitch", "en", False), Entry("asshole", "en", False),
    Entry("bastard", "en", False), Entry("dick", "en", False), Entry("cunt", "en", False),
    Entry("motherfucker", "en", False), Entry("bullshit", "en", False), Entry("whore", "en", False),
]
# "mal" gibi çok anlamlı bir kelime varsayılan olarak kapalı gelir; kullanıcı açabilir.
for _e in DEFAULT_ENTRIES:
    if _e.stem == "mal":
        _e.enabled = False

DEFAULT_WHITELIST = {"sikke", "siklet", "sikleti", "gotik", "gotikler", "picnic", "dickens", "analiz", "malzeme", "malik", "mali"}
_EN_INFLECT = re.compile(r"^(s|es|ed|ing|er|ers|y)?$")


@dataclass
class Word:
    text: str
    start: float
    end: float


@dataclass
class Hit:
    word: str
    start: float
    end: float
    matched: str
    approved: bool = True     # kullanıcı tek tek onaylar/reddeder


@dataclass
class ProfanityFilter:
    entries: list[Entry] = field(default_factory=lambda: [Entry(**e.__dict__) for e in DEFAULT_ENTRIES])
    whitelist: set[str] = field(default_factory=lambda: set(DEFAULT_WHITELIST))

    def is_profane(self, token: str) -> str | None:
        n_fold, n_raw = normalize(token), normalize(token, fold=False)
        if len(n_fold) < 2 or n_fold in {normalize(w) for w in self.whitelist}:
            return None
        for e in self.entries:
            if not e.enabled:
                continue
            strict = any(ch in _DIAC for ch in e.stem.lower())   # göt/piç: "got" ≠ "göt"
            # strict girdiler önce ö/ç'li biçimle, sonra (yalnızca ekli kelimelerde) ASCII yazımla denenir: "gotune"
            tries = [(n_raw, normalize(e.stem, fold=False), True)] if strict else [(n_fold, normalize(e.stem), True)]
            if strict:
                tries.append((n_fold, normalize(e.stem), False))
            for n, stem, allow_exact in tries:
                if n == stem and allow_exact:
                    return e.stem
                if n.startswith(stem) and len(n) > len(stem):
                    rest = n[len(stem):]
                    if e.lang == "tr" and e.suffixes and len(stem) >= 3 and _TR_SUFFIX.match(rest):
                        return e.stem
                    if e.lang == "en" and _EN_INFLECT.match(rest):
                        return e.stem
        return None

    def scan(self, words: list[Word]) -> list[Hit]:
        hits = []
        for w in words:
            m = self.is_profane(w.text)
            if m:
                hits.append(Hit(w.text.strip(), w.start, w.end, m))
        return hits

    # ---- kullanıcı sözlüğü ----
    def add(self, stem: str, lang: str = "tr", suffixes: bool = True) -> None:
        self.entries.append(Entry(stem, lang, suffixes))

    def remove(self, stem: str) -> None:
        self.entries = [e for e in self.entries if e.stem != stem]

    def save(self, path: str) -> None:
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"entries": [e.__dict__ for e in self.entries], "whitelist": sorted(self.whitelist)},
                      f, ensure_ascii=False, indent=1)

    @staticmethod
    def load(path: str) -> "ProfanityFilter":
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
        return ProfanityFilter([Entry(**e) for e in d["entries"]], set(d["whitelist"]))
