"""Otomatik ton dengeleme: konuşmanın uzun süreli ortalama spektrumunu ölçer, hedef konuşma eğrisine yaklaştıracak
yumuşak bir EQ önerir (düzeltme sınırlı: fazla boost/kesme yok)."""
from __future__ import annotations

from typing import Iterable

import numpy as np

BANDS = [100, 160, 250, 400, 630, 1000, 1600, 2500, 4000, 6300]
# Hedef: konuşma için dengeli, hafif eğimli spektrum (dB, 500 Hz'e göre). Genel kabul gören ortalama konuşma eğrisine yakın.
TARGET = {100: -7, 160: -3, 250: 0, 400: 0, 630: -1, 1000: -4, 1600: -8, 2500: -11, 4000: -15, 6300: -20}
MAX_BOOST, MAX_CUT = 4.0, -6.0


def measure_bands(chunks: Iterable[np.ndarray], sr: int, speech_db: float = -40.0) -> dict[int, float] | None:
    """Konuşma karelerinin ortalama güç spektrumunu 1/3 oktav bantlara toplar. Konuşma yoksa None."""
    n = 1024
    win = np.hanning(n); freqs = np.fft.rfftfreq(n, 1 / sr)
    acc = np.zeros(n // 2 + 1); count = 0
    carry = np.empty(0, np.float32)
    for ch in chunks:
        data = np.concatenate([carry, ch]) if carry.size else ch
        use = (data.size // n) * n
        carry = data[use:].copy()
        if not use:
            continue
        fr = data[:use].reshape(-1, n).astype(np.float64)
        db = 20 * np.log10(np.maximum(np.sqrt((fr ** 2).mean(axis=1)), 1e-9))
        keep = db > speech_db
        if keep.any():
            acc += (np.abs(np.fft.rfft(fr[keep] * win, axis=1)) ** 2).sum(axis=0); count += int(keep.sum())
    if count < 20:
        return None
    acc /= count
    out = {}
    for c in BANDS:
        m = (freqs >= c / 2 ** (1 / 6)) & (freqs < c * 2 ** (1 / 6))
        out[c] = 10 * np.log10(acc[m].sum() + 1e-18)
    return out


def deviation(bands: dict[int, float]) -> float:
    """Hedef eğriden ortalama mutlak sapma (dB); 500 Hz civarı bantların ortalamasına göre hizalanır."""
    ref = np.mean([bands[c] - TARGET[c] for c in (250, 400, 630, 1000)])
    return float(np.mean([abs(bands[c] - TARGET[c] - ref) for c in BANDS]))


def suggest_eq(bands: dict[int, float], strength: float = 0.6, q: float = 1.2) -> list[tuple[float, float, float]]:
    """[(frekans, kazanç_dB, q)] — küçük düzeltmeler (<0.7 dB) atlanır."""
    ref = np.mean([bands[c] - TARGET[c] for c in (250, 400, 630, 1000)])
    out = []
    for c in BANDS:
        g = -(bands[c] - TARGET[c] - ref) * strength
        g = float(min(MAX_BOOST, max(MAX_CUT, g)))
        if abs(g) >= 0.7:
            out.append((float(c), round(g, 1), q))
    return out


def analyze_file(path: str, strength: float = 0.6, sr: int = 16000) -> list[tuple[float, float, float]]:
    from ..media.ffmpeg import stream_pcm
    b = measure_bands(stream_pcm(path, sr, 10.0), sr)
    return suggest_eq(b, strength) if b else []
