#!/usr/bin/env python3
"""Validate sitemap.xml / robots.txt / llms.txt against the built pages — stdlib only.

    python3 scripts/check_sitemap.py [--root DIR]

Checks: well-formed XML · every <loc> is a canonical https://draft.ipe.rest/ URL with no ?query ·
the page file exists, its <link rel=canonical> equals <loc> and its hreflang links equal the sitemap alternates ·
hreflang clusters are reciprocal and contain x-default · lastmod is a real past date ·
robots.txt names the sitemap · llms.txt links every sitemap page.
Exit 0 = ok, 1 = problems (listed).
"""
import argparse
import datetime as dt
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

SITE = "https://draft.ipe.rest"
NS = {"s": "http://www.sitemaps.org/schemas/sitemap/0.9", "x": "http://www.w3.org/1999/xhtml"}
HREFLANG_RE = re.compile(r"^(x-default|[a-z]{2,3}(-[A-Za-z0-9]{2,8})?)$")
LINK_RE = re.compile(r"<link\b[^>]*>", re.I)


def attrs(tag):
    return dict(re.findall(r'([\w:-]+)="([^"]*)"', tag))


def url_to_file(root, url):
    path = url[len(SITE):]
    if path.endswith("/"):
        path += "index.html"
    return Path(root) / path.lstrip("/")


def page_links(text):
    canonical, alts = None, {}
    for tag in LINK_RE.findall(text):
        a = attrs(tag)
        if a.get("rel") == "canonical":
            canonical = a.get("href")
        elif a.get("rel") == "alternate" and a.get("hreflang"):
            alts[a["hreflang"]] = a.get("href")
    return canonical, alts


def check(root):
    root = Path(root)
    errs = []
    try:
        tree = ET.parse(root / "sitemap.xml")
    except (ET.ParseError, OSError) as ex:
        return ["sitemap.xml: %s" % ex]
    now = dt.datetime.now(dt.timezone(dt.timedelta(hours=9)))
    today = now.date()
    entries = {}
    for u in tree.getroot().findall("s:url", NS):
        loc = (u.findtext("s:loc", "", NS) or "").strip()
        if loc in entries:
            errs.append("duplicate <loc> %s" % loc)
        lastmod = (u.findtext("s:lastmod", "", NS) or "").strip()
        alts = {}
        for l in u.findall("x:link", NS):
            if l.get("rel") == "alternate":
                alts[l.get("hreflang")] = l.get("href")
        entries[loc] = (lastmod, alts)
    if not entries:
        errs.append("sitemap.xml has no <url>")
    for loc, (lastmod, alts) in entries.items():
        if not loc.startswith(SITE + "/") or "?" in loc or "#" in loc:
            errs.append("%s: loc must be a clean %s/ URL (no query/fragment)" % (loc, SITE))
            continue
        try:
            if len(lastmod) == 10:
                future = dt.date.fromisoformat(lastmod) > today
            else:  # W3C datetime with an explicit offset, e.g. 2026-10-24T16:00:00+09:00
                w = dt.datetime.fromisoformat(lastmod)
                if w.tzinfo is None:
                    raise ValueError(lastmod)
                future = w > now
            if future:
                errs.append("%s: lastmod %s is in the future" % (loc, lastmod))
        except ValueError:
            errs.append("%s: lastmod missing or not YYYY-MM-DD / YYYY-MM-DDTHH:MM:SS+09:00: %r" % (loc, lastmod))
        f = url_to_file(root, loc)
        if not f.is_file():
            errs.append("%s: file not found (%s)" % (loc, f.relative_to(root) if root in f.parents else f))
            continue
        page_text = f.read_text(encoding="utf-8")
        if re.search(r'<meta name="robots" content="[^"]*noindex', page_text):
            errs.append("%s: is noindex but listed in the sitemap" % loc)
        canonical, page_alts = page_links(page_text)
        if canonical != loc:
            errs.append("%s: page canonical is %r" % (loc, canonical))
        if alts:
            for h in alts:
                if not HREFLANG_RE.match(h or ""):
                    errs.append("%s: bad hreflang %r" % (loc, h))
            if "x-default" not in alts:
                errs.append("%s: alternates lack x-default" % loc)
            if loc not in alts.values():
                errs.append("%s: alternates do not include the page itself" % loc)
            for h, href in alts.items():
                if "?" in (href or ""):
                    errs.append("%s: alternate %s has a query string: %s" % (loc, h, href))
                other = entries.get(href)
                if other is None:
                    errs.append("%s: alternate %s -> %s is not in the sitemap" % (loc, h, href))
                elif other[1] != alts:
                    errs.append("%s: alternates are not reciprocal with %s" % (loc, href))
            if page_alts != alts:
                errs.append("%s: page hreflang links differ from sitemap alternates" % loc)
    robots = (root / "robots.txt")
    if not robots.is_file() or ("Sitemap: " + SITE + "/sitemap.xml") not in robots.read_text(encoding="utf-8"):
        errs.append("robots.txt must contain 'Sitemap: %s/sitemap.xml'" % SITE)
    llms = (root / "llms.txt")
    if llms.is_file():
        text = llms.read_text(encoding="utf-8")
        for loc in entries:
            if "(%s)" % loc not in text:
                errs.append("llms.txt does not link %s" % loc)
    else:
        errs.append("llms.txt missing")
    return errs


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", default=str(Path(__file__).resolve().parent.parent))
    a = ap.parse_args(argv)
    errs = check(a.root)
    if errs:
        print("check_sitemap: %d problem(s)\n  " % len(errs) + "\n  ".join(errs), file=sys.stderr)
        return 1
    n = len(ET.parse(Path(a.root) / "sitemap.xml").getroot().findall("s:url", NS))
    print("check_sitemap: OK — %d URL(s)" % n)
    return 0


if __name__ == "__main__":
    sys.exit(main())
