import os, sys, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from videolab.analysis.profanity import Word
from videolab.analysis.transcript_tools import *
from videolab.core.model import Timeline, Clip
from videolab.core.edit_ops import apply_cuts, merge_ranges


def W(text, a, b): return Word(text, a, b)


class ToolsTests(unittest.TestCase):
    def test_fillers(self):
        ws = [W("Bugün", 0, .4), W("ııı", .5, 1.0), W("yani", 1.0, 1.3), W("um,", 1.4, 1.7), W("başlıyoruz", 1.8, 2.5)]
        f = find_fillers(ws)
        self.assertEqual([s.text for s in f], ["ııı", "um,"])
        self.assertEqual(len(find_fillers(ws, tr_words=True)), 3)

    def test_retake(self):
        a = [W(t, i * .4, i * .4 + .35) for i, t in enumerate("bugün sizlere yeni bir video getirdim".split())]
        b = [W(t, 4 + i * .4, 4 + i * .4 + .35) for i, t in enumerate("bugün sizlere yeni bir video getirdim".split())]
        r = find_retakes(a + b)
        self.assertEqual(len(r), 1); self.assertAlmostEqual(r[0].end, 4.0)

    def test_text_edit_ranges(self):
        ws = [W("a", 0, .5), W("b", .6, 1.0), W("c", 1.1, 1.5), W("d", 1.6, 2.0)]
        r = ranges_from_deleted_words(ws, {1, 2})
        self.assertEqual(len(r), 1); self.assertLess(r[0][0], .6); self.assertGreaterEqual(r[0][0], .5)
        self.assertLessEqual(r[0][1], 1.6)

    def test_apply_cuts_keeps_sync(self):
        tl = Timeline(30); c = tl.add_clip(tl.tracks[0].id, Clip("a.mp4", 0, 20, 0))
        cut = apply_cuts(tl, c, [(2, 3), (10, 12), (2.5, 3.5)])     # kesişen aralıklar birleşir
        self.assertAlmostEqual(cut, 3.5, places=2); self.assertAlmostEqual(tl.duration, 16.5, places=2)
        self.assertEqual(merge_ranges([(1, 2), (1.5, 3)]), [(1, 3)])

    def test_srt_roundtrip_and_ass(self):
        ws = [W("Merhaba", 0, .5), W("dünya.", .5, 1.0), W("İkinci", 3, 3.4), W("cümle", 3.4, 3.9)]
        cues = words_to_cues(ws)
        self.assertEqual(len(cues), 2)
        back = parse_srt(to_srt(cues))
        self.assertEqual([c.text for c in back], [c.text for c in cues])
        self.assertAlmostEqual(back[1].start, 3.0, places=2)
        ass = to_ass(cues, SubStyle())
        self.assertIn("\\kf", ass); self.assertIn("Dialogue: 0,0:00:00.00", ass)

    def test_chapters(self):
        ws = []
        for i in range(600):
            t = i * 1.0 + (3 if i % 150 == 0 and i else 0)
            ws.append(W("gitar" if i < 300 else "piyano", t, t + .5))
        ch = make_chapters(ws, target=4)
        self.assertEqual(ch[0][0], 0.0); self.assertGreaterEqual(len(ch), 2)
        self.assertTrue(chapters_text(ch).startswith("00:00 "))


if __name__ == "__main__":
    unittest.main()


class MappingTests(unittest.TestCase):
    def test_source_to_timeline_after_cut(self):
        from videolab.core.edit_ops import source_to_timeline
        tl = Timeline(30); c = tl.add_clip(tl.tracks[0].id, Clip("a.mp4", 0, 20, 0))
        apply_cuts(tl, c, [(2, 4)])
        self.assertAlmostEqual(source_to_timeline(tl, "a.mp4", 1.0), 1.0, places=2)
        self.assertAlmostEqual(source_to_timeline(tl, "a.mp4", 10.0), 8.0, places=2)
        self.assertIsNone(source_to_timeline(tl, "a.mp4", 3.0))


class SpeakerSubtitleTests(unittest.TestCase):
    def test_speaker_cues_srt_ass(self):
        ws = [W("Selam", 0, .4), W("nasılsın", .4, .9), W("iyiyim", 1.0, 1.4), W("sen", 1.4, 1.6)]
        cues = words_to_cues(ws, speakers=[0, 0, 1, 1])
        self.assertEqual([c.speaker for c in cues], [0, 1])
        self.assertTrue(to_srt(cues, speaker_prefix=True).count("Konuşmacı") == 2)
        self.assertEqual(speaker_name(1, {1: "Ayşe"}), "Ayşe")
        ass = to_ass(cues, SubStyle()); self.assertIn("Style: S0", ass); self.assertIn("Style: S1", ass); self.assertIn(",S1,,", ass)
