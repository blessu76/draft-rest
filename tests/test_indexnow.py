import contextlib
import datetime as dt
import io
import re
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import indexnow  # noqa: E402

KEY = "0123456789abcdef0123456789abcdef"
SITEMAP = """<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9" xmlns:xhtml="http://www.w3.org/1999/xhtml">
  <url><loc>https://example.test/</loc>
    <xhtml:link rel="alternate" hreflang="ko" href="https://example.test//ko/"/></url>
  <url><loc>https://example.test/a/</loc></url>
  <url><loc>https://example.test/a/</loc></url>
</urlset>
"""


class IndexNow(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)

    def test_find_key(self):
        (self.dir / "notes.txt").write_text("x\n")
        (self.dir / (KEY + ".txt")).write_text(KEY + "\n")
        self.assertEqual(indexnow.find_key(self.dir), KEY)

    def test_find_key_ignores_mismatch_and_long_names(self):
        (self.dir / (KEY + ".txt")).write_text("other\n")
        (self.dir / ("a" * 64 + ".txt")).write_text("a" * 64)
        with self.assertRaises(SystemExit):
            indexnow.find_key(self.dir)

    def test_sitemap_urls(self):
        (self.dir / "sitemap.xml").write_text(SITEMAP)
        self.assertEqual(indexnow.sitemap_urls(self.dir / "sitemap.xml"),
                         ["https://example.test/", "https://example.test/a/"])

    def test_payload(self):
        p = indexnow.build_payload(KEY, ["https://example.test/", "https://example.test/a/"])
        self.assertEqual(p["host"], "example.test")
        self.assertEqual(p["key"], KEY)
        self.assertEqual(p["keyLocation"], "https://example.test/%s.txt" % KEY)
        self.assertEqual(len(p["urlList"]), 2)

    def test_payload_rejects_empty_and_mixed_hosts(self):
        with self.assertRaises(SystemExit):
            indexnow.build_payload(KEY, [])
        with self.assertRaises(SystemExit):
            indexnow.build_payload(KEY, ["https://a.test/", "https://b.test/"])

    def test_dry_run_sends_nothing(self):
        (self.dir / "sitemap.xml").write_text(SITEMAP)
        (self.dir / (KEY + ".txt")).write_text(KEY)
        orig = indexnow.send
        indexnow.send = lambda *a, **k: self.fail("network call in dry-run")
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(indexnow.main(["--root", str(self.dir), "--dry-run"]), 0)
        finally:
            indexnow.send = orig

    def test_repo_sitemap_payload(self):
        urls = indexnow.sitemap_urls(ROOT / "sitemap.xml")
        key = indexnow.find_key(ROOT)  # the committed public key file <key>.txt (its content is the key itself)
        payload = indexnow.build_payload(key, urls)
        self.assertEqual(payload["keyLocation"], "https://draft.ipe.rest/%s.txt" % key)
        self.assertEqual(payload["host"], "draft.ipe.rest")


CHANGED_SITEMAP = """<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9" xmlns:xhtml="http://www.w3.org/1999/xhtml">
  <url><loc>https://example.test/</loc><lastmod>2026-10-29</lastmod></url>
  <url><loc>https://example.test/a/</loc><lastmod>2026-10-29T00:30:00+09:00</lastmod></url>
  <url><loc>https://example.test/b/</loc><lastmod>2026-10-28T23:59:00+09:00</lastmod></url>
  <url><loc>https://example.test/c/</loc><lastmod>2026-10-28T16:00:00+00:00</lastmod></url>
  <url><loc>https://example.test/d/</loc><lastmod>2026-10-27</lastmod></url>
  <url><loc>https://example.test/e/</loc><lastmod>garbage</lastmod></url>
</urlset>
"""
DAY = dt.date(2026, 10, 29)


class ChangedToday(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        (self.dir / "sitemap.xml").write_text(CHANGED_SITEMAP)
        (self.dir / (KEY + ".txt")).write_text(KEY)

    def run_main(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = indexnow.main(["--root", str(self.dir), *argv])
        return code, out.getvalue(), err.getvalue()

    def stub_send(self, fn):
        orig = indexnow.send
        indexnow.send = fn
        self.addCleanup(setattr, indexnow, "send", orig)

    def test_lastmod_day_is_converted_to_kst(self):
        self.assertEqual(indexnow.lastmod_day("2026-10-29"), DAY)
        self.assertEqual(indexnow.lastmod_day("2026-10-29T00:30:00+09:00"), DAY)
        self.assertEqual(indexnow.lastmod_day("2026-10-28T16:00:00+00:00"), DAY)  # 01:00 KST next day
        self.assertEqual(indexnow.lastmod_day("2026-10-28T16:00:00Z"), DAY)
        self.assertIsNone(indexnow.lastmod_day("garbage"))
        self.assertIsNone(indexnow.lastmod_day(None))

    def test_today_is_kst(self):
        late_utc = dt.datetime(2026, 10, 28, 16, 0, tzinfo=dt.timezone.utc)
        self.assertEqual(indexnow.today_kst(late_utc), DAY)

    def test_changed_urls_are_todays_plus_sitemap(self):
        self.assertEqual(indexnow.changed_urls(self.dir / "sitemap.xml", DAY),
                         ["https://example.test/", "https://example.test/a/", "https://example.test/c/", "https://example.test/sitemap.xml"])

    def test_nothing_changed_sends_nothing(self):
        self.stub_send(lambda *a, **k: self.fail("sent although nothing changed"))
        code, out, _ = self.run_main("--changed-today", "--date", "2026-10-30")
        self.assertEqual(code, 0)
        self.assertIn("nothing to submit", out)

    def test_changed_today_payload_and_dry_run(self):
        self.stub_send(lambda *a, **k: self.fail("network call in dry-run"))
        code, out, _ = self.run_main("--changed-today", "--date", "2026-10-29", "--dry-run")
        self.assertEqual(code, 0)
        payload = __import__("json").loads(out.split("\n", 1)[1])
        self.assertEqual(payload["urlList"][-1], "https://example.test/sitemap.xml")
        self.assertEqual(len(payload["urlList"]), 4)

    def test_changed_today_sends_once_and_reports_ok(self):
        sent = []
        self.stub_send(lambda payload, *a, **k: sent.append(payload) or 200)
        code, out, _ = self.run_main("--changed-today", "--date", "2026-10-29")
        self.assertEqual((code, len(sent)), (0, 1))
        self.assertIn("HTTP 200 (4 URLs)", out)

    def test_explicit_urls_cannot_be_combined(self):
        with self.assertRaises(SystemExit):
            self.run_main("--changed-today", "https://example.test/x/")

    def test_network_error_is_reported_not_raised(self):
        import urllib.error
        import urllib.request
        orig = urllib.request.urlopen

        def boom(*a, **k):
            raise urllib.error.URLError("no route")
        urllib.request.urlopen = boom
        self.addCleanup(setattr, urllib.request, "urlopen", orig)
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertIsNone(indexnow.send({"host": "example.test"}))
        code, out, err = self.run_main("--changed-today", "--date", "2026-10-29")
        self.assertEqual(code, 1)
        self.assertIn("network error", err)
        self.assertIn("not sent", err)

    def test_timeout_is_reported_not_raised(self):
        import urllib.request
        orig = urllib.request.urlopen

        def slow(*a, **k):
            raise TimeoutError("timed out")
        urllib.request.urlopen = slow
        self.addCleanup(setattr, urllib.request, "urlopen", orig)
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertIsNone(indexnow.send({"host": "example.test"}))


class DeployWorkflow(unittest.TestCase):
    """The IndexNow step runs after Deploy, before the Slack notices, and can never fail the deploy."""

    @classmethod
    def setUpClass(cls):
        text = (ROOT / ".github" / "workflows" / "deploy.yml").read_text(encoding="utf-8")
        cls.steps = re.split(r"(?m)^      - name: ", text)[1:]
        cls.names = [s.split("\n", 1)[0] for s in cls.steps]

    def step(self, prefix):
        return next(s for n, s in zip(self.names, self.steps) if n.startswith(prefix))

    def test_indexnow_step_follows_deploy_and_precedes_notices(self):
        i = self.names.index("Deploy")
        j = next(k for k, n in enumerate(self.names) if n.startswith("IndexNow"))
        self.assertEqual(j, i + 1)
        self.assertLess(j, self.names.index("Notify Slack \u2014 success"))

    def test_indexnow_step_cannot_break_the_deploy(self):
        s = self.step("IndexNow")
        self.assertIn("continue-on-error: true", s)
        self.assertIn("python3 scripts/indexnow.py --changed-today", s)
        self.assertIn('|| echo "::warning::', s)
        self.assertIn("if: success()", s)
        self.assertNotIn("secrets.", s)  # the key is a public file, no secret involved


if __name__ == "__main__":
    unittest.main()
