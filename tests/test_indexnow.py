import contextlib
import io
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


if __name__ == "__main__":
    unittest.main()
