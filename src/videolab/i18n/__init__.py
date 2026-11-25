"""Çoklu dil desteği: i18n/<dil>.json dosyaları. Yeni dil eklemek için yeni bir JSON dosyası yeterli."""
import json
from pathlib import Path

_DIR = Path(__file__).parent
_lang = "tr"
_data: dict[str, str] = {}


def set_language(lang: str) -> None:
    global _lang, _data
    path = _DIR / f"{lang}.json"
    _lang = lang if path.exists() else "tr"
    _data = json.loads((_DIR / f"{_lang}.json").read_text(encoding="utf-8"))


def tr(key: str, **kw) -> str:
    if not _data:
        set_language(_lang)
    s = _data.get(key, key)
    return s.format(**kw) if kw else s
