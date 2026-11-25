import os, shutil, subprocess, sys, tempfile, threading, unittest
import numpy as np
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from videolab.analysis.autocrop import smooth_track
from videolab.analysis.profanity import Word
from videolab.core.pipeline import AutoEditOptions, Job, JobQueue, auto_edit
from videolab.core.plugins import load_plugins
from videolab.analysis.silence import SilenceParams
from videolab.export.exporter import ExportSettings
from videolab.media.ffmpeg import probe, stream_pcm
from videolab.media.proxy import make_proxy, waveform_peaks
from videolab.media.recorder import build_record_command
from videolab.media.youtube import build_description, pick_thumbnails


class PureTests(unittest.TestCase):
    def test_smooth_track_deadzone_and_loss(self):
        raw = [(i * .5, 0.30 + (0.01 if i % 2 else 0)) for i in range(10)]           # titreme: kamera durmalı
        raw += [(5 + i * .5, None) for i in range(4)]                                # yüz kayıp: son konumda kal
        raw += [(7 + i * .5, 0.75) for i in range(10)]                               # kişi sağa geçti
        keys = smooth_track(raw)
        self.assertLess(len(keys), 8)
        self.assertAlmostEqual(keys[0][1], 0.30, delta=0.03); self.assertAlmostEqual(keys[-1][1], 0.75, delta=0.03)
        self.assertEqual(keys, sorted(keys))

    def test_plugins_isolated(self):
        d = tempfile.mkdtemp()
        open(os.path.join(d, "good.py"), "w").write("def register(api):\n    api.add_analyzer('x', lambda w: [])\n")
        open(os.path.join(d, "bad.py"), "w").write("raise RuntimeError('bozuk')\n")
        api, errs = load_plugins(d)
        self.assertIn("x", api.analyzers); self.assertEqual(len(errs), 1)
        shutil.rmtree(d)

    def test_record_commands(self):
        c = build_record_command("screen", "o.mp4", platform="win32"); self.assertIn("gdigrab", c)
        c = build_record_command("webcam", "o.mp4", platform="win32", webcam_name="Cam"); self.assertIn("video=Cam", c)
        c = build_record_command("screen", "o.mp4", platform="linux"); self.assertIn("x11grab", c)
        with self.assertRaises(ValueError): build_record_command("webcam", "o.mp4", platform="win32")

    def test_description(self):
        d = build_description("Başlık", "Özet", [(0, "A"), (60, "B"), (120, "C")], ["müzik", "gitar dersi"])
        self.assertIn("00:00 A", d); self.assertIn("#gitardersi", d)

    def test_queue_continues_after_failure(self):
        q = JobQueue()
        def bad(p, c): raise RuntimeError("x")
        q.add(Job("a", bad)); q.add(Job("b", lambda p, c: 42))
        q.run_all()
        self.assertEqual([j.status for j in q.jobs], ["hata", "bitti"]); self.assertEqual(q.jobs[1].result, 42)
        q2 = JobQueue(); q2.add(Job("c", lambda p, c: 1)); ev = threading.Event(); ev.set(); q2.run_all(cancel=ev)
        self.assertEqual(q2.jobs[0].status, "iptal")


@unittest.skipUnless(shutil.which("ffmpeg"), "ffmpeg gerekli")
class MediaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import scipy.io.wavfile as w
        cls.d = tempfile.mkdtemp(); sr = 16000; t = np.arange(int(12 * sr)) / sr
        m = ((t < 3) | ((t >= 5) & (t < 8)) | (t >= 9)).astype(float)               # 3-5 ve 8-9 sessiz
        w.write(os.path.join(cls.d, "a.wav"), sr, (0.5 * np.sin(2 * np.pi * 300 * t) * m * 32767).astype(np.int16))
        cls.src = os.path.join(cls.d, "src.mp4")
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc=s=640x360:r=30:d=12",
                        "-i", os.path.join(cls.d, "a.wav"), "-shortest", "-c:v", "libx264", "-pix_fmt", "yuv420p",
                        "-c:a", "aac", cls.src], check=True)

    @classmethod
    def tearDownClass(cls): shutil.rmtree(cls.d, ignore_errors=True)

    def test_proxy_and_waveform(self):
        out = make_proxy(self.src, os.path.join(self.d, "p.mp4"), 180)
        self.assertEqual(probe(out).height, 180)
        pk = waveform_peaks(self.src, 20)
        self.assertAlmostEqual(len(pk), 12 * 20, delta=6)
        self.assertGreater(pk[20], 0.3); self.assertLess(pk[80], 0.05)               # 4. sn sessiz

    def test_thumbnails(self):
        paths = pick_thumbnails(self.src, os.path.join(self.d, "th"), 2)
        self.assertEqual(len(paths), 2); self.assertTrue(all(os.path.getsize(p) > 1000 for p in paths))

    def test_auto_edit_silence_filler_profanity(self):
        words = [Word("merhaba", 0.2, 0.8), Word("ııı", 1.0, 1.4), Word("siktir", 6.0, 6.5), Word("bitti", 9.5, 10)]
        out = os.path.join(self.d, "auto.mp4")
        opt = AutoEditOptions(silence=SilenceParams(min_silence=0.6), remove_fillers=True, censor_profanity=True,
                              transcriber=lambda p: words)
        s = auto_edit(self.src, ExportSettings(out), opt)
        self.assertEqual((s["silences"], s["fillers"], s["profanity"]), (2, 1, 1))
        info = probe(out)
        self.assertAlmostEqual(info.duration, 12 - s["cut_seconds"], delta=0.25)
        self.assertLess(info.duration, 11)
        # sansürlü bölge, kesimlerden sonraki zamanda sessiz olmalı (ses vardı, mute değil bip: yine de bip genliği 0.35)
        pcm = np.concatenate(list(stream_pcm(out, 16000, 5)))
        self.assertGreater(len(pcm) / 16000, 5)


if __name__ == "__main__":
    unittest.main()
