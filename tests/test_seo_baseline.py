"""SEO baseline regressions: the head meta, canonical / hreflang, sitemap and robots.txt of the generated site.
Only what the site already satisfies is checked (the build in memory, like test_ga4.py).
Known and not checked yet: the es/pt/fr/de privacy page descriptions (and their og / twitter copies) are 167-173
characters, over the 160 limit; add a length check only with an explicit allow-list for those four pages.
Run: python3 -m unittest discover -s tests"""
import html
import re
import sys
import unittest
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import build_site  # noqa: E402

SITE = build_site.SITE
CODES = set(build_site.CODES)


def tag(page, pattern):
    m = re.search(pattern, page, re.S)
    return html.unescape(m.group(1)) if m else None


def title_of(page):
    return tag(page, r"<title>(.*?)</title>")


def desc_of(page):
    return tag(page, r'<meta name="description" content="(.*?)">')


def canonical_of(page):
    return tag(page, r'<link rel="canonical" href="(.*?)">')


def indexable(page):
    return "noindex" not in (tag(page, r'<meta name="robots" content="(.*?)">') or "")


class SeoBaseline(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.files = build_site.build(ROOT)
        cls.html = {k: v for k, v in cls.files.items() if k.endswith(".html")}
        cls.pages = {k: v for k, v in cls.html.items() if indexable(v)}
        cls.sitemap = cls.files["sitemap.xml"]

    def test_there_are_indexable_pages_in_every_language(self):
        self.assertGreater(len(self.pages), 100)
        for code in CODES:
            self.assertTrue([r for r in self.pages if r.startswith(code + "/")], code)

    def test_every_indexable_page_has_title_and_description(self):
        for rel, p in self.pages.items():
            self.assertTrue(title_of(p), rel)
            self.assertTrue(desc_of(p), rel)

    def test_no_title_or_description_repeats_between_pages(self):
        titles, descs = defaultdict(list), defaultdict(list)
        for rel, p in self.pages.items():
            titles[title_of(p)].append(rel)
            descs[desc_of(p)].append(rel)
        self.assertEqual({k: v for k, v in titles.items() if len(v) > 1}, {})
        self.assertEqual({k: v for k, v in descs.items() if len(v) > 1}, {})

    def test_canonical_is_the_page_own_url(self):
        for rel, p in self.pages.items():
            url = SITE + "/" + (rel[: -len("index.html")] if rel.endswith("index.html") else rel)
            self.assertEqual(canonical_of(p), url, rel)

    def test_html_lang_matches_the_language_folder(self):
        for rel, p in self.pages.items():
            folder = rel.split("/")[0]
            lang = tag(p, r'<html lang="(.*?)"')
            self.assertTrue(lang, rel)
            if folder in CODES:
                self.assertEqual(lang, folder, rel)
            else:  # site-wide pages (home, about, privacy) are the default language
                self.assertIn(lang, CODES, rel)

    def test_open_graph_and_twitter_tags_mirror_the_page(self):
        for rel, p in self.pages.items():
            self.assertRegex(p, r'<meta property="og:type" content="(website|article)">', rel)
            self.assertEqual(tag(p, r'<meta property="og:url" content="(.*?)">'), canonical_of(p), rel)
            self.assertEqual(tag(p, r'<meta property="og:title" content="(.*?)">'), title_of(p), rel)
            og_desc = tag(p, r'<meta property="og:description" content="(.*?)">')
            self.assertTrue(og_desc, rel)  # the share text may differ from the meta description (the home page does)
            self.assertEqual(tag(p, r'<meta property="og:image" content="(.*?)">'), SITE + "/og-image.png", rel)
            self.assertIn('<meta name="twitter:card" content="summary_large_image">', p, rel)
            self.assertEqual(tag(p, r'<meta name="twitter:title" content="(.*?)">'), title_of(p), rel)
            self.assertEqual(tag(p, r'<meta name="twitter:description" content="(.*?)">'), og_desc, rel)

    def test_every_indexable_page_has_one_h1_and_a_viewport(self):
        for rel, p in self.pages.items():
            self.assertEqual(len(re.findall(r"<h1[ >]", p)), 1, rel)
            self.assertIn('<meta name="viewport" content="width=device-width, initial-scale=1.0">', p, rel)

    def test_hreflang_covers_every_language_and_x_default(self):
        for rel, p in self.pages.items():
            langs = re.findall(r'<link rel="alternate" hreflang="([^"]+)" href="https://draft\.ipe\.rest/[^"]*">', p)
            self.assertEqual(sorted(langs), sorted(CODES | {"x-default"}), rel)

    def test_every_indexable_page_has_structured_data(self):
        for rel, p in self.pages.items():
            self.assertIn('<script type="application/ld+json">', p, rel)

    def test_sitemap_lists_exactly_the_indexable_pages(self):
        locs = re.findall(r"<loc>(.*?)</loc>", self.sitemap)
        self.assertEqual(len(locs), len(set(locs)))
        self.assertEqual(set(locs), {canonical_of(p) for p in self.pages.values()})

    def test_noindex_pages_are_never_in_the_sitemap(self):
        locs = set(re.findall(r"<loc>(.*?)</loc>", self.sitemap))
        hidden = {k: v for k, v in self.html.items() if not indexable(v)}
        self.assertIn("404.html", hidden)
        for rel in hidden:
            self.assertNotIn(SITE + "/" + rel, locs, rel)
            self.assertNotIn(SITE + "/" + (rel[: -len("index.html")] if rel.endswith("index.html") else rel), locs, rel)

    def test_404_page_is_noindex_without_canonical(self):
        p = self.html["404.html"]
        self.assertRegex(p, r'<meta name="robots" content="noindex[^"]*">')
        self.assertNotIn('<link rel="canonical"', p)
        self.assertEqual(len(re.findall(r"<h1[ >]", p)), 1)

    def test_robots_txt_allows_all_and_points_at_the_sitemap(self):
        robots = (ROOT / "robots.txt").read_text(encoding="utf-8")
        self.assertRegex(robots, r"(?m)^User-agent: \*\nAllow: /$")
        self.assertNotRegex(robots, r"(?mi)^Disallow:\s*/\s*$")
        self.assertIn("Sitemap: %s/sitemap.xml" % SITE, robots)

    def test_committed_sitemap_and_static_files_exist(self):
        committed = (ROOT / "sitemap.xml").read_text(encoding="utf-8")
        # <lastmod> follows the build date (today for uncommitted files), so it is left out of the comparison
        self.assertEqual(build_site.strip_lastmod(committed), build_site.strip_lastmod(self.sitemap))
        for name in ("robots.txt", "llms.txt", "404.html", "og-image.png", "favicon.ico"):
            self.assertTrue((ROOT / name).is_file(), name)


if __name__ == "__main__":
    unittest.main()
