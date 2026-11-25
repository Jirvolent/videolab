"""YouTube hazırlığı: küçük resim kare seçici ve açıklama metni."""
from __future__ import annotations

from ..analysis.transcript_tools import chapters_text


def pick_thumbnails(path: str, out_prefix: str, count: int = 3, samples: int = 40) -> list[str]:
    """Netlik (Laplacian varyansı) ve parlaklık dengesine göre en iyi kareleri JPEG olarak kaydeder."""
    import cv2
    cap = cv2.VideoCapture(path)
    n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    if n <= 0:
        raise RuntimeError("Video açılamadı")
    scored = []
    for k in range(samples):
        idx = int(n * (0.05 + 0.9 * k / max(1, samples - 1)))
        cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
        ok, fr = cap.read()
        if not ok:
            continue
        g = cv2.cvtColor(fr, cv2.COLOR_BGR2GRAY)
        sharp = cv2.Laplacian(g, cv2.CV_64F).var()
        bright = g.mean()
        penalty = 1.0 if 50 < bright < 200 else 0.4          # çok karanlık/yanık kareleri ele
        scored.append((sharp * penalty, idx, fr))
    cap.release()
    out, used = [], []
    for _, idx, fr in sorted(scored, key=lambda x: -x[0]):
        if any(abs(idx - u) < n * 0.08 for u in used):        # birbirine yakın kareleri alma
            continue
        p = f"{out_prefix}_{len(out) + 1}.jpg"
        cv2.imwrite(p, fr, [cv2.IMWRITE_JPEG_QUALITY, 92]); out.append(p); used.append(idx)
        if len(out) == count:
            break
    return out


def build_description(title: str, summary: str, chapters: list[tuple[float, str]], tags: list[str]) -> str:
    parts = [title, "", summary.strip(), ""]
    if len(chapters) >= 3:                                    # YouTube bölümleri için en az 3 gerekir
        parts += ["Bölümler:", chapters_text(chapters), ""]
    parts.append(" ".join("#" + t.strip("# ").replace(" ", "") for t in tags if t.strip()))
    return "\n".join(parts).strip() + "\n"
