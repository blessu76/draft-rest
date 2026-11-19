import datetime as dt
import random
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import pick_publish_time as ppt  # noqa: E402


def repo(stamps):
    d = Path(tempfile.mkdtemp())
    for i, s in enumerate(stamps):
        (d / "posts" / ("p%d" % i)).mkdir(parents=True)
        (d / "posts" / ("p%d" % i) / "ko.md").write_text("---\ntitle: t\npublished: %s\n---\nbody\n" % s, encoding="utf-8")
    return d


class Pick(unittest.TestCase):
    def test_always_in_window_and_off_round_minutes(self):
        d = repo([])
        for seed in range(300):
            t = ppt.pick(dt.date(2026, 11, 15), d, rng=random.Random(seed))
            h, m = map(int, t.split(" ")[1].split(":"))
            self.assertTrue(12 <= h <= 17, t)
            self.assertNotIn(m, (0, 30), t)

    def test_avoids_previous_day_hour(self):
        d = repo(["2026-11-14T16:00:00+09:00"])
        for seed in range(300):
            self.assertNotEqual(ppt.pick(dt.date(2026, 11, 15), d, rng=random.Random(seed)).split(" ")[1][:2], "16")

    def test_avoids_hour_already_used_same_day(self):
        d = repo(["2026-11-14T16:01:00+09:00"])
        for seed in range(300):
            t = ppt.pick(dt.date(2026, 11, 14), d, rng=random.Random(seed))
            self.assertNotEqual(t.split(" ")[1][:2], "16")

    def test_not_before(self):
        d = repo([])
        for seed in range(100):
            self.assertGreaterEqual(ppt.pick(dt.date(2026, 11, 15), d, 15 * 60 + 10, random.Random(seed)).split(" ")[1], "15:10")

    def test_nothing_left_raises(self):
        with self.assertRaises(ValueError):
            ppt.pick(dt.date(2026, 11, 15), repo([]), 18 * 60)

    def test_unreadable_stamps_are_ignored(self):
        d = repo(["not-a-time"])
        self.assertTrue(ppt.pick(dt.date(2026, 11, 15), d))


if __name__ == "__main__":
    unittest.main()
