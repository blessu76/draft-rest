import contextlib
import datetime as dt
import io
import re
import shutil
import sys
import tempfile
import unittest
from unittest import mock
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))
import build_site  # noqa: E402
import publish_post  # noqa: E402
from test_build_site import write_post  # noqa: E402

KST = build_site.KST
FULL = "word " * 400  # a body that meets the 400-word / 800-character target in every language


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


class Lint(unittest.TestCase):
    """Warning-only SEO lint (SEO guide P1-2 follow-up list): thin body, long <title>, long description, duplicate title."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)

    def file(self, slug, lang):
        return self.dir / "posts" / slug / (lang + ".md" if lang in ("ko", "en") else "translations/%s.md" % lang)

    def edit(self, slug, lang, old, new):
        f = self.file(slug, lang)
        text = f.read_text(encoding="utf-8")
        self.assertIn(old, text)
        f.write_text(text.replace(old, new, 1), encoding="utf-8")

    def lint(self, slug="q-one"):
        return publish_post.lint_post(self.dir, slug)

    def test_clean_post_has_no_warnings(self):
        write_post(self.dir, "q-one", extra="draft: true\n", body=FULL)
        self.assertEqual(self.lint(), [])

    def test_body_thresholds_words_and_cjk_characters(self):
        write_post(self.dir, "q-one", body="word " * 299 + "\n\n## ## > -")
        w = self.lint()
        for c in ("en", "de", "fr"):
            self.assertTrue(any(x.startswith("q-one/%s: body is 299 words (< 300 floor)" % c) for x in w), (c, w))
        self.assertFalse(any("q-one/%s: body is" % c in x for c in ("ko", "ja", "zh") for x in w), w)  # 299 'words' = 1495 chars: long enough
        write_post(self.dir, "q-two", body="word " * 300)
        w = self.lint("q-two")
        self.assertTrue(any(x.startswith("q-two/en: body is 300 words (< 400 target)") for x in w), w)  # exactly 300 is above the floor, below the target
        self.assertFalse([x for x in w if "floor" in x])
        write_post(self.dir, "q-full", body="word " * 400)
        self.assertFalse([x for x in self.lint("q-full") if "body is" in x])
        write_post(self.dir, "q-cjk", body="가" * 599)
        w = self.lint("q-cjk")
        for c in ("ja", "zh"):
            self.assertTrue(any(x.startswith("q-cjk/%s: body is 599 chars (< 600 floor)" % c) for x in w), (c, w))
        self.assertTrue(any(x.startswith("q-cjk/ko: body is 599 chars (< 800 target)") for x in w), w)  # ko: target only, the build owns its floor
        self.assertFalse(any("q-cjk/ko" in x and "floor" in x for x in w), w)
        write_post(self.dir, "q-cjk2", body="가 " * 400)  # 400 visible characters + spaces
        self.assertTrue(any("q-cjk2/ko: body is 400 chars" in x for x in self.lint("q-cjk2")))
        write_post(self.dir, "q-cjk3", body="가" * 799)
        w = self.lint("q-cjk3")
        for c in ("ko", "ja", "zh"):
            self.assertTrue(any(x.startswith("q-cjk3/%s: body is 799 chars (< 800 target)" % c) for x in w), (c, w))
        self.assertFalse(any("floor" in x and x.split(":")[0].split("/")[1] in ("ko", "ja", "zh") for x in w), w)  # (the 1-word latin files are not the point here)
        write_post(self.dir, "q-cjk4", body="가" * 800)
        self.assertFalse(any(("q-cjk4/%s: body is" % c) in x for c in ("ko", "ja", "zh") for x in self.lint("q-cjk4")))

    def test_floor_and_target_findings_are_split(self):
        langs = {"en": {"_body": "w " * 299}, "ru": {"_body": "w " * 300}, "de": {"_body": "w " * 400},
                 "zh": {"_body": "字" * 599}, "ja": {"_body": "字" * 600}, "ko": {"_body": "字" * 799}}
        floor, target = publish_post.body_length_findings("s", langs)
        self.assertEqual([x.split(":")[0] for x in floor], ["s/en", "s/zh"])
        self.assertEqual([x.split(":")[0] for x in target], ["s/ja", "s/ko", "s/ru"])
        self.assertTrue(all(publish_post.is_floor_warning(x) for x in floor))
        self.assertFalse(any(publish_post.is_floor_warning(x) for x in target))

    def test_body_size_counts_visible_text_only(self):
        cjk = ("# 見出し\n\n- 項目あ\n> 引用い\n\n"
               "[リンク](https://example.com/very/long/url/path)と**強調**\n\n![図](img/a.png)\n\n"
               "```\nprint('code block content')\n```\n\n---\n<b>タグ</b>")
        # visible: 見出し(3) 項目あ(3) 引用い(3) リンク(3) と(1) 強調(2) タグ(2) = 17
        for lang in ("ja", "zh"):
            self.assertEqual(publish_post.body_size(cjk, lang), (17, "chars"))
        latin = "# Title here\n\n1. first item\n2. second item\n- bullet one\n> quoted words\n\n[link text](https://x.io/a/b) and **bold** *it*\n\n```\nnot counted at all\n```\n\n![alt](a.png)\n---\n"
        # Title here(2) first item(2) second item(2) bullet one(2) quoted words(2) link text and bold it(5) = 15
        self.assertEqual(publish_post.body_size(latin, "en"), (15, "words"))
        self.assertEqual(publish_post.body_size("1. a\n2) b\n3. c", "de"), (3, "words"))

    def test_markdown_noise_does_not_lift_a_post_over_the_floor(self):
        noisy = "\n".join("- [字字字字字字字字字字](https://example.com/%s)" % ("p" * 30) for _ in range(59))  # 590 visible chars, URLs add far more
        floor, _ = publish_post.body_length_findings("s", {"ja": {"_body": noisy}})
        self.assertEqual([x.split(":")[0] for x in floor], ["s/ja"])
        self.assertIn("body is 590 chars", floor[0])

    def test_rendered_title_length_latin_60_cjk_40(self):
        write_post(self.dir, "q-one", body=FULL)
        self.edit("q-one", "en", "title: T en", "title: " + "x" * 60)  # suffix dropped by post_title: exactly 60, fine
        self.edit("q-one", "de", "title: T de", "title: " + "x" * 61)
        self.edit("q-one", "ko", "title: T ko", "title: " + "가" * 30)  # + ' — draft()' = 40, fine
        self.edit("q-one", "ja", "title: T ja", "title: " + "あ" * 31)  # 41 with suffix
        w = self.lint()
        self.assertFalse(any(x.startswith("q-one/en: <title>") for x in w), w)
        self.assertTrue(any(x.startswith("q-one/de: <title> is 61 chars (> 60)") for x in w), w)
        self.assertFalse(any(x.startswith("q-one/ko: <title>") for x in w), w)
        self.assertTrue(any(x.startswith("q-one/ja: <title> is 41 chars (> 40)") for x in w), w)

    def test_description_length_latin_160_cjk_110(self):
        write_post(self.dir, "q-one", body=FULL)
        self.edit("q-one", "en", "description: d en", "description: " + "x" * 160)
        self.edit("q-one", "fr", "description: d fr", "description: " + "x" * 161)  # the build refuses this one, the lint only warns
        self.edit("q-one", "ko", "description: d ko", "description: " + "가" * 110)
        self.edit("q-one", "zh", "description: d zh", "description: " + "字" * 111)
        w = self.lint()
        self.assertFalse(any(x.startswith("q-one/en: description") for x in w), w)
        self.assertTrue(any(x.startswith("q-one/fr: description is 161 chars (> 160)") for x in w), w)
        self.assertFalse(any(x.startswith("q-one/ko: description") for x in w), w)
        self.assertTrue(any(x.startswith("q-one/zh: description is 111 chars (> 110)") for x in w), w)

    def test_duplicate_title_inside_one_language(self):
        write_post(self.dir, "q-one", body=FULL)
        write_post(self.dir, "q-two", body=FULL)  # same fixture titles: 'T en', 'T ko' ...
        self.edit("q-two", "ko", "title: T ko", "title: 다른 제목")
        w = self.lint("q-two")
        self.assertTrue(any(x == "q-two/en: title is identical to the en title of post 'q-one'" for x in w), w)
        self.assertFalse(any("q-two/ko" in x and "identical" in x for x in w), w)
        self.edit("q-two", "en", "title: T en", "title:   t   EN ")  # case and spacing do not hide a duplicate
        self.assertTrue(any("q-two/en: title is identical" in x for x in self.lint("q-two")))

    def test_no_shared_image_warning(self):
        write_post(self.dir, "q-one", body=FULL)
        self.assertFalse(any("image" in x.lower() or "og-image" in x for x in self.lint()))

    def test_unreadable_file_is_a_warning_not_an_exception(self):
        write_post(self.dir, "q-one", body=FULL)
        self.file("q-one", "de").write_text("no front matter", encoding="utf-8")
        w = self.lint()
        self.assertTrue(any(x.startswith("q-one/de: cannot lint") for x in w), w)

    def test_cli_prints_warnings_to_stderr_and_still_succeeds(self):
        write_post(self.dir, "q-one", extra="draft: true\n", body="word " * 100)
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = publish_post.main(["q-one", "--root", str(self.dir), "--at", (dt.datetime.now(KST) - dt.timedelta(minutes=5)).isoformat()])
        self.assertEqual(code, 0)
        self.assertIn("draft flag removed", out.getvalue())
        self.assertIn("WARN q-one/en: body is 100 words (< 300 floor)", err.getvalue())
        self.assertIn("published anyway", err.getvalue())
        self.assertNotIn("draft", self.file("q-one", "en").read_text(encoding="utf-8").split("---")[1])  # it really published

    def publish_cli(self, slug="q-one"):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = publish_post.main([slug, "--root", str(self.dir), "--at", (dt.datetime.now(KST) - dt.timedelta(minutes=5)).isoformat()])
        return code, out.getvalue(), err.getvalue()

    def test_cli_below_floor_still_publishes_with_banner(self):
        write_post(self.dir, "q-one", extra="draft: true\n", body="word " * 299)
        code, out, err = self.publish_cli()
        self.assertEqual(code, 0)
        self.assertIn("LENGTH FLOOR", err)
        self.assertIn("published anyway", err)
        self.assertIn("q-one/en: body is 299 words (< 300 floor)", err)
        self.assertRegex(self.file("q-one", "en").read_text(encoding="utf-8"), r"(?m)^published: ")  # it really published
        self.assertNotRegex(self.file("q-one", "en").read_text(encoding="utf-8"), r"(?m)^draft:")

    def test_cli_below_target_warns_without_banner(self):
        write_post(self.dir, "q-one", extra="draft: true\n", body="word " * 350)
        code, out, err = self.publish_cli()
        self.assertEqual(code, 0)
        self.assertIn("WARN q-one/en: body is 350 words (< 400 target)", err)
        self.assertNotIn("LENGTH FLOOR", err)

    def test_cli_length_crash_never_changes_the_exit_code(self):
        write_post(self.dir, "q-one", extra="draft: true\n", body=FULL)
        with mock.patch.object(publish_post, "body_length_findings", side_effect=RuntimeError("boom")):
            code, out, err = self.publish_cli()
        self.assertEqual(code, 0)
        self.assertIn("draft flag removed", out)
        self.assertIn("WARN lint skipped", err)
        write_post(self.dir, "q-two", extra="draft: true\n", body="word " * 100)
        with mock.patch.object(publish_post, "is_floor_warning", side_effect=RuntimeError("boom")):
            code, out, err = self.publish_cli("q-two")
        self.assertEqual(code, 0)
        self.assertIn("WARN length banner skipped", err)

    def test_cli_survives_a_lint_crash(self):
        write_post(self.dir, "q-one", extra="draft: true\n", body=FULL)
        out, err = io.StringIO(), io.StringIO()
        for exc in (UnicodeDecodeError("utf-8", b"\xff", 0, 1, "bad"), KeyError("title"), RuntimeError("boom")):
            with mock.patch.object(publish_post, "lint_post", side_effect=exc), contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                code = publish_post.main(["q-one", "--root", str(self.dir), "--at", (dt.datetime.now(KST) - dt.timedelta(minutes=5)).isoformat()])
            self.assertEqual(code, 0)
        self.assertIn("draft flag removed", out.getvalue())
        self.assertIn("WARN lint skipped", err.getvalue())
        self.assertEqual(err.getvalue().count("\n"), 3)  # one WARN line per crash

    def test_lint_crash_in_a_foreign_post_file_does_not_fail_publishing(self):
        write_post(self.dir, "q-one", extra="draft: true\n", body=FULL)
        write_post(self.dir, "q-two", body=FULL)
        self.file("q-two", "en").write_bytes(b"---\n\xff\xfe\n---\n")  # not UTF-8
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = publish_post.main(["q-one", "--root", str(self.dir), "--at", (dt.datetime.now(KST) - dt.timedelta(minutes=5)).isoformat()])
        self.assertEqual(code, 0)

    def test_cli_is_quiet_when_nothing_to_warn_about(self):
        write_post(self.dir, "q-one", extra="draft: true\n", body=FULL)
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            publish_post.main(["q-one", "--root", str(self.dir), "--at", (dt.datetime.now(KST) - dt.timedelta(minutes=5)).isoformat()])
        self.assertEqual(err.getvalue(), "")

    def test_repo_posts_lint_without_crashing(self):
        for d in sorted((ROOT / "posts").iterdir()):
            if d.is_dir():
                self.assertIsInstance(publish_post.lint_post(ROOT, d.name), list)


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
