"""Kaynak-zaman aralıklarını (sessizlik, dolgu sözcüğü, silinen kelimeler…) timeline'dan keser."""
from __future__ import annotations

from .model import Clip, Timeline


def merge_ranges(ranges: list[tuple[float, float]], gap: float = 0.0) -> list[tuple[float, float]]:
    out: list[tuple[float, float]] = []
    for a, b in sorted(r for r in ranges if r[1] > r[0]):
        if out and a <= out[-1][1] + gap:
            out[-1] = (out[-1][0], max(out[-1][1], b))
        else:
            out.append((a, b))
    return out


def apply_cuts(tl: Timeline, clip: Clip, source_ranges: list[tuple[float, float]]) -> float:
    """clip'in KAYNAK zamanındaki aralıkları ripple ile keser. Toplam kesilen süreyi döndürür.
    Sondan başa uygulanır: önceki konumlar kaymaz. Video kanallarının hepsinden aynı aralık çıkar (senkron korunur)."""
    ids = [t.id for t in tl.tracks if t.kind == "video"]
    base_start, base_in, base_out, speed = clip.start, clip.source_in, clip.source_out, clip.speed
    cut_total = 0.0
    for a, b in reversed(merge_ranges(source_ranges)):
        a, b = max(a, base_in), min(b, base_out)
        if b - a <= 1e-3:
            continue
        ta = base_start + (a - base_in) / speed
        tb = base_start + (b - base_in) / speed
        tl.remove_range(ids, ta, tb, ripple=True)
        cut_total += tb - ta
    return cut_total


def source_to_timeline(tl: Timeline, media_path: str, t: float) -> float | None:
    """Kaynak zamanını (kesimlerden sonraki) timeline zamanına çevirir; kesilmişse None."""
    for tr in tl.tracks:
        if tr.kind != "video":
            continue
        for c in tr.clips:
            if c.media_path == media_path and c.source_in - 1e-6 <= t <= c.source_out + 1e-6:
                return c.start + (t - c.source_in) / c.speed
    return None


def apply_transitions(tl: Timeline, name: str, dur: float = 0.5, skip_same_media: bool = True) -> int:
    """Ana video kanalındaki klip sınırlarına geçiş atar. skip_same_media: aynı dosyanın ardışık parçaları
    (sessizlik kesimi gibi) arasına geçiş KONMAZ; yalnızca farklı kliplerin arasına konur. Atanan sayı döner."""
    main = next((t for t in tl.tracks if t.kind == "video" and t.clips), None)
    if main is None:
        return 0
    clips = sorted(main.clips, key=lambda c: c.start)
    n = 0
    for prev, cur in zip(clips, clips[1:]):
        if skip_same_media and prev.media_path == cur.media_path:
            continue
        cur.transition, cur.transition_dur = name, dur; n += 1
    return n
