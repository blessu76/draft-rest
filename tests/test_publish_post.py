import datetime as dt
import re
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))
import build_site  # noqa: E402
import publish_post  # noqa: E402
from test_build_site import write_post  # noqa: E402

KST = build_site.KST


class PublishPost(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)

    def test_stamps_date_and_published_and_removes_draft(self):
        write_post(self.dir, "q-one", extra="draft: true\n")
        when = dt.datetime.now(KST) - dt.timedelta(minutes=5)
        files, iso = publish_post.publish(self.dir, "q-one", when)
        self.assertEqual(len(files), len(build_site.CODES))
        for f in files:
            head = f.read_text(encoding="utf-8").split("---")[1]
            self.assertNotIn("draft", head)
            self.assertIn("date: %s\n" % when.date().isoformat(), head)
            self.assertEqual(re.findall(r"^published: (.*)$", head, flags=re.M), [iso])
        self.assertRegex(iso, r"^\d{4}-\d\d-\d\dT\d\d:\d\d:00\+09:00$")

    def test_default_time_is_now_kst_and_result_builds(self):
        for n in ("src", "assets", "locales", "content", "shared"):
            if (ROOT / n).is_dir():
                shutil.copytree(ROOT / n, self.dir / n)
        for n in ("llms.txt", "og-image.png"):
            shutil.copy(ROOT / n, self.dir / n)
        write_post(self.dir, "q-one", extra="draft: true\n")
        _, iso = publish_post.publish(self.dir, "q-one")
        posts, errors = build_site.load_posts(self.dir)
        self.assertEqual((len(posts), errors), (1, []))
        self.assertIn(">%s %s KST</time>" % (iso[:10], iso[11:16]), build_site.build(self.dir)["en/blog/q-one/index.html"])

    def test_bad_file_writes_nothing(self):
        write_post(self.dir, "q-one", extra="draft: true\n")
        bad = self.dir / "posts/q-one/translations/de.md"
        bad.write_text(re.sub(r"^date:.*\n", "", bad.read_text(encoding="utf-8"), flags=re.M), encoding="utf-8")
        before = {f: f.read_text(encoding="utf-8") for f in (self.dir / "posts").rglob("*.md")}
        with self.assertRaises(SystemExit) as cm:
            publish_post.publish(self.dir, "q-one")
        self.assertIn("no `date:` line", str(cm.exception))
        self.assertEqual(before, {f: f.read_text(encoding="utf-8") for f in (self.dir / "posts").rglob("*.md")})

    def test_future_time_is_refused(self):
        write_post(self.dir, "q-one", extra="draft: true\n")
        with self.assertRaises(SystemExit):
            publish_post.publish(self.dir, "q-one", dt.datetime.now(KST) + dt.timedelta(hours=2))


class PublishedRequired(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)

    def set_date(self, d):
        for f in (self.dir / "posts" / "a-post").rglob("*.md"):
            f.write_text(f.read_text(encoding="utf-8").replace("date: 2026-10-01", "date: " + d), encoding="utf-8")

    def test_missing_published_fails_from_cutoff_day(self):
        write_post(self.dir, "a-post")
        self.set_date("2026-10-24")
        self.assertTrue(any("`published` is required" in e for e in build_site.load_posts(self.dir)[1]))

    def test_with_published_it_passes(self):
        write_post(self.dir, "a-post", extra="published: 2026-10-24T09:00:00+09:00\n")
        self.set_date("2026-10-24")
        self.assertEqual(build_site.load_posts(self.dir)[1], [])

    def test_date_only_before_cutoff_still_allowed(self):
        write_post(self.dir, "a-post")
        self.set_date("2026-10-23")
        self.assertEqual(build_site.load_posts(self.dir)[1], [])


if __name__ == "__main__":
    unittest.main()
