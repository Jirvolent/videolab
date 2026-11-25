import os, shutil, subprocess, sys, tempfile, unittest
import numpy as np
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from videolab.core.model import Timeline, Clip
from videolab.export.exporter import ExportSettings, TRANSITIONS, export
from videolab.media.ffmpeg import probe


def mk(path, color, dur, sine=True):
    args = ["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", f"color=c={color}:s=640x360:r=30:d={dur}"]
    if sine:
        args += ["-f", "lavfi", "-i", f"sine=f=300:d={dur}"]
    subprocess.run(args + ["-c:v", "libx264", "-pix_fmt", "yuv420p"] + (["-c:a", "aac"] if sine else []) + [path], check=True)


def pixel(path, t, x, y, w=1280, h=720):
    raw = subprocess.run(["ffmpeg", "-v", "error", "-ss", str(t), "-i", path, "-frames:v", "1", "-f", "rawvideo",
                          "-pix_fmt", "rgb24", "-"], capture_output=True, check=True).stdout
    a = np.frombuffer(raw, np.uint8).reshape(h, w, 3)
    return a[y, x].astype(int)


@unittest.skipUnless(shutil.which("ffmpeg"), "ffmpeg gerekli")
class Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.d = tempfile.mkdtemp()
        cls.red = os.path.join(cls.d, "red.mp4"); cls.blue = os.path.join(cls.d, "blue.mp4"); cls.silent = os.path.join(cls.d, "silent.mp4")
        mk(cls.red, "red", 4); mk(cls.blue, "blue", 4); mk(cls.silent, "green", 3, sine=False)

    @classmethod
    def tearDownClass(cls): shutil.rmtree(cls.d, ignore_errors=True)

    def _two(self, trans, dur=0.5):
        tl = Timeline(30); v = tl.tracks[0].id
        tl.add_clip(v, Clip(self.red, 0, 4, 0)); tl.add_clip(v, Clip(self.blue, 0, 4, 4, transition=trans, transition_dur=dur))
        return tl

    def test_crossfade_duration_and_blend(self):
        out = os.path.join(self.d, "x.mp4")
        export(self._two("fade", 1.0), ExportSettings(out, resolution="720p"))
        self.assertAlmostEqual(probe(out).duration, 7.0, delta=0.15)           # 4 + 4 - 1
        self.assertTrue(probe(out).has_audio)
        a, mid, b = pixel(out, 1.0, 100, 100), pixel(out, 3.5, 100, 100), pixel(out, 5.5, 100, 100)
        self.assertGreater(a[0], 200); self.assertGreater(b[2], 200)           # başta kırmızı, sonda mavi
        self.assertTrue(mid[0] > 60 and mid[2] > 60)                           # ortada karışım

    def test_mixed_cut_and_transition_with_silent_clip(self):
        tl = Timeline(30); v = tl.tracks[0].id
        tl.add_clip(v, Clip(self.red, 0, 2, 0)); tl.add_clip(v, Clip(self.red, 2, 4, 2))            # düz kesme
        tl.add_clip(v, Clip(self.silent, 0, 3, 4, transition="wipeleft", transition_dur=0.5))       # sessiz klip + geçiş
        tl.add_clip(v, Clip(self.blue, 0, 4, 7))                                                    # düz kesme
        out = os.path.join(self.d, "m.mp4"); export(tl, ExportSettings(out, resolution="720p"))
        self.assertAlmostEqual(probe(out).duration, 4 + 3 - 0.5 + 4, delta=0.2)

    def test_many_transitions_valid(self):
        for name in ["dissolve", "fadeblack", "slideleft", "circleopen", "pixelize", "zoomin", "radial", "squeezeh"]:
            out = os.path.join(self.d, f"t_{name}.mp4"); export(self._two(name, 0.4), ExportSettings(out, resolution="720p"))
            self.assertAlmostEqual(probe(out).duration, 7.6, delta=0.2, msg=name)

    def test_overlay_image_window(self):
        png = os.path.join(self.d, "meme.png")
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "color=c=yellow:s=400x400", "-frames:v", "1", png], check=True)
        tl = Timeline(30); tl.add_clip(tl.tracks[0].id, Clip(self.blue, 0, 4, 0))
        tl.add_clip(tl.tracks[1].id, Clip(png, 0, 1.5, 1.0, scale=0.3, pos_x=0.5, pos_y=0.5))      # V2: 1.0–2.5 sn
        out = os.path.join(self.d, "o.mp4"); export(tl, ExportSettings(out, resolution="720p"))
        self.assertTrue(pixel(out, 0.5, 640, 360)[2] > 200)                      # önce mavi
        p = pixel(out, 1.75, 640, 360); self.assertTrue(p[0] > 200 and p[1] > 200 and p[2] < 80)   # sarı meme
        self.assertTrue(pixel(out, 3.2, 640, 360)[2] > 200)                      # sonra yine mavi
        self.assertAlmostEqual(probe(out).duration, 4.0, delta=0.15)

    def test_overlay_video_meme(self):
        tl = Timeline(30); tl.add_clip(tl.tracks[0].id, Clip(self.blue, 0, 4, 0))
        tl.add_clip(tl.tracks[1].id, Clip(self.red, 0, 1, 2.0, scale=0.25, pos_x=1.0, pos_y=1.0))  # sağ alt, kısa video
        out = os.path.join(self.d, "ov.mp4"); export(tl, ExportSettings(out, resolution="720p"))
        p = pixel(out, 2.5, 1200, 650); self.assertTrue(p[0] > 200 and p[2] < 80)
        self.assertTrue(pixel(out, 1.0, 1200, 650)[2] > 200)


if __name__ == "__main__":
    unittest.main()
