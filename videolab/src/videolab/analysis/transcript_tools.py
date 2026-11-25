"""Transkript tabanlı araçlar: dolgu sözcüğü, tekrar çekim, metinden düzenleme, bölümler, SRT/ASS altyazı."""
from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from difflib import SequenceMatcher

from .profanity import Word, normalize

# ---------------------------------------------------------------- dolgu sözcükleri
_FILLER_SOUNDS = [re.compile(p) for p in (
    r"^(e{2,}|ı{2,}m*|ö{2,}|a{2,}h?|h?m{2,}|hm+|ım+|ehm*|eh+)$",       # TR: eee, ııı, hmm
    r"^(u+h+m*|u+m+|e+r+m*|h+m+|a+h+|e+h+)$")]                           # EN: uh, um, erm
_FILLER_WORDS_TR = {"yani", "şey", "işte", "falan", "filan", "hani", "böyle"}   # varsayılan KAPALI (gerçek kelimeler)
_FILLER_PHRASES_EN = [("you", "know"), ("i", "mean"), ("sort", "of"), ("kind", "of")]  # varsayılan KAPALI


@dataclass
class Span:
    start: float
    end: float
    text: str
    kind: str                 # "filler" | "retake" | "deleted"
    approved: bool = True


def _clean(t: str) -> str:
    return re.sub(r"[^\wığüşöç]", "", t.lower().replace("İ", "i").replace("I", "ı"))


def find_fillers(words: list[Word], sounds: bool = True, tr_words: bool = False,
                 en_phrases: bool = False) -> list[Span]:
    out: list[Span] = []
    cleaned = [_clean(w.text) for w in words]
    skip = set()
    if en_phrases:
        for i in range(len(words) - 1):
            if (cleaned[i], cleaned[i + 1]) in _FILLER_PHRASES_EN:
                out.append(Span(words[i].start, words[i + 1].end, f"{words[i].text} {words[i+1].text}", "filler"))
                skip.update((i, i + 1))
    for i, (w, c) in enumerate(zip(words, cleaned)):
        if i in skip or not c:
            continue
        if (sounds and any(p.match(c) for p in _FILLER_SOUNDS)) or (tr_words and c in _FILLER_WORDS_TR):
            out.append(Span(w.start, w.end, w.text.strip(), "filler"))
    return sorted(out, key=lambda s: s.start)


# ---------------------------------------------------------------- cümleler ve tekrar çekim
def split_sentences(words: list[Word], gap: float = 0.7) -> list[list[Word]]:
    sents, cur = [], []
    for w in words:
        if cur and (w.start - cur[-1].end > gap or re.search(r"[.!?…]$", cur[-1].text.strip())):
            sents.append(cur); cur = []
        cur.append(w)
    if cur:
        sents.append(cur)
    return sents


def find_retakes(words: list[Word], similarity: float = 0.75, min_words: int = 4, window: float = 20.0) -> list[Span]:
    """Art arda söylenen benzer cümlelerde İLK deneme 'tekrar çekim' sayılır (son deneme kalır)."""
    sents = split_sentences(words)
    norm = [" ".join(normalize(w.text, fold=False) for w in s) for s in sents]
    out: list[Span] = []
    for i in range(len(sents) - 1):
        a, b = sents[i], sents[i + 1]
        if len(a) < min_words or len(b) < min_words or b[0].start - a[-1].end > window:
            continue
        if SequenceMatcher(None, norm[i], norm[i + 1]).ratio() >= similarity:
            out.append(Span(a[0].start, b[0].start, " ".join(w.text for w in a), "retake"))
    return out


# ---------------------------------------------------------------- metinden düzenleme
def ranges_from_deleted_words(words: list[Word], deleted: set[int], pad: float = 0.02) -> list[tuple[float, float]]:
    """Silinen kelime indekslerinden (ardışıklar birleşir) kaynak-zaman aralıkları üretir.
    Aralık, komşu kelimelere taşmayacak şekilde kırpılır."""
    out: list[tuple[float, float]] = []
    run: list[int] = []
    for i in sorted(deleted) + [-1]:
        if run and (i == -1 or i != run[-1] + 1):
            a = words[run[0]].start - pad if run[0] == 0 else max(words[run[0] - 1].end, words[run[0]].start - pad)
            b = words[run[-1]].end + pad if run[-1] == len(words) - 1 else min(words[run[-1] + 1].start, words[run[-1]].end + pad)
            out.append((max(0.0, a), b)); run = []
        if i != -1:
            run.append(i)
    return out


# ---------------------------------------------------------------- bölümler / YouTube zaman damgaları
_STOP = set("""bir bu şu ve ile için ama fakat çok daha gibi de da ki mi mı mu mü ne nasıl ben sen o biz siz onlar var yok
evet hayır yani şey işte tamam şimdi sonra önce kadar olarak olan oldu olur ise bunu şunu onu burada orada
the a an and or but to of in on at is are was were be it this that for with as you i we they he she so just like
have has had do does did not no yes can will would there here what when how why then them these those""".split())


def make_chapters(words: list[Word], target: int = 8, min_len: float = 45.0) -> list[tuple[float, str]]:
    """Konuşma duraklarına ve kelime dağarcığına göre bölüm başlıkları önerir. (başlangıç_sn, başlık)"""
    if not words:
        return []
    total = words[-1].end
    n = max(1, min(target, int(total // min_len)))
    pts = [0.0]
    for k in range(1, n):
        ideal = total * k / n
        cand = [i for i in range(1, len(words)) if abs(words[i].start - ideal) < total / n / 2]
        if not cand:
            continue
        best = max(cand, key=lambda i: (words[i].start - words[i - 1].end) - 0.0005 * abs(words[i].start - ideal))
        if words[best].start - pts[-1] >= min_len:
            pts.append(words[best].start)
    pts.append(total + 1)
    chapters = []
    for a, b in zip(pts, pts[1:]):
        cnt = Counter(c for w in words if a <= w.start < b for c in [_clean(w.text)] if len(c) > 3 and c not in _STOP)
        title = " ".join(w for w, _ in cnt.most_common(3)).title() or "Bölüm"
        chapters.append((a, title))
    return chapters


def fmt_ts(t: float) -> str:
    t = int(t); h, m, s = t // 3600, t % 3600 // 60, t % 60
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


def chapters_text(chapters: list[tuple[float, str]]) -> str:
    return "\n".join(f"{fmt_ts(t)} {title}" for t, title in chapters)


# ---------------------------------------------------------------- altyazı (cue) / SRT / ASS
@dataclass
class Cue:
    start: float
    end: float
    text: str
    words: list[Word] | None = None
    speaker: int | None = None


def words_to_cues(words: list[Word], max_chars: int = 42, max_dur: float = 5.0, gap: float = 0.8,
                  speakers: list[int] | None = None) -> list[Cue]:
    """speakers: her kelime için konuşmacı no (diarize.label_words); konuşmacı değişince yeni satır başlar."""
    cues, cur, cur_sp = [], [], []
    def flush():
        if cur:
            sp = cur_sp[0] if speakers and cur_sp[0] >= 0 else None
            cues.append(Cue(cur[0].start, cur[-1].end, " ".join(w.text.strip() for w in cur), list(cur), sp))
            cur.clear(); cur_sp.clear()
    for i, w in enumerate(words):
        sp = speakers[i] if speakers else 0
        if cur:
            text_len = len(" ".join(x.text.strip() for x in cur + [w]))
            if (w.start - cur[-1].end > gap or text_len > max_chars or w.end - cur[0].start > max_dur
                    or re.search(r"[.!?…]$", cur[-1].text.strip()) or (speakers and sp != cur_sp[0])):
                flush()
        cur.append(w); cur_sp.append(sp)
    flush()
    return cues


def _srt_time(t: float) -> str:
    ms = int(round(t * 1000)); h, ms = divmod(ms, 3600000); m, ms = divmod(ms, 60000); s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def speaker_name(n: int | None, names: dict[int, str] | None = None) -> str:
    return (names or {}).get(n, f"Konuşmacı {n + 1}") if n is not None else ""


def to_srt(cues: list[Cue], speaker_prefix: bool = False, names: dict[int, str] | None = None) -> str:
    def text(c: Cue) -> str:
        return f"{speaker_name(c.speaker, names)}: {c.text}" if speaker_prefix and c.speaker is not None else c.text
    return "\n".join(f"{i}\n{_srt_time(c.start)} --> {_srt_time(c.end)}\n{text(c)}\n" for i, c in enumerate(cues, 1))


def parse_srt(text: str) -> list[Cue]:
    cues = []
    for block in re.split(r"\n\s*\n", text.strip().replace("\r\n", "\n")):
        lines = block.split("\n")
        idx = next((i for i, l in enumerate(lines) if "-->" in l), None)
        if idx is None:
            continue
        m = re.findall(r"(\d+):(\d+):(\d+)[,.](\d+)", lines[idx])
        if len(m) != 2:
            continue
        t = [int(h) * 3600 + int(mi) * 60 + int(s) + int(ms.ljust(3, "0")[:3]) / 1000 for h, mi, s, ms in m]
        cues.append(Cue(t[0], t[1], "\n".join(lines[idx + 1:]).strip()))
    return cues


@dataclass
class SubStyle:
    font: str = "Arial"
    size: int = 54
    primary: str = "#FFD400"      # vurgulanan (söylenen) kelime
    base: str = "#FFFFFF"         # henüz söylenmemiş kelime
    outline_color: str = "#000000"
    outline: float = 3.0
    shadow: float = 1.0
    margin_v: int = 80
    bold: bool = True
    highlight_words: bool = True  # CapCut tarzı kelime vurgusu


def _ass_color(hex_color: str) -> str:
    h = hex_color.lstrip("#"); r, g, b = h[0:2], h[2:4], h[4:6]
    return f"&H00{b}{g}{r}".upper()


def _ass_time(t: float) -> str:
    cs = int(round(t * 100)); h, cs = divmod(cs, 360000); m, cs = divmod(cs, 6000); s, cs = divmod(cs, 100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


SPEAKER_COLORS = ["#FFD400", "#4DD2FF", "#7CFF6B", "#FF7AD9", "#FF9F40", "#B28DFF"]


def to_ass(cues: list[Cue], style: SubStyle, width: int = 1920, height: int = 1080) -> str:
    speakers = sorted({c.speaker for c in cues if c.speaker is not None})
    head = (f"[Script Info]\nScriptType: v4.00+\nPlayResX: {width}\nPlayResY: {height}\nWrapStyle: 0\n\n"
            "[V4+ Styles]\nFormat: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,OutlineColour,BackColour,Bold,"
            "Italic,Underline,StrikeOut,ScaleX,ScaleY,Spacing,Angle,BorderStyle,Outline,Shadow,Alignment,MarginL,MarginR,MarginV,Encoding\n"
            f"Style: Default,{style.font},{style.size},{_ass_color(style.primary)},{_ass_color(style.base)},"
            f"{_ass_color(style.outline_color)},&H80000000,{-1 if style.bold else 0},0,0,0,100,100,0,0,1,"
            f"{style.outline},{style.shadow},2,40,40,{style.margin_v},1\n"
            + "".join(f"Style: S{sp},{style.font},{style.size},{_ass_color(SPEAKER_COLORS[sp % len(SPEAKER_COLORS)])},"
                      f"{_ass_color(style.base)},{_ass_color(style.outline_color)},&H80000000,{-1 if style.bold else 0},0,0,0,100,100,0,0,1,"
                      f"{style.outline},{style.shadow},2,40,40,{style.margin_v},1\n" for sp in speakers)
            + "\n[Events]\nFormat: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text\n")
    lines = []
    for c in cues:
        if style.highlight_words and c.words:
            parts = []
            for i, w in enumerate(c.words):
                nxt = c.words[i + 1].start if i + 1 < len(c.words) else w.end
                parts.append(f"{{\\kf{max(1, int(round((nxt - w.start) * 100)))}}}{w.text.strip()}")
            text = " ".join(parts)
        else:
            text = c.text.replace("\n", "\\N")
        st = f"S{c.speaker}" if c.speaker is not None else "Default"
        lines.append(f"Dialogue: 0,{_ass_time(c.start)},{_ass_time(c.end)},{st},,0,0,0,,{text}")
    return head + "\n".join(lines) + "\n"
