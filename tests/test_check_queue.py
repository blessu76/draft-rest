import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import build_site  # noqa: E402
import check_queue  # noqa: E402

FM = "---\ntitle: T %s\ndescription: %s\ndate: 2026-10-28\nslug: %s\n%s---\n\n%s\n"


def write(root, slug, desc=None, ko_len=1400, extra="draft: true\n", skip=(), slug_in_file=None):
    for c in build_site.CODES:
        if c in skip:
            continue
        f = Path(root) / "posts" / slug / (c + ".md" if c in ("ko", "en") else "translations/%s.md" % c)
        f.parent.mkdir(parents=True, exist_ok=True)
        body = "가" * ko_len if c == "ko" else "word " * 300
        d = (desc or {}).get(c, "short description " + c)
        f.write_text(FM % (c, d, slug_in_file or slug, extra, body), encoding="utf-8")


class CheckQueue(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def run_check(self, *slugs):
        return check_queue.check_queue(self.dir, list(slugs) or None)

    def test_good_draft_passes_and_published_posts_are_skipped(self):
        write(self.dir, "q-good")
        write(self.dir, "already-live", extra="published: 2026-10-28T00:00:00+09:00\n")
        checked, errors = self.run_check()
        self.assertEqual((checked, errors), (["q-good"], []))

    def test_description_limit_is_the_build_limit_per_language(self):
        write(self.dir, "q-edge", desc={"fr": "x" * build_site.DESC_MAX, "de": "x" * (build_site.DESC_MAX + 1)})
        _, errors = self.run_check()
        self.assertEqual(len(errors), 1)
        self.assertIn("q-edge/de: description is %d chars" % (build_site.DESC_MAX + 1), errors[0])

    def test_queue_check_and_build_agree(self):
        write(self.dir, "q-long", desc={"fr": "x" * 161}, extra="")
        _, build_errors = build_site.load_posts(self.dir)
        _, queue_errors = self.run_check("q-long")
        self.assertEqual([e for e in queue_errors if "description" in e], [e for e in build_errors if "description" in e])
        write(self.dir, "q-short", ko_len=build_site.KO_BODY_MIN - 1, extra="")
        _, build_errors = build_site.load_posts(self.dir)
        _, queue_errors = self.run_check("q-short")
        self.assertEqual([e for e in queue_errors if "ko body" in e], [e for e in build_errors if "ko body" in e])

    def test_ko_body_bounds(self):
        for n, ok in ((build_site.KO_BODY_MIN - 1, False), (build_site.KO_BODY_MIN, True), (build_site.KO_BODY_MAX, True), (build_site.KO_BODY_MAX + 1, False)):
            shutil.rmtree(self.dir / "posts", ignore_errors=True)
            write(self.dir, "q-ko", ko_len=n)
            self.assertEqual(self.run_check()[1] == [], ok, n)

    def test_missing_language_and_slug_mismatch(self):
        write(self.dir, "q-miss", skip=("vi",))
        _, errors = self.run_check()
        self.assertTrue(any("missing language file vi" in e for e in errors), errors)
        shutil.rmtree(self.dir / "posts")
        write(self.dir, "q-slug", slug_in_file="other")
        _, errors = self.run_check()
        self.assertTrue(any("folder name" in e for e in errors), errors)

    def test_draft_must_not_be_stamped_and_must_have_a_date(self):
        write(self.dir, "q-stamp", extra="draft: true\npublished: 2026-10-28T16:00:00+09:00\n")
        _, errors = self.run_check()
        self.assertTrue(any("must not carry `published`" in e for e in errors), errors)
        f = self.dir / "posts" / "q-stamp" / "en.md"
        f.write_text(f.read_text().replace("date: 2026-10-28\n", ""), encoding="utf-8")
        _, errors = self.run_check()
        self.assertTrue(any("en" in e and "date" in e for e in errors), errors)

    def test_draft_flag_must_match_across_languages(self):
        write(self.dir, "q-mix")
        f = self.dir / "posts" / "q-mix" / "translations" / "fr.md"
        f.write_text(f.read_text().replace("draft: true\n", ""), encoding="utf-8")
        _, errors = self.run_check()
        self.assertTrue(any("`draft` differs" in e for e in errors), errors)

    def test_real_queue_in_this_repo_is_clean(self):
        _, errors = check_queue.check_queue(ROOT)
        self.assertEqual(errors, [])


if __name__ == "__main__":
    unittest.main()
