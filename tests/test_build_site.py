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

class RedirectedLanguages(unittest.TestCase):
    """Ended languages (pt zh ar hi ru — kit LEGACY_REDIRECTS; ADR 0087) and removed pages never 404: every old URL is a forward
    (noindex + canonical + refresh) to a page this build makes, and none of them is in the sitemap or carries hreflang."""

    @classmethod
    def setUpClass(cls):
        cls.files = build_site.build(ROOT)

    def target(self, rel):
        m = re.search(r'<link rel="canonical" href="https://draft\.ipe\.rest(/[^"]*)">', self.files[rel])
        return m.group(1)

    def test_every_old_page_forwards_noindex_with_canonical_and_refresh(self):
        old = [r for r in self.files if r.split("/")[0] in build_site.LEGACY_LANGS and r.endswith("/index.html")]
        self.assertGreater(len(old), 100)
        for rel in old:
            t, tgt = self.files[rel], self.target(rel)
            self.assertRegex(t, r'<meta name="robots" content="noindex, ?follow">', rel)
            self.assertIn('<meta http-equiv="refresh" content="0; url=https://draft.ipe.rest%s">' % tgt, t, rel)
            self.assertNotIn("hreflang", t, rel)
            self.assertIn(tgt.strip("/") + "/index.html" if tgt != "/" else "index.html", self.files, rel)

    def test_destinations(self):
        for c in ("ar", "hi", "ru"):  # -> English (the root)
            self.assertEqual(self.target("%s/index.html" % c), "/")
            self.assertEqual(self.target("%s/about/index.html" % c), "/about/")
            self.assertEqual(self.target("%s/blog/index.html" % c), "/journal/")
            self.assertEqual(self.target("%s/blog/page/2/index.html" % c), "/journal/page/2/")
        self.assertEqual(self.target("ar/blog/start-later/index.html"), "/journal/start-later/")
        self.assertEqual(self.target("zh/index.html"), "/zh-Hant/")
        self.assertEqual(self.target("zh/blog/start-later/index.html"), "/zh-Hant/journal/start-later/")
        self.assertEqual(self.target("pt/blog/index.html"), "/pt-BR/journal/")
        self.assertEqual(self.target("releases/index.html"), "/about/")

    def test_posts_21_to_26_are_forwarded_too(self):
        for slug in ("pin-the-hour", "one-object-on-the-table", "one-small-want", "verb-over-adjective", "one-small-slip", "the-way-between"):
            self.assertEqual(self.target("ru/blog/%s/index.html" % slug), "/journal/%s/" % slug)
            self.assertEqual(self.target("ko/blog/%s/index.html" % slug), "/ko/journal/%s/" % slug)
            self.assertIn("ko/journal/%s/index.html" % slug, self.files)
            self.assertIn("journal/%s/index.html" % slug, self.files)

    def test_not_in_sitemap(self):
        locs = re.findall(r"<loc>(.*?)</loc>", self.files["sitemap.xml"])
        self.assertFalse([u for u in locs if re.match(r"https://draft\.ipe\.rest/(ar|hi|ru|zh|pt|releases)/", u)])
        self.assertFalse([u for u in locs if "/blog/" in u])
        self.assertTrue([u for u in locs if u == "https://draft.ipe.rest/ko/journal/"])


class SitemapLanguages(unittest.TestCase):
    """The sitemap's language set has a single source (the kit's SUPPORTED list); ended languages never leak into it."""
    def test_hreflang_set_is_the_kit_supported_list(self):
        text = (ROOT / "sitemap.xml").read_text(encoding="utf-8")
        tags = set(re.findall(r'hreflang="([^"]+)"', text)) - {"x-default"}
        self.assertEqual(tags, set(build_site.kit_lang.SUPPORTED))
        self.assertEqual(len(tags), 12)
        self.assertIn("zh-Hant", tags)
        self.assertEqual(len(build_site.LISTED), 12)

    def test_forwarded_languages_are_unlisted(self):
        for c in build_site.LEGACY_LANGS:
            self.assertNotIn(c, build_site.LISTED)
            self.assertNotIn(c, build_site.kit_lang.SUPPORTED)

    def test_every_ended_language_is_out_of_the_sitemap(self):
        text = (ROOT / "sitemap.xml").read_text(encoding="utf-8")
        self.assertFalse(re.findall(r"<loc>https://draft\.ipe\.rest/(?:ar|hi|ru|zh|pt)/", text))
        self.assertFalse(re.findall(r'hreflang="(?:ar|hi|ru|zh|zh-Hans|pt)"', text))


class ZhHansEnded(unittest.TestCase):
    """zh (zh-Hans) is ended (ADR 0087): forward + noindex on disk, while zh-Hant stays a live, listed language."""
    def test_zh_is_forwarded_zh_hant_is_not(self):
        self.assertIn("zh", build_site.LEGACY_LANGS)
        self.assertNotIn("zh-Hant", build_site.LEGACY_LANGS)
        self.assertIn("zh-Hant", build_site.LISTED)

    def test_zh_pages_on_disk_are_noindex_forwards(self):
        for rel in ("zh/index.html", "zh/about/index.html", "zh/blog/index.html"):
            t = (ROOT / rel).read_text(encoding="utf-8")
            self.assertRegex(t, r'<meta name="robots" content="noindex, ?follow">', rel)
            self.assertIn('http-equiv="refresh"', t, rel)
            self.assertNotIn('content="index, follow"', t, rel)

    def test_zh_hant_hreflang_stays_in_sitemap(self):
        text = (ROOT / "sitemap.xml").read_text(encoding="utf-8")
        self.assertIn('hreflang="zh-Hant"', text)
        self.assertIn("https://draft.ipe.rest/zh-Hant/", text)


class DeployWorkflow(unittest.TestCase):
    """deploy.yml also fires after the scheduled publish succeeds (GITHUB_TOKEN pushes do not trigger push events)."""
    def setUp(self):
        import yaml
        wf = ROOT / ".github" / "workflows"
        self.dep = yaml.safe_load((wf / "deploy.yml").read_text(encoding="utf-8"))
        self.pub = yaml.safe_load((wf / "publish-scheduled.yml").read_text(encoding="utf-8"))
        self.text = (wf / "deploy.yml").read_text(encoding="utf-8")

    def triggers(self):
        return self.dep.get("on", self.dep.get(True))  # PyYAML reads the bare key `on` as True

    def test_workflow_run_names_the_publish_workflow(self):
        t = self.triggers()
        self.assertEqual(t["workflow_run"]["workflows"], [self.pub["name"]])
        self.assertEqual(t["workflow_run"]["types"], ["completed"])
        self.assertIn("push", t)
        self.assertIn("workflow_dispatch", t)

    def test_job_only_blocked_for_failed_workflow_run(self):
        cond = self.dep["jobs"]["deploy"]["if"]
        self.assertIn("github.event_name != 'workflow_run'", cond)
        self.assertIn("github.event.workflow_run.conclusion == 'success'", cond)

    def test_checkout_main_for_workflow_run_and_no_new_secrets(self):
        co = self.dep["jobs"]["deploy"]["steps"][0]
        self.assertIn("'main'", co["with"]["ref"])
        self.assertIn("workflow_run", co["with"]["ref"])
        self.assertNotIn("PAT", self.text)
        self.assertEqual(set(re.findall(r"secrets\.(\w+)", self.text)), {"SLACK_BOT_TOKEN"})


class Locales(unittest.TestCase):
    def test_twelve_languages_with_en_as_fallback(self):
        self.assertEqual(len(build_site.CODES), 12)
        self.assertEqual(build_site.CODES[0], "en")
        self.assertEqual(set(build_site.CODES), set("en ko ja zh-Hant es pt-BR fr de id th vi tr".split()))

    def test_ended_languages_are_redirect_stubs_not_listed(self):
        self.assertEqual(set(build_site.CODES), set(build_site.LISTED))
        self.assertTrue(set(build_site.BLOG_LISTED) <= set(build_site.LISTED))
        self.assertEqual(set(build_site.LEGACY_LANGS), {"pt", "zh", "ar", "hi", "ru"})
        for c in build_site.LEGACY_LANGS:
            self.assertNotIn(c, build_site.CODES)

    def test_every_language_has_every_english_key(self):
        loc = build_site.load_locales(ROOT)
        en = set(loc["en"])
        for c, d in loc.items():
            self.assertEqual(en - set(d), set(), "%s misses keys" % c)

    def test_template_keys_exist(self):
        loc = build_site.load_locales(ROOT)
        tpl = (ROOT / "src" / "home_body.html").read_text(encoding="utf-8")
        reserved = {"LANGSEL", "FOOTLANGS", "FOOTLINKS", "TOPLINK", "BLOGCARDS", "STUDIO"}
        for k in set(re.findall(r"\{\{(\w+)", tpl)) - reserved:
            self.assertIn(k, loc["en"], k)


class Pages(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.files = {k: v for k, v in build_site.build(ROOT).items()
                     if k not in [p + "index.html" for p in build_site.RETIRED_PATHS]}  # forwards for removed pages: see RedirectedLanguages

    @property
    def home(self):
        return {k: v for k, v in self.files.items()
                if k == "index.html" or (k.count("/") == 1 and k.endswith("/index.html") and k.split("/")[0] not in build_site.PAGES + build_site.LEGAL + ("journal",) + build_site.LEGACY_LANGS)}

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
        for c in build_site.LISTED:
            self.assertIn('href="%s"' % build_site.home_path(c), t)
        self.assertNotIn("<loc>https://draft.ipe.rest/404", self.files["sitemap.xml"])

    def test_404_links_to_the_blog_list(self):
        t = self.files["404.html"]
        self.assertIn('<a href="/journal/">', t)
        self.assertIn("/journal/index.html", {"/" + k for k in self.files})
        self.assertEqual(t.count('href="/journal/"'), 1)

    def test_og_locale_alternates_and_short_og_description(self):
        loc = build_site.load_locales(ROOT)
        t = self.files["ko/index.html"]
        self.assertIn('<meta property="og:locale" content="ko_KR">', t)
        self.assertEqual(len(re.findall(r'property="og:locale:alternate"', t)), len(build_site.LISTED) - 1)
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
            self.assertEqual(len(re.findall(r'rel="alternate" hreflang=', text)), len(build_site.LISTED) + 1, rel)
            self.assertIn('hreflang="x-default" href="https://draft.ipe.rest/"', text, rel)
            self.assertNotIn("?lang=", text, rel)
            self.assertNotIn("data-i18n", text, rel)
            self.assertNotIn("{{", text, rel)
            self.assertIn('<html lang="%s"%s>' % (build_site.tag(lang) if lang else "en", ""), text, rel)

    def test_only_root_has_language_detection(self):
        """Kit v0.7.2: the root carries the redirecting ipe-lang.js (data-redirect); every other page only the select."""
        self.assertIn("data-redirect", self.files["index.html"])
        self.assertRegex(self.files["index.html"], r'/assets/ipe-lang\.js\?v=[0-9a-f]+')
        for rel, text in self.files.items():
            if not rel.endswith(".html") or rel == "index.html" or 'http-equiv="refresh"' in text:
                continue
            self.assertNotIn("data-redirect", text, rel)

    def test_top_language_select_on_every_page(self):
        for rel, text in self.indexed_home.items():
            lang = rel.split("/")[0] if "/" in rel else "en"
            self.assertIn('id="ipe-lang-select"', text, rel)
            self.assertEqual(len(re.findall(r"<option ", text.split('id="ipe-lang-select"')[1].split("</select>")[0])), 12, rel)

    def test_root_language_rule_saved_then_browser_then_english(self):
        js = (ROOT / "assets" / "ipe-lang.js").read_text(encoding="utf-8")
        self.assertIn("ipe_lang", js)
        self.assertIn("nav.languages", js)
        self.assertLess(js.index("stored()"), js.index("nav.languages"))
        self.assertIn("ipe_lang", (ROOT / "assets" / "site.js").read_text(encoding="utf-8"))
        self.assertNotIn("draft_lang", self.files["index.html"])
        self.assertNotIn("langhint", (ROOT / "assets" / "site.js").read_text(encoding="utf-8"))

    def test_footer_has_terms_link_but_nav_does_not(self):
        for c in build_site.CODES:
            rel = "index.html" if c == "en" else "%s/index.html" % c
            text = self.files[rel]
            url = build_site.legal_url(c, "terms")
            foot = text[text.index("<footer"):]
            self.assertIn('href="%s"' % url, foot, rel)
            self.assertNotIn(url, text[:text.index("<footer")], rel)

    def test_journal_nav_label_in_every_language(self):
        loc = build_site.load_locales(ROOT)
        for c in build_site.CODES:
            self.assertTrue(loc[c]["nav_journal"], c)
            self.assertNotIn("blog_title_old", loc[c])
        self.assertEqual(loc["en"]["nav_journal"], "Journal")

    def test_old_blog_urls_are_noindex_meta_refresh_stubs(self):
        t = self.files["en/blog/index.html"]
        self.assertIn('http-equiv="refresh"', t)
        self.assertIn('rel="canonical"', t)
        self.assertIn("noindex,follow", t)
        self.assertIn("/journal/", t)
        self.assertIn("journal/index.html", self.files)

    def test_ended_language_stubs_point_to_the_new_language(self):
        for old, new in (("pt", "pt-BR"), ("zh", "zh-Hant"), ("ar", "en"), ("hi", "en"), ("ru", "en")):
            t = self.files["%s/index.html" % old]
            self.assertIn('http-equiv="refresh"', t, old)
            self.assertIn("noindex", t, old)
            self.assertNotIn("<loc>%s</loc>" % build_site.page_url(old), self.files["sitemap.xml"])

    def test_language_page_uses_its_own_strings(self):
        loc = build_site.load_locales(ROOT)
        self.assertIn(loc["ko"]["hero_h1"], self.files["ko/index.html"])
        self.assertIn(loc["en"]["hero_h1"], self.files["index.html"])
        self.assertNotIn(loc["ko"]["hero_h1"], self.files["index.html"])

    def test_hero_demo_text_is_in_data_attribute(self):
        loc = build_site.load_locales(ROOT)
        self.assertIn('data-raw="%s"' % build_site.esc(loc["ja"]["demo_raw"]), self.files["ja/index.html"])

    def test_footer_links_to_every_language(self):
        for c in build_site.LISTED:
            self.assertIn('href="%s"' % build_site.home_path(c), self.files["index.html"])

    def test_json_ld_parses(self):
        for rel, text in self.indexed_home.items():
            m = re.search(r'<script type="application/ld\+json">\n(.*?)\n</script>', text, re.S)
            self.assertEqual(json.loads(m.group(1))["@graph"][0]["@type"], "MobileApplication", rel)

    def test_assets_are_cache_busted(self):
        for rel, text in self.files.items():
            if rel.endswith("index.html") and rel != "en/index.html" and 'http-equiv="refresh"' not in text:
                self.assertRegex(text, r'/assets/site\.css\?v=[0-9a-f]{8}"')
                self.assertRegex(text, r'/assets/site\.js\?v=[0-9a-f]{8}"')

    def test_llms_block_lists_every_page(self):
        for c in build_site.LISTED:
            self.assertIn("(%s)" % build_site.page_url(c), self.files["llms.txt"])
        self.assertNotIn("One post per day", self.files["llms.txt"])


class EndedLanguages(unittest.TestCase):
    """ar/hi/ru end support (redirect to en), pt -> pt-BR, zh -> zh-Hant; th and tr are new full languages."""

    @classmethod
    def setUpClass(cls):
        cls.files = build_site.build(ROOT)

    def test_no_rtl_and_no_dir_attribute(self):
        self.assertEqual(build_site.RTL, ())
        for rel, text in self.files.items():
            if rel.endswith(".html"):
                self.assertNotIn(' dir="rtl"', text, rel)

    def test_new_languages_have_every_section(self):
        for c in ("th", "tr", "zh-Hant", "pt-BR"):
            for rel in ("%s/index.html" % c, "%s/about/index.html" % c, "%s/privacy/index.html" % c, "%s/terms/index.html" % c,
                        "%s/index.html" % build_site.journal_rel(c), "%s/feed.xml" % build_site.journal_rel(c)):
                self.assertIn(rel, self.files, rel)
        self.assertIn('<html lang="th">', self.files["th/index.html"])
        self.assertIn('<html lang="zh-Hant">', self.files["zh-Hant/index.html"])

    def test_ended_languages_are_not_listed_anywhere(self):
        home = self.files["index.html"]
        for c in build_site.LEGACY_LANGS:
            self.assertNotIn('hreflang="%s"' % c, home)
            self.assertNotIn('<option value="%s"' % c, home)
            self.assertNotIn("/%s/" % c, self.files["sitemap.xml"])
            self.assertNotIn("(%s)" % build_site.page_url(c), self.files["llms.txt"])

    def test_sitemap_has_no_leaks_per_kit(self):
        import sys as _s
        _s.path.insert(0, str(ROOT / "vendor"))
        from ipe_web_kit import redirects
        self.assertEqual(list(redirects.sitemap_leaks(self.files["sitemap.xml"])), [])

    def test_every_post_in_every_language(self):
        posts, errors = build_site.load_posts(ROOT)
        self.assertEqual(errors, [])
        for p in posts:
            for c in build_site.CODES:
                self.assertIn(c, p["langs"], p["slug"])
                self.assertIn("%s/%s/index.html" % (build_site.journal_rel(c), p["slug"]), self.files)


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
        self.assertIn('href="/journal/"', root)


POST_FM = "---\ntitle: %s\ndescription: d %s\ndate: 2026-10-01\ncopy_review: legacy-2026-11-14\nslug: %s\n%s---\n\n%s\n"


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
        for c in build_site.BLOG_CODES:
            for rel in ("%s/index.html" % build_site.journal_rel(c), "%s/feed.xml" % build_site.journal_rel(c), "%s/blank-caption-box/index.html" % build_site.journal_rel(c)):
                self.assertIn(rel, self.files)

    def test_post_has_hreflang_group_and_x_default_en(self):
        t = self.files["ko/journal/blank-caption-box/index.html"]
        self.assertEqual(len(re.findall(r'rel="alternate" hreflang=', t)), len(build_site.BLOG_LISTED) + 1)
        self.assertIn('hreflang="x-default" href="https://draft.ipe.rest/journal/blank-caption-box/"', t)
        self.assertIn('<link rel="canonical" href="https://draft.ipe.rest/ko/journal/blank-caption-box/">', t)
        self.assertIn('"@type": "BlogPosting"', t)

    def test_feed_is_valid_xml(self):
        import xml.etree.ElementTree as ET
        for c in build_site.BLOG_CODES:
            ch = ET.fromstring(self.files["%s/feed.xml" % build_site.journal_rel(c)].split("?>", 1)[1]).find("channel")
            self.assertEqual(ch.find("language").text, build_site.tag(c))
            self.assertEqual(len(ch.findall("item")), len(build_site.load_posts(ROOT)[0]))
            self.assertGreaterEqual(len(ch.findall("item")), 1)

    def test_home_links_to_blog_and_blog_is_in_sitemap_and_llms(self):
        self.assertIn('href="/ko/journal/"', self.files["ko/index.html"])
        self.assertIn("https://draft.ipe.rest/ko/journal/blank-caption-box/", self.files["sitemap.xml"])
        self.assertIn("(https://draft.ipe.rest/journal/blank-caption-box/)", self.files["llms.txt"])

    def test_first_post_ko_length(self):
        posts, errors = build_site.load_posts(ROOT)
        self.assertEqual(errors, [])
        first = next(p for p in posts if p["slug"] == "blank-caption-box")
        self.assertTrue(1200 <= len(first["langs"]["ko"]["_body"].strip()) <= 1800)

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
        write_post(self.dir, "a-post", langs=[c for c in build_site.BLOG_CODES if c != "de"])
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
        for c in build_site.BLOG_CODES:
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
        for n in ("src", "assets", "content", "vendor"):
            if (ROOT / n).is_dir():
                self.shutil.copytree(ROOT / n, self.dir / n)
        for n in ("llms.txt", "og-image.png"):
            self.shutil.copy(ROOT / n, self.dir / n)

    def build_with(self, published):
        extra = "published: %s\n" % published if published else ""
        write_post(self.dir, "a-post", extra=extra)
        return build_site.build(self.dir)

    def test_nine_past_nine_is_zero_padded_and_has_no_seconds(self):
        f = self.build_with("2026-10-01T09:09:45+09:00")
        for c in build_site.BLOG_CODES:
            for rel in ("%s/a-post/index.html" % build_site.journal_rel(c), "%s/index.html" % build_site.journal_rel(c)):
                self.assertIn(">2026-10-01 09:09 KST</time>", f[rel])
                self.assertNotIn("09:09:", re.sub(r"<time datetime=[^>]*>", "", f[rel]).replace("T09:09:00+09:00", ""))
        post = f["journal/a-post/index.html"]
        self.assertIn('<time datetime="2026-10-01T09:09+09:00" data-ipe-time title="2026-10-01 09:09 KST">', post)
        self.assertIn('"datePublished": "2026-10-01T09:09:00+09:00"', post)
        self.assertIn('"dateModified": "2026-10-01T09:09:00+09:00"', post)
        self.assertIn("<lastmod>2026-10-01T09:09:00+09:00</lastmod>", f["sitemap.xml"])
        self.assertIn("Thu, 01 Oct 2026 09:09:00 +0900", f["journal/feed.xml"])

    def test_other_offsets_are_converted_to_kst(self):
        f = self.build_with("2026-09-30T23:30:00+00:00")  # 08:30 KST on 10-01
        self.assertIn(">2026-10-01 08:30 KST</time>", f["journal/a-post/index.html"])
        self.assertIn('datetime="2026-10-01T08:30+09:00"', f["journal/a-post/index.html"])

    def test_post_without_published_shows_date_only(self):
        f = self.build_with(None)
        post = f["journal/a-post/index.html"]
        self.assertIn('<time datetime="2026-10-01">2026-10-01</time>', post)
        self.assertIn('// <span class="j-no">No. 1</span> · <time datetime="2026-10-01">', post)
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
        post = build_site.build(ROOT)["journal/blank-caption-box/index.html"]
        self.assertIn(">2026-10-23 17:30 KST</time>", post)
        self.assertIn('"datePublished": "2026-10-23T17:30:00+09:00"', post)


PAGER_LABEL = {"en": "Page", "ko": "페이지", "ja": "ページ", "zh-Hant": "頁", "es": "Página", "pt-BR": "Página",
               "id": "Halaman", "th": "หน้า", "vi": "Trang", "fr": "Page", "de": "Seite", "tr": "Sayfa"}
PAGE_WORD = dict(PAGER_LABEL, **{"zh-Hant": "第"})  # unused by the title check below; zh-Hant writes "第 2 頁"


class NumberingAndPaging(unittest.TestCase):
    """Davy 10-27: 'No. N' on every post (oldest = No. 1) and at most 10 posts per list page (/page/2/ ...)."""

    N = 12

    def make_root(self, n):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        d = Path(tmp.name)
        shutil.copytree(ROOT / "locales", d / "locales")
        for name in ("src", "assets", "content", "vendor"):
            if (ROOT / name).is_dir():
                shutil.copytree(ROOT / name, d / name)
        for name in ("llms.txt", "og-image.png", "robots.txt"):
            shutil.copy(ROOT / name, d / name)
        # slugs sort opposite to dates, so a slug-ordered numbering would fail
        for i in range(n):
            slug = "post-%02d" % (n - i)
            write_post(d, slug, extra="published: 2026-10-%02dT09:00:00+09:00\n" % (i + 1))
            for f in (d / "posts" / slug).rglob("*.md"):
                f.write_text(f.read_text(encoding="utf-8").replace("date: 2026-10-01", "date: 2026-10-%02d" % (i + 1)), encoding="utf-8")
        write_post(d, "unpublished-draft", extra="draft: true\n")
        return d

    def build(self, n):
        return build_site.build(self.make_root(n))

    def test_page_split_ten_and_rest(self):
        files = self.build(self.N)
        for c in build_site.BLOG_CODES:
            self.assertEqual(files["%s/index.html" % build_site.journal_rel(c)].count('<li>\n        <p class="comment">'), 10)
            self.assertEqual(files["%s/page/2/index.html" % build_site.journal_rel(c)].count('<li>\n        <p class="comment">'), 2)
            self.assertNotIn("%s/page/3/index.html" % build_site.journal_rel(c), files)

    def test_page_one_url_unchanged_and_no_page_one_file(self):
        files = self.build(self.N)
        for c in build_site.BLOG_CODES:
            self.assertNotIn("%s/page/1/index.html" % build_site.journal_rel(c), files)
            html = files["%s/index.html" % build_site.journal_rel(c)]
            self.assertIn('<link rel="canonical" href="https://draft.ipe.rest%s">' % build_site.journal_path(c), html)
            self.assertNotIn("/page/1/", html)
            self.assertIn('href="%spage/2/"' % build_site.journal_path(c), html)
        sm = files["sitemap.xml"]
        self.assertNotIn("/page/1/", sm)

    def test_page_two_canonical_title_prev_and_hreflang(self):
        files = self.build(self.N)
        loc = build_site.load_locales(ROOT)
        for c in build_site.BLOG_CODES:
            html = files["%s/page/2/index.html" % build_site.journal_rel(c)]
            url = "https://draft.ipe.rest%spage/2/" % build_site.journal_path(c)
            self.assertIn('<link rel="canonical" href="%s">' % url, html)
            title = re.search(r"<title>(.*?)</title>", html).group(1)
            word = PAGER_LABEL[c]
            suffix = " · " + loc[c]["blog_page"].format(n=2)
            self.assertTrue(title.endswith(suffix), title)
            desc = re.search(r'<meta name="description" content="(.*?)">', html).group(1)
            self.assertTrue(desc.endswith(suffix), desc)
            self.assertIn('<a class="pg-step" rel="prev" href="%s">' % build_site.journal_path(c), html)
            self.assertNotIn('rel="next"', html)
            self.assertIn('<span class="pg-num" aria-current="page">2</span>', html)
            self.assertIn('<a class="pg-num" href="%s" aria-label="%s">1</a>' % (build_site.journal_path(c), loc[c]["blog_page"].format(n=1)), html)
            for o in build_site.BLOG_LISTED:
                self.assertIn('hreflang="%s" href="https://draft.ipe.rest%spage/2/"' % (build_site.tag(o), build_site.journal_path(o)), html)
            self.assertIn('hreflang="x-default" href="https://draft.ipe.rest/journal/page/2/"', html)
            page1 = files["%s/index.html" % build_site.journal_rel(c)]
            self.assertNotIn(" %s 2" % word, re.search(r"<title>(.*?)</title>", page1).group(1))
            self.assertIn('<a class="pg-step" rel="next" href="%spage/2/">' % build_site.journal_path(c), page1)
            self.assertIn('<span class="pg-num" aria-current="page">1</span>', page1)
            self.assertIn('<nav class="pager" aria-label="%s">' % PAGER_LABEL[c], page1)
            self.assertIn('<nav class="pager" aria-label="%s">' % PAGER_LABEL[c], html)

    def test_sitemap_has_page_two_for_every_language(self):
        root = self.make_root(self.N)
        files = build_site.build(root)
        sm = files["sitemap.xml"]
        for c in build_site.BLOG_LISTED:
            self.assertIn("<loc>https://draft.ipe.rest%spage/2/</loc>" % build_site.journal_path(c), sm)
        for rel, text in files.items():  # the checker wants every sitemap URL built on disk
            f = root / rel
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text(text, encoding="utf-8")
        self.assertEqual(check_sitemap.main(["--root", str(root)]), 0)

    def test_item_list_covers_only_the_page_in_page_order(self):
        files = self.build(self.N)
        for page, want in (("journal", 10), ("journal/page/2", 2)):
            html = files["%s/index.html" % page]
            il = ld_of(html, "Blog")["mainEntity"]
            self.assertEqual(il["numberOfItems"], want)
            self.assertEqual([x["position"] for x in il["itemListElement"]], list(range(1, want + 1)))
            self.assertEqual(len(ld_of(html, "Blog")["blogPost"]), want)

    def test_numbers_oldest_is_one_same_in_every_language_drafts_excluded(self):
        files = self.build(self.N)
        for c in build_site.BLOG_CODES:
            self.assertIn("No. 1</span>", files["%s/page/2/index.html" % build_site.journal_rel(c)])
            oldest = files["%s/post-%02d/index.html" % (build_site.journal_rel(c), self.N)]
            newest = files["%s/post-01/index.html" % build_site.journal_rel(c)]
            self.assertIn('<span class="j-no">No. 1</span>', oldest)
            self.assertIn('<span class="j-no">No. %d</span>' % self.N, newest)  # draft did not take a number
            self.assertNotIn("No. %d</span>" % (self.N + 1), files["%s/index.html" % build_site.journal_rel(c)])
            self.assertNotIn("unpublished-draft", files["%s/index.html" % build_site.journal_rel(c)])

    def test_home_cards_carry_the_same_numbers(self):
        files = self.build(self.N)
        for c in build_site.BLOG_CODES:
            home = files["index.html" if c == "en" else "%s/index.html" % c]
            self.assertEqual(re.findall(r'class="j-no">(No\. \d+)<', home), ["No. 12", "No. 11", "No. 10"])

    def test_earlier_numbers_do_not_change_when_a_newer_post_arrives(self):
        posts = build_site.load_posts(self.make_root(6))[0]
        before = build_site.post_numbers(posts[1:])  # newest dropped = the state before it arrived
        after = build_site.post_numbers(posts)
        self.assertEqual({k: after[k] for k in before}, before)
        self.assertEqual(sorted(after.values()), list(range(1, 7)))

    def test_reserved_slug_page_is_a_build_error(self):
        root = self.make_root(2)
        write_post(root, "page")
        with self.assertRaises(build_site.BuildError) as cm:
            build_site.build(root)
        self.assertIn("reserved", str(cm.exception))

    def test_few_posts_make_no_second_page(self):
        files = self.build(5)
        self.assertEqual([r for r in files if "/page/" in r and "/blog/" not in r], [])
        self.assertNotIn('class="pager"', files["journal/index.html"])
        self.assertNotIn("/page/", files["sitemap.xml"])

    def test_repo_today_has_only_the_pages_it_needs(self):
        files = build_site.build(ROOT)
        posts, _ = build_site.load_posts(ROOT)
        pages = -(-len(posts) // build_site.LIST_PAGE_SIZE)
        for c in build_site.BLOG_CODES:
            extra = sorted(r for r in files if r.startswith("%s/page/" % build_site.journal_rel(c)) and r.endswith("/index.html"))
            want = ["%s/page/%d/index.html" % (build_site.journal_rel(c), n) for n in range(2, pages + 1)]
            self.assertEqual(extra, want, c)


class StageSite(unittest.TestCase):
    def test_only_public_files_are_staged(self):
        import stage_site
        with tempfile.TemporaryDirectory() as tmp:
            files = {f.as_posix() for f in stage_site.stage(ROOT, tmp)}
            for must in ("index.html", "404.html", "CNAME", ".nojekyll", "robots.txt", "sitemap.xml", "llms.txt", "og-image.png",
                         "assets/site.css", "assets/site.js", "ko/index.html", "en/index.html", "ko/journal/feed.xml"):
                self.assertIn(must, files)
            self.assertTrue(any(re.match(r"^[0-9a-f]{32}\.txt$", f) for f in files), "IndexNow key file")
            for f in files:
                self.assertFalse(f.startswith(("scripts/", "tests/", "posts/", "locales/", "src/", ".github/", "_site/")), f)
                self.assertNotIn(f.rsplit(".", 1)[-1], ("md", "py", "json", "yml"), f)

    def test_every_built_file_is_staged(self):
        """Whatever the build writes is meant to be served: forwards (old /blog/, ended languages, /releases/) and the root feed too,
        or the old URL 404s after deploy."""
        import stage_site
        with tempfile.TemporaryDirectory() as tmp:
            files = {f.as_posix() for f in stage_site.stage(ROOT, tmp)}
        built = set(build_site.build(ROOT))
        self.assertEqual(sorted(built - files), [])
        for must in ("feed.xml", "journal/feed.xml", "releases/index.html", "ko/blog/index.html", "pt/index.html", "zh/blog/index.html",
                     "ru/blog/start-later/index.html", "pt-BR/journal/index.html"):
            self.assertIn(must, files)

    def test_nothing_stale_is_staged_from_ended_language_folders(self):
        import stage_site
        with tempfile.TemporaryDirectory() as tmp:
            files = {f.as_posix() for f in stage_site.stage(ROOT, tmp)}
        built = set(build_site.build(ROOT))
        legacy = {f for f in files if f.split("/")[0] in build_site.LEGACY_LANGS + ("releases",)}
        self.assertEqual(sorted(legacy - built), [])


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


class LocalTime(unittest.TestCase):
    """Company-wide publish-time module (ipe-rest c466827, v2): byte-identical copy, inlined; every <time> carries data-ipe-time and +09:00."""

    SHA256 = "57326449ddf5050eabadd1394d69eb2b0f61c88f084ec83ee4aff6fcad0f74b8"

    @classmethod
    def setUpClass(cls):
        cls.files = build_site.build(ROOT)
        cls.pages = {k: v for k, v in cls.files.items() if re.match(r"^(?:[a-z]{2}/)?journal/.+\.html$", k)}

    def test_copy_matches_canonical_hash(self):
        import hashlib
        data = (ROOT / build_site.LOCALTIME_JS).read_bytes()
        self.assertEqual(hashlib.sha256(data).hexdigest(), self.SHA256)
        self.assertEqual(len(data), 1639)

    def test_build_inlines_module_bytes_before_body_end(self):
        js = (ROOT / build_site.LOCALTIME_JS).read_bytes().decode("utf-8")
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
        for c in build_site.BLOG_CODES:
            got = [re.search(r'href="%s([^/"]+)/"' % build_site.journal_path(c), x).group(1) for x in self.cards(c)]
            self.assertEqual(got, want, c)
            self.assertLessEqual(len(got), 3, c)
            for slug, x in zip(want, self.cards(c)):
                p = next(q for q in self.posts if q["slug"] == slug)
                self.assertIn(build_site.esc(p["langs"][c]["title"]), x, c)
                self.assertEqual(x.count("<a "), 1, c)  # the whole card is one link

    def test_newest_published_post_is_first(self):
        newest = self.posts[0]["slug"]
        self.assertEqual(build_site.when_key(self.posts[0]["date"]), max(build_site.when_key(p["date"]) for p in self.posts))
        for c in build_site.BLOG_CODES:
            self.assertIn("%s%s/" % (build_site.journal_path(c), newest), self.cards(c)[0], c)

    def test_see_all_link_and_no_unpublished(self):
        drafts = {d.name for d in (ROOT / "posts").iterdir() if d.is_dir()} - {p["slug"] for p in self.posts}
        for c in build_site.BLOG_CODES:
            self.assertIn('class="btn-line" href="%s"' % build_site.journal_path(c), self.home(c), c)
            for slug in drafts:
                self.assertNotIn(slug, self.home(c), c)

    def test_section_sits_right_after_hero_and_once(self):
        for c in build_site.BLOG_CODES:
            h = self.home(c)
            self.assertEqual(h.count('class="blognotes"'), 1, c)
            self.assertLess(h.index("</header>"), h.index('class="blognotes"'), c)
            self.assertLess(h.index('class="blognotes"'), h.index('<section class="problem">'), c)

    def test_times_are_kst_convertible_and_module_inlined_once(self):
        import hashlib
        js = (ROOT / build_site.LOCALTIME_JS).read_bytes()
        for c in build_site.BLOG_CODES:
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


def ld_blocks(html):
    return [json.loads(x) for x in re.findall(r'<script type="application/ld\+json">\n(.*?)\n</script>', html, re.S)]


def ld_of(html, typ):
    for b in ld_blocks(html):
        for n in b.get("@graph", [b]):
            if n.get("@type") == typ:
                return n
    raise AssertionError("no %s block" % typ)


HUB = "https://ipe.rest/#organization"
AUTHOR = {"@type": "Organization", "@id": HUB, "name": "ipe()", "url": "https://ipe.rest/"}


FREE_WORDS = r"free|무료|無料|免费|免費|gratis|grátis|gratuit|kostenlos|бесплатно|miễn phí"


class JsonLd(unittest.TestCase):
    """Davy 10-26: every page's JSON-LD points at the ipe.rest Organization hub; list pages carry an ItemList."""

    @classmethod
    def setUpClass(cls):
        cls.files = build_site.build(ROOT)
        cls.posts, _ = build_site.load_posts(ROOT)

    def home(self, c):
        return self.files["index.html" if c == build_site.DEFAULT_LANG else "%s/index.html" % c]

    def test_post_publisher_author_and_blog_ids(self):
        for c in build_site.BLOG_CODES:
            for p in self.posts:
                d = ld_of(self.files["%s/%s/index.html" % (build_site.journal_rel(c), p["slug"])], "BlogPosting")
                pub = d["publisher"]
                self.assertEqual(pub["@id"], HUB)
                self.assertEqual(pub["name"], "ipe()")
                self.assertEqual(pub["logo"]["url"], "https://ipe.rest/icon-512.png")
                self.assertEqual(d["author"], AUTHOR)
                self.assertEqual(d["isPartOf"]["@id"], "https://draft.ipe.rest%s#blog" % build_site.journal_path(c))

    def test_list_blog_itemlist_and_ids(self):
        for c in build_site.BLOG_CODES:
            html = self.files["%s/index.html" % build_site.journal_rel(c)]
            blog = ld_of(html, "Blog")
            self.assertEqual(blog["@id"], "https://draft.ipe.rest%s#blog" % build_site.journal_path(c))
            self.assertEqual(blog["isPartOf"], {"@id": "https://draft.ipe.rest/#website"})
            self.assertEqual(blog["publisher"]["@id"], HUB)
            self.assertEqual(blog["publisher"]["logo"]["url"], "https://ipe.rest/icon-512.png")
            self.assertEqual(blog["author"], AUTHOR)
            items = blog["mainEntity"]["itemListElement"]
            shown = re.findall(r'<li>\s*<p class="comment">.*?<h2><a href="(%s[^"]+/)"' % build_site.journal_path(c), html, re.S)
            self.assertEqual(len(items), min(len(self.posts), build_site.LIST_PAGE_SIZE))
            self.assertEqual(len(items), len(shown))
            self.assertEqual([i["position"] for i in items], list(range(1, len(items) + 1)))
            self.assertEqual([i["url"] for i in items], ["https://draft.ipe.rest" + u for u in shown])
            self.assertEqual(blog["mainEntity"]["numberOfItems"], len(items))

    def test_home_organization_and_website_ids(self):
        for c in build_site.BLOG_CODES:
            html = self.home(c)
            org = ld_of(html, "Organization")
            self.assertEqual(org["@id"], HUB)
            self.assertEqual(org["name"], "ipe()")
            self.assertEqual(org["url"], "https://ipe.rest/")
            self.assertEqual(org["logo"]["url"], "https://ipe.rest/icon-512.png")
            site = ld_of(html, "WebSite")
            self.assertEqual(site["@id"], "https://draft.ipe.rest/#website")
            self.assertEqual(site["publisher"], {"@id": HUB})
            app = ld_of(html, "MobileApplication")
            self.assertEqual(app["publisher"], {"@id": HUB})
            self.assertEqual(app["author"], {"@id": HUB})

    def test_every_organization_node_is_the_hub(self):
        def walk(n):
            if isinstance(n, dict):
                yield n
                for v in n.values():
                    yield from walk(v)
            elif isinstance(n, list):
                for v in n:
                    yield from walk(v)
        for rel, t in self.files.items():
            if not (rel.endswith(".html") and "application/ld+json" in t):
                continue
            blocks = ld_blocks(t)
            for n in walk(blocks):
                if n.get("@type") == "Organization":
                    self.assertEqual(n.get("name"), "ipe()", rel)
                    self.assertEqual(n.get("@id"), HUB, rel)
            if not rel.endswith("about/index.html"):
                self.assertNotIn("ipe studio", json.dumps(blocks, ensure_ascii=False).lower(), rel)

    def test_app_node_is_one_entity_ios_only(self):
        ids = set()
        for c in build_site.BLOG_CODES:
            for t in (self.home(c), self.files[build_site.page_path(c, "about").strip("/") + "/index.html"]):
                for b in ld_blocks(t):
                    for n in [b] + list(b.get("@graph", [])) + [b.get("mainEntity", {})]:
                        if n.get("@type") == "MobileApplication":
                            ids.add(n["@id"])
                            self.assertEqual(n["operatingSystem"], "iOS")
        self.assertEqual(ids, {"https://draft.ipe.rest/#app"})

    def test_website_node_identical_on_all_homes(self):
        nodes = {json.dumps(ld_of(self.home(c), "WebSite"), sort_keys=True) for c in build_site.BLOG_CODES}
        self.assertEqual(len(nodes), 1)

    def test_blog_list_items_reference_article_ids(self):
        for c in build_site.BLOG_CODES:
            html = self.files["%s/index.html" % build_site.journal_rel(c)]
            blog = ld_of(html, "Blog")
            for it in blog["mainEntity"]["itemListElement"]:
                self.assertEqual(it["item"], {"@id": it["url"] + "#article"})
            for bp in blog["blogPost"]:
                self.assertEqual(bp["@id"], bp["url"] + "#article")

    def test_about_titles_within_60(self):
        for c in build_site.BLOG_CODES:
            for slug in build_site.PAGES:
                t = html_unescape(re.search(r"<title>(.*?)</title>", self.files[build_site.page_path(c, slug).strip("/") + "/index.html"]).group(1))
                self.assertLessEqual(len(t), 60, (c, slug, len(t)))

    def article(self, c, slug):
        return ld_of(self.files["%s/%s/index.html" % (build_site.journal_rel(c), slug)], "BlogPosting")

    def test_image_is_imageobject_with_real_file_size(self):
        w, h = build_site.image_size(ROOT / "og-image.png")
        self.assertEqual((w, h), (1200, 630))
        for c in build_site.BLOG_CODES:
            for p in self.posts:
                img = self.article(c, p["slug"])["image"]
                self.assertEqual(img, {"@type": "ImageObject", "url": "https://draft.ipe.rest/og-image.png", "width": w, "height": h})
                self.assertEqual(self.article(c, p["slug"])["publisher"]["logo"]["width"], 512)

    def test_word_count_method_is_pinned(self):
        self.assertEqual(build_site.word_count("<p>One two  three</p><p>four</p>", "en"), 4)
        self.assertEqual(build_site.word_count("<p>첫 줄이 이야기를 살립니다</p>", "ko"), 4)  # space-delimited: words
        self.assertEqual(build_site.word_count("<p>最初の、ひと文。 A1</p>", "ja"), 8)  # characters; spaces and punctuation excluded
        self.assertEqual(build_site.word_count("<p>第一句，很重要。</p>", "zh-Hant"), 6)
        self.assertEqual(build_site.word_count("<p>วันนี้ ฝนตก</p>", "th"), 7)  # th: letters/digits only (combining marks and spaces excluded)
        self.assertEqual(build_site.word_count("<p>a &amp; b</p>", "en"), 3)

    def test_post_has_wordcount_keywords_section_about_per_language(self):
        loc = build_site.load_locales(ROOT)
        for c in build_site.BLOG_CODES:
            for p in self.posts:
                d = self.article(c, p["slug"])
                body = build_site.markdown(p["langs"][c]["_body"])
                self.assertEqual(d["wordCount"], build_site.word_count(body, c))
                self.assertGreater(d["wordCount"], 100, c)
                self.assertEqual(d["keywords"], loc[c]["ld_keywords"])
                self.assertEqual(d["articleSection"], loc[c]["ld_section"])
                self.assertEqual(d["about"], [{"@type": "Thing", "name": loc[c]["ld_topic"]}])
        self.assertNotEqual(loc["ko"]["ld_section"], loc["en"]["ld_section"])

    def test_article_ids_and_translation_links(self):
        for p in self.posts:
            slug = p["slug"]
            en = self.article("en", slug)
            self.assertEqual(en["@id"], "https://draft.ipe.rest/journal/%s/#article" % slug)
            self.assertNotIn("translationOfWork", en)
            want = {"https://draft.ipe.rest%s%s/#article" % (build_site.journal_path(c), slug) for c in build_site.BLOG_LISTED if c != "en"}
            self.assertEqual({x["@id"] for x in en["workTranslation"]}, want)
            self.assertEqual(len(en["workTranslation"]), len(build_site.BLOG_LISTED) - 1)
            for c in build_site.BLOG_CODES:
                if c == "en":
                    continue
                d = self.article(c, slug)
                self.assertEqual(d["@id"], "https://draft.ipe.rest%s%s/#article" % (build_site.journal_path(c), slug))
                self.assertEqual(d["translationOfWork"]["@id"], en["@id"])
                self.assertEqual(d["translationOfWork"]["inLanguage"], "en")
                self.assertNotIn("workTranslation", d)
                if c in build_site.BLOG_LISTED:
                    self.assertIn(d["@id"], {x["@id"] for x in en["workTranslation"]})


class JsonLdPostFields(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        shutil.copytree(ROOT / "locales", self.dir / "locales")
        for n in ("src", "assets", "content", "vendor"):
            if (ROOT / n).is_dir():
                shutil.copytree(ROOT / n, self.dir / n)
        for n in ("llms.txt", "og-image.png"):
            shutil.copy(ROOT / n, self.dir / n)

    def test_date_modified_follows_updated_else_published(self):
        write_post(self.dir, "a-post", extra="published: 2026-10-01T09:09:45+09:00\n")
        write_post(self.dir, "b-post", extra="published: 2026-10-01T10:00:00+09:00\nupdated: 2026-10-20T11:30:00+09:00\n")
        f = build_site.build(self.dir)
        a = ld_of(f["ko/journal/a-post/index.html"], "BlogPosting")
        b = ld_of(f["ko/journal/b-post/index.html"], "BlogPosting")
        self.assertEqual(a["dateModified"], a["datePublished"])
        self.assertEqual(b["datePublished"], "2026-10-01T10:00:00+09:00")
        self.assertEqual(b["dateModified"], "2026-10-20T11:30:00+09:00")

    def test_draft_post_is_not_in_itemlist(self):
        write_post(self.dir, "a-post", extra="published: 2026-10-01T09:09:45+09:00\n")
        write_post(self.dir, "z-draft", extra="draft: true\n")
        f = build_site.build(self.dir)
        urls = [i["url"] for i in ld_of(f["ko/journal/index.html"], "Blog")["mainEntity"]["itemListElement"]]
        self.assertEqual(urls, ["https://draft.ipe.rest/ko/journal/a-post/"])
        self.assertNotIn("z-draft", f["ko/journal/index.html"])


    def test_front_matter_overrides_keywords_section_about(self):
        write_post(self.dir, "a-post", extra="published: 2026-10-01T09:09:45+09:00\nkeywords: alpha, beta\nsection: Craft\nabout: Hooks | Openings | Extra\n")
        d = ld_of(build_site.build(self.dir)["ko/journal/a-post/index.html"], "BlogPosting")
        self.assertEqual(d["keywords"], "alpha, beta")
        self.assertEqual(d["articleSection"], "Craft")
        self.assertEqual([a["name"] for a in d["about"]], ["Hooks", "Openings"])



class SeoFixes(unittest.TestCase):
    """10-26 SEO audit: no placeholder links, About/Privacy pages, title/description lengths, touch icon, home <main>."""

    @classmethod
    def setUpClass(cls):
        cls.files = build_site.build(ROOT)
        cls.posts, _ = build_site.load_posts(ROOT)
        cls.loc = build_site.load_locales(ROOT)

    def pages(self):
        return {k: v for k, v in self.files.items() if k.endswith(".html")}

    def title(self, html):
        return re.search(r"<title>(.*?)</title>", html, re.S).group(1)

    def test_no_placeholder_links_anywhere(self):
        for rel, t in self.pages().items():
            self.assertNotIn('href="#"', t, rel)

    def test_cta_is_not_a_link_but_keeps_its_text(self):
        for c in build_site.BLOG_CODES:
            home = self.files["index.html" if c == "en" else "%s/index.html" % c]
            self.assertNotIn('<a class="btn"', home, c)
            self.assertEqual(home.count('class="btn" aria-disabled="true"'), 3, c)  # two store buttons + community
            self.assertGreaterEqual(home.count("<span>%s</span>" % html_unescape_free(self.loc[c]["cta_download"])), 2, c)
            self.assertIn("<span>%s</span>" % html_unescape_free(self.loc[c]["comm_cta"]), home, c)
            post = self.files["%s/%s/index.html" % (build_site.journal_rel(c), self.posts[0]["slug"])]
            self.assertIn('class="btn" aria-disabled="true"', post, c)
            self.assertNotIn('<a class="btn"', post, c)

    def test_legal_paths_forward_to_ipe_rest(self):
        for c in build_site.CODES:
            for slug in build_site.LEGAL:
                rel = build_site.page_path(c, slug).strip("/") + "/index.html"
                t = self.files[rel]
                target = build_site.legal_url(c, slug)
                self.assertIn('<meta http-equiv="refresh" content="0; url=%s">' % target, t, rel)
                self.assertIn('<link rel="canonical" href="%s">' % target, t, rel)
                self.assertIn('<meta name="robots" content="noindex,follow">', t, rel)
                self.assertIn('<a href="%s">' % target, t, rel)
                self.assertIn('<html lang="%s"' % build_site.tag(c), t, rel)
        for c in build_site.LISTED:
            home = self.files["index.html" if c == "en" else "%s/index.html" % c]
            self.assertIn('href="%s"' % build_site.legal_url(c, "privacy"), home, c)
        self.assertEqual(build_site.legal_url("ko", "privacy"), "https://ipe.rest/ko/legal/privacy/")
        self.assertEqual(build_site.legal_url("ja", "terms"), "https://ipe.rest/ja/legal/terms/")
        self.assertEqual(build_site.legal_url("zh-Hant", "terms"), "https://ipe.rest/zh-Hant/legal/terms/")
        self.assertNotIn("/privacy/", self.files["sitemap.xml"])
        self.assertNotIn("/terms/", self.files["sitemap.xml"])

    def test_about_pages_in_every_language(self):
        for slug in build_site.PAGES:
            for c in [x for x in build_site.page_codes(slug) if x in build_site.LISTED]:
                rel = ("%s/index.html" % slug) if c == "en" else "%s/%s/index.html" % (c, slug)
                t = self.files[rel]
                url = build_site.content_url(c, slug)
                self.assertIn('<link rel="canonical" href="%s">' % url, t)
                self.assertEqual(len(re.findall(r'rel="alternate" hreflang=', t)), len(set(build_site.page_codes(slug)) & set(build_site.LISTED)) + 1, rel)
                self.assertIn("<loc>%s</loc>" % url, self.files["sitemap.xml"])
                home = self.files["index.html" if c == "en" else "%s/index.html" % c]
                self.assertIn('href="%s"' % build_site.page_path(c, slug), home, "%s footer link to %s" % (c, slug))
        self.assertNotIn("/faq", self.files["sitemap.xml"])
        for rel, t in self.pages().items():
            self.assertNotIn("/faq/", t, rel)

    def test_content_pages_say_nothing_about_price_or_free(self):
        for c in build_site.BLOG_CODES:
            d = build_site.load_content(ROOT)[c]
            text = json.dumps({k: d[k] for k in ("about",) + (("privacy",) if "privacy" in d else ())}, ensure_ascii=False)
            self.assertNotRegex(text, r"[$€¥]|USD|\d+[.,]\d{2}\s", c)
            self.assertNotRegex(text.lower(), FREE_WORDS, c)

    def test_footer_has_no_support_link(self):
        for c in build_site.BLOG_CODES:
            home = self.files["index.html" if c == "en" else "%s/index.html" % c]
            self.assertNotIn(">%s</a>" % self.loc[c]["foot_support"], home, c)

    def test_post_title_suffix_rule(self):
        self.assertEqual(build_site.post_title("Short"), "Short — draft()")
        long = "x" * 51
        self.assertEqual(build_site.post_title(long), long)
        self.assertEqual(len(build_site.post_title("x" * 50)), 60)
        for c in build_site.BLOG_CODES:
            for p in self.posts:
                t = self.files["%s/%s/index.html" % (build_site.journal_rel(c), p["slug"])]
                head = p["langs"][c]["title"]
                self.assertEqual(html_unescape(self.title(t)), build_site.post_title(head))
                self.assertIn("<h1>%s</h1>" % build_site.esc(head), t)

    def test_blog_list_title_is_descriptive_per_language(self):
        seen = set()
        for c in build_site.BLOG_CODES:
            t = html_unescape(self.title(self.files["%s/index.html" % build_site.journal_rel(c)]))
            self.assertEqual(t, self.loc[c]["blog_title"])
            self.assertLessEqual(len(t), 60, c)
            self.assertGreater(len(t), 20, c)
            seen.add(t)
        self.assertEqual(len(seen), 12)

    def test_home_description_lengths(self):
        for c in build_site.BLOG_CODES:
            d = self.loc[c]["meta_desc_short"]
            self.assertLessEqual(len(d), 100 if c in ("ko", "ja", "zh-Hant") else 160, c)
            home = self.files["index.html" if c == "en" else "%s/index.html" % c]
            self.assertIn('<meta name="description" content="%s">' % build_site.esc(d), home)

    def test_post_descriptions_within_limit_and_validated(self):
        for p in self.posts:
            for c, m in p["langs"].items():
                self.assertLessEqual(len(m["description"]), build_site.DESC_MAX, "%s/%s" % (p["slug"], c))

    def test_touch_icon_and_favicon(self):
        for rel, t in self.pages().items():
            if 'http-equiv="refresh"' in t:  # redirect stub, no <head> furniture
                continue
            self.assertIn('<link rel="apple-touch-icon" href="/apple-touch-icon.png">', t, rel)
        png = (ROOT / "apple-touch-icon.png").read_bytes()
        self.assertEqual(build_site.image_size(ROOT / "apple-touch-icon.png"), (180, 180))
        self.assertEqual(png[:8], b"\x89PNG\r\n\x1a\n")
        self.assertEqual((ROOT / "favicon.ico").read_bytes()[:4], b"\x00\x00\x01\x00")
        import stage_site
        names = {p.as_posix() for p in stage_site.public_files(ROOT)}
        self.assertTrue({"apple-touch-icon.png", "favicon.ico", "about/index.html", "privacy/index.html", "terms/index.html", "ko/about/index.html"} <= names)

    def test_render_blocking_resources_are_tamed(self):
        """10-26 perf: fonts swap + preconnect, site.js deferred; the inline localtime script stays where it is."""
        samples = ["index.html", "ko/index.html", "journal/index.html", "ko/journal/%s/index.html" % self.posts[0]["slug"], "about/index.html"]
        for rel in samples:
            t = self.files[rel]
            self.assertRegex(t, r'<script src="/assets/site\.js\?v=[0-9a-f]{8}" defer></script>', rel)
            self.assertNotRegex(t, r'<script src="/assets/site\.js[^>]*></script>(?<!defer></script>)', rel)
            self.assertIn('<link rel="preconnect" href="https://fonts.googleapis.com">', t, rel)
            self.assertIn('<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>', t, rel)
            font = re.search(r'<link href="(https://fonts\.googleapis\.com/[^"]+)" rel="stylesheet">', t)
            self.assertTrue(font and "display=swap" in font.group(1), rel)
            self.assertLess(t.index("fonts.googleapis.com"), t.index("/assets/site.css"), rel)
            self.assertIn('href="/assets/site.css?v=', t, rel)
        post = self.files["ko/journal/%s/index.html" % self.posts[0]["slug"]]
        self.assertIn("<script>", post[post.index("</footer>"):])  # inline localtime, after the footer, not deferred
        self.assertLess(post.index("</footer>"), post.rindex("<script>"))

    def test_home_has_one_main_landmark_around_the_content(self):
        for c in build_site.BLOG_CODES:
            home = self.files["index.html" if c == "en" else "%s/index.html" % c]
            self.assertEqual(home.count("<main"), 1, c)
            self.assertEqual(home.count("</main>"), 1, c)
            a, b = home.index("<main"), home.index("</main>")
            self.assertIn("<h1", home[a:b])
            self.assertIn('<section class="pricing">', home[a:b])
            self.assertLess(home.index("<footer>"), len(home))
            self.assertGreater(home.index("<footer>"), b)
            self.assertLess(home.index('class="toplink"'), a)


def html_unescape_free(s):
    """Text as the home template writes it (& < > escaped, quotes kept)."""
    import html
    return html.escape(s, quote=False)


def html_unescape(s):
    import html
    return html.unescape(s)


class BlogPostingAudit(unittest.TestCase):
    """SEO guide P0-8: every published post page (all posts x 13 languages) carries a complete BlogPosting node."""

    REQUIRED = ("@id", "headline", "description", "datePublished", "dateModified", "inLanguage", "mainEntityOfPage", "url",
                "image", "author", "publisher", "isPartOf", "wordCount", "keywords", "articleSection")
    ISO = re.compile(r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\+09:00$")

    @classmethod
    def setUpClass(cls):
        cls.files = build_site.build(ROOT)
        cls.posts, _ = build_site.load_posts(ROOT)

    def pages(self):
        for p in self.posts:
            for c in build_site.BLOG_CODES:
                yield p, c, self.files["%s/%s/index.html" % (build_site.journal_rel(c), p["slug"])]

    def test_there_are_posts_to_audit(self):
        self.assertGreaterEqual(len(list(self.pages())), 13)

    def test_required_fields_publisher_and_dates_on_every_page(self):
        import datetime as dt
        import html as htmllib
        now = dt.datetime.now(build_site.KST)
        for p, c, page in self.pages():
            where = "%s/%s" % (c, p["slug"])
            d = ld_of(page, "BlogPosting")
            for k in self.REQUIRED:
                self.assertTrue(d.get(k), "%s: missing %s" % (where, k))
            self.assertEqual(d["publisher"]["@id"], HUB, where)
            self.assertEqual(d["author"]["@id"], HUB, where)
            self.assertEqual(d["inLanguage"], build_site.tag(c), where)
            self.assertEqual(d["url"], build_site.post_url(c, p["slug"]), where)
            self.assertEqual(d["mainEntityOfPage"]["@id"], d["url"], where)
            for k in ("datePublished", "dateModified"):
                self.assertRegex(d[k], self.ISO, "%s: %s" % (where, k))
                self.assertLessEqual(dt.datetime.fromisoformat(d[k]), now, "%s: %s is in the future" % (where, k))
            self.assertLessEqual(d["datePublished"], d["dateModified"], where)
            title = htmllib.unescape(re.search(r"<title>(.*?)</title>", page, re.S).group(1))
            self.assertIn(d["headline"], title, "%s: headline is not part of <title>" % where)
            self.assertIsInstance(d["wordCount"], int, where)
            self.assertGreater(d["wordCount"], 0, where)

    def test_translation_links_and_breadcrumb_on_every_page(self):
        for p, c, page in self.pages():
            where = "%s/%s" % (c, p["slug"])
            d = ld_of(page, "BlogPosting")
            if c == build_site.DEFAULT_LANG:
                self.assertEqual(len(d["workTranslation"]), len(build_site.BLOG_LISTED) - 1, where)
                self.assertNotIn("translationOfWork", d, where)
            else:
                self.assertEqual(d["translationOfWork"]["@id"], build_site.article_id("en", p["slug"]), where)
                self.assertNotIn("workTranslation", d, where)
            crumb = ld_of(page, "BreadcrumbList")["itemListElement"]
            self.assertEqual([x["position"] for x in crumb], [1, 2, 3], where)
            self.assertEqual(crumb[-1]["item"], d["url"], where)


class PostMoreLinks(unittest.TestCase):
    """SEO guide P1-1: previous / next post and the latest 3 posts (same language) under every post."""

    @classmethod
    def setUpClass(cls):
        cls.files = build_site.build(ROOT)
        cls.posts, _ = build_site.load_posts(ROOT)  # newest first

    def page(self, c, slug):
        return self.files["%s/%s/index.html" % (build_site.journal_rel(c), slug)]

    @staticmethod
    def hrefs(page, cls):
        m = re.search(r'<(nav|section) class="%s".*?</\1>' % cls, page, re.S)
        return re.findall(r'href="([^"]+)"', m.group(0)) if m else []

    def test_repo_has_enough_posts_to_exercise_this(self):
        self.assertGreaterEqual(len(self.posts), 4)

    def test_prev_next_follow_publication_order_in_every_language(self):
        for i, p in enumerate(self.posts):
            for c in build_site.BLOG_CODES:
                want = []
                if i + 1 < len(self.posts):
                    want.append("%s%s/" % (build_site.journal_path(c), self.posts[i + 1]["slug"]))  # older = previous
                if i > 0:
                    want.append("%s%s/" % (build_site.journal_path(c), self.posts[i - 1]["slug"]))  # newer = next
                self.assertEqual(self.hrefs(self.page(c, p["slug"]), "post-adj"), want, "%s/%s" % (c, p["slug"]))
        newest = self.page("en", self.posts[0]["slug"])
        oldest = self.page("en", self.posts[-1]["slug"])
        self.assertNotIn('rel="next"', newest)
        self.assertIn('rel="prev"', newest)
        self.assertNotIn('rel="prev"', oldest)
        self.assertIn('rel="next"', oldest)

    def test_related_is_the_latest_three_other_posts_in_the_same_language(self):
        for i, p in enumerate(self.posts):
            skip = {p["slug"]} | {self.posts[j]["slug"] for j in (i - 1, i + 1) if 0 <= j < len(self.posts)}
            for c in build_site.BLOG_CODES:
                want = ["%s%s/" % (build_site.journal_path(c), q["slug"]) for q in self.posts if q["slug"] not in skip][:3]
                got = self.hrefs(self.page(c, p["slug"]), "post-related")
                self.assertEqual(got, want, "%s/%s" % (c, p["slug"]))
                adj = self.hrefs(self.page(c, p["slug"]), "post-adj")
                self.assertFalse(set(got) & set(adj), "%s/%s related repeats previous/next" % (c, p["slug"]))
                self.assertNotIn("/blog/%s/" % p["slug"], "".join(got))
        self.assertEqual(len(self.hrefs(self.page("en", self.posts[0]["slug"]), "post-related")), min(3, len(self.posts) - 2))

    def test_labels_and_titles_are_in_the_page_language(self):
        loc = build_site.load_locales(ROOT)
        for c in build_site.BLOG_CODES:
            page = self.page(c, self.posts[1]["slug"])
            for k in ("post_prev", "post_next", "post_related"):
                self.assertIn(loc[c][k], page, "%s %s" % (c, k))
            self.assertIn('<span class="adj-title">%s</span>' % build_site.esc(self.posts[0]["langs"][c]["title"]), page)  # posts[0] is the next post of posts[1]
            self.assertIn(">%s</a>" % build_site.esc(self.posts[3]["langs"][c]["title"]), page)  # posts[3] is the first related link of posts[1]
        self.assertNotEqual(loc["ko"]["post_prev"], loc["en"]["post_prev"])  # translated, not the English fallback

    def test_block_sits_between_cta_and_post_foot(self):
        t = self.page("en", self.posts[1]["slug"])
        self.assertLess(t.index('class="post-cta"'), t.index('class="post-adj"'))
        self.assertLess(t.index('class="post-related"'), t.index('class="post-foot"'))
        self.assertEqual(t.count('class="post-related"'), 1)

    def test_css_wraps_long_titles_and_stacks_on_small_screens(self):
        css = (ROOT / "assets" / "site.css").read_text(encoding="utf-8")
        self.assertRegex(css, r"\.post-adj\{display:flex;flex-direction:column")  # one column below 640px
        self.assertRegex(css, r"\.post-adj \.adj-title\{[^}]*overflow-wrap:anywhere")
        self.assertRegex(css, r"\.post-related a\{[^}]*overflow-wrap:anywhere")
        self.assertRegex(css, r"\.post-adj a\{[^}]*min-width:0")
        self.assertRegex(css, r"@media \(min-width:640px\)\{\.post-adj\{flex-direction:row")  # row only on wide screens


class PostMoreLinksSmall(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        shutil.copytree(ROOT / "locales", self.dir / "locales")
        for n in ("src", "assets", "content", "vendor"):
            if (ROOT / n).is_dir():
                shutil.copytree(ROOT / n, self.dir / n)
        for n in ("llms.txt", "og-image.png"):
            shutil.copy(ROOT / n, self.dir / n)

    def test_single_post_has_no_extra_links(self):
        write_post(self.dir, "a-post", extra="published: 2026-10-01T09:09:45+09:00\n")
        t = build_site.build(self.dir)["ko/journal/a-post/index.html"]
        self.assertNotIn("post-adj", t)
        self.assertNotIn("post-related", t)

    def test_two_posts_link_each_other_only(self):
        write_post(self.dir, "a-post", extra="published: 2026-10-01T09:09:45+09:00\n")
        write_post(self.dir, "b-post", extra="published: 2026-10-01T10:30:00+09:00\n")
        f = build_site.build(self.dir)
        a, b = f["journal/a-post/index.html"], f["journal/b-post/index.html"]
        self.assertIn('rel="next" href="/journal/b-post/"', a)
        self.assertNotIn('rel="prev"', a)
        self.assertIn('rel="prev" href="/journal/a-post/"', b)
        self.assertNotIn('rel="next"', b)
        self.assertEqual(PostMoreLinks.hrefs(a, "post-related"), [])  # the only other post is already the next link
        self.assertNotIn("post-related", a)

    def test_three_posts_related_fills_with_next_latest(self):
        for n, t in (("a-post", "09:00:00"), ("b-post", "10:00:00"), ("c-post", "11:00:00"), ("d-post", "12:00:00")):
            write_post(self.dir, n, extra="published: 2026-10-01T%s+09:00\n" % t)
        b = build_site.build(self.dir)["journal/b-post/index.html"]  # prev a, next c -> only d is left
        self.assertEqual(PostMoreLinks.hrefs(b, "post-adj"), ["/journal/a-post/", "/journal/c-post/"])
        self.assertEqual(PostMoreLinks.hrefs(b, "post-related"), ["/journal/d-post/"])

    def test_draft_posts_are_never_linked(self):
        write_post(self.dir, "a-post", extra="published: 2026-10-01T09:09:45+09:00\n")
        write_post(self.dir, "z-draft", extra="draft: true\n")
        self.assertNotIn("z-draft", build_site.build(self.dir)["journal/a-post/index.html"])


class DescriptionLimit(unittest.TestCase):
    def test_too_long_post_description_fails_the_build(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            shutil.copytree(ROOT / "locales", d / "locales")
            for n in ("src", "assets", "content", "vendor"):
                shutil.copytree(ROOT / n, d / n)
            for n in ("llms.txt", "og-image.png"):
                shutil.copy(ROOT / n, d / n)
            write_post(d, "a-post", extra="published: 2026-10-01T09:09:45+09:00\n")
            f = d / "posts" / "a-post" / "en.md"
            f.write_text(f.read_text(encoding="utf-8").replace("description: d en", "description: " + "x" * 161), encoding="utf-8")
            with self.assertRaises(build_site.BuildError) as cm:
                build_site.build(d)
            self.assertIn("a-post/en: description is", str(cm.exception))


if __name__ == "__main__":
    unittest.main()
