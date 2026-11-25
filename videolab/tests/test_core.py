import os, sys, tempfile, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from videolab.core.model import Timeline, Clip
from videolab.core.history import History
from videolab.core.project import Project


class TimelineTests(unittest.TestCase):
    def setUp(self):
        self.tl = Timeline(30)
        self.v1 = self.tl.tracks[0].id
        self.c = self.tl.add_clip(self.v1, Clip("a.mp4", 0, 10, 0))

    def test_split(self):
        l, r = self.tl.split_clip(self.c.id, 4.0)
        self.assertAlmostEqual(l.end, 4.0); self.assertAlmostEqual(r.start, 4.0)
        self.assertAlmostEqual(r.source_in, 4.0); self.assertAlmostEqual(r.end, 10.0)

    def test_split_with_speed(self):
        c = self.tl.add_clip(self.v1, Clip("b.mp4", 0, 10, 20, speed=2.0))   # süre 5 sn
        l, r = self.tl.split_clip(c.id, 22.0)
        self.assertAlmostEqual(r.source_in, 4.0)

    def test_split_outside_fails(self):
        with self.assertRaises(ValueError):
            self.tl.split_clip(self.c.id, 11)

    def test_ripple_remove_middle(self):
        self.tl.remove_range([self.v1], 3, 5)
        clips = self.tl.tracks[0].clips
        self.assertEqual(len(clips), 2)
        self.assertAlmostEqual(clips[1].start, 3.0); self.assertAlmostEqual(clips[1].source_in, 5.0)
        self.assertAlmostEqual(self.tl.duration, 8.0)

    def test_move_across_kind_rejected(self):
        with self.assertRaises(ValueError):
            self.tl.move_clip(self.c.id, 1, self.tl.tracks[2].id)

    def test_undo_redo(self):
        h = History(self.tl)
        h.checkpoint("böl"); self.tl.split_clip(self.c.id, 5)
        self.assertEqual(len(self.tl.tracks[0].clips), 2)
        h.undo(); self.assertEqual(len(self.tl.tracks[0].clips), 1)
        h.redo(); self.assertEqual(len(self.tl.tracks[0].clips), 2)

    def test_save_load(self):
        p = Project(name="Deneme", timeline=self.tl)
        with tempfile.TemporaryDirectory() as d:
            path = p.save(os.path.join(d, "x.vlab"))
            q = Project.load(path)
            self.assertEqual(q.name, "Deneme")
            self.assertAlmostEqual(q.timeline.duration, 10.0)


if __name__ == "__main__":
    unittest.main()
