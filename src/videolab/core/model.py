"""Timeline veri modeli. Tüm süreler saniye cinsindendir; kare hassasiyeti snap() ile sağlanır."""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field, asdict, replace
from typing import Optional

EPS = 1e-6


def new_id() -> str:
    return uuid.uuid4().hex[:10]


def snap(t: float, fps: float) -> float:
    """Zamanı en yakın kareye yuvarlar."""
    return round(t * fps) / fps


@dataclass
class Clip:
    media_path: str
    source_in: float          # kaynak dosyada başlangıç (sn)
    source_out: float         # kaynak dosyada bitiş (sn)
    start: float = 0.0        # timeline üzerinde başlangıç (sn)
    speed: float = 1.0
    volume: float = 1.0
    fade_in: float = 0.0
    fade_out: float = 0.0
    id: str = field(default_factory=new_id)
    transition: str = "none"        # bir ÖNCEKİ klipten bu klibe geçiş (exporter.TRANSITIONS anahtarları)
    transition_dur: float = 0.5
    pos_x: float = 0.5              # bindirme (V2+) konumu: 0..1 (0=sol/üst, 1=sağ/alt)
    pos_y: float = 0.5
    scale: float = 0.3              # bindirme genişliği: çıktı genişliğinin oranı
    label: str = ""                 # kütüphane adı vb. (arayüzde gösterim)

    @property
    def duration(self) -> float:
        return (self.source_out - self.source_in) / self.speed

    @property
    def end(self) -> float:
        return self.start + self.duration

    def to_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_dict(d: dict) -> "Clip":
        return Clip(**d)


@dataclass
class Track:
    kind: str                 # "video" | "audio"
    name: str
    clips: list[Clip] = field(default_factory=list)
    id: str = field(default_factory=new_id)

    def sort(self) -> None:
        self.clips.sort(key=lambda c: c.start)

    def to_dict(self) -> dict:
        return {"kind": self.kind, "name": self.name, "id": self.id,
                "clips": [c.to_dict() for c in self.clips]}

    @staticmethod
    def from_dict(d: dict) -> "Track":
        return Track(kind=d["kind"], name=d["name"], id=d["id"],
                     clips=[Clip.from_dict(c) for c in d["clips"]])


class Timeline:
    def __init__(self, fps: float = 30.0):
        self.fps = fps
        self.tracks: list[Track] = [
            Track("video", "V1"), Track("video", "V2"),
            Track("audio", "A1"), Track("audio", "A2"),
        ]

    # ---- sorgular ----
    def track(self, track_id: str) -> Track:
        for t in self.tracks:
            if t.id == track_id:
                return t
        raise KeyError(track_id)

    def find_clip(self, clip_id: str) -> tuple[Track, Clip]:
        for t in self.tracks:
            for c in t.clips:
                if c.id == clip_id:
                    return t, c
        raise KeyError(clip_id)

    @property
    def duration(self) -> float:
        return max((c.end for t in self.tracks for c in t.clips), default=0.0)

    # ---- düzenleme ----
    def add_clip(self, track_id: str, clip: Clip) -> Clip:
        t = self.track(track_id)
        t.clips.append(clip)
        t.sort()
        return clip

    def delete_clip(self, clip_id: str) -> None:
        t, c = self.find_clip(clip_id)
        t.clips.remove(c)

    def move_clip(self, clip_id: str, new_start: float, new_track_id: Optional[str] = None) -> None:
        t, c = self.find_clip(clip_id)
        c.start = max(0.0, snap(new_start, self.fps))
        if new_track_id and new_track_id != t.id:
            dst = self.track(new_track_id)
            if dst.kind != t.kind:
                raise ValueError("Klip yalnızca aynı türdeki kanala taşınabilir")
            t.clips.remove(c)
            dst.clips.append(c)
            dst.sort()
        else:
            t.sort()

    def split_clip(self, clip_id: str, at: float) -> tuple[Clip, Clip]:
        """Klibi timeline zamanı `at` noktasında ikiye böler."""
        t, c = self.find_clip(clip_id)
        at = snap(at, self.fps)
        if not (c.start + EPS < at < c.end - EPS):
            raise ValueError("Bölme noktası klibin içinde olmalı")
        src_cut = c.source_in + (at - c.start) * c.speed
        right = replace(c, id=new_id(), source_in=src_cut, start=at, fade_in=0.0, transition="none")
        c.source_out = src_cut
        c.fade_out = 0.0
        t.clips.append(right)
        t.sort()
        return c, right

    def remove_range(self, track_ids: list[str], start: float, end: float, ripple: bool = True) -> None:
        """[start,end) aralığını verilen kanallardan çıkarır; ripple ise sonrasını sola kaydırır.
        Sessizlik kesme ve 'bölümü çıkar' işlemleri bunu kullanır."""
        cut = end - start
        if cut <= EPS:
            return
        for tid in track_ids:
            t = self.track(tid)
            new_clips: list[Clip] = []
            for c in t.clips:
                if c.end <= start + EPS:
                    new_clips.append(c)
                elif c.start >= end - EPS:
                    if ripple:
                        c.start -= cut
                    new_clips.append(c)
                else:
                    if c.start < start - EPS:
                        new_clips.append(replace(c, id=new_id(), source_out=c.source_in + (start - c.start) * c.speed,
                                                 fade_out=0.0))
                    if c.end > end + EPS:
                        r_src_in = c.source_in + (end - c.start) * c.speed
                        new_clips.append(replace(c, id=new_id(), source_in=r_src_in, start=start if ripple else end,
                                                 fade_in=0.0, transition="none"))
            t.clips = new_clips
            t.sort()

    # ---- serileştirme ----
    def to_dict(self) -> dict:
        return {"fps": self.fps, "tracks": [t.to_dict() for t in self.tracks]}

    @staticmethod
    def from_dict(d: dict) -> "Timeline":
        tl = Timeline(d.get("fps", 30.0))
        tl.tracks = [Track.from_dict(t) for t in d["tracks"]]
        return tl
