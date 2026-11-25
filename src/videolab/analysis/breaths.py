"""Nefes algılama: konuşma aralarındaki, gürültü benzeri (spektral düzlüğü yüksek), konuşmadan belirgin kısık kısa sesler.
Akışlı çalışır (3 saatlik videoda RAM sabit). Heuristik bir yöntemdir: sonuç kullanıcıya gösterilir, istenmeyenler elenebilir."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Iterable

import numpy as np

from .silence import FRAME_SEC


@dataclass
class BreathParams:
    min_len: float = 0.12            # sn: bundan kısa "nefes" sayılmaz (tıkırtıdır, ayrı ele alınır)
    max_len: float = 1.3             # sn: bundan uzun ses nefes değildir
    below_speech_db: float = 12.0    # konuşma seviyesinin en az bu kadar altında olmalı
    floor_margin_db: float = 6.0     # zemin gürültüsünün en az bu kadar üstünde olmalı
    flatness_min: float = 0.10       # gürültü benzerliği (0..1); sesli harfler ~0, nefes/frikatif daha yüksek
    sandwich_ms: float = 60.0        # iki yanı da hemen konuşmayla çevriliyse kelime içi 's/ş/f' sesidir, nefes değil
    max_gap_to_speech: float = 0.5   # en az bir tarafında bu mesafede konuşma olmalı


@dataclass
class BreathSegment:
    start: float
    end: float
    level_db: float
    enabled: bool = True


def frame_features(chunks: Iterable[np.ndarray], sr: int) -> tuple[np.ndarray, np.ndarray]:
    """20 ms kareler için (dBFS, spektral düzlük 100–6000 Hz)."""
    n = max(64, int(sr * FRAME_SEC))
    win = np.hanning(n)
    freqs = np.fft.rfftfreq(n, 1 / sr)
    band = (freqs >= 100) & (freqs <= min(6000, sr / 2 - 1))
    carry = np.empty(0, np.float32)
    dbs: list[np.ndarray] = []; fl: list[np.ndarray] = []
    for ch in chunks:
        data = np.concatenate([carry, ch]) if carry.size else ch
        use = (data.size // n) * n
        carry = data[use:].copy()
        if not use:
            continue
        fr = data[:use].reshape(-1, n).astype(np.float64)
        rms = np.sqrt((fr ** 2).mean(axis=1))
        dbs.append((20 * np.log10(np.maximum(rms, 1e-9))).astype(np.float32))
        p = np.abs(np.fft.rfft(fr * win, axis=1))[:, band] ** 2 + 1e-14
        fl.append((np.exp(np.log(p).mean(axis=1)) / p.mean(axis=1)).astype(np.float32))
    if not dbs:
        return np.empty(0, np.float32), np.empty(0, np.float32)
    return np.concatenate(dbs), np.concatenate(fl)


def find_breaths(db: np.ndarray, flat: np.ndarray, p: BreathParams = BreathParams()) -> list[BreathSegment]:
    if db.size < 10:
        return []
    floor = float(np.percentile(db, 5))
    active = db[db > floor + 15]
    if active.size < 10:
        return []
    speech_ref = float(np.percentile(active, 90))
    hi, lo = speech_ref - p.below_speech_db, floor + p.floor_margin_db
    if hi <= lo:
        return []
    cand = (db >= lo) & (db <= hi) & (flat >= p.flatness_min)
    # 1 karelik boşlukları kapat
    for i in range(1, len(cand) - 1):
        if not cand[i] and cand[i - 1] and cand[i + 1]:
            cand[i] = True
    loud = db > speech_ref - 8
    gap = int(round(p.max_gap_to_speech / FRAME_SEC))
    padded = np.concatenate([[False], cand, [False]]).astype(np.int8)
    d = np.diff(padded)
    out: list[BreathSegment] = []
    for s, e in zip(np.where(d == 1)[0], np.where(d == -1)[0]):
        dur = (e - s) * FRAME_SEC
        if dur < p.min_len or dur > p.max_len:
            continue
        near = loud[max(0, s - gap):s].any() or loud[e:e + gap].any()
        sw = max(1, int(round(p.sandwich_ms / 1000 / FRAME_SEC)))
        if not near or (loud[max(0, s - sw):s].any() and loud[e:e + sw].any()):
            continue
        out.append(BreathSegment(round(s * FRAME_SEC, 3), round(e * FRAME_SEC, 3), float(np.median(db[s:e]))))
    return out


def detect_breaths_file(path: str, p: BreathParams = BreathParams(), sr: int = 16000,
                        on_progress: Callable[[float], None] | None = None) -> list[BreathSegment]:
    from ..media.ffmpeg import stream_pcm
    db, fl = frame_features(stream_pcm(path, sr, 10.0), sr)
    return find_breaths(db, fl, p)
