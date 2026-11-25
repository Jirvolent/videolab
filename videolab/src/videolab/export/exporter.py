"""Timeline -> gerçek video. Tek bir FFmpeg süreci, filter_complex ile akış tabanlı işlem (RAM'e yüklemez).
Kapsam (v0.1): V1 kanalı sıralı klipler (ses bağlı), hız, fade, sansür. Bindirme/geçiş sonraki aşamalar."""
from __future__ import annotations

import subprocess
import threading
from dataclasses import dataclass, field
from typing import Callable

from ..core.model import Timeline
from ..media.ffmpeg import FFmpegError, find_binary, probe, _NOWIN
from .censor import CensorRegion, beep_filter
from .voicefx import VoiceFX, build_filter

RESOLUTIONS = {"720p": 720, "1080p": 1080, "1440p": 1440, "4K": 2160}
ASPECTS = {"16:9": (16, 9), "9:16": (9, 16), "1:1": (1, 1)}


@dataclass
class ExportSettings:
    output: str
    container: str = "mp4"          # mp4 | mov | mkv
    codec: str = "h264"             # h264 | h265
    resolution: str = "1080p"       # kısa kenar değil, "yükseklik sınıfı" (dikeyde genişlik)
    aspect: str = "16:9"
    fps: int = 30
    crf: int = 20
    preset: str = "medium"
    hw: str = "none"                # none | nvenc | qsv | amf
    fit: str = "fit"                # fit (siyah bant) | fill (kırp)
    censor: list[CensorRegion] = field(default_factory=list)
    audio_bitrate: str = "192k"
    ducking: bool = False               # konuşma varken müziği kıs (sidechain)
    duck_threshold: float = 0.03        # doğrusal genlik (~ -30 dB)
    duck_ratio: float = 10.0
    loudnorm: bool = False              # LUFS normalizasyonu
    target_lufs: float = -14.0          # YouTube hedefi
    subtitle_ass: str | None = None     # videoya gömülecek .ass dosyası
    stabilize: bool = False             # deshake
    auto_color: bool = False            # otomatik renk/kontrast
    follow: list[tuple[float, float]] = field(default_factory=list)   # 9:16 takip: (timeline sn, merkez x 0..1)
    breath_envelope: str | None = None  # envelope.write_envelope ile yazılmış kazanç zarfı (nefes azaltma)
    declick: bool = False               # ağız sesi / tıkırtı azaltma (adeclick)
    voicefx: VoiceFX | None = None      # konuşma tonu eşitleme zinciri

    def size(self) -> tuple[int, int]:
        a, b = ASPECTS[self.aspect]
        short = RESOLUTIONS[self.resolution]
        if a >= b:
            h = short; w = round(h * a / b)
        else:
            w = short; h = round(w * b / a)
        return w // 2 * 2, h // 2 * 2


def _atempo(speed: float) -> str:
    chain, s = [], speed
    while s > 2.0:
        chain.append("atempo=2.0"); s /= 2.0
    while s < 0.5:
        chain.append("atempo=0.5"); s /= 0.5
    chain.append(f"atempo={s:.5f}")
    return ",".join(chain)


def _esc_path(p: str) -> str:
    """FFmpeg filtre sözdizimi için yol kaçışı (Windows sürücü harfi dahil)."""
    return p.replace("\\", "/").replace(":", "\\:").replace("'", "\\'")


def follow_expr(keys: list[tuple[float, float]], out_w: int, max_steps: int = 120) -> str:
    """Zamana bağlı crop x ifadesi: anahtar karelerin merkezi arasında doğrusal geçiş.
    Anahtar sayısı max_steps'i aşarsa seyreltilir (ifade uzunluğu sınırlı kalır)."""
    keys = sorted(keys)
    if len(keys) > max_steps:
        stride = len(keys) / max_steps
        keys = [keys[int(i * stride)] for i in range(max_steps)]
    def px(c):  # merkez oranı -> sol kenar piksel ifadesi, kare dışına taşmaz
        return f"max(0,min(iw-{out_w},{c:.4f}*iw-{out_w / 2:.1f}))"
    if not keys:
        return f"(iw-{out_w})/2"
    expr = px(keys[-1][1])
    for (t0, c0), (t1, c1) in reversed(list(zip(keys, keys[1:]))):
        seg = f"({c0:.4f}+({c1 - c0:.4f})*(t-{t0:.3f})/{max(t1 - t0, 1e-3):.3f})"
        expr = f"if(lt(t,{t1:.3f}),max(0,min(iw-{out_w},{seg}*iw-{out_w / 2:.1f})),{expr})"
    return f"if(lt(t,{keys[0][0]:.3f}),{px(keys[0][1])},{expr})"


def _encoder(s: ExportSettings) -> list[str]:
    names = {("h264", "none"): "libx264", ("h265", "none"): "libx265",
             ("h264", "nvenc"): "h264_nvenc", ("h265", "nvenc"): "hevc_nvenc",
             ("h264", "qsv"): "h264_qsv", ("h265", "qsv"): "hevc_qsv",
             ("h264", "amf"): "h264_amf", ("h265", "amf"): "hevc_amf"}
    enc = names[(s.codec, s.hw)]
    args = ["-c:v", enc]
    if s.hw == "none":
        args += ["-preset", s.preset, "-crf", str(s.crf)]
        if s.codec == "h265" and s.container in ("mp4", "mov"):
            args += ["-tag:v", "hvc1"]
    elif s.hw == "nvenc":
        args += ["-preset", "p5", "-cq", str(s.crf)]
    else:
        args += ["-global_quality", str(s.crf)]
    return args + ["-pix_fmt", "yuv420p"]


IMAGE_EXT = (".png", ".jpg", ".jpeg", ".webp", ".bmp")

TRANSITIONS = {   # xfade adı -> Türkçe etiket
    "none": "Yok (düz kesme)", "fade": "Karartmasız geçiş (fade)", "dissolve": "Çözülme", "fadeblack": "Siyaha geçiş",
    "fadewhite": "Beyaza geçiş", "wipeleft": "Sola silme", "wiperight": "Sağa silme", "wipeup": "Yukarı silme",
    "wipedown": "Aşağı silme", "slideleft": "Sola kayma", "slideright": "Sağa kayma", "slideup": "Yukarı kayma",
    "slidedown": "Aşağı kayma", "smoothleft": "Yumuşak sola", "smoothright": "Yumuşak sağa", "circleopen": "Daire açılma",
    "circleclose": "Daire kapanma", "radial": "Radyal", "pixelize": "Pikselleşme", "zoomin": "Yakınlaşma",
    "hblur": "Yatay bulanıklık", "squeezeh": "Yatay sıkıştırma", "squeezev": "Dikey sıkıştırma", "diagtl": "Çapraz",
    "horzopen": "Yatay açılma", "vertopen": "Dikey açılma", "fadegrays": "Griye geçiş", "hlslice": "Dilimler",
}


def _group_clips(clips) -> list[list[int]]:
    """Geçişsiz bitişik klipler tek concat grubunda; geçiş olan sınırlarda yeni grup başlar."""
    groups: list[list[int]] = [[0]]
    for i in range(1, len(clips)):
        if clips[i].transition not in ("none", "") and clips[i].transition_dur > 0.04:
            groups.append([i])
        else:
            groups[-1].append(i)
    return groups


def build_command(tl: Timeline, s: ExportSettings) -> tuple[list[str], float]:
    vtracks = [t for t in tl.tracks if t.kind == "video"]
    main = next((t for t in vtracks if t.clips), None)
    if main is None:
        raise FFmpegError("Dışa aktarılacak klip yok")
    overlays = [c for t in vtracks if t is not main for c in sorted(t.clips, key=lambda c: c.start)]
    clips = sorted(main.clips, key=lambda c: c.start)
    W, H = s.size()
    paths: list[str] = []
    for c in clips:
        if c.media_path not in paths:
            paths.append(c.media_path)
    infos = {p: probe(p) for p in paths}
    f: list[str] = []
    for i, c in enumerate(clips):
        idx = paths.index(c.media_path)
        dur = c.duration
        if s.follow:
            scale = f"scale=-2:{H}"
        elif s.fit == "fill":
            scale = f"scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H}"
        else:
            scale = f"scale={W}:{H}:force_original_aspect_ratio=decrease,pad={W}:{H}:(ow-iw)/2:(oh-ih)/2:black"
        vline = (f"[{idx}:v]trim=start={c.source_in:.4f}:end={c.source_out:.4f},"
                 f"setpts=(PTS-STARTPTS)/{c.speed:.5f},{scale},setsar=1,fps={s.fps},format=yuv420p,settb=AVTB")
        if c.fade_in > 0:
            vline += f",fade=t=in:st=0:d={c.fade_in:.3f}"
        if c.fade_out > 0:
            vline += f",fade=t=out:st={max(0, dur - c.fade_out):.3f}:d={c.fade_out:.3f}"
        f.append(vline + f"[v{i}]")
        if infos[c.media_path].has_audio:
            af = (f"[{idx}:a]atrim=start={c.source_in:.4f}:end={c.source_out:.4f},asetpts=PTS-STARTPTS,"
                  f"{_atempo(c.speed)},aresample=48000,aformat=channel_layouts=stereo")
        else:
            af = f"anullsrc=r=48000:cl=stereo,atrim=duration={dur:.4f},asetpts=PTS-STARTPTS"
        if c.volume != 1.0:
            af += f",volume={c.volume:.3f}"
        if c.fade_in > 0:
            af += f",afade=t=in:st=0:d={c.fade_in:.3f}"
        if c.fade_out > 0:
            af += f",afade=t=out:st={max(0, dur - c.fade_out):.3f}:d={c.fade_out:.3f}"
        f.append(af + f"[a{i}]")

    # ---- gruplar (concat) ve aralarındaki geçişler (xfade / acrossfade)
    groups = _group_clips(clips)
    gdur = []
    for k, g in enumerate(groups):
        gdur.append(sum(clips[i].duration for i in g))
        if len(g) == 1:
            f.append(f"[v{g[0]}]null[gv{k}]"); f.append(f"[a{g[0]}]anull[ga{k}]")
        else:
            f.append("".join(f"[v{i}][a{i}]" for i in g) + f"concat=n={len(g)}:v=1:a=1[gv{k}t][ga{k}]")
            f.append(f"[gv{k}t]settb=AVTB[gv{k}]")
    cur_v, cur_a, cur_dur = "gv0", "ga0", gdur[0]
    for k in range(1, len(groups)):
        c0 = clips[groups[k][0]]
        d = min(c0.transition_dur, cur_dur - 0.05, gdur[k] - 0.05)
        name = c0.transition if c0.transition in TRANSITIONS else "fade"
        f.append(f"[{cur_v}][gv{k}]xfade=transition={name}:duration={d:.3f}:offset={cur_dur - d:.3f}[xv{k}]")
        f.append(f"[{cur_a}][ga{k}]acrossfade=d={d:.3f}[xa{k}]")
        cur_v, cur_a, cur_dur = f"xv{k}", f"xa{k}", cur_dur + gdur[k] - d
    f.append(f"[{cur_v}]null[vcat0]"); f.append(f"[{cur_a}]anull[acat]")
    total = cur_dur

    # ---- video son işlemleri
    chain = []
    if s.follow:
        chain.append(f"crop={W}:{H}:x='{follow_expr(s.follow, W)}':y=0")
    if s.stabilize:
        chain.append("deshake")
    if s.auto_color:
        chain.append("normalize=smoothing=30")
    f.append(f"[vcat0]{','.join(chain) if chain else 'null'}[vbase]")

    # ---- ses: sansür -> müzik/efekt (A kanalları) -> ducking -> LUFS
    steps = [k for k, on in (("env", bool(s.breath_envelope)), ("declick", s.declick), ("fx", s.voicefx is not None)) if on]
    labels, cur_lbl = {}, "acat"
    for i, k in enumerate(steps):
        labels[k] = (cur_lbl, f"apre{i}"); cur_lbl = f"apre{i}"
    parts, _ = beep_filter(s.censor, in_label=cur_lbl, out_label="speech")
    f += parts
    music = [(t, c) for t in tl.tracks if t.kind == "audio" for c in t.clips]
    n_in = len(paths)
    extra_inputs: list[list[str]] = []
    for j, (_, c) in enumerate(music):
        idx = n_in + j
        extra_inputs.append(["-i", c.media_path])
        dur = c.duration
        mf = (f"[{idx}:a]atrim=start={c.source_in:.4f}:end={c.source_out:.4f},asetpts=PTS-STARTPTS,{_atempo(c.speed)},"
              f"aresample=48000,aformat=channel_layouts=stereo,volume={c.volume:.3f}")
        if c.fade_in > 0: mf += f",afade=t=in:st=0:d={c.fade_in:.3f}"
        if c.fade_out > 0: mf += f",afade=t=out:st={max(0, dur - c.fade_out):.3f}:d={c.fade_out:.3f}"
        ms = int(c.start * 1000)
        f.append(mf + f",adelay={ms}|{ms}[m{j}]")
    if "env" in labels:       # nefes kısma: konuşma sesi × kazanç zarfı (sıkıştırıcıdan ÖNCE; yoksa makeup nefesi yükseltir)
        env_idx = n_in + len(music); extra_inputs.append(["-i", s.breath_envelope])
        a, b = labels["env"]
        f.append(f"[{env_idx}:a]aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo:sample_rates=48000[envg]")
        f.append(f"[{a}]aformat=sample_fmts=fltp:channel_layouts=stereo:sample_rates=48000[envsrc]")
        f.append(f"[envsrc][envg]amultiply[{b}]")
    if "declick" in labels:
        a, b = labels["declick"]; f.append(f"[{a}]adeclick=w=25:o=75:a=8:t=2:b=4[{b}]")
    if "fx" in labels:
        a, b = labels["fx"]; f.append(f"[{a}]{build_filter(s.voicefx)}[{b}]")
    final = "speech"
    if music:
        if len(music) == 1:
            f.append("[m0]anull[music]")
        else:
            f.append("".join(f"[m{j}]" for j in range(len(music))) + f"amix=inputs={len(music)}:duration=longest:normalize=0[music]")
        if s.ducking:
            f.append("[speech]asplit=2[sp1][sp2]")
            f.append(f"[music][sp2]sidechaincompress=threshold={s.duck_threshold}:ratio={s.duck_ratio}:attack=20:release=500:makeup=1[ducked]")
            f.append("[sp1][ducked]amix=inputs=2:duration=first:normalize=0[mixed]")
        else:
            f.append("[speech][music]amix=inputs=2:duration=first:normalize=0[mixed]")
        final = "mixed"
    if s.loudnorm:
        f.append(f"[{final}]loudnorm=I={s.target_lufs}:TP=-1.5:LRA=11[aout]")
    else:
        f.append(f"[{final}]anull[aout]")

    # ---- bindirmeler (V2+): meme / görsel / logo; sonra altyazı en üstte
    cur = "vbase"
    for m, c in enumerate(overlays):
        idx = n_in + len(music) + (1 if s.breath_envelope else 0) + m
        dur = c.duration
        is_img = c.media_path.lower().endswith(IMAGE_EXT)
        if is_img:
            extra_inputs.append(["-loop", "1", "-framerate", str(s.fps), "-t", f"{dur:.3f}", "-i", c.media_path])
            pre = ""
        else:
            extra_inputs.append(["-stream_loop", "-1", "-t", f"{c.source_in + dur * c.speed:.3f}", "-i", c.media_path])
            pre = f"trim=start={c.source_in:.4f},setpts=(PTS-STARTPTS)/{c.speed:.5f},"
        ow = max(16, int(W * c.scale) // 2 * 2)
        fd = min(0.15, dur / 4)
        f.append(f"[{idx}:v]{pre}scale={ow}:-2,format=rgba,fade=t=in:st=0:d={fd:.3f}:alpha=1,"
                 f"fade=t=out:st={max(0, dur - fd):.3f}:d={fd:.3f}:alpha=1,setpts=PTS-STARTPTS+{c.start:.4f}/TB[ov{m}]")
        f.append(f"[{cur}][ov{m}]overlay=x='(W-w)*{c.pos_x:.3f}':y='(H-h)*{c.pos_y:.3f}':"
                 f"enable='between(t,{c.start:.3f},{c.start + dur:.3f})':eof_action=pass[o{m}]")
        cur = f"o{m}"
    if s.subtitle_ass:
        f.append(f"[{cur}]ass='{_esc_path(s.subtitle_ass)}'[vcat]")
    else:
        f.append(f"[{cur}]null[vcat]")

    cmd = [find_binary("ffmpeg"), "-y", "-v", "error", "-nostats", "-progress", "pipe:1"]
    for p in paths:
        cmd += ["-i", p]
    for args in extra_inputs:
        cmd += args
    cmd += ["-filter_complex", ";".join(f), "-map", "[vcat]", "-map", "[aout]"]
    cmd += _encoder(s) + ["-c:a", "aac", "-b:a", s.audio_bitrate, "-t", f"{total:.4f}"]
    if s.container in ("mp4", "mov"):
        cmd += ["-movflags", "+faststart"]
    cmd.append(s.output)
    return cmd, total


def export(tl: Timeline, s: ExportSettings, on_progress: Callable[[float, float | None], None] | None = None,
           cancel: threading.Event | None = None) -> None:
    """on_progress(yüzde 0-1, kalan_saniye). cancel.set() ile iptal edilir; yarım dosya silinir."""
    import os, time
    cmd, total = build_command(tl, s)
    t0 = time.time()
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, creationflags=_NOWIN)
    err: list[str] = []
    threading.Thread(target=lambda: err.append(proc.stderr.read()), daemon=True).start()
    try:
        for line in proc.stdout:
            if cancel is not None and cancel.is_set():
                proc.terminate(); proc.wait()
                if os.path.exists(s.output): os.remove(s.output)
                raise InterruptedError("Dışa aktarma iptal edildi")
            if line.startswith("out_time_us="):
                try:
                    done = int(line.split("=")[1]) / 1e6
                except ValueError:
                    continue
                frac = min(1.0, done / total) if total else 0.0
                el = time.time() - t0
                if on_progress:
                    on_progress(frac, (el / frac - el) if frac > 0.01 else None)
        proc.wait()
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()
        proc.stdout.close()
        proc.stderr.close()
    if proc.returncode != 0:
        raise FFmpegError("".join(err).strip()[-1500:] or "FFmpeg hata verdi")
    if on_progress:
        on_progress(1.0, 0.0)
