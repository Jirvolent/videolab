"""Konuşma tonu eşitleme zinciri (FFmpeg): yüksek geçiren, gürültü azaltma, de-esser, EQ, kompresör, seviye dengeleme, limiter."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class VoiceFX:
    highpass: float = 80.0
    denoise: bool = False
    deess: bool = True
    eq: list[tuple[float, float, float]] = field(default_factory=list)        # (Hz, dB, q): hazır ayar + otomatik EQ birleşimi
    comp_threshold_db: float = -20.0
    comp_ratio: float = 3.0
    attack_ms: float = 15.0
    release_ms: float = 250.0
    makeup_db: float = 3.0
    leveling: bool = True                                                       # kısık/yüksek cümleleri dengeler (dynaudnorm)
    limiter: bool = True


PRESET_LABELS = {"dogal": "Doğal (hafif)", "podcast": "Podcast (sıcak ve dolgun)",
                 "youtube": "YouTube (parlak ve net)", "zayif_mikrofon": "Zayıf mikrofonu düzelt"}


def preset(name: str) -> VoiceFX:
    if name == "dogal":
        return VoiceFX(70, False, True, [(3500, 1.0, 1.0)], -18, 2.0, 20, 300, 1.5, False)
    if name == "youtube":
        return VoiceFX(90, False, True, [(180, -2.5, 1.0), (300, -1.5, 1.2), (3000, 3.0, 1.0), (6500, 2.0, 1.0), (11000, 2.0, 0.7)],
                       -22, 4.0, 10, 200, 4.0, True)
    if name == "zayif_mikrofon":
        return VoiceFX(110, True, True, [(160, -3.0, 1.0), (2800, 3.0, 1.0), (7000, 1.5, 0.8)], -22, 3.5, 15, 250, 4.0, True)
    return VoiceFX(80, False, True, [(200, -2.0, 1.0), (3500, 2.5, 1.0), (9000, 1.5, 0.7)], -20, 3.0, 15, 250, 3.0, True)   # podcast


def _lin(db: float) -> float:
    return max(0.000976563, min(1.0, 10 ** (db / 20)))


def build_filter(fx: VoiceFX) -> str:
    parts = []
    if fx.highpass > 0:
        parts.append(f"highpass=f={fx.highpass:.0f}")
    if fx.denoise:
        parts.append("afftdn=nr=12:nf=-30")
    if fx.deess:
        parts.append("deesser=i=0.3:m=0.5:f=0.5")
    for f, g, q in sorted(fx.eq):
        parts.append(f"equalizer=f={f:.0f}:t=q:w={q:.2f}:g={g:.1f}")
    if fx.comp_ratio > 1.01:          # oran 1 ise kompresör atlanır (yalnızca EQ istendiğinde)
        parts.append(f"acompressor=threshold={_lin(fx.comp_threshold_db):.5f}:ratio={fx.comp_ratio:.2f}:"
                     f"attack={fx.attack_ms:.0f}:release={fx.release_ms:.0f}:makeup={min(64.0, max(1.0, 10 ** (fx.makeup_db / 20))):.3f}")
    if fx.leveling:
        parts.append("dynaudnorm=f=300:g=11:p=0.9:m=8:s=8")
    if fx.limiter:
        parts.append("alimiter=limit=0.89:attack=5:release=60")
    return ",".join(parts)
