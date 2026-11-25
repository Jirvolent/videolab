"""Intro/outro YUVASI: kullanıcı kendi intro ve outro videosunu seçer; her videonun başına/sonuna otomatik eklenir.
Program intro/outro ÜRETMEZ. Ayarlar SQLite'ta saklanır (RecentProjects.set/get)."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, asdict

from .model import Clip, Timeline
from ..media.ffmpeg import probe


@dataclass
class Branding:
    intro_path: str = ""
    outro_path: str = ""
    intro_enabled: bool = True
    outro_enabled: bool = True
    transition: str = "none"          # intro/outro ile ana video arasındaki geçiş
    transition_dur: float = 0.5

    def save(self, store) -> None: store.set("branding", json.dumps(asdict(self)))

    @staticmethod
    def load(store) -> "Branding":
        raw = store.get("branding")
        return Branding(**json.loads(raw)) if raw else Branding()


def intro_offset(b: Branding) -> float:
    """Ana içeriğin nihai videoda kaç saniye sonra başladığı (intro süresi − geçiş çakışması); intro yoksa 0."""
    if not (b.intro_enabled and b.intro_path and os.path.exists(b.intro_path)):
        return 0.0
    return probe(b.intro_path).duration - (b.transition_dur if b.transition != "none" else 0.0)


def with_branding(tl: Timeline, b: Branding) -> Timeline:
    """Timeline'ın KOPYASINI döndürür: V1'in başına intro, sonuna outro eklenir (proje değişmez).
    Dosya yoksa ilgili parça sessizce atlanır; bu yüzden eksik dosya dışa aktarmayı bozmaz."""
    out = Timeline.from_dict(tl.to_dict())
    main = next((t for t in out.tracks if t.kind == "video" and t.clips), None)
    if main is None:
        return out
    use_intro = b.intro_enabled and b.intro_path and os.path.exists(b.intro_path)
    use_outro = b.outro_enabled and b.outro_path and os.path.exists(b.outro_path)
    if use_intro:
        d = probe(b.intro_path).duration
        shift = intro_offset(b)
        for t in out.tracks:                                   # tüm kanalları (müzik, meme) ana içeriğin yeni başlangıcına kaydır
            for c in t.clips: c.start += shift
        first = min(main.clips, key=lambda c: c.start)
        first.transition, first.transition_dur = b.transition, b.transition_dur
        main.clips.insert(0, Clip(b.intro_path, 0, d, 0, label="intro"))
    if use_outro:
        d = probe(b.outro_path).duration
        end = max(c.end for c in main.clips)
        main.clips.append(Clip(b.outro_path, 0, d, end, transition=b.transition, transition_dur=b.transition_dur, label="outro"))
    main.sort()
    return out
