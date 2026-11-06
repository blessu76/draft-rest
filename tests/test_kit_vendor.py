"""Web kit (vendor/ipe_web_kit) — the copy is untouched, pinned to a tag, and wired into the build."""
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import build_site  # noqa: E402
from ipe_web_kit import __version__ as KIT_VERSION, ui  # noqa: E402  (build_site puts vendor/ on sys.path)


class KitVendor(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.files = build_site.build(ROOT)

    def test_vendor_copy_is_unmodified(self):
        r = subprocess.run([sys.executable, str(ROOT / "vendor" / "ipe_web_kit" / "vendor.py"), "verify", str(ROOT)],
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_pinned_tag(self):
        stamp = (ROOT / "vendor" / "ipe_web_kit" / "KIT_VERSION").read_text(encoding="utf-8").split()
        self.assertEqual(stamp[0], "v" + KIT_VERSION)
        self.assertRegex(stamp[1], r"^[0-9a-f]{40}$")

    def test_imports_come_from_vendor(self):
        self.assertTrue(Path(ui.__file__).resolve().is_relative_to(ROOT / "vendor") if hasattr(Path, "is_relative_to")
                        else str(Path(ui.__file__).resolve()).startswith(str((ROOT / "vendor").resolve())))

    def test_indexnow_module_not_adopted(self):
        # kit v0.1.0 indexnow has no --changed-today (the deploy workflow runs it), so scripts/indexnow.py stays the web's own
        src = (ROOT / "scripts" / "indexnow.py").read_text(encoding="utf-8")
        self.assertIn("--changed-today", src)
        self.assertNotIn("ipe_web_kit", src)

    def test_kit_css_is_generated_and_cache_busted(self):
        self.assertEqual(self.files[build_site.KIT_CSS], ui.css_text())
        href = '/%s?v=%s"' % (build_site.KIT_CSS, ui.css_version())
        for rel, text in self.files.items():
            if rel.endswith(".html") and "<head>" in text and 'http-equiv="refresh"' not in text:
                self.assertIn(href, text, rel)
                self.assertLess(text.index(href), text.index("/assets/site.css?v="), rel)  # site.css wins the cascade

    def test_footer_studio_line(self):
        home = self.files["ko/index.html"]
        self.assertIn('<p class="ipe-studio" dir="ltr"><span class="ipe-studio__org"><a href="https://ipe.rest/">an ipe studio app</a></span></p>', home)
        self.assertNotIn("foot-studio", home)
        blog = [t for r, t in self.files.items() if r.startswith("ja/blog/") and r.endswith("index.html")]
        self.assertTrue(blog)
        for t in blog:
            self.assertIn('class="ipe-studio"', t)

    def test_theme_maps_draft_tokens(self):
        css = (ROOT / "assets" / "site.css").read_text(encoding="utf-8")
        for decl in ("--ipe-accent:var(--gold-deep)", "--ipe-font-mono:var(--mono)", "--ipe-line:var(--line)"):
            self.assertIn(decl, css)


if __name__ == "__main__":
    unittest.main()
