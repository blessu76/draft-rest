import json
import re
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import build_site  # noqa: E402
import check_sitemap  # noqa: E402


class Locales(unittest.TestCase):
    def test_eleven_languages_with_en_as_fallback(self):
        self.assertEqual(len(build_site.CODES), 11)
        self.assertEqual(build_site.CODES[0], "en")

    def test_every_language_has_every_english_key(self):
        loc = build_site.load_locales(ROOT)
        en = set(loc["en"])
        for c, d in loc.items():
            self.assertEqual(en - set(d), set(), "%s misses keys" % c)

    def test_template_keys_exist(self):
        loc = build_site.load_locales(ROOT)
        tpl = (ROOT / "src" / "home_body.html").read_text(encoding="utf-8")
        reserved = {"LANGSEL", "FOOTLANGS", "BLOGLINK", "TOPLINK"}
        for k in set(re.findall(r"\{\{(\w+)", tpl)) - reserved:
            self.assertIn(k, loc["en"], k)


class Pages(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.files = build_site.build(ROOT)

    def test_page_set(self):
        pages = {k for k in self.files if k.endswith("index.html")}
        self.assertEqual(pages, {"index.html"} | {"%s/index.html" % c for c in build_site.CODES})

    def test_canonical_and_hreflang(self):
        for rel, text in self.files.items():
            if not rel.endswith("index.html"):
                continue
            lang = rel.split("/")[0] if "/" in rel else None
            url = build_site.page_url(lang)
            self.assertIn('<link rel="canonical" href="%s">' % url, text, rel)
            self.assertEqual(len(re.findall(r'rel="alternate" hreflang=', text)), 12, rel)
            self.assertIn('hreflang="x-default" href="https://draft.ipe.rest/"', text, rel)
            self.assertNotIn("?lang=", text.replace(build_site.LEGACY_REDIRECT, ""), rel)
            self.assertNotIn("data-i18n", text, rel)
            self.assertNotIn("{{", text, rel)
            self.assertIn('<html lang="%s">' % (lang or "en"), text, rel)

    def test_only_root_has_legacy_redirect(self):
        self.assertIn("location.replace", self.files["index.html"])
        for c in build_site.CODES:
            self.assertNotIn("location.replace", self.files["%s/index.html" % c])

    def test_legacy_redirect_covers_all_languages(self):
        m = re.search(r"\^\(([^)]*)\)\$", build_site.LEGACY_REDIRECT)
        self.assertEqual(m.group(1).split("|"), build_site.CODES)

    def test_language_page_uses_its_own_strings(self):
        loc = build_site.load_locales(ROOT)
        self.assertIn(loc["ko"]["hero_h1"], self.files["ko/index.html"])
        self.assertIn(loc["en"]["hero_h1"], self.files["index.html"])
        self.assertNotIn(loc["ko"]["hero_h1"], self.files["index.html"])

    def test_hero_demo_text_is_in_data_attribute(self):
        loc = build_site.load_locales(ROOT)
        self.assertIn('data-raw="%s"' % build_site.esc(loc["ja"]["demo_raw"]), self.files["ja/index.html"])

    def test_footer_links_to_every_language(self):
        for c in build_site.CODES:
            self.assertIn('href="/%s/"' % c, self.files["index.html"])

    def test_json_ld_parses(self):
        for rel, text in self.files.items():
            if rel.endswith("index.html"):
                m = re.search(r'<script type="application/ld\+json">\n(.*?)\n</script>', text, re.S)
                self.assertEqual(json.loads(m.group(1))["@graph"][0]["@type"], "MobileApplication", rel)

    def test_assets_are_cache_busted(self):
        for rel, text in self.files.items():
            if rel.endswith("index.html"):
                self.assertRegex(text, r'/assets/site\.css\?v=[0-9a-f]{8}"')
                self.assertRegex(text, r'/assets/site\.js\?v=[0-9a-f]{8}"')

    def test_llms_block_lists_every_page(self):
        for c in build_site.CODES:
            self.assertIn("(%s)" % build_site.page_url(c), self.files["llms.txt"])


class RepoIsBuilt(unittest.TestCase):
    def test_generated_files_are_up_to_date(self):
        self.assertEqual(build_site.main(["--check"]), 0)

    def test_sitemap_checker_passes(self):
        self.assertEqual(check_sitemap.check(ROOT), [])


class SitemapChecker(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        for rel, text in build_site.build(ROOT).items():
            f = self.dir / rel
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text(text, encoding="utf-8")
        shutil.copy(ROOT / "robots.txt", self.dir / "robots.txt")

    def sitemap(self, fn):
        p = self.dir / "sitemap.xml"
        p.write_text(fn(p.read_text(encoding="utf-8")), encoding="utf-8")

    def test_ok_baseline(self):
        self.assertEqual(check_sitemap.check(self.dir), [])

    def test_query_string_url_is_rejected(self):
        self.sitemap(lambda s: s.replace('hreflang="ko" href="https://draft.ipe.rest/ko/"', 'hreflang="ko" href="https://draft.ipe.rest/?lang=ko"', 1))
        self.assertTrue(check_sitemap.check(self.dir))

    def test_missing_page_is_rejected(self):
        (self.dir / "ko" / "index.html").unlink()
        self.assertTrue(any("file not found" in e for e in check_sitemap.check(self.dir)))

    def test_future_lastmod_is_rejected(self):
        self.sitemap(lambda s: re.sub(r"<lastmod>[^<]*</lastmod>", "<lastmod>2999-01-01</lastmod>", s, count=1))
        self.assertTrue(any("future" in e for e in check_sitemap.check(self.dir)))

    def test_missing_robots_sitemap_line(self):
        (self.dir / "robots.txt").write_text("User-agent: *\nAllow: /\n")
        self.assertTrue(any("robots.txt" in e for e in check_sitemap.check(self.dir)))

    def test_broken_xml(self):
        (self.dir / "sitemap.xml").write_text("<urlset>")
        self.assertTrue(check_sitemap.check(self.dir))


if __name__ == "__main__":
    unittest.main()
