import os, shutil, subprocess, sys, tempfile, unittest
import numpy as np
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from videolab.analysis.diarize import diarize, label_words, speech_regions
from videolab.analysis.profanity import Word
from videolab.analysis.silence import frame_levels_db
from videolab.core.branding import Branding, with_branding
from videolab.core.library import Library
from videolab.core.model import Clip, Timeline
from videolab.core.project import RecentProjects
from videolab.export.exporter import ExportSettings, export
from videolab.media.ffmpeg import probe


def voice(f0, formants, dur, sr=16000, seed=0):
    """Sentetik 'ses': temel frekans + formant benzeri filtre (farklı konuşmacı = farklı f0/formant)."""
    t = np.arange(int(dur * sr)) / sr
    rng = np.random.default_rng(seed)
    f = f0 * (1 + 0.03 * np.sin(2 * np.pi * 0.7 * t + rng.uniform(0, 6)))      # doğal titreşim
    ph = 2 * np.pi * np.cumsum(f) / sr
    x = sum(np.sin(k * ph) / k for k in range(1, 30))
    X = np.fft.rfft(x); fr = np.fft.rfftfreq(len(x), 1 / sr)
    env = sum(np.exp(-0.5 * ((fr - c) / 150) ** 2) for c in formants) + 0.05
    y = np.fft.irfft(X * env, len(x)); y = y / np.abs(y).max() * 0.5
    return y.astype(np.float32)


class DiarizeTests(unittest.TestCase):
    def test_two_synthetic_speakers(self):
        sr = 16000; gap = np.zeros(int(0.6 * sr), np.float32)
        A = lambda s: voice(110, [500, 1500], 3, seed=s); B = lambda s: voice(230, [800, 2500], 3, seed=s)
        x = np.concatenate([A(1), gap, B(2), gap, A(3), gap, B(4)])
        lv = frame_levels_db([x], sr); regions = speech_regions(lv)
        self.assertEqual(len(regions), 4)
        segs = diarize(x, sr, regions, n_speakers=2, backend="mfcc")
        def who(t): return next(s.speaker for s in segs if s.start <= t <= s.end)
        sp = [who(1.5), who(5.1), who(8.7), who(12.3)]
        self.assertEqual(sp[0], sp[2]); self.assertEqual(sp[1], sp[3]); self.assertNotEqual(sp[0], sp[1])
        words = [Word("a", 1, 1.4), Word("b", 5, 5.4)]
        lab = label_words(words, segs); self.assertNotEqual(lab[0], lab[1])

    def test_auto_speaker_count_single(self):
        sr = 16000; x = np.concatenate([voice(120, [500, 1500], 3, seed=s) for s in (1, 2)])
        segs = diarize(x, sr, [(0, 3), (3, 6)], backend="mfcc")
        self.assertEqual(len({s.speaker for s in segs}), 1)


@unittest.skipUnless(shutil.which("ffmpeg"), "ffmpeg gerekli")
class LibraryBrandingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.d = tempfile.mkdtemp()
        def mk(name, color, dur, audio=True):
            p = os.path.join(cls.d, name)
            a = ["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", f"color=c={color}:s=640x360:r=30:d={dur}"]
            if audio: a += ["-f", "lavfi", "-i", f"sine=f=400:d={dur}"]
            subprocess.run(a + ["-c:v", "libx264", "-pix_fmt", "yuv420p"] + (["-c:a", "aac"] if audio else []) + [p], check=True); return p
        cls.main = mk("main.mp4", "blue", 4); cls.intro = mk("intro.mp4", "red", 2, audio=False); cls.outro = mk("outro.mp4", "green", 1.5)
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "color=c=yellow:s=100x100", "-frames:v", "1", os.path.join(cls.d, "k.png")], check=True)
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "sine=f=800:d=0.7", os.path.join(cls.d, "boing.wav")], check=True)

    @classmethod
    def tearDownClass(cls): shutil.rmtree(cls.d, ignore_errors=True)

    def test_library_import_scan_search(self):
        lib = Library(os.path.join(self.d, "lib.db"), os.path.join(self.d, "library"))
        lib.import_file(os.path.join(self.d, "k.png"), "meme", "komik")
        lib.import_file(os.path.join(self.d, "boing.wav"), "sfx", "komik")
        # kullanıcı klasöre elle dosya da atabilir
        shutil.copy(os.path.join(self.d, "k.png"), os.path.join(self.d, "library", "memes", "kedi.png"))
        self.assertEqual(lib.scan(), 1)
        self.assertEqual(len(lib.search("", "meme")), 2); self.assertEqual(len(lib.search("komik")), 2)
        it = lib.search("boing")[0]; self.assertEqual(it.kind, "sfx"); self.assertAlmostEqual(it.duration, 0.7, delta=0.1)
        os.remove(os.path.join(self.d, "library", "memes", "kedi.png")); lib.scan()
        self.assertEqual(len(lib.search("", "meme")), 1)

    def test_branding_adds_intro_outro_and_exports(self):
        tl = Timeline(30); tl.add_clip(tl.tracks[0].id, Clip(self.main, 0, 4, 0))
        tl.add_clip(tl.tracks[2].id, Clip(os.path.join(self.d, "boing.wav"), 0, 0.7, 1.0))          # müzik/efekt, ana videonun 1. sn'sinde
        b = Branding(self.intro, self.outro) if False else Branding(self.intro, self.outro, transition="fade", transition_dur=0.5)
        bt = with_branding(tl, b)
        self.assertEqual(len(tl.tracks[0].clips), 1)                                                 # proje değişmedi
        self.assertEqual([c.label for c in bt.tracks[0].clips], ["intro", "", "outro"])
        self.assertAlmostEqual(bt.tracks[2].clips[0].start, 2.5, places=2)                           # efekt: intro 2 sn − geçiş 0.5 sn kadar kaydı
        out = os.path.join(self.d, "b.mp4"); export(bt, ExportSettings(out, resolution="720p"))
        self.assertAlmostEqual(probe(out).duration, 2 + 4 + 1.5 - 0.5 - 0.5, delta=0.2)
        self.assertTrue(probe(out).has_audio)                                                        # sessiz intro olsa da

    def test_branding_missing_file_is_skipped_and_store(self):
        tl = Timeline(30); tl.add_clip(tl.tracks[0].id, Clip(self.main, 0, 4, 0))
        bt = with_branding(tl, Branding("/yok/intro.mp4", "/yok/outro.mp4"))
        self.assertEqual(len(bt.tracks[0].clips), 1)
        store = RecentProjects(os.path.join(self.d, "s.db")); Branding(self.intro, self.outro, False, True, "dissolve").save(store)
        r = Branding.load(store); self.assertEqual((r.intro_path, r.intro_enabled, r.transition), (self.intro, False, "dissolve"))
        self.assertEqual(len(with_branding(tl, r).tracks[0].clips), 2)                               # yalnızca outro


if __name__ == "__main__":
    unittest.main()


class AutoCountTests(unittest.TestCase):
    def test_three_speakers_auto(self):
        sr = 16000
        parts = [voice(110, [500, 1500], 4, seed=1), voice(230, [800, 2500], 4, seed=2), voice(160, [400, 3000], 4, seed=3), voice(230, [800, 2500], 4, seed=5)]
        x = np.concatenate(parts); regions = [(i * 4, i * 4 + 4) for i in range(4)]
        segs = diarize(x, sr, regions, backend="mfcc")
        self.assertEqual(len({s.speaker for s in segs}), 3)


@unittest.skipUnless(shutil.which("ffmpeg"), "ffmpeg gerekli")
class StreamDiarizeTests(unittest.TestCase):
    def test_file_stream_matches(self):
        import scipy.io.wavfile as w
        from videolab.analysis.diarize import diarize_file
        sr = 16000; gap = np.zeros(int(0.8 * sr), np.float32)
        x = np.concatenate([voice(110, [500, 1500], 5, seed=1), gap, voice(230, [800, 2500], 5, seed=2), gap, voice(110, [500, 1500], 5, seed=3)])
        d = tempfile.mkdtemp(); p = os.path.join(d, "x.wav"); w.write(p, sr, (x * 32767).astype(np.int16))
        regions = speech_regions(frame_levels_db([x], sr)); self.assertEqual(len(regions), 3)
        segs = diarize_file(p, regions)
        who = lambda t: next(s.speaker for s in segs if s.start <= t <= s.end)
        self.assertEqual(who(2), who(12.5)); self.assertNotEqual(who(2), who(8))
        shutil.rmtree(d)

class TransitionAssignTests(unittest.TestCase):
    def test_skips_same_media(self):
        from videolab.core.edit_ops import apply_transitions
        tl = Timeline(30); v = tl.tracks[0].id
        tl.add_clip(v, Clip("a.mp4", 0, 2, 0)); tl.add_clip(v, Clip("a.mp4", 3, 5, 2)); tl.add_clip(v, Clip("b.mp4", 0, 2, 4))
        self.assertEqual(apply_transitions(tl, "dissolve", 0.4), 1)
        self.assertEqual([c.transition for c in tl.tracks[0].clips], ["none", "none", "dissolve"])
