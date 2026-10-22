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
import publish_post  # noqa: E402


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
        reserved = {"LANGSEL", "FOOTLANGS", "FOOTLINKS", "TOPLINK"}
        for k in set(re.findall(r"\{\{(\w+)", tpl)) - reserved:
            self.assertIn(k, loc["en"], k)


class Pages(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.files = build_site.build(ROOT)

    @property
    def home(self):
        return {k: v for k, v in self.files.items()
                if k == "index.html" or (k.count("/") == 1 and k.endswith("/index.html") and k.split("/")[0] not in build_site.PAGES)}

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
        # an explicit ?lang=xx wins over the saved value, and is saved itself
        self.assertLess(build_site.LEGACY_REDIRECT.index("setItem('draft_lang',l)"), build_site.LEGACY_REDIRECT.index("getItem('draft_lang')"))
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


class ContentPages(unittest.TestCase):
    """FAQ / About / Privacy in 11 languages (English at /<page>/, others at /<lang>/<page>/)."""

    @classmethod
    def setUpClass(cls):
        cls.files = build_site.build(ROOT)
        cls.content = build_site.load_content(ROOT)

    def rel(self, lang, slug):
        return build_site.page_path(lang, slug).strip("/") + "/index.html"

    def ld(self, text):
        return [json.loads(m) for m in re.findall(r'<script type="application/ld\+json">\n(.*?)\n</script>', text, re.S)]

    def test_every_page_in_every_language(self):
        for slug in build_site.PAGES:
            for c in build_site.CODES:
                self.assertIn(self.rel(c, slug), self.files)
        self.assertNotIn("en/faq/index.html", self.files)

    def test_clusters_are_symmetric_with_x_default_english(self):
        for slug in build_site.PAGES:
            for c in build_site.CODES:
                t = self.files[self.rel(c, slug)]
                self.assertIn('<link rel="canonical" href="%s">' % build_site.content_url(c, slug), t)
                self.assertEqual(len(re.findall(r'rel="alternate" hreflang=', t)), 12)
                self.assertIn('hreflang="x-default" href="%s"' % build_site.content_url("en", slug), t)
                self.assertIn('hreflang="en" href="https://draft.ipe.rest/%s/"' % slug, t)
                self.assertIn("<loc>%s</loc>" % build_site.content_url(c, slug), self.files["sitemap.xml"])

    def test_json_ld_parses_and_matches(self):
        for c in build_site.CODES:
            faq = [x for x in self.ld(self.files[self.rel(c, "faq")]) if x["@type"] == "FAQPage"][0]
            self.assertEqual(len(faq["mainEntity"]), len(self.content[c]["faq"]["items"]))
            self.assertGreaterEqual(len(faq["mainEntity"]), 8)
            self.assertNotIn("](", json.dumps(faq, ensure_ascii=False))
            about = self.ld(self.files[self.rel(c, "about")])
            kinds = {x["@type"] for x in about}
            self.assertTrue({"AboutPage", "Organization", "BreadcrumbList"} <= kinds, c)
            app = [x for x in about if x["@type"] == "AboutPage"][0]["mainEntity"]
            self.assertEqual(app["@type"], "MobileApplication")
            for forbidden in ("sameAs", "downloadUrl", "installUrl"):
                self.assertNotIn(forbidden, json.dumps(about), c)
            for slug in ("privacy",):
                self.assertTrue(self.ld(self.files[self.rel(c, slug)]))

    def test_content_files_are_complete_and_free_of_placeholders(self):
        en = self.content["en"]
        for c, d in self.content.items():
            self.assertEqual(len(d["faq"]["items"]), len(en["faq"]["items"]), c)
            self.assertEqual(len(d["privacy"]["sections"]), len(en["privacy"]["sections"]), c)
            self.assertEqual(len(d["about"]["sections"]), len(en["about"]["sections"]), c)
            self.assertTrue(re.match(r"^\d{4}-\d{2}-\d{2}$", d["updated"]))
            self.assertIn("https://ipe.rest", json.dumps(d["about"]) + json.dumps(d["faq"]))
            for slug in build_site.PAGES:
                self.assertIn("<h1>", self.files[self.rel(c, slug)])

    def test_placeholder_links_are_gone_and_new_pages_linked_everywhere(self):
        for rel, t in self.files.items():
            if rel.endswith("index.html") and rel != "en/index.html" and rel != "404.html":
                self.assertNotIn('href="#">Privacy', t, rel)
                lang = rel.split("/")[0] if rel.split("/")[0] in build_site.CODES else "en"
                for slug in build_site.PAGES:
                    self.assertIn('href="%s"' % build_site.page_path(lang, slug), t, (rel, slug))

    def test_not_in_noindex_and_in_llms(self):
        for slug in build_site.PAGES:
            for c in build_site.CODES:
                self.assertNotIn("noindex", self.files[self.rel(c, slug)])
                self.assertIn("(%s)" % build_site.content_url(c, slug), self.files["llms.txt"])

    def test_privacy_does_not_overclaim(self):
        """Facts only: the unconfirmed items are announced as 'to be published before launch', never stated as fact."""
        en = json.dumps(self.content["en"]["privacy"])
        self.assertIn("still being finalized", en)
        self.assertIn("No cookies", en)
        self.assertNotIn("end-to-end", en.lower())
        self.assertNotIn("GDPR", en)

    def test_language_switch_goes_to_the_same_page(self):
        t = self.files["ko/faq/index.html"]
        self.assertIn('data-path="faq/" data-en="/faq/"', t)
        self.assertIn('href="/faq/" hreflang="en"', t)
        self.assertIn('href="/ja/faq/" hreflang="ja"', t)


class StageSite(unittest.TestCase):
    def test_only_public_files_are_staged(self):
        import stage_site
        with tempfile.TemporaryDirectory() as tmp:
            files = {f.as_posix() for f in stage_site.stage(ROOT, tmp)}
            for must in ("index.html", "404.html", "CNAME", ".nojekyll", "robots.txt", "sitemap.xml", "llms.txt", "og-image.png",
                         "assets/site.css", "assets/site.js", "ko/index.html", "en/index.html", "ko/blog/feed.xml",
                         "faq/index.html", "about/index.html", "privacy/index.html", "ko/faq/index.html", "ja/privacy/index.html"):
                self.assertIn(must, files)
            self.assertTrue(any(re.match(r"^[0-9a-f]{32}\.txt$", f) for f in files), "IndexNow key file")
            for f in files:
                self.assertFalse(f.startswith(("scripts/", "tests/", "posts/", "locales/", "src/", ".github/", "_site/")), f)
                self.assertNotIn(f.rsplit(".", 1)[-1], ("md", "py", "json", "yml"), f)


class Publish(unittest.TestCase):
    def test_publish_removes_draft_and_sets_date_then_builds(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            for rel in ("src", "locales", "assets"):
                shutil.copytree(ROOT / rel, tmp / rel)
            shutil.copy(ROOT / "llms.txt", tmp / "llms.txt")
            write_post(tmp, "queued-one", extra="draft: true\n")
            self.assertEqual(build_site.load_posts(tmp), ([], []))
            self.assertEqual(build_site.load_posts(tmp, drafts=True)[1], [])
            publish_post.publish(tmp, "queued-one", "2026-10-01")
            posts, errors = build_site.load_posts(tmp)
            self.assertEqual((len(posts), errors), (1, []))
            self.assertNotIn("draft", (tmp / "posts/queued-one/ja.md".replace("ja.md", "translations/ja.md")).read_text(encoding="utf-8").split("---")[1])
            files = build_site.build(tmp)
            self.assertIn("de/blog/queued-one/index.html", files)

    def test_missing_date_line_errors_and_writes_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            write_post(tmp, "queued-one", extra="draft: true\n")
            bad = tmp / "posts/queued-one/translations/de.md"
            bad.write_text(re.sub(r"^date:.*\n", "", bad.read_text(encoding="utf-8"), flags=re.M), encoding="utf-8")
            before = {f: f.read_text(encoding="utf-8") for f in (tmp / "posts").rglob("*.md")}
            with self.assertRaises(SystemExit) as cm:
                publish_post.publish(tmp, "queued-one", "2026-10-01")
            self.assertIn("no `date:` line", str(cm.exception))
            self.assertEqual(before, {f: f.read_text(encoding="utf-8") for f in (tmp / "posts").rglob("*.md")})

    def test_future_or_malformed_date_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            write_post(tmp, "queued-one", extra="draft: true\n")
            for d in ("2999-01-01", "10/01/2026"):
                with self.assertRaises(SystemExit):
                    publish_post.publish(tmp, "queued-one", d)

    def test_queue_posts_in_repo_validate(self):
        self.assertEqual(build_site.load_posts(ROOT, drafts=True)[1], [])


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


class Pricing(unittest.TestCase):
    """Monthly price is $2.99 everywhere; $1.99 must never appear; no yearly price is invented."""

    @classmethod
    def setUpClass(cls):
        cls.files = build_site.build(ROOT)
        cls.content = build_site.load_content(ROOT)

    def test_no_1_99_anywhere(self):
        for rel, text in self.files.items():
            if isinstance(text, bytes):
                text = text.decode("utf-8", "ignore")
            self.assertNotRegex(text, r"1[.,]99", rel)
        for path in [*ROOT.glob("content/*.json"), *ROOT.glob("locales/*.json"), *ROOT.glob("posts/**/*"), ROOT / "llms.txt"]:
            if path.is_file():
                self.assertNotRegex(path.read_text(encoding="utf-8"), r"1[.,]99", str(path))

    def test_monthly_price_is_2_99(self):
        for c in build_site.CODES:
            home = self.files[build_site.home_path(c).strip("/") + "/index.html" if build_site.home_path(c).strip("/") else "index.html"]
            self.assertIn("$2.99<span>", home)
            self.assertIn('"price": "2.99"', home)
        self.assertIn("$2.99/month", (ROOT / "llms.txt").read_text(encoding="utf-8"))

    def test_faq_price_answer_has_caveats_and_matches_json_ld(self):
        for c in build_site.CODES:
            answer = self.content[c]["faq"]["items"][6][1]
            self.assertRegex(answer, r"2[.,]99", c)
            html = self.files[build_site.page_path(c, "faq").strip("/") + "/index.html"]
            ld = [json.loads(m) for m in re.findall(r'<script type="application/ld\+json">\n(.*?)\n</script>', html, re.S)]
            faq = [x for x in ld if x["@type"] == "FAQPage"][0]
            texts = [q["acceptedAnswer"]["text"] for q in faq["mainEntity"]]
            self.assertIn(answer, texts)
            self.assertIn("3", answer)  # 3-day trial caveat is spelled out

    def test_no_yearly_price(self):
        for rel, text in self.files.items():
            if rel.endswith((".html", ".txt")) and isinstance(text, str):
                self.assertNotRegex(text, r"(19|24|29)[.,]99", rel)


class Facts(unittest.TestCase):
    """Claims we cannot back yet stay off the site: iOS-only, 'never used to train', other apps described."""

    @classmethod
    def setUpClass(cls):
        cls.files = build_site.build(ROOT)
        cls.content = build_site.load_content(ROOT)

    def pages(self):
        for rel, text in self.files.items():
            if rel.endswith((".html", ".txt")) and isinstance(text, str):
                yield rel, text

    def test_platform_is_ios_and_android(self):
        for rel, text in self.pages():
            for m in re.finditer(r"\biOS\b", text):
                near = text[max(0, m.start() - 12): m.end() + 40]
                self.assertTrue(re.search(r"Android", near) or "apple-mobile" in near or "iOS, Android" in near, (rel, near))

    def test_json_ld_operating_system_lists_android(self):
        for c in build_site.CODES:
            html = self.files[build_site.page_path(c, "about").strip("/") + "/index.html"]
            self.assertIn('"operatingSystem": "iOS, Android"', html)

    def test_no_training_promise_and_no_other_app_described(self):
        for rel, text in self.pages():
            self.assertNotIn("Draft AI", text, rel)
            self.assertNotRegex(text, r"never used to train|nie zum Trainieren|jamais utilisés pour entraîner|학습에 쓰지 않|学習にも使わない|绝不用于训练", rel)

    def test_free_note_is_one_key_and_resolved_everywhere(self):
        for c in build_site.CODES:
            faq = self.content[c]["faq"]
            self.assertTrue(faq["free_note"].strip(), c)
            self.assertNotIn("{", json.dumps(faq["items"], ensure_ascii=False), c)
            self.assertIn(faq["free_note"], faq["items"][6][1], c)
            raw = json.loads((ROOT / "content" / (c + ".json")).read_text(encoding="utf-8"))
            self.assertIn("{free_note}", raw["faq"]["items"][6][1], c)
            self.assertEqual(sum("{free_note}" in a for _, a in raw["faq"]["items"]), 1, c)


if __name__ == "__main__":
    unittest.main()
