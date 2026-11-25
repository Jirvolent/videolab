"""Ekran / webcam kaydı (FFmpeg ile). Komut üretimi testli; canlı kayıt cihaza bağlıdır."""
from __future__ import annotations

import subprocess
import sys

from .ffmpeg import _NOWIN, find_binary


def build_record_command(kind: str, out: str, fps: int = 30, platform: str | None = None,
                         webcam_name: str | None = None, with_audio: bool = False) -> list[str]:
    plat = platform or sys.platform
    cmd = [find_binary("ffmpeg"), "-y", "-v", "error"]
    if kind == "screen":
        if plat.startswith("win"):
            cmd += ["-f", "gdigrab", "-framerate", str(fps), "-i", "desktop"]
        elif plat == "darwin":
            cmd += ["-f", "avfoundation", "-framerate", str(fps), "-i", "1:none"]
        else:
            cmd += ["-f", "x11grab", "-framerate", str(fps), "-i", ":0.0"]
    elif kind == "webcam":
        if plat.startswith("win"):
            if not webcam_name: raise ValueError("Windows'ta webcam adı gerekli (ör. 'Integrated Camera')")
            cmd += ["-f", "dshow", "-framerate", str(fps), "-i", f"video={webcam_name}"]
        elif plat == "darwin":
            cmd += ["-f", "avfoundation", "-framerate", str(fps), "-i", "0:none"]
        else:
            cmd += ["-f", "v4l2", "-framerate", str(fps), "-i", webcam_name or "/dev/video0"]
    else:
        raise ValueError("kind: 'screen' veya 'webcam'")
    return cmd + ["-c:v", "libx264", "-preset", "ultrafast", "-crf", "20", "-pix_fmt", "yuv420p", out]


class Recording:
    def __init__(self, cmd: list[str]):
        self.proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE, creationflags=_NOWIN)

    def stop(self) -> None:
        """'q' göndererek dosyayı düzgün kapatır (bozuk dosya bırakmaz)."""
        try:
            self.proc.stdin.write(b"q"); self.proc.stdin.flush()
            self.proc.wait(timeout=15)
        except Exception:
            self.proc.kill()
        finally:
            for s in (self.proc.stdin, self.proc.stderr):
                try: s.close()
                except Exception: pass
