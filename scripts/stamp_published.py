#!/usr/bin/env python3
"""Stamp the real publish time on a post — run it in the publish step, right before the commit that is pushed to main.

    python3 scripts/stamp_published.py <slug> [--at 2026-10-24T16:00:00+09:00]

Sets `date` (KST day) and `published` (KST, e.g. 2026-10-24T16:00:00+09:00) in all 11 language files of
posts/<slug>/ to the same value (default: now). Never pre-stamp a planned time — if the push slips, re-run it.
Then: python3 scripts/build_site.py && python3 scripts/build_site.py --check && python3 scripts/check_sitemap.py
"""
import argparse
import datetime as dt
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
KST = dt.timezone(dt.timedelta(hours=9))


def stamp(root, slug, when):
    files = sorted((Path(root) / "posts" / slug).rglob("*.md"))
    if not files:
        raise SystemExit("no posts/%s/*.md" % slug)
    iso = when.isoformat(timespec="seconds")
    for f in files:
        t = f.read_text(encoding="utf-8")
        end = t.find("\n---", 4)
        head, rest = t[:end], t[end:]
        head = re.sub(r"^(date|published):.*\n?", "", head, flags=re.M)
        head = head.rstrip("\n") + "\ndate: %s\npublished: %s" % (when.date().isoformat(), iso)
        f.write_text(head + rest, encoding="utf-8")
    return len(files), iso


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("slug")
    ap.add_argument("--at", help="ISO time with offset (default: now)")
    a = ap.parse_args(argv)
    when = dt.datetime.fromisoformat(a.at) if a.at else dt.datetime.now(KST)
    if when.tzinfo is None:
        sys.exit("--at needs an offset, e.g. +09:00")
    n, iso = stamp(ROOT, a.slug, when.astimezone(KST).replace(second=0, microsecond=0))
    print("stamp_published: %s -> %s (%d files)" % (a.slug, iso, n))


if __name__ == "__main__":
    main()
