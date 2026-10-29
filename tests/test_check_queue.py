import contextlib
import io
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


def write(root, slug, desc=None, ko_len=1400, extra="draft: true\n", skip=(), slug_in_file=None, words=400, cjk=800):
    for c in build_site.CODES:
        if c in skip:
            continue
        f = Path(root) / "posts" / slug / (c + ".md" if c in ("ko", "en") else "translations/%s.md" % c)
        f.parent.mkdir(parents=True, exist_ok=True)
        body = "가" * ko_len if c == "ko" else "字" * cjk if c in ("ja", "zh") else "word " * words
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

    def test_body_floor_is_an_error_target_is_a_warning(self):
        write(self.dir, "q-floor", words=299)
        _, errors, warnings = check_queue.scan(self.dir)
        self.assertEqual(len(errors), 8, errors)  # en es pt id ru vi fr de
        self.assertIn("q-floor/ru: body is 299 words (< 300 floor)", errors)
        shutil.rmtree(self.dir / "posts")
        write(self.dir, "q-mid", words=300)
        _, errors, warnings = check_queue.scan(self.dir)
        self.assertEqual(errors, [])
        self.assertEqual(len(warnings), 8, warnings)
        self.assertIn("q-mid/ru: body is 300 words (< 400 target)", warnings)
        shutil.rmtree(self.dir / "posts")
        write(self.dir, "q-full", words=400)
        self.assertEqual(check_queue.scan(self.dir), (["q-full"], [], []))

    def test_cjk_floor_and_ko_target(self):
        write(self.dir, "q-cjk", cjk=599)
        _, errors, _ = check_queue.scan(self.dir)
        self.assertEqual(sorted(e.split(":")[0] for e in errors), ["q-cjk/ja", "q-cjk/zh"])
        shutil.rmtree(self.dir / "posts")
        write(self.dir, "q-cjk", cjk=600, ko_len=build_site.KO_BODY_MIN)  # ko at the build minimum (1,100 chars) is already above the 800-char target
        _, errors, warnings = check_queue.scan(self.dir)
        self.assertEqual(errors, [])
        self.assertEqual(sorted(w.split(":")[0] for w in warnings), ["q-cjk/ja", "q-cjk/zh"])

    def test_main_prints_warnings_and_exits_by_errors_only(self):
        write(self.dir, "q-mid", words=350)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = check_queue.main(["--root", str(self.dir)])
        self.assertEqual(code, 0)
        self.assertIn("check_queue: WARN q-mid/en: body is 350 words (< 400 target)", buf.getvalue())
        write(self.dir, "q-low", words=100)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = check_queue.main(["--root", str(self.dir)])
        self.assertEqual(code, 1)

    def test_published_posts_are_not_floor_checked_by_default(self):
        write(self.dir, "already-live", words=50, extra="published: 2026-10-28T00:00:00+09:00\n")
        self.assertEqual(self.run_check(), ([], []))
        self.assertTrue(any("floor" in e for e in self.run_check("already-live")[1]))  # explicit slug = verify mode

    def test_build_never_fails_on_short_published_body(self):
        write(self.dir, "q-short", words=50, extra="")
        _, build_errors = build_site.load_posts(self.dir)
        self.assertFalse([e for e in build_errors if "body is" in e and ("floor" in e or "words" in e)], build_errors)

    def test_queue_and_publish_share_findings(self):
        write(self.dir, "q-share", words=250)
        from publish_post import lint_post
        queue_floor = [e for e in self.run_check()[1] if "floor" in e]
        lint_floor = [w for w in lint_post(self.dir, "q-share") if "floor" in w]
        self.assertEqual(queue_floor, lint_floor)
        self.assertEqual(len(queue_floor), 8)

    def test_real_queue_in_this_repo_is_clean(self):
        _, errors = check_queue.check_queue(ROOT)
        self.assertEqual(errors, [])


if __name__ == "__main__":
    unittest.main()
