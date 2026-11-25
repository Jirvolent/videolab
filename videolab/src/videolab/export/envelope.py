"""Kazanç zarfı (gain envelope): bölgesel ses kısma için. Zarf, 1 kHz'lik bir WAV dosyasına yazılır;
FFmpeg'e ek girdi olarak verilip `amultiply` ile konuşma sesiyle çarpılır. Böylece binlerce nefes bölgesi için
dev bir filtre ifadesi gerekmez (komut satırı sınırına takılmaz) ve geçişler yumuşak olur."""
from __future__ import annotations

import numpy as np
import scipy.io.wavfile as wavfile

RATE = 1000


def build_envelope(regions: list[tuple[float, float, float]], total: float, ramp: float = 0.02) -> np.ndarray:
    """regions: (başlangıç_sn, bitiş_sn, doğrusal kazanç 0..1). Kenarlarda `ramp` sn'lik yumuşak geçiş (bölgenin DIŞINA taşar)."""
    n = int((total + 2.0) * RATE)
    env = np.ones(n, np.float32)
    t = np.arange(n) / RATE
    for a, b, g in regions:
        lo, hi = max(0, int((a - ramp) * RATE)), min(n, int((b + ramp) * RATE) + 1)
        if hi <= lo:
            continue
        tt = t[lo:hi]
        w = np.clip(np.minimum((tt - (a - ramp)) / ramp, ((b + ramp) - tt) / ramp), 0, 1)
        env[lo:hi] = np.minimum(env[lo:hi], (1 - (1 - g) * w).astype(np.float32))
    return env


def write_envelope(path: str, env: np.ndarray) -> str:
    # STEREO yazılır: mono zarf FFmpeg'de stereoya yükseltilirken -3 dB düşürülür ve konuşma sesi kısılırdı
    mono = np.round(np.clip(env, 0, 1) * 32767).astype(np.int16)
    wavfile.write(path, RATE, np.stack([mono, mono], axis=1))
    return path
