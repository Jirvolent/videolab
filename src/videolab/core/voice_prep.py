"""Ses iyileştirme hazırlığı: nefes zarfı, ağız sesi, ton eşitleme. UI'dan bağımsız; tek video dosyası için çalışır."""
from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass, field
from typing import Callable

from ..analysis.autoeq import analyze_file
from ..analysis.breaths import BreathParams, BreathSegment, detect_breaths_file
from ..export.envelope import build_envelope, write_envelope
from ..export.exporter import ExportSettings
from ..export.voicefx import VoiceFX, preset


@dataclass
class VoiceOptions:
    breath: bool = False
    breath_gain_db: float = -14.0         # -14: doğal (nefes duyulur ama kısık); -60: neredeyse sessiz
    breath_params: BreathParams = field(default_factory=BreathParams)
    mouth_clicks: bool = False
    preset: str | None = None             # "dogal" | "podcast" | "youtube" | "zayif_mikrofon" | None
    auto_eq: bool = False
    auto_eq_strength: float = 0.6
    denoise: bool = False

    @property
    def any(self) -> bool:
        return self.breath or self.mouth_clicks or bool(self.preset) or self.auto_eq


def prepare(settings: ExportSettings, src: str, opt: VoiceOptions, to_timeline: Callable[[float], float | None],
            total: float, offset: float = 0.0, breaths: list[BreathSegment] | None = None) -> list[str]:
    """settings'i yerinde günceller. Silinmesi gereken geçici dosyaların yollarını döndürür.
    to_timeline: kaynak zamanını timeline zamanına çevirir (kesilmiş yerler için None).
    offset: intro vb. nedeniyle ana içeriğin kayması. breaths: UI'da onaylanmış liste (None ise otomatik algılanır)."""
    temps: list[str] = []
    if opt.breath:
        segs = breaths if breaths is not None else detect_breaths_file(src, opt.breath_params)
        gain = 10 ** (opt.breath_gain_db / 20)
        regions = []
        for sg in segs:
            if not sg.enabled:
                continue
            a, b = to_timeline(sg.start), to_timeline(sg.end)
            if a is not None and b is not None and b > a:
                regions.append((a + offset, b + offset, gain))
        if regions:
            fd, path = tempfile.mkstemp(suffix=".wav", prefix="vl_env_"); os.close(fd)
            write_envelope(path, build_envelope(regions, total + offset)); temps.append(path)
            settings.breath_envelope = path
    settings.declick = opt.mouth_clicks
    auto = analyze_file(src, opt.auto_eq_strength) if opt.auto_eq else []
    if opt.preset:
        fx = preset(opt.preset); fx.denoise = fx.denoise or opt.denoise; fx.eq = list(fx.eq) + auto
        settings.voicefx = fx
    elif auto or opt.denoise:
        settings.voicefx = VoiceFX(highpass=70, denoise=opt.denoise, deess=False, eq=auto, comp_ratio=1.0, leveling=False, limiter=False)
    return temps
