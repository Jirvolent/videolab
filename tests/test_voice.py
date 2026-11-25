import os, shutil, subprocess, sys, tempfile, unittest
import numpy as np
import scipy.io.wavfile as wavfile
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
sys.path.insert(0, os.path.dirname(__file__))
from test_library_branding_diarize import voice
from videolab.analysis.autoeq import analyze_file, deviation, measure_bands, suggest_eq
from videolab.analysis.breaths import BreathParams, detect_breaths_file, find_breaths, frame_features
from videolab.core.model import Clip, Timeline
from videolab.core.pipeline import AutoEditOptions, auto_edit
from videolab.core.voice_prep import VoiceOptions, prepare
from videolab.export.envelope import build_envelope, write_envelope
from videolab.export.exporter import ExportSettings, export
from videolab.export.voicefx import build_filter, preset
from videolab.media.ffmpeg import probe, stream_pcm

SR = 16000


def breath_noise(dur, amp, seed=0):
    """Gürültü benzeri nefes: 1–6 kHz bandında beyaz gürültü, yumuşak zarflı."""
    rng = np.random.default_rng(seed); n = int(dur * SR)
    x = rng.standard_normal(n); X = np.fft.rfft(x); f = np.fft.rfftfreq(n, 1 / SR)
    X[(f < 1000) | (f > 6000)] = 0; y = np.fft.irfft(X, n)
    y = y / np.abs(y).max() * amp
    return (y * np.hanning(n) ** 0.5).astype(np.float32)


def silence(d): return np.zeros(int(d * SR), np.float32)
def rms(x): return float(np.sqrt(np.mean(x.astype(np.float64) ** 2)))
def db(x): return 20 * np.log10(max(x, 1e-9))


def scene():
    """0-2 konuşma | 2.2-2.7 nefes | 2.8-5 konuşma | 5-6 sessiz | 6-8 konuşma (içinde 7.0-7.2 yüksek 's' sesi)"""
    sib = breath_noise(0.2, 0.25, 9)
    v3 = voice(110, [500, 1500], 2, seed=3).copy(); v3[int(1.0 * SR):int(1.2 * SR)] = sib       # konuşma içinde 's'
    return np.concatenate([voice(110, [500, 1500], 2, seed=1), silence(0.2), breath_noise(0.5, 0.05, 5), silence(0.1),
                           voice(110, [500, 1500], 2.2, seed=2), silence(1.0), v3]) + np.random.default_rng(0).normal(0, 1e-4, int(8.0 * SR)).astype(np.float32)


def write_wav(path, x): wavfile.write(path, SR, (np.clip(x, -1, 1) * 32767).astype(np.int16))


def make_video(path, wav):
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "color=c=gray:s=640x360:r=30:d=8", "-i", wav, "-shortest",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", path], check=True)


class BreathDetectTests(unittest.TestCase):
    def test_detects_breath_not_sibilant(self):
        x = scene(); db_, fl = frame_features([x], SR)
        segs = find_breaths(db_, fl)
        self.assertEqual(len(segs), 1, segs)
        self.assertAlmostEqual(segs[0].start, 2.2, delta=0.15); self.assertAlmostEqual(segs[0].end, 2.7, delta=0.15)

    def test_envelope_shape(self):
        env = build_envelope([(1.0, 2.0, 0.1)], 5.0, ramp=0.05)
        self.assertAlmostEqual(float(env[1500]), 0.1, places=2)               # bölge içi
        self.assertAlmostEqual(float(env[500]), 1.0, places=2); self.assertAlmostEqual(float(env[3000]), 1.0, places=2)
        self.assertTrue(0.1 < env[975] < 1.0)                                  # kenarda yumuşak geçiş


@unittest.skipUnless(shutil.which("ffmpeg"), "ffmpeg gerekli")
class VoiceExportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.d = tempfile.mkdtemp(); cls.x = scene()
        cls.wav = os.path.join(cls.d, "s.wav"); write_wav(cls.wav, cls.x)
        cls.src = os.path.join(cls.d, "s.mp4"); make_video(cls.src, cls.wav)

    @classmethod
    def tearDownClass(cls): shutil.rmtree(cls.d, ignore_errors=True)

    def _tl(self):
        tl = Timeline(30); tl.add_clip(tl.tracks[0].id, Clip(self.src, 0, 8, 0)); return tl

    def _pcm(self, path): return np.concatenate(list(stream_pcm(path, SR, 5)))

    def test_breath_reduction_exports(self):
        s = ExportSettings(os.path.join(self.d, "b.mp4"), resolution="720p")
        temps = prepare(s, self.src, VoiceOptions(breath=True, breath_gain_db=-18), lambda t: t, 8.0)
        export(self._tl(), s, None); [os.remove(t) for t in temps]
        before, after = self._pcm(self.src), self._pcm(s.output)
        seg = lambda a, b, p: p[int(a * SR):int(b * SR)]
        self.assertLess(db(rms(seg(2.3, 2.6, after))) - db(rms(seg(2.3, 2.6, before))), -12)     # nefes ≥12 dB kısıldı
        self.assertAlmostEqual(db(rms(seg(0.5, 1.5, after))), db(rms(seg(0.5, 1.5, before))), delta=1.5)   # konuşma korundu
        self.assertAlmostEqual(db(rms(seg(7.0, 7.2, after))), db(rms(seg(7.0, 7.2, before))), delta=1.5)   # 's' sesi dokunulmadı

    def test_breath_follows_cuts(self):
        """Sessizlik kesilince nefes zarfı doğru kayar: 2.0–3.2 sn kesilir, 3.2'deki nefes ~2.1 sn'ye gelir."""
        x = np.concatenate([voice(110, [500, 1500], 2, seed=1), silence(1.2), breath_noise(0.5, 0.05, 5), silence(0.1),
                            voice(110, [500, 1500], 2, seed=2)]) + np.random.default_rng(0).normal(0, 1e-4, int(5.8 * SR)).astype(np.float32)
        w = os.path.join(self.d, "f.wav"); write_wav(w, x); v = os.path.join(self.d, "f.mp4"); make_video(v, w)
        out = os.path.join(self.d, "p.mp4")
        from videolab.analysis.silence import SilenceParams
        opt = AutoEditOptions(silence=SilenceParams(min_silence=0.9, threshold_db=-55, pad_before=0.05, pad_after=0.05),
                              voice=VoiceOptions(breath=True, breath_gain_db=-18))
        summary = auto_edit(v, ExportSettings(out, resolution="720p"), opt)
        self.assertEqual(summary["silences"], 1)
        before, after = self._pcm(v), self._pcm(out)
        b_src = db(rms(before[int(3.3 * SR):int(3.6 * SR)])); b_out = db(rms(after[int(2.2 * SR):int(2.5 * SR)]))
        self.assertLess(b_out, b_src - 12, (b_src, b_out))                                          # kaymış nefes kısıldı
        self.assertAlmostEqual(db(rms(after[int(0.5 * SR):int(1.5 * SR)])), db(rms(before[int(0.5 * SR):int(1.5 * SR)])), delta=1.5)

    def test_declick(self):
        x = voice(110, [500, 1500], 4, seed=1) * 0.0 + breath_noise(4, 0.002, 1) * 0 + (np.sin(2 * np.pi * 200 * np.arange(4 * SR) / SR) * 0.05).astype(np.float32)
        rng = np.random.default_rng(3); pos = [int(t * SR) for t in (0.8, 1.7, 2.6, 3.3)]
        for p in pos: x[p:p + 20] += (rng.standard_normal(20) * 0.5).astype(np.float32)             # ~1 ms tıkırtı
        w = os.path.join(self.d, "c.wav"); write_wav(w, x); v = os.path.join(self.d, "c.mp4"); make_video(v, w)
        tl = Timeline(30); tl.add_clip(tl.tracks[0].id, Clip(v, 0, 4, 0))
        o = os.path.join(self.d, "cd.mp4"); export(tl, ExportSettings(o, resolution="720p", declick=True))
        a, b = self._pcm(v), self._pcm(o)
        peak = lambda s, p: float(np.abs(s[p - 40:p + 60]).max())
        ratios = [peak(b, p) / peak(a, p) for p in pos]
        self.assertLess(float(np.mean(ratios)), 0.6, ratios)

    def test_leveling_reduces_dynamic_range(self):
        loud = voice(110, [500, 1500], 2, seed=1); quiet = (voice(110, [500, 1500], 2, seed=2) * 0.08).astype(np.float32)
        x = np.concatenate([loud, silence(0.3), quiet, silence(0.3), loud, silence(0.3), quiet])
        w = os.path.join(self.d, "l.wav"); write_wav(w, x); v = os.path.join(self.d, "l.mp4"); make_video(v, w)
        tl = Timeline(30); tl.add_clip(tl.tracks[0].id, Clip(v, 0, 8, 0))
        o = os.path.join(self.d, "lo.mp4"); export(tl, ExportSettings(o, resolution="720p", voicefx=preset("podcast")))
        a, b = self._pcm(v), self._pcm(o)
        gap = lambda p: db(rms(p[int(0.3 * SR):int(1.7 * SR)])) - db(rms(p[int(2.6 * SR):int(3.9 * SR)]))   # yüksek - kısık (dB)
        self.assertGreater(gap(a), 20); self.assertLess(gap(b), gap(a) - 8)

    def test_preset_filters_valid(self):
        for name in ("dogal", "podcast", "youtube", "zayif_mikrofon"):
            v = os.path.join(self.d, f"{name}.mp4"); tl = self._tl()
            export(tl, ExportSettings(v, resolution="720p", voicefx=preset(name)))
            self.assertTrue(probe(v).has_audio, name)


@unittest.skipUnless(shutil.which("ffmpeg"), "ffmpeg gerekli")
def shaped_speech(perturb, dur=12.0, seed=0):
    """Hedef konuşma eğrisine göre şekillendirilmiş, hece ritminde modüle edilmiş gürültü (+ bantlara bozulma)."""
    from videolab.analysis.autoeq import TARGET
    rng = np.random.default_rng(seed); n = int(dur * SR)
    X = np.fft.rfft(rng.standard_normal(n)); f = np.fft.rfftfreq(n, 1 / SR)
    pts = sorted((c, TARGET[c] + perturb.get(c, 0)) for c in TARGET)
    gdb = np.interp(np.log2(np.maximum(f, 1)), np.log2([p[0] for p in pts]), [p[1] for p in pts])
    gdb = gdb - 10 * np.log10(np.maximum(f, 1) / 1000)          # TARGET 1/3 oktav BAND seviyesi: yoğunluk = band / bant genişliği
    gdb[f < 80] = -60
    y = np.fft.irfft(X * 10 ** (gdb / 20), n)
    t = np.arange(n) / SR; env = np.clip(np.sin(2 * np.pi * 3.5 * t), 0, None) ** 0.5            # hece benzeri açılıp kapanma
    y = y * env; return (y / np.abs(y).max() * 0.6).astype(np.float32)


@unittest.skipUnless(shutil.which("ffmpeg"), "ffmpeg gerekli")
class AutoEQTests(unittest.TestCase):
    def test_autoeq_fixes_boomy_dull_voice(self):
        d = tempfile.mkdtemp()
        x = shaped_speech({160: 6, 250: 6, 400: 3, 2500: -5, 4000: -6})                              # boğuk + mat ses
        w = os.path.join(d, "a.wav"); write_wav(w, x)
        before = measure_bands(stream_pcm(w, SR, 5), SR); eq = suggest_eq(before, 1.0)
        self.assertTrue(any(f <= 400 and g < -1.5 for f, g, _ in eq)); self.assertTrue(any(f >= 2500 and g > 1.5 for f, g, _ in eq))
        out = os.path.join(d, "b.wav")
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", w, "-af", ",".join(f"equalizer=f={f:.0f}:t=q:w={q}:g={g}" for f, g, q in eq), out], check=True)
        after = measure_bands(stream_pcm(out, SR, 5), SR)
        self.assertLess(deviation(after), deviation(before) * 0.6, (deviation(before), deviation(after)))
        self.assertEqual(suggest_eq(measure_bands(stream_pcm(w, SR, 5), SR), 0.0), [])
        shutil.rmtree(d)

    def test_balanced_voice_needs_little(self):
        d = tempfile.mkdtemp(); w = os.path.join(d, "n.wav"); write_wav(w, shaped_speech({}))
        eq = suggest_eq(measure_bands(stream_pcm(w, SR, 5), SR), 1.0)
        self.assertTrue(all(abs(g) < 2.5 for _, g, _ in eq), eq); shutil.rmtree(d)


if __name__ == "__main__":
    unittest.main()
