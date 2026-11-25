import os, subprocess, sys, tempfile, unittest, shutil
import numpy as np
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from videolab.core.model import Timeline, Clip
from videolab.export.exporter import ExportSettings, export
from videolab.export.censor import CensorRegion
from videolab.media.ffmpeg import probe, stream_pcm


@unittest.skipUnless(shutil.which("ffmpeg"), "ffmpeg gerekli")
class ExportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.d = tempfile.mkdtemp()
        cls.src = os.path.join(cls.d, "src.mp4")
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc=s=640x360:r=30:d=6",
                        "-f", "lavfi", "-i", "sine=f=300:d=6", "-c:v", "libx264", "-pix_fmt", "yuv420p",
                        "-c:a", "aac", cls.src], check=True)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.d, ignore_errors=True)

    def _tl(self):
        tl = Timeline(30)
        tl.add_clip(tl.tracks[0].id, Clip(self.src, 0, 6, 0))
        return tl

    def test_cut_out_middle_and_export(self):
        tl = self._tl()
        tl.remove_range([tl.tracks[0].id], 2.0, 4.0)
        out = os.path.join(self.d, "o.mp4")
        seen = []
        export(tl, ExportSettings(out, resolution="720p"), on_progress=lambda f, r: seen.append(f))
        info = probe(out)
        self.assertAlmostEqual(info.duration, 4.0, delta=0.15)
        self.assertEqual((info.width, info.height), (1280, 720))
        self.assertTrue(info.has_audio)
        self.assertAlmostEqual(seen[-1], 1.0)

    def test_vertical_and_speed(self):
        tl = Timeline(30)
        tl.add_clip(tl.tracks[0].id, Clip(self.src, 0, 6, 0, speed=2.0))
        out = os.path.join(self.d, "v.mkv")
        export(tl, ExportSettings(out, container="mkv", aspect="9:16", resolution="720p", fps=24))
        info = probe(out)
        self.assertEqual((info.width, info.height), (720, 1280))
        self.assertAlmostEqual(info.duration, 3.0, delta=0.2)

    def test_beep_covers_word(self):
        tl = self._tl()
        out = os.path.join(self.d, "b.mp4")
        export(tl, ExportSettings(out, censor=[CensorRegion(2.0, 3.0, "mute")]))
        pcm = np.concatenate(list(stream_pcm(out, 16000, 5)))
        rms = lambda a, b: float(np.sqrt(np.mean(pcm[int(a * 16000):int(b * 16000)] ** 2)))
        self.assertGreater(rms(0.5, 1.5), 0.05)
        self.assertLess(rms(2.1, 2.9), 0.01)        # sessize alındı
        out2 = os.path.join(self.d, "b2.mp4")
        export(tl, ExportSettings(out2, censor=[CensorRegion(2.0, 3.0, "beep")]))
        pcm = np.concatenate(list(stream_pcm(out2, 16000, 5)))
        self.assertGreater(rms(2.1, 2.9), 0.1)      # bip duyuluyor

    def test_cancel(self):
        import threading
        ev = threading.Event(); ev.set()
        out = os.path.join(self.d, "c.mp4")
        with self.assertRaises(InterruptedError):
            export(self._tl(), ExportSettings(out), cancel=ev)
        self.assertFalse(os.path.exists(out))


if __name__ == "__main__":
    unittest.main()


@unittest.skipUnless(shutil.which("ffmpeg"), "ffmpeg gerekli")
class ExportExtrasTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import scipy.io.wavfile as w
        cls.d = tempfile.mkdtemp()
        sr = 16000; t = np.arange(6 * sr) / sr
        speech = (0.4 * np.sin(2 * np.pi * 300 * t) * ((t >= 2) & (t < 4))).astype(np.float32)   # konuşma yalnızca 2-4 sn
        w.write(os.path.join(cls.d, "speech.wav"), sr, (speech * 32767).astype(np.int16))
        cls.src = os.path.join(cls.d, "src.mp4")
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc=s=1280x720:r=30:d=6",
                        "-i", os.path.join(cls.d, "speech.wav"), "-shortest", "-c:v", "libx264", "-pix_fmt", "yuv420p",
                        "-c:a", "aac", cls.src], check=True)
        cls.music = os.path.join(cls.d, "music.wav")
        w.write(cls.music, sr, (0.4 * np.sin(2 * np.pi * 900 * t) * 32767).astype(np.int16))

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.d, ignore_errors=True)

    def _tl(self):
        tl = Timeline(30)
        tl.add_clip(tl.tracks[0].id, Clip(self.src, 0, 6, 0))
        tl.add_clip(tl.tracks[2].id, Clip(self.music, 0, 6, 0))      # A1: müzik
        return tl

    @staticmethod
    def _tone_level(pcm, a, b, freq, sr=16000):
        seg = pcm[int(a * sr):int(b * sr)]
        spec = np.abs(np.fft.rfft(seg * np.hanning(len(seg)))) / len(seg)
        return float(spec[int(freq * len(seg) / sr)])

    def test_music_ducks_under_speech(self):
        out = os.path.join(self.d, "d.mp4")
        export(self._tl(), ExportSettings(out, ducking=True))
        pcm = np.concatenate(list(stream_pcm(out, 16000, 5)))
        free = self._tone_level(pcm, 0.5, 1.5, 900)       # konuşma yokken müzik
        ducked = self._tone_level(pcm, 2.6, 3.6, 900)     # konuşma sırasında müzik
        self.assertGreater(free, 0.01)
        self.assertLess(ducked, free * 0.6)

    def test_no_ducking_keeps_music(self):
        out = os.path.join(self.d, "nd.mp4")
        export(self._tl(), ExportSettings(out, ducking=False))
        pcm = np.concatenate(list(stream_pcm(out, 16000, 5)))
        self.assertAlmostEqual(self._tone_level(pcm, 2.6, 3.6, 900) / self._tone_level(pcm, 0.5, 1.5, 900), 1.0, delta=0.15)

    def test_loudnorm_runs(self):
        out = os.path.join(self.d, "ln.mp4")
        export(self._tl(), ExportSettings(out, loudnorm=True))
        self.assertTrue(probe(out).has_audio)

    def test_burn_ass_and_stabilize(self):
        from videolab.analysis.transcript_tools import Cue, SubStyle, to_ass
        from videolab.analysis.profanity import Word
        ass = os.path.join(self.d, "s.ass")
        ws = [Word("Merhaba", 1, 1.5), Word("dünya", 1.5, 2)]
        open(ass, "w", encoding="utf-8").write(to_ass([Cue(1, 2, "Merhaba dünya", ws)], SubStyle(), 1280, 720))
        out = os.path.join(self.d, "sub.mp4")
        export(self._tl(), ExportSettings(out, subtitle_ass=ass, stabilize=True, auto_color=True, resolution="720p"))
        self.assertEqual(probe(out).width, 1280)

    def test_follow_crop_vertical(self):
        out = os.path.join(self.d, "f.mp4")
        keys = [(0, 0.3), (2, 0.3), (3, 0.7), (6, 0.7)]
        export(self._tl(), ExportSettings(out, aspect="9:16", resolution="720p", follow=keys))
        info = probe(out)
        self.assertEqual((info.width, info.height), (720, 1280))

    def test_follow_expr_is_bounded(self):
        from videolab.export.exporter import follow_expr
        e = follow_expr([(i * 0.5, 0.5 + 0.1 * (i % 3)) for i in range(5000)], 720)
        self.assertLess(len(e), 40000)
