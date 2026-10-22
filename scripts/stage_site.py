#!/usr/bin/env python3
"""Copy only the public files into an output directory (default _site/) — what GitHub Pages serves.

    python3 scripts/stage_site.py [--root DIR] [--out DIR]

Whitelist: root files (index.html, 404.html, CNAME, .nojekyll, robots.txt, sitemap.xml, llms.txt, og-image.png,
the IndexNow key file <32 hex>.txt), assets/, the language folders (en ko ja zh es pt id ru vi fr de) and the English content-page folders (faq about privacy).
Everything else (scripts/ tests/ posts/ locales/ src/ .github/ manuscripts, STATUS.md, ...) stays out.
Standard library only.
"""
import argparse
import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from build_site import CODES, PAGES  # noqa: E402

ROOT_FILES = ("index.html", "404.html", "CNAME", ".nojekyll", "robots.txt", "sitemap.xml", "llms.txt", "og-image.png")
KEY_RE = re.compile(r"^[0-9a-f]{32}\.txt$")
# inside language folders only generated site files are public (never a stray .md)
PUBLIC_EXT = {".html", ".xml"}


def public_files(root):
    root = Path(root)
    out = [Path(n) for n in ROOT_FILES if (root / n).is_file()]
    out += [Path(p.name) for p in root.iterdir() if p.is_file() and KEY_RE.match(p.name)]
    if (root / "assets").is_dir():
        out += [f.relative_to(root) for f in sorted((root / "assets").rglob("*")) if f.is_file()]
    for c in list(CODES) + list(PAGES):  # PAGES = the English faq/about/privacy folders at the root
        d = root / c
        if d.is_dir():
            out += [f.relative_to(root) for f in sorted(d.rglob("*")) if f.is_file() and f.suffix in PUBLIC_EXT]
    return sorted(set(out))


def stage(root, out):
    out = Path(out)
    if out.exists():
        shutil.rmtree(out)
    files = public_files(root)
    for rel in files:
        dst = out / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(Path(root) / rel, dst)
    return files


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", default=str(ROOT))
    ap.add_argument("--out", default=str(ROOT / "_site"))
    a = ap.parse_args(argv)
    files = stage(a.root, a.out)
    print("stage_site: %d public file(s) -> %s" % (len(files), a.out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
