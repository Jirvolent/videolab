"""FFmpeg/FFprobe sarmalayıcı. Büyük dosyalar için ses akış (stream) olarak okunur; RAM sabit kalır."""
from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass
from typing import Iterator

import numpy as np

_NOWIN = getattr(subprocess, "CREATE_NO_WINDOW", 0)


class FFmpegError(RuntimeError):
    pass


def find_binary(name: str) -> str:
    p = shutil.which(name)
    if not p:
        raise FFmpegError(f"{name} bulunamadı. INSTALL.md dosyasına bakın.")
    return p


@dataclass
class MediaInfo:
    path: str
    duration: float
    has_video: bool
    has_audio: bool
    width: int = 0
    height: int = 0
    fps: float = 0.0
    audio_rate: int = 0


def _parse_rate(s: str) -> float:
    try:
        a, b = s.split("/")
        return float(a) / float(b) if float(b) else 0.0
    except Exception:
        return 0.0


def probe(path: str) -> MediaInfo:
    cmd = [find_binary("ffprobe"), "-v", "error", "-print_format", "json",
           "-show_format", "-show_streams", path]
    r = subprocess.run(cmd, capture_output=True, text=True, creationflags=_NOWIN)
    if r.returncode != 0:
        raise FFmpegError(r.stderr.strip() or "ffprobe başarısız")
    d = json.loads(r.stdout)
    v = next((s for s in d["streams"] if s["codec_type"] == "video"), None)
    a = next((s for s in d["streams"] if s["codec_type"] == "audio"), None)
    dur = float(d["format"].get("duration") or (v or a or {}).get("duration") or 0)
    return MediaInfo(path, dur, v is not None, a is not None,
                     int(v["width"]) if v else 0, int(v["height"]) if v else 0,
                     _parse_rate(v.get("avg_frame_rate", "0/1")) if v else 0.0,
                     int(a["sample_rate"]) if a else 0)


def stream_pcm(path: str, sample_rate: int = 16000, chunk_seconds: float = 10.0) -> Iterator[np.ndarray]:
    """Sesi mono float32 parçalar halinde üretir (3 saatlik videoda bile birkaç MB RAM)."""
    cmd = [find_binary("ffmpeg"), "-v", "error", "-i", path, "-vn", "-ac", "1",
           "-ar", str(sample_rate), "-f", "f32le", "-"]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, creationflags=_NOWIN)
    bytes_per_chunk = int(sample_rate * chunk_seconds) * 4
    try:
        while True:
            buf = proc.stdout.read(bytes_per_chunk)
            if not buf:
                break
            buf = buf[: len(buf) // 4 * 4]
            yield np.frombuffer(buf, dtype=np.float32)
    finally:
        proc.stdout.close()
        proc.terminate()
        proc.wait()
