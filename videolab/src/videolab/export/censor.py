"""Bip / sessize alma / efekt ile sansür için FFmpeg ses filtresi üretir."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class CensorRegion:
    start: float            # timeline/ses zamanı (sn)
    end: float
    mode: str = "beep"      # "beep" | "mute" | "sfx"
    pre: float = 0.0        # bip başlangıcını ayarla (negatif = erken)
    post: float = 0.0       # bip bitişini ayarla (pozitif = geç)
    sfx_path: str | None = None

    @property
    def a(self) -> float:
        return max(0.0, self.start + self.pre)

    @property
    def b(self) -> float:
        return self.end + self.post


def beep_filter(regions: list[CensorRegion], in_label: str = "0:a", out_label: str = "aout",
                freq: int = 1000, beep_gain: float = 0.35, rate: int = 48000) -> tuple[list[str], list[str]]:
    """(filter_complex parçaları, ek -i girdileri) döndürür.
    Orijinal ses bölgede susturulur; bip/efekt üzerine karıştırılır. Bip kelimenin TAMAMINI kapsar."""
    active = [r for r in regions if r.b > r.a]
    if not active:
        return [f"[{in_label}]anull[{out_label}]"], []
    gate = "+".join(f"between(t,{r.a:.3f},{r.b:.3f})" for r in active)
    parts = [f"[{in_label}]volume=0:enable='{gate}'[muted]"]
    mix = ["[muted]"]
    extra: list[str] = []
    beeps = [r for r in active if r.mode == "beep"]
    if beeps:
        bgate = "+".join(f"between(t,{r.a:.3f},{r.b:.3f})" for r in beeps)
        parts.append(f"aevalsrc='{beep_gain}*sin(2*PI*{freq}*t)*({bgate})':s={rate}:d=86400[beep]")
        # d=86400 sınırsız gibidir; çıktı amix duration=first ile ana sesin uzunluğuna kesilir
        mix.append("[beep]")
    n = len(mix)
    parts.append(f"{''.join(mix)}amix=inputs={n}:duration=first:normalize=0[{out_label}]")
    return parts, extra
