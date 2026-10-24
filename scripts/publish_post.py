#!/usr/bin/env python3
"""Publish a queued post: drop `draft: true` from all language files and stamp the real publish time.

    python3 scripts/publish_post.py <slug> [--at 2026-10-24T16:00:00+09:00]
    then: python3 scripts/build_site.py && python3 scripts/build_site.py --check && python3 scripts/check_sitemap.py && python3 -m unittest discover -s tests

Sets `date` (KST day) and `published` (KST, e.g. 2026-10-24T16:00:00+09:00) in every language file — default: now (KST).
Run it right before the commit that is pushed to main; if the push slips, re-run scripts/stamp_published.py.
Validates every file first and writes nothing if any file is bad. A future time is refused.
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


def rewrite(text, when):
    """New text of one post file (draft flag removed, date + published set) or ValueError — never writes."""
    text = text.replace("\r\n", "\n")
    if not text.startswith("---\n"):
        raise ValueError("bad front matter (must start with ---)")
    head, sep, rest = text[4:].partition("\n---")
    if not sep:
        raise ValueError("front matter is not closed with ---")
    if not re.search(r"^date:.*$", head, flags=re.M):
        raise ValueError("no `date:` line in front matter")
    head = re.sub(r"^(draft|published):.*\n?", "", head, flags=re.M)
    head = re.sub(r"^date:.*$", "date: " + when.date().isoformat(), head, flags=re.M)
    head = head.rstrip("\n") + "\npublished: " + when.isoformat(timespec="seconds")
    return "---\n" + head + "\n---" + rest


def publish(root, slug, when=None):
    """Validate every language file first; write only if all of them are fine (no partial publish)."""
    when = (when or dt.datetime.now(KST)).astimezone(KST).replace(second=0, microsecond=0)
    files = post_files(root, slug)
    if not files:
        raise SystemExit("no files for slug %r under posts/" % slug)
    if when > dt.datetime.now(KST) + dt.timedelta(minutes=1):
        raise SystemExit("--at %s is in the future (stamp the real publish time)" % when.isoformat())
    new, errors = {}, []
    for f in files:
        try:
            new[f] = rewrite(f.read_text(encoding="utf-8"), when)
        except ValueError as ex:
            errors.append("%s: %s" % (f, ex))
    if errors:
        raise SystemExit("publish_post: nothing written\n  " + "\n  ".join(errors))
    for f, text in new.items():
        f.write_text(text, encoding="utf-8")
    return files, when.isoformat(timespec="seconds")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("slug")
    ap.add_argument("--at", help="ISO time with offset (default: now, KST)")
    ap.add_argument("--root", default=str(ROOT))
    a = ap.parse_args(argv)
    when = dt.datetime.fromisoformat(a.at) if a.at else None
    if when is not None and when.tzinfo is None:
        raise SystemExit("--at needs an offset, e.g. +09:00")
    files, iso = publish(a.root, a.slug, when)
    print("publish_post: %s -> %d files, published %s, draft flag removed" % (a.slug, len(files), iso))
    return 0


if __name__ == "__main__":
    sys.exit(main())
