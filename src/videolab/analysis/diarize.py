"""Konuşmacı ayırma. API anahtarı/hesap GEREKTİRMEZ.
Gömme (embedding) arka uçları:
  - "resemblyzer" (kurulu ise; en doğru, pip install resemblyzer) 
  - "mfcc" (yerleşik yedek: NumPy/SciPy, bağımlılıksız; belirgin farklı seslerde iş görür, benzer seslerde zayıf kalır)
Akış: konuşma bölgeleri -> pencereler -> gömme -> hiyerarşik kümeleme -> birleştirme -> kelimelere etiket."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Iterable

import numpy as np
from scipy.cluster.hierarchy import fcluster, linkage
from scipy.fft import dct

from .profanity import Word
from .silence import FRAME_SEC


@dataclass
class SpeakerSegment:
    start: float
    end: float
    speaker: int           # 0, 1, 2…


# ------------------------------------------------------------------ yerleşik MFCC + pitch gömmesi
def _mel_fb(sr: int, n_fft: int, n_mels: int = 26) -> np.ndarray:
    hz2mel = lambda h: 2595 * np.log10(1 + h / 700); mel2hz = lambda m: 700 * (10 ** (m / 2595) - 1)
    pts = mel2hz(np.linspace(hz2mel(60), hz2mel(sr / 2), n_mels + 2))
    bins = np.floor((n_fft + 1) * pts / sr).astype(int)
    fb = np.zeros((n_mels, n_fft // 2 + 1))
    for m in range(1, n_mels + 1):
        l, c, r = bins[m - 1], bins[m], bins[m + 1]
        for k in range(l, c): fb[m - 1, k] = (k - l) / max(1, c - l)
        for k in range(c, r): fb[m - 1, k] = (r - k) / max(1, r - c)
    return fb


def _pitch(frame: np.ndarray, sr: int) -> float:
    f = frame - frame.mean()
    if np.max(np.abs(f)) < 1e-4: return 0.0
    ac = np.correlate(f, f, "full")[len(f) - 1:]
    lo, hi = int(sr / 400), int(sr / 70)
    seg = ac[lo:hi]
    if seg.size == 0 or ac[0] <= 0: return 0.0
    k = int(np.argmax(seg)) + lo
    return sr / k if ac[k] / ac[0] > 0.3 else 0.0


def mfcc_embedding(x: np.ndarray, sr: int) -> np.ndarray:
    n_fft, hop = 512, 160 if sr == 16000 else int(sr * 0.01)
    if x.size < n_fft + hop: x = np.pad(x, (0, n_fft + hop - x.size))
    win = np.hanning(n_fft)
    frames = np.lib.stride_tricks.sliding_window_view(x, n_fft)[::hop]
    energy = (frames ** 2).mean(axis=1)
    keep = energy > energy.max() * 0.05                            # sessiz kareleri dışla
    frames = frames[keep] if keep.sum() > 3 else frames
    spec = np.abs(np.fft.rfft(frames * win, axis=1)) ** 2
    logmel = np.log(spec @ _mel_fb(sr, n_fft).T + 1e-9)
    mf = dct(logmel, type=2, axis=1, norm="ortho")[:, 1:14]
    pitches = np.array([_pitch(fr, sr) for fr in frames[:: max(1, len(frames) // 40)]])
    voiced = pitches[pitches > 0]
    p = np.log(np.median(voiced)) if voiced.size else 0.0
    # ilk MFCC'ler ses tınısı; pitch ayırt edici ama ağırlığı kontrollü
    return np.concatenate([mf.mean(axis=0), mf.std(axis=0) * 0.5, [p * 3.0]])


def resemblyzer_embedding() -> Callable[[np.ndarray, int], np.ndarray]:
    from resemblyzer import VoiceEncoder        # kurulu değilse ImportError
    enc = VoiceEncoder()
    def fn(x: np.ndarray, sr: int) -> np.ndarray:
        return enc.embed_utterance(x.astype(np.float32))      # 16 kHz bekler
    return fn


def get_backend(name: str = "auto") -> tuple[str, Callable[[np.ndarray, int], np.ndarray]]:
    if name in ("auto", "resemblyzer"):
        try: return "resemblyzer", resemblyzer_embedding()
        except Exception:
            if name == "resemblyzer": raise
    return "mfcc", mfcc_embedding


# ------------------------------------------------------------------ ana akış
def speech_regions(levels_db: np.ndarray, threshold_db: float = -38.0, min_len: float = 0.4, gap: float = 0.3) -> list[tuple[float, float]]:
    """Seviye dizisinden (silence.frame_levels_db çıktısı) konuşma bölgeleri."""
    loud = np.concatenate([[False], levels_db > threshold_db, [False]]).astype(np.int8)
    d = np.diff(loud); s, e = np.where(d == 1)[0] * FRAME_SEC, np.where(d == -1)[0] * FRAME_SEC
    out: list[tuple[float, float]] = []
    for a, b in zip(s, e):
        if out and a - out[-1][1] <= gap: out[-1] = (out[-1][0], b)
        else: out.append((a, b))
    return [(a, b) for a, b in out if b - a >= min_len]


def _windows(regions, win, hop):
    wins: list[tuple[float, float]] = []
    for a, b in regions:
        t = a
        while t < b - 0.3:
            wins.append((t, min(b, t + win))); t += hop
    return wins


def diarize_file(path: str, regions: list[tuple[float, float]], n_speakers: int | None = None, backend: str = "auto",
                 sr: int = 16000, win: float = 1.5, hop: float = 0.75, max_speakers: int = 6,
                 threshold: float | None = None, on_progress: Callable[[float], None] | None = None) -> list[SpeakerSegment]:
    """Dosyadan AKIŞLI okuyarak çalışır (3 saatlik videoda bile RAM sabit): yalnızca penceredeki ses tutulur."""
    from ..media.ffmpeg import stream_pcm
    name, embed = get_backend(backend)
    wins = _windows(regions, win, hop)
    if not wins:
        return []
    it = iter(stream_pcm(path, sr, 10.0))
    buf, buf_start, done_all = np.empty(0, np.float32), 0.0, False
    embs = []
    for i, (a, b) in enumerate(wins):
        while not done_all and buf_start + buf.size / sr < b:
            try: buf = np.concatenate([buf, next(it)])
            except StopIteration: done_all = True
        lo = int((a - buf_start) * sr); hi = int((b - buf_start) * sr)
        embs.append(embed(buf[max(0, lo):hi], sr))
        drop = int((a - buf_start) * sr)               # pencereler sıralı: öncesini at
        if drop > 0: buf, buf_start = buf[drop:], buf_start + drop / sr
        if on_progress and i % 20 == 0: on_progress((i + 1) / len(wins))
    return _cluster(np.array(embs), wins, name, n_speakers, max_speakers, threshold)


def diarize(samples: np.ndarray, sr: int, regions: list[tuple[float, float]], n_speakers: int | None = None,
            backend: str = "auto", win: float = 1.5, hop: float = 0.75, max_speakers: int = 6,
            threshold: float | None = None) -> list[SpeakerSegment]:
    """Bellekteki ses için (kısa videolar/testler). Uzun videolarda diarize_file kullanın."""
    name, embed = get_backend(backend)
    wins = _windows(regions, win, hop)
    if not wins: return []
    E = np.array([embed(samples[int(a * sr): int(b * sr)], sr) for a, b in wins])
    return _cluster(E, wins, name, n_speakers, max_speakers, threshold)


def _cluster(E, wins, name, n_speakers, max_speakers, threshold) -> list[SpeakerSegment]:

    if len(wins) == 1: return [SpeakerSegment(wins[0][0], wins[0][1], 0)]
    if name == "mfcc":
        Z, thr = linkage(E, "ward"), (threshold if threshold is not None else 10.0)        # ham öznitelik: aynı kişi <~1, farklı kişi >~80 (sentetik testte)
    else:
        Z, thr = linkage(E, "average", metric="cosine"), (threshold if threshold is not None else 0.30)
    if n_speakers:
        labels = fcluster(Z, n_speakers, "maxclust")
    else:
        labels = fcluster(Z, thr, "distance")
        if labels.max() > max_speakers:
            labels = fcluster(Z, max_speakers, "maxclust")
    labels = _smooth(labels, 2)
    # etiketleri ilk görünme sırasına göre 0,1,2…
    order = {l: i for i, l in enumerate(dict.fromkeys(labels))}
    segs: list[SpeakerSegment] = []
    for (a, b), l in zip(wins, labels):
        sp = order[l]
        if segs and segs[-1].speaker == sp and a <= segs[-1].end + 1e-3: segs[-1].end = max(segs[-1].end, b)
        elif segs and a < segs[-1].end:                           # örtüşen pencere farklı konuşmacı: sınırı ortadan böl
            mid = (a + segs[-1].end) / 2; segs[-1].end = mid; segs.append(SpeakerSegment(mid, b, sp))
        else: segs.append(SpeakerSegment(a, b, sp))
    return segs


def _smooth(labels: np.ndarray, r: int) -> np.ndarray:
    """Tek pencerelik sapmaları komşu çoğunluğa çek (konuşmacı bir anda 'zıplamasın')."""
    out = labels.copy()
    for i in range(len(labels)):
        nb = labels[max(0, i - r): i + r + 1]
        vals, cnt = np.unique(nb, return_counts=True)
        out[i] = vals[np.argmax(cnt)]
    return out


def label_words(words: list[Word], segs: list[SpeakerSegment]) -> list[int]:
    """Her kelimeye konuşmacı no (orta noktasına en yakın bölüm; bölüm yoksa -1)."""
    res = []
    for w in words:
        mid = (w.start + w.end) / 2
        best, dist = -1, 1e9
        for s in segs:
            d = 0.0 if s.start <= mid <= s.end else min(abs(mid - s.start), abs(mid - s.end))
            if d < dist: best, dist = s.speaker, d
        res.append(best if dist < 1.0 else -1)
    return res
