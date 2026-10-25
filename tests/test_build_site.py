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
        reserved = {"LANGSEL", "FOOTLANGS", "BLOGLINK", "TOPLINK", "BLOGCARDS"}
        for k in set(re.findall(r"\{\{(\w+)", tpl)) - reserved:
            self.assertIn(k, loc["en"], k)


class Pages(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.files = build_site.build(ROOT)

    @property
    def home(self):
        return {k: v for k, v in self.files.items() if k == "index.html" or (k.count("/") == 1 and k.endswith("/index.html"))}

    @property
    def indexed_home(self):
        return {k: v for k, v in self.home.items() if k not in ("en/index.html", "404.html")}

    def test_page_set(self):
        self.assertEqual(set(self.home), {"index.html"} | {"%s/index.html" % c for c in build_site.CODES})

    def test_english_is_the_root_only(self):
        """One English body: / (canonical, hreflang en AND x-default). /en/ is a noindex stub, not in the sitemap."""
        root = self.files["index.html"]
        self.assertIn('<link rel="canonical" href="https://draft.ipe.rest/">', root)
        self.assertIn('hreflang="en" href="https://draft.ipe.rest/"', root)
        self.assertIn('hreflang="x-default" href="https://draft.ipe.rest/"', root)
        self.assertNotIn("https://draft.ipe.rest/en/\"", self.files["ko/index.html"])
        stub = self.files["en/index.html"]
        self.assertIn('content="noindex', stub)
        self.assertIn('<link rel="canonical" href="https://draft.ipe.rest/">', stub)
        self.assertNotIn("hreflang", stub)
        self.assertNotIn("<h1", stub)
        self.assertNotIn("<loc>https://draft.ipe.rest/en/</loc>", self.files["sitemap.xml"])
        self.assertNotIn("(https://draft.ipe.rest/en/)", self.files["llms.txt"])

    def test_404_is_noindex_and_links_every_language(self):
        t = self.files["404.html"]
        self.assertIn('content="noindex', t)
        self.assertNotIn('rel="canonical"', t)
        for c in build_site.CODES:
            self.assertIn('href="%s"' % build_site.home_path(c), t)
        self.assertNotIn("<loc>https://draft.ipe.rest/404", self.files["sitemap.xml"])

    def test_og_locale_alternates_and_short_og_description(self):
        loc = build_site.load_locales(ROOT)
        t = self.files["ko/index.html"]
        self.assertIn('<meta property="og:locale" content="ko_KR">', t)
        self.assertEqual(len(re.findall(r'property="og:locale:alternate"', t)), 10)
        self.assertNotIn('og:locale:alternate" content="ko_KR"', t)
        og = re.search(r'property="og:description" content="([^"]*)"', t).group(1)
        meta = re.search(r'name="description" content="([^"]*)"', t).group(1)
        self.assertNotEqual(og, meta)
        self.assertLess(len(og), len(meta))

    def test_canonical_and_hreflang(self):
        for rel, text in self.indexed_home.items():
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
            if c != "en":
                self.assertNotIn("location.replace", self.files["%s/index.html" % c])

    def test_root_has_language_hint_but_no_auto_redirect_on_browser_language(self):
        root = self.files["index.html"]
        self.assertIn('id="langhint"', root)
        self.assertNotIn("navigator.language", build_site.LEGACY_REDIRECT)
        self.assertIn("draft_lang", build_site.LEGACY_REDIRECT)
        self.assertIn("toLowerCase", build_site.LEGACY_REDIRECT)
        self.assertNotIn('id="langhint"', self.files["ko/index.html"])

    def test_legacy_redirect_covers_all_languages(self):
        m = re.search(r"var C='([^']*)'", build_site.LEGACY_REDIRECT)
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
            self.assertIn('href="%s"' % build_site.home_path(c), self.files["index.html"])

    def test_json_ld_parses(self):
        for rel, text in self.indexed_home.items():
            m = re.search(r'<script type="application/ld\+json">\n(.*?)\n</script>', text, re.S)
            self.assertEqual(json.loads(m.group(1))["@graph"][0]["@type"], "MobileApplication", rel)

    def test_assets_are_cache_busted(self):
        for rel, text in self.files.items():
            if rel.endswith("index.html") and rel != "en/index.html":
                self.assertRegex(text, r'/assets/site\.css\?v=[0-9a-f]{8}"')
                self.assertRegex(text, r'/assets/site\.js\?v=[0-9a-f]{8}"')

    def test_llms_block_lists_every_page(self):
        for c in build_site.CODES:
            self.assertIn("(%s)" % build_site.page_url(c), self.files["llms.txt"])
        self.assertNotIn("One post per day", self.files["llms.txt"])


class InternalLinks(unittest.TestCase):
    """Every internal href/src in every generated HTML page must resolve to a real file (or a directory index.html)."""

    ATTR = re.compile(r'\b(?:href|src)="([^"]*)"')

    @classmethod
    def setUpClass(cls):
        cls.files = build_site.build(ROOT)

    def exists(self, path):
        path = path.split("#")[0].split("?")[0]
        rel = path.lstrip("/")
        if path.endswith("/"):
            rel += "index.html"
        return rel in self.files or (ROOT / rel).is_file()

    def test_all_internal_links_resolve(self):
        broken, checked = [], 0
        for rel, text in self.files.items():
            if not rel.endswith(".html"):
                continue
            for u in self.ATTR.findall(text):
                if u.startswith(build_site.SITE + "/"):
                    u = u[len(build_site.SITE):]
                if not u.startswith("/") or u.startswith("//"):
                    continue
                checked += 1
                if not self.exists(u):
                    broken.append("%s -> %s" % (rel, u))
        self.assertEqual(broken, [])
        self.assertGreater(checked, 500)

    def test_root_blog_link_points_to_english_blog(self):
        root = self.files["index.html"]
        self.assertNotIn('href="/blog/"', root)
        self.assertIn('href="/en/blog/"', root)


POST_FM = "---\ntitle: %s\ndescription: d %s\ndate: 2026-10-01\nslug: %s\n%s---\n\n%s\n"


def write_post(root, slug, langs=None, body=None, extra="", slug_in_file=None):
    for c in langs or build_site.CODES:
        f = Path(root) / "posts" / slug / (c + ".md" if c in ("ko", "en") else "translations/%s.md" % c)
        f.parent.mkdir(parents=True, exist_ok=True)
        b = body if body is not None else ("가" * 1400 if c == "ko" else "word " * 300)
        f.write_text(POST_FM % ("T " + c, c, slug_in_file or slug, extra, b), encoding="utf-8")


class Blog(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.files = build_site.build(ROOT)

    def test_every_language_has_list_feed_and_post(self):
        for c in build_site.CODES:
            for rel in ("%s/blog/index.html" % c, "%s/blog/feed.xml" % c, "%s/blog/blank-caption-box/index.html" % c):
                self.assertIn(rel, self.files)

    def test_post_has_hreflang_group_and_x_default_en(self):
        t = self.files["ko/blog/blank-caption-box/index.html"]
        self.assertEqual(len(re.findall(r'rel="alternate" hreflang=', t)), 12)
        self.assertIn('hreflang="x-default" href="https://draft.ipe.rest/en/blog/blank-caption-box/"', t)
        self.assertIn('<link rel="canonical" href="https://draft.ipe.rest/ko/blog/blank-caption-box/">', t)
        self.assertIn('"@type": "BlogPosting"', t)

    def test_feed_is_valid_xml(self):
        import xml.etree.ElementTree as ET
        for c in build_site.CODES:
            ch = ET.fromstring(self.files["%s/blog/feed.xml" % c].split("?>", 1)[1]).find("channel")
            self.assertEqual(ch.find("language").text, c)
            self.assertEqual(len(ch.findall("item")), len(build_site.load_posts(ROOT)[0]))
            self.assertGreaterEqual(len(ch.findall("item")), 1)

    def test_home_links_to_blog_and_blog_is_in_sitemap_and_llms(self):
        self.assertIn('href="/ko/blog/"', self.files["ko/index.html"])
        self.assertIn("https://draft.ipe.rest/ko/blog/blank-caption-box/", self.files["sitemap.xml"])
        self.assertIn("(https://draft.ipe.rest/en/blog/blank-caption-box/)", self.files["llms.txt"])

    def test_first_post_ko_length(self):
        posts, errors = build_site.load_posts(ROOT)
        self.assertEqual(errors, [])
        self.assertTrue(1200 <= len(posts[0]["langs"]["ko"]["_body"].strip()) <= 1800)

    def test_markdown_escapes_html_and_bad_links(self):
        out = build_site.markdown("<script>x</script> [a](javascript:alert(1)) **b**")
        self.assertNotIn("<script>", out)
        self.assertIn('href="#"', out)
        self.assertIn("<strong>b</strong>", out)


class PostValidation(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)

    def test_complete_post_is_ok(self):
        write_post(self.dir, "a-post")
        posts, errors = build_site.load_posts(self.dir)
        self.assertEqual((len(posts), errors), (1, []))

    def test_missing_language_is_an_error(self):
        write_post(self.dir, "a-post", langs=[c for c in build_site.CODES if c != "de"])
        self.assertTrue(any("missing languages: de" in e for e in build_site.load_posts(self.dir)[1]))

    def test_slug_must_match_folder(self):
        write_post(self.dir, "a-post", slug_in_file="other")
        self.assertTrue(any("folder name" in e for e in build_site.load_posts(self.dir)[1]))

    def test_bad_slug_and_date(self):
        write_post(self.dir, "Bad_Slug")
        self.assertTrue(build_site.load_posts(self.dir)[1])

    def test_draft_is_skipped_everywhere(self):
        write_post(self.dir, "a-post", extra="draft: true\n")
        self.assertEqual(build_site.load_posts(self.dir), ([], []))

    def test_ko_length_is_enforced(self):
        write_post(self.dir, "a-post", body="짧다")
        self.assertTrue(any("ko body" in e for e in build_site.load_posts(self.dir)[1]))

    def test_posts_sorted_newest_first(self):
        write_post(self.dir, "old-one")
        write_post(self.dir, "new-one")
        for c in build_site.CODES:
            f = self.dir / "posts" / "new-one" / (c + ".md" if c in ("ko", "en") else "translations/%s.md" % c)
            f.write_text(f.read_text(encoding="utf-8").replace("2026-10-01", "2026-10-02"), encoding="utf-8")
        self.assertEqual([p["slug"] for p in build_site.load_posts(self.dir)[0]], ["new-one", "old-one"])


class PublishedTime(unittest.TestCase):
    """Davy 10-24: show HH:MM (KST, two digits, no seconds) next to the date; machine forms carry +09:00."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        self.shutil = __import__("shutil")
        self.shutil.copytree(ROOT / "locales", self.dir / "locales")
        for n in ("src", "assets", "content", "shared"):
            if (ROOT / n).is_dir():
                self.shutil.copytree(ROOT / n, self.dir / n)
        for n in ("llms.txt",):
            self.shutil.copy(ROOT / n, self.dir / n)

    def build_with(self, published):
        extra = "published: %s\n" % published if published else ""
        write_post(self.dir, "a-post", extra=extra)
        return build_site.build(self.dir)

    def test_nine_past_nine_is_zero_padded_and_has_no_seconds(self):
        f = self.build_with("2026-10-01T09:09:45+09:00")
        for c in build_site.CODES:
            for rel in ("%s/blog/a-post/index.html" % c, "%s/blog/index.html" % c):
                self.assertIn(">2026-10-01 09:09 KST</time>", f[rel])
                self.assertNotIn("09:09:", re.sub(r"<time datetime=[^>]*>", "", f[rel]).replace("T09:09:00+09:00", ""))
        post = f["en/blog/a-post/index.html"]
        self.assertIn('<time datetime="2026-10-01T09:09+09:00" data-ipe-time title="2026-10-01 09:09 KST">', post)
        self.assertIn('"datePublished": "2026-10-01T09:09:00+09:00"', post)
        self.assertIn('"dateModified": "2026-10-01T09:09:00+09:00"', post)
        self.assertIn("<lastmod>2026-10-01T09:09:00+09:00</lastmod>", f["sitemap.xml"])
        self.assertIn("Thu, 01 Oct 2026 09:09:00 +0900", f["en/blog/feed.xml"])

    def test_other_offsets_are_converted_to_kst(self):
        f = self.build_with("2026-09-30T23:30:00+00:00")  # 08:30 KST on 10-01
        self.assertIn(">2026-10-01 08:30 KST</time>", f["en/blog/a-post/index.html"])
        self.assertIn('datetime="2026-10-01T08:30+09:00"', f["en/blog/a-post/index.html"])

    def test_post_without_published_shows_date_only(self):
        f = self.build_with(None)
        post = f["en/blog/a-post/index.html"]
        self.assertIn('// <time datetime="2026-10-01">2026-10-01</time>', post)
        self.assertIn('"datePublished": "2026-10-01"', post)
        self.assertIn("<lastmod>2026-10-01</lastmod>", f["sitemap.xml"])
        self.assertNotRegex(post, r"// 2026-10-01 \d\d:\d\d")

    def test_published_must_have_offset_time_and_match_date(self):
        for bad in ("2026-10-01T09:09:00", "2026-10-01", "2026-10-02T09:09:00+09:00"):
            write_post(self.dir, "a-post", extra="published: %s\n" % bad)
            self.assertTrue(build_site.load_posts(self.dir)[1], bad)

    def test_published_must_match_across_languages(self):
        write_post(self.dir, "a-post", extra="published: 2026-10-01T09:09:00+09:00\n")
        f = self.dir / "posts" / "a-post" / "ko.md"
        f.write_text(f.read_text(encoding="utf-8").replace("09:09", "09:10"), encoding="utf-8")
        self.assertTrue(any("`published` differs" in e for e in build_site.load_posts(self.dir)[1]))

    def test_same_day_posts_sort_by_time(self):
        write_post(self.dir, "early-one", extra="published: 2026-10-01T08:00:00+09:00\n")
        write_post(self.dir, "late-one", extra="published: 2026-10-01T16:00:00+09:00\n")
        self.assertEqual([p["slug"] for p in build_site.load_posts(self.dir)[0]], ["late-one", "early-one"])

    def test_future_published_is_rejected(self):
        write_post(self.dir, "a-post", extra="published: 2999-10-01T09:09:00+09:00\n")
        for f in (self.dir / "posts" / "a-post").rglob("*.md"):
            f.write_text(f.read_text(encoding="utf-8").replace("date: 2026-10-01", "date: 2999-10-01"), encoding="utf-8")
        self.assertTrue(any("future" in e for e in build_site.load_posts(self.dir)[1]))

    def test_stamp_script_sets_date_and_published_in_all_languages(self):
        sys.path.insert(0, str(ROOT / "scripts"))
        import stamp_published
        write_post(self.dir, "a-post", extra="published: 2026-10-01T08:00:00+09:00\n")
        n, iso = stamp_published.stamp(self.dir, "a-post", __import__("datetime").datetime(
            2026, 10, 3, 9, 9, tzinfo=build_site.KST))
        self.assertEqual((n, iso), (len(build_site.CODES), "2026-10-03T09:09:00+09:00"))
        posts, errors = build_site.load_posts(self.dir)
        self.assertEqual(errors, [])
        self.assertEqual(build_site.fmt_date(posts[0]["date"]), "2026-10-03 09:09")

    def test_first_post_uses_its_recorded_deploy_time(self):
        post = build_site.build(ROOT)["en/blog/blank-caption-box/index.html"]
        self.assertIn(">2026-10-23 17:30 KST</time>", post)
        self.assertIn('"datePublished": "2026-10-23T17:30:00+09:00"', post)


class StageSite(unittest.TestCase):
    def test_only_public_files_are_staged(self):
        import stage_site
        with tempfile.TemporaryDirectory() as tmp:
            files = {f.as_posix() for f in stage_site.stage(ROOT, tmp)}
            for must in ("index.html", "404.html", "CNAME", ".nojekyll", "robots.txt", "sitemap.xml", "llms.txt", "og-image.png",
                         "assets/site.css", "assets/site.js", "ko/index.html", "en/index.html", "ko/blog/feed.xml"):
                self.assertIn(must, files)
            self.assertTrue(any(re.match(r"^[0-9a-f]{32}\.txt$", f) for f in files), "IndexNow key file")
            for f in files:
                self.assertFalse(f.startswith(("scripts/", "tests/", "posts/", "locales/", "src/", ".github/", "_site/")), f)
                self.assertNotIn(f.rsplit(".", 1)[-1], ("md", "py", "json", "yml"), f)


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

    def test_datetime_lastmod_ok_but_needs_offset_and_not_future(self):
        self.sitemap(lambda s: re.sub(r"<lastmod>[^<]*</lastmod>", "<lastmod>2026-10-01T09:09:00+09:00</lastmod>", s, count=1))
        self.assertEqual(check_sitemap.check(self.dir), [])
        self.sitemap(lambda s: re.sub(r"<lastmod>[^<]*</lastmod>", "<lastmod>2026-10-01T09:09:00</lastmod>", s, count=1))
        self.assertTrue(check_sitemap.check(self.dir))
        self.sitemap(lambda s: re.sub(r"<lastmod>[^<]*</lastmod>", "<lastmod>2999-01-01T09:09:00+09:00</lastmod>", s, count=1))
        self.assertTrue(any("future" in e for e in check_sitemap.check(self.dir)))

    def test_missing_robots_sitemap_line(self):
        (self.dir / "robots.txt").write_text("User-agent: *\nAllow: /\n")
        self.assertTrue(any("robots.txt" in e for e in check_sitemap.check(self.dir)))

    def test_broken_xml(self):
        (self.dir / "sitemap.xml").write_text("<urlset>")
        self.assertTrue(check_sitemap.check(self.dir))


if __name__ == "__main__":
    unittest.main()


class LocalTime(unittest.TestCase):
    """Company-wide publish-time module (ipe-rest c466827, v2): byte-identical copy, inlined; every <time> carries data-ipe-time and +09:00."""

    SHA256 = "57326449ddf5050eabadd1394d69eb2b0f61c88f084ec83ee4aff6fcad0f74b8"

    @classmethod
    def setUpClass(cls):
        cls.files = build_site.build(ROOT)
        cls.pages = {k: v for k, v in cls.files.items() if re.match(r"^[a-z]{2}/blog/.+\.html$", k)}

    def test_copy_matches_canonical_hash(self):
        import hashlib
        data = (ROOT / "shared" / "ipe-localtime.js").read_bytes()
        self.assertEqual(hashlib.sha256(data).hexdigest(), self.SHA256)
        self.assertEqual(len(data), 1639)

    def test_build_inlines_module_bytes_before_body_end(self):
        js = (ROOT / "shared" / "ipe-localtime.js").read_bytes().decode("utf-8")
        self.assertTrue(self.pages)
        for rel, html in self.pages.items():
            self.assertIn("<script>" + js + "</script>\n</body>", html, rel)
            self.assertEqual(html.count("ipe-localtime v2"), 1, rel)
            self.assertNotIn("ipe-localtime.js\"", html, rel)  # inline, never an external src

    def test_every_time_tag_is_convertible_and_kst(self):
        n = 0
        for rel, html in self.pages.items():
            for m in re.finditer(r"<time\b([^>]*)>([^<]*)</time>", html):
                n += 1
                attrs, text = m.group(1), m.group(2)
                self.assertIn("data-ipe-time", attrs, rel)
                self.assertRegex(attrs, r'datetime="\d{4}-\d\d-\d\dT\d\d:\d\d\+09:00"', rel)
                self.assertRegex(text, r"^\d{4}-\d\d-\d\d \d\d:\d\d KST$", rel)
        self.assertGreater(n, 0)

    def test_pages_without_times_do_not_carry_the_script(self):
        for rel in ("en/index.html", "404.html"):  # the /en/ stub and the 404 list no times
            self.assertNotIn("ipe-localtime", self.files[rel], rel)


class HomeCards(unittest.TestCase):
    """Home page 'field notes' cards: newest 3 published posts of the page language, one link per card, built statically."""

    @classmethod
    def setUpClass(cls):
        cls.files = build_site.build(ROOT)
        cls.posts, _ = build_site.load_posts(ROOT)

    def home(self, lang):
        return self.files["index.html" if lang == build_site.DEFAULT_LANG else "%s/index.html" % lang]

    def cards(self, lang):
        return re.findall(r'<li class="bcard reveal">(.*?)</li>', self.home(lang), re.S)

    def test_count_order_language_and_links(self):
        want = [p["slug"] for p in self.posts][:3]
        self.assertTrue(want)
        for c in build_site.CODES:
            got = [re.search(r'href="/%s/blog/([^/"]+)/"' % c, x).group(1) for x in self.cards(c)]
            self.assertEqual(got, want, c)
            self.assertLessEqual(len(got), 3, c)
            for slug, x in zip(want, self.cards(c)):
                p = next(q for q in self.posts if q["slug"] == slug)
                self.assertIn(build_site.esc(p["langs"][c]["title"]), x, c)
                self.assertEqual(x.count("<a "), 1, c)  # the whole card is one link

    def test_newest_published_post_is_first(self):
        newest = self.posts[0]["slug"]
        self.assertEqual(newest, "first-line-hook")
        for c in build_site.CODES:
            self.assertIn("/%s/blog/%s/" % (c, newest), self.cards(c)[0], c)

    def test_see_all_link_and_no_unpublished(self):
        drafts = {d.name for d in (ROOT / "posts").iterdir() if d.is_dir()} - {p["slug"] for p in self.posts}
        for c in build_site.CODES:
            self.assertIn('class="btn-line" href="/%s/blog/"' % c, self.home(c), c)
            for slug in drafts:
                self.assertNotIn(slug, self.home(c), c)

    def test_section_sits_right_after_hero_and_once(self):
        for c in build_site.CODES:
            h = self.home(c)
            self.assertEqual(h.count('class="blognotes"'), 1, c)
            self.assertLess(h.index("</header>"), h.index('class="blognotes"'), c)
            self.assertLess(h.index('class="blognotes"'), h.index('<section class="problem">'), c)

    def test_times_are_kst_convertible_and_module_inlined_once(self):
        import hashlib
        js = (ROOT / "shared" / "ipe-localtime.js").read_bytes()
        for c in build_site.CODES:
            h = self.home(c)
            self.assertIn("<script>" + js.decode("utf-8") + "</script>\n</body>", h, c)
            self.assertEqual(h.count("ipe-localtime v2"), 1, c)
            for m in re.finditer(r"<time\b([^>]*)>([^<]*)</time>", h):
                self.assertIn("data-ipe-time", m.group(1), c)
                self.assertRegex(m.group(2), r"^\d{4}-\d\d-\d\d \d\d:\d\d KST$", c)

    def test_no_posts_no_section(self):
        self.assertEqual(build_site.blog_cards_html({}, "en", []), "")

    def test_home_lastmod_follows_newest_post(self):
        sm = self.files["sitemap.xml"]
        newest = build_site.when_iso(self.posts[0]["updated"])[:10]
        m = re.search(r"<loc>https://draft\.ipe\.rest/</loc>\s*<lastmod>([^<]+)</lastmod>", sm)
        self.assertTrue(m)
        self.assertGreaterEqual(m.group(1)[:10], newest)
