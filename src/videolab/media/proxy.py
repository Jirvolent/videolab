"""Proxy önizleme ve dalga formu."""
from __future__ import annotations

import subprocess
import threading
from typing import Callable

import numpy as np

from .ffmpeg import FFmpegError, _NOWIN, find_binary, probe, stream_pcm


def make_proxy(src: str, dst: str, height: int = 360, on_progress: Callable[[float], None] | None = None,
               cancel: threading.Event | None = None) -> str:
    """4K/uzun videolar için düşük çözünürlüklü, kare-hassas (sık keyframe) önizleme kopyası. Dışa aktarma orijinali kullanır."""
    dur = probe(src).duration
    cmd = [find_binary("ffmpeg"), "-y", "-v", "error", "-nostats", "-progress", "pipe:1", "-i", src,
           "-vf", f"scale=-2:{height}", "-c:v", "libx264", "-preset", "veryfast", "-crf", "28", "-g", "15",
           "-c:a", "aac", "-b:a", "96k", dst]
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, creationflags=_NOWIN)
    try:
        for line in p.stdout:
            if cancel is not None and cancel.is_set():
                p.terminate(); p.wait(); raise InterruptedError("Proxy iptal edildi")
            if line.startswith("out_time_us=") and on_progress and dur:
                try: on_progress(min(1.0, int(line.split("=")[1]) / 1e6 / dur))
                except ValueError: pass
        p.wait()
    finally:
        if p.poll() is None: p.kill(); p.wait()
        p.stdout.close()
    if p.returncode != 0:
        raise FFmpegError("Proxy oluşturulamadı")
    return dst


def waveform_peaks(path: str, peaks_per_sec: int = 20) -> np.ndarray:
    """Akışlı okuma: dalga formu için saniyede `peaks_per_sec` tepe değeri (0..1). 3 saatte ~216 bin değer."""
    sr = 8000
    win = sr // peaks_per_sec
    carry = np.empty(0, dtype=np.float32); out = []
    for ch in stream_pcm(path, sr, 10.0):
        data = np.concatenate([carry, ch]) if carry.size else ch
        use = (data.size // win) * win
        carry = data[use:].copy()
        if use:
            out.append(np.abs(data[:use]).reshape(-1, win).max(axis=1))
    if carry.size:
        out.append(np.array([np.abs(carry).max()], dtype=np.float32))
    return np.concatenate(out) if out else np.empty(0, dtype=np.float32)
