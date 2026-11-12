"""GA4: one snippet in every generated page (head() is the single insertion point) and privacy / llms.txt text that matches it."""
import json
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import build_site  # noqa: E402

GA_ID = "G-XG4BH800J0"
OPTOUT = "https://tools.google.com/dlpage/gaoptout"


class Ga4(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.files = build_site.build(ROOT)
        cls.html = {k: v for k, v in cls.files.items() if k.endswith(".html")}

    def test_constant_is_the_ipe_rest_property(self):
        self.assertEqual(build_site.GA_MEASUREMENT_ID, GA_ID)

    def test_every_generated_page_has_the_snippet_exactly_once(self):
        self.assertGreater(len(self.html), 100)
        for rel, text in self.html.items():
            if rel == "en/index.html":  # instant redirect stub to / (noindex): the target page counts the visit
                self.assertNotIn(GA_ID, text)
                continue
            with self.subTest(rel):
                self.assertEqual(text.count(GA_ID), 1)
                self.assertEqual(text.count("googletagmanager.com/gtag/js?id="), 1)
                self.assertEqual(text.count("window.gtag('config',GA_ID)"), 1)
                self.assertLess(text.index(GA_ID), text.index("</head>"))

    def test_page_kinds_are_covered(self):
        for rel in ("index.html", "ko/index.html", "404.html", "about/index.html", "privacy/index.html", "de/privacy/index.html",
                    "ko/blog/index.html", "en/blog/blank-caption-box/index.html"):
            self.assertIn(rel, self.html)
            self.assertEqual(self.html[rel].count(GA_ID), 1, rel)

    def test_only_the_outbound_event_and_no_other_tracker(self):
        text = self.html["index.html"]
        self.assertEqual(re.findall(r"gtag\('event','(\w+)'", text), ["outbound_click"])
        self.assertNotIn("doubleclick", text)
        for rel in ("assets/site.js", "assets/site.css"):
            self.assertNotIn(GA_ID, (ROOT / rel).read_text(encoding="utf-8"))

    def test_privacy_website_section_matches_the_tracking(self):
        for c in build_site.privacy_codes():
            rel = "privacy/index.html" if c == "en" else "%s/privacy/index.html" % c
            with self.subTest(c):
                t = self.html[rel]
                self.assertIn("Google Analytics", t)
                self.assertIn("_ga", t)
                self.assertIn(OPTOUT, t)
                self.assertIn("Cloudflare", t)
                self.assertIn("2026-11-01", t)

    def test_app_sections_are_untouched(self):
        # the privacy page is shared with the app: only section 3 (the website) may mention the site's analytics
        for c in build_site.privacy_codes():
            sections = json.loads((ROOT / "content" / ("%s.json" % c)).read_text(encoding="utf-8"))["privacy"]["sections"]
            self.assertEqual(len(sections), 4, c)
            for i in (0, 1, 3):
                self.assertNotIn("Google Analytics", json.dumps(sections[i], ensure_ascii=False), c)
            self.assertIn("Google Analytics", json.dumps(sections[2], ensure_ascii=False), c)
        en = json.loads((ROOT / "content/en.json").read_text(encoding="utf-8"))["privacy"]["sections"][1]
        self.assertEqual(en["h"], "In the app: still being finalized")
        self.assertEqual(len(en["li"]), 6)

    def test_no_stale_no_cookies_claim(self):
        stale = re.compile(r"No cookies are set|쿠키를 설정하지 않습니다|Cookieは設定しません|不设置任何 Cookie|No se instalan cookies|"
                           r"Nenhum cookie é definido|Tidak ada cookie yang dipasang|Файлы cookie не устанавливаются|"
                           r"Không đặt cookie nào|Aucun cookie n’est déposé|Es werden keine Cookies gesetzt")
        for rel, t in self.html.items():
            if rel.endswith("privacy/index.html"):
                with self.subTest(rel):
                    self.assertIsNone(stale.search(t))

    def test_llms_txt_mentions_website_analytics(self):
        text = (ROOT / "llms.txt").read_text(encoding="utf-8")
        self.assertIn("Google Analytics", text)


if __name__ == "__main__":
    unittest.main()
