import os, sys, unittest
import numpy as np
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from videolab.analysis.silence import SilenceParams, find_silences, frame_levels_db
from videolab.analysis.profanity import ProfanityFilter, Word, normalize


def tone_mask(sr, dur, speech):
    t = np.arange(int(sr * dur)) / sr
    m = np.zeros_like(t)
    for a, b in speech:
        m[(t >= a) & (t < b)] = 1
    return (0.5 * np.sin(2 * np.pi * 300 * t) * m).astype(np.float32)


class SilenceTests(unittest.TestCase):
    def test_detects_long_ignores_short(self):
        sr = 16000
        x = tone_mask(sr, 10.3, [(0, 3), (5, 8), (8.3, 10.3)])
        lv = frame_levels_db([x[:50000], x[50000:]], sr)      # parçalı akış
        segs = find_silences(lv, SilenceParams())
        self.assertEqual(len(segs), 1)
        self.assertAlmostEqual(segs[0].start, 3.0, places=1)
        self.assertAlmostEqual(segs[0].end, 5.0, places=1)
        self.assertGreater(segs[0].cut_start, segs[0].start)   # koruma payı bırakıldı
        self.assertLess(segs[0].cut_end, segs[0].end)

    def test_cut_ratio_leaves_natural_pause(self):
        sr = 16000
        x = tone_mask(sr, 10, [(0, 3), (7, 10)])
        lv = frame_levels_db([x], sr)
        full = find_silences(lv, SilenceParams(cut_ratio=1.0))[0]
        half = find_silences(lv, SilenceParams(cut_ratio=0.5))[0]
        self.assertAlmostEqual(half.cut_duration, full.cut_duration / 2, places=1)


class ProfanityTests(unittest.TestCase):
    def setUp(self):
        self.f = ProfanityFilter()

    def test_turkish_suffix_and_spelling(self):
        for w in ["siktir", "Siktir!", "siiiiktir", "s1ktir", "orospunun", "amk", "AMK", "götün", "gotune", "piçler"]:
            self.assertIsNotNone(self.f.is_profane(w), w)

    def test_no_false_positives(self):
        for w in ["sıkıntı", "sikke", "got", "pic", "class", "assistant", "merhaba", "analiz", "mal"]:
            self.assertIsNone(self.f.is_profane(w), w)

    def test_english(self):
        for w in ["fuck", "Fucking,", "shits", "bitch"]:
            self.assertIsNotNone(self.f.is_profane(w), w)
        self.assertIsNone(self.f.is_profane("shitake"))

    def test_scan_timings(self):
        hits = self.f.scan([Word("bu", 0, .2), Word("siktir", .3, .8), Word("git", .8, 1.0)])
        self.assertEqual(len(hits), 1)
        self.assertEqual((hits[0].start, hits[0].end), (.3, .8))

    def test_user_dictionary(self):
        self.f.add("zırtapoz")
        self.assertIsNotNone(self.f.is_profane("zırtapozlar"))


if __name__ == "__main__":
    unittest.main()
