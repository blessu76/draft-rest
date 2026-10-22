#!/usr/bin/env python3
"""Publish a queued post: drop `draft: true` from all language files and (optionally) set the date.

    python3 scripts/publish_post.py <slug> [--date YYYY-MM-DD]
    then: python3 scripts/build_site.py && python3 scripts/check_sitemap.py && python3 -m unittest discover -s tests

Date defaults to today (KST). It must not be in the future (check_sitemap rejects future lastmod).
"""
import argparse
import datetime as dt
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
KST = dt.timezone(dt.timedelta(hours=9))


def post_files(root, slug):
    d = Path(root) / "posts" / slug
    return [f for f in [d / "ko.md", d / "en.md"] + sorted((d / "translations").glob("*.md")) if f.is_file()]


def rewrite(f, text, date):
    """Return the new text of one post file (draft flag removed, date set) or raise ValueError — never writes."""
    text = text.replace("\r\n", "\n")
    if not text.startswith("---\n"):
        raise ValueError("bad front matter (must start with ---)")
    head, sep, rest = text[4:].partition("\n---")
    if not sep:
        raise ValueError("front matter is not closed with ---")
    if not re.search(r"^date:.*$", head, flags=re.M):
        raise ValueError("no `date:` line in front matter")
    head = re.sub(r"^draft:.*\n?", "", head, flags=re.M)
    head = re.sub(r"^date:.*$", "date: " + date, head, flags=re.M)
    return "---\n" + head.rstrip("\n") + "\n---" + rest


def publish(root, slug, date):
    """Validate every language file first; write only if all of them are fine (no partial publish)."""
    files = post_files(root, slug)
    if not files:
        raise SystemExit("no files for slug %r under posts/" % slug)
    try:
        dt.date.fromisoformat(date)
    except ValueError:
        raise SystemExit("--date must be YYYY-MM-DD, got %r" % date)
    if dt.date.fromisoformat(date) > dt.datetime.now(KST).date():
        raise SystemExit("--date %s is in the future (check_sitemap rejects future lastmod)" % date)
    new, errors = {}, []
    for f in files:
        try:
            new[f] = rewrite(f, f.read_text(encoding="utf-8"), date)
        except ValueError as ex:
            errors.append("%s: %s" % (f, ex))
    if errors:
        raise SystemExit("publish_post: nothing written\n  " + "\n  ".join(errors))
    for f, text in new.items():
        f.write_text(text, encoding="utf-8")
    return files


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("slug")
    ap.add_argument("--date", default=dt.datetime.now(KST).date().isoformat())
    ap.add_argument("--root", default=str(ROOT))
    a = ap.parse_args(argv)
    files = publish(a.root, a.slug, a.date)
    print("publish_post: %s -> %d files, date %s, draft flag removed" % (a.slug, len(files), a.date))
    return 0


if __name__ == "__main__":
    sys.exit(main())
