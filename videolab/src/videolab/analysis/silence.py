"""Sessizlik algılama: akışlı RMS (dB) analizi + kullanıcı ayarlı kesim aralıkları."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

import numpy as np

FRAME_SEC = 0.02  # 20 ms çözünürlük


@dataclass
class SilenceParams:
    min_silence: float = 0.6        # bu süreden kısa sessizlikler dokunulmaz (sn)
    threshold_db: float = -35.0     # bu seviyenin altı "sessiz"
    cut_ratio: float = 1.0          # sessizliğin kesilecek oranı (1.0 = koruma payı dışında hepsi)
    pad_before: float = 0.12        # konuşmadan ÖNCE korunacak süre (sn)
    pad_after: float = 0.15         # konuşmadan SONRA korunacak süre (sn)


@dataclass
class SilenceSegment:
    start: float          # algılanan sessizlik başlangıcı
    end: float            # algılanan sessizlik bitişi
    cut_start: float      # gerçekten kesilecek aralık
    cut_end: float
    enabled: bool = True  # kullanıcı tek tek iptal edebilir

    @property
    def cut_duration(self) -> float:
        return max(0.0, self.cut_end - self.cut_start)


def frame_levels_db(chunks: Iterable[np.ndarray], sample_rate: int) -> np.ndarray:
    """Akıştan 20 ms'lik RMS dBFS değerleri üretir. Parça sınırlarında kalan örnekler taşınır."""
    n = max(1, int(sample_rate * FRAME_SEC))
    carry = np.empty(0, dtype=np.float32)
    out: list[np.ndarray] = []
    for ch in chunks:
        data = np.concatenate([carry, ch]) if carry.size else ch
        usable = (data.size // n) * n
        carry = data[usable:].copy()
        if usable:
            fr = data[:usable].reshape(-1, n).astype(np.float64)
            rms = np.sqrt(np.mean(fr * fr, axis=1))
            out.append((20 * np.log10(np.maximum(rms, 1e-9))).astype(np.float32))
    return np.concatenate(out) if out else np.empty(0, dtype=np.float32)


def find_silences(levels_db: np.ndarray, p: SilenceParams) -> list[SilenceSegment]:
    if levels_db.size == 0:
        return []
    quiet = levels_db < p.threshold_db
    # sessiz bölgelerin başlangıç/bitiş indeksleri
    padded = np.concatenate([[False], quiet, [False]]).astype(np.int8)
    d = np.diff(padded)
    starts, ends = np.where(d == 1)[0], np.where(d == -1)[0]
    total = levels_db.size * FRAME_SEC
    segs: list[SilenceSegment] = []
    for s_i, e_i in zip(starts, ends):
        s, e = s_i * FRAME_SEC, e_i * FRAME_SEC
        if e - s < p.min_silence:
            continue
        # Baştaki/sondaki sessizlikte yalnızca konuşmaya bakan tarafta pay bırak
        cs = s + (p.pad_after if s > 0 else 0.0)
        ce = e - (p.pad_before if e < total - FRAME_SEC else 0.0)
        if ce - cs <= FRAME_SEC:
            continue
        shrink = (1.0 - p.cut_ratio) * (ce - cs) / 2.0   # doğal duraklamayı ortada bırak
        cs, ce = cs + shrink, ce - shrink
        if ce - cs > FRAME_SEC:
            segs.append(SilenceSegment(float(round(s, 3)), float(round(e, 3)), float(round(cs, 3)), float(round(ce, 3))))
    return segs
