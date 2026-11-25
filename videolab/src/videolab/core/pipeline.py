"""Otomatik düzenleme hattı + toplu işlem kuyruğu. UI'dan bağımsız; testli."""
from __future__ import annotations

import os
import threading
from dataclasses import dataclass, field
from typing import Callable

from ..analysis.profanity import ProfanityFilter, Word
from ..analysis.silence import SilenceParams, find_silences, frame_levels_db
from ..analysis.transcript_tools import find_fillers
from ..export.censor import CensorRegion
from ..export.exporter import ExportSettings, export
from ..media.ffmpeg import probe, stream_pcm
from .branding import Branding, intro_offset, with_branding
from .edit_ops import apply_cuts, apply_transitions
from .voice_prep import VoiceOptions, prepare
from .model import Clip, Timeline

Transcriber = Callable[[str], list[Word]]


@dataclass
class AutoEditOptions:
    silence: SilenceParams | None = None
    remove_fillers: bool = False
    censor_profanity: bool = False
    censor_mode: str = "beep"
    transcriber: Transcriber | None = None      # faster-whisper sarmalayıcısı (veya test için sahte)
    profanity: ProfanityFilter = field(default_factory=ProfanityFilter)
    branding: Branding | None = None             # intro/outro yuvası
    voice: VoiceOptions | None = None            # nefes/ağız sesi/ton eşitleme
    transition: str = "none"                     # klip sınırları için (tek klipte etkisiz)


def auto_edit(src: str, settings: ExportSettings, opt: AutoEditOptions,
              progress: Callable[[float, float | None], None] | None = None,
              cancel: threading.Event | None = None) -> dict:
    """Sessizlik + dolgu sözcüğü kesimi, küfür sansürü, dışa aktarma. Özet sözlük döner."""
    info = probe(src)
    tl = Timeline(30.0)
    clip = tl.add_clip(tl.tracks[0].id, Clip(src, 0, info.duration, 0))
    cuts: list[tuple[float, float]] = []
    words: list[Word] = []
    if opt.transcriber and (opt.remove_fillers or opt.censor_profanity):
        words = opt.transcriber(src)
    summary = {"silences": 0, "fillers": 0, "profanity": 0, "cut_seconds": 0.0}
    if opt.silence and info.has_audio:
        segs = [s for s in find_silences(frame_levels_db(stream_pcm(src, 16000, 10.0), 16000), opt.silence) if s.enabled]
        cuts += [(s.cut_start, s.cut_end) for s in segs]; summary["silences"] = len(segs)
    if opt.remove_fillers:
        fl = find_fillers(words); cuts += [(s.start, s.end) for s in fl]; summary["fillers"] = len(fl)
    hits = opt.profanity.scan(words) if opt.censor_profanity else []
    # sansür bölgeleri kesimlerden SONRAKİ timeline zamanına çevrilmeli
    from .edit_ops import merge_ranges
    merged = merge_ranges(cuts)
    def to_timeline(t: float) -> float:
        removed = sum(min(b, t) - a for a, b in merged if a < t)
        return t - removed
    regions = []
    for h in hits:
        if any(a <= h.start and h.end <= b for a, b in merged):
            continue                                   # zaten kesilmiş
        regions.append(CensorRegion(to_timeline(h.start), to_timeline(h.end), opt.censor_mode))
    summary["profanity"] = len(regions)
    summary["cut_seconds"] = apply_cuts(tl, clip, cuts)
    temps: list[str] = []
    off = intro_offset(opt.branding) if opt.branding else 0.0
    settings.censor = [CensorRegion(r.start + off, r.end + off, r.mode) for r in regions]     # intro kadar ötele
    if opt.voice and opt.voice.any and info.has_audio:
        def mapper(t: float):
            return None if any(a < t < b for a, b in merged) else to_timeline(t)
        temps = prepare(settings, src, opt.voice, mapper, tl.duration, off)
    if opt.branding:
        tl = with_branding(tl, opt.branding)
    try:
        export(tl, settings, progress, cancel)
    finally:
        for t in temps:
            if os.path.exists(t): os.remove(t)
    return summary


@dataclass
class Job:
    name: str
    run: Callable[[Callable[[float, float | None], None], threading.Event], object]
    status: str = "bekliyor"        # bekliyor | çalışıyor | bitti | hata | iptal
    result: object = None
    error: str = ""


class JobQueue:
    """Sıralı toplu işlem: bir iş hata verse bile diğerleri devam eder."""
    def __init__(self):
        self.jobs: list[Job] = []

    def add(self, job: Job) -> Job:
        self.jobs.append(job); return job

    def run_all(self, on_job_progress: Callable[[int, float], None] | None = None,
                cancel: threading.Event | None = None) -> None:
        cancel = cancel or threading.Event()
        for i, j in enumerate(self.jobs):
            if j.status != "bekliyor":
                continue
            if cancel.is_set():
                j.status = "iptal"; continue
            j.status = "çalışıyor"
            try:
                j.result = j.run(lambda f, r=None, i=i: on_job_progress and on_job_progress(i, f), cancel)
                j.status = "bitti"
            except InterruptedError:
                j.status = "iptal"
            except Exception as e:
                j.status, j.error = "hata", str(e)
