"""9:16 otomatik takip kırpma: yüz algıla -> yumuşat -> anahtar kareler (ExportSettings.follow)."""
from __future__ import annotations

import statistics
from typing import Callable


def detect_face_track(path: str, sample_fps: float = 2.0, on_progress: Callable[[float], None] | None = None,
                      should_cancel: Callable[[], bool] | None = None) -> list[tuple[float, float | None]]:
    """(saniye, yüz merkezi x oranı 0..1 | None). Birden fazla yüz varsa en büyüğü seçilir."""
    import cv2
    cap = cv2.VideoCapture(path)
    if not cap.isOpened():
        raise RuntimeError("Video açılamadı")
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    total = cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0
    dur = total / fps if total else 0
    det = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
    if det.empty():
        raise RuntimeError("Yüz algılama modeli bulunamadı (opencv-python paketini yeniden kurun).")
    out: list[tuple[float, float | None]] = []
    step = 1.0 / sample_fps
    t = 0.0
    try:
        while True:
            if should_cancel and should_cancel():
                break
            cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000)
            ok, frame = cap.read()
            if not ok:
                break
            h, w = frame.shape[:2]
            sc = 480.0 / w if w > 480 else 1.0
            small = cv2.cvtColor(cv2.resize(frame, None, fx=sc, fy=sc), cv2.COLOR_BGR2GRAY)
            faces = det.detectMultiScale(small, 1.2, 5, minSize=(40, 40))
            if len(faces):
                x, y, fw, fh = max(faces, key=lambda r: r[2] * r[3])
                out.append((t, (x + fw / 2) / small.shape[1]))
            else:
                out.append((t, None))
            if on_progress and dur:
                on_progress(min(1.0, t / dur))
            t += step
    finally:
        cap.release()
    return out


def smooth_track(raw: list[tuple[float, float | None]], median_win: int = 5, deadzone: float = 0.06,
                 move_time: float = 0.6, default: float = 0.5) -> list[tuple[float, float]]:
    """Yüz kaybolunca son konumda kalır, küçük titremelerde kamera durur (deadzone),
    gerçek harekette move_time sürede yumuşakça kayar. Çıktı: (t, merkez) anahtar kareleri (az sayıda)."""
    if not raw:
        return []
    filled, last = [], default
    for t, c in raw:
        last = c if c is not None else last
        filled.append((t, last))
    half = median_win // 2
    med = [(t, statistics.median(c for _, c in filled[max(0, i - half): i + half + 1])) for i, (t, _) in enumerate(filled)]
    keys = [(med[0][0], med[0][1])]
    cur = med[0][1]
    for t, c in med[1:]:
        if abs(c - cur) > deadzone:
            keys.append((t, cur))                 # hareket başlamadan önce eski konumda tut
            keys.append((t + move_time, c))       # yeni konuma yumuşak geçiş
            cur = c
    keys.append((med[-1][0] + 1.0, cur))
    # zaman sırasını koru, çakışanları ayıkla
    out: list[tuple[float, float]] = []
    for t, c in keys:
        if out and t <= out[-1][0]:
            t = out[-1][0] + 1e-3
        out.append((t, c))
    return out
