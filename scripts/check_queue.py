#!/usr/bin/env python3
"""Check queued (draft) posts BEFORE they go into the queue — the same limits the build enforces at publish time.

    python3 scripts/check_queue.py              # every post under posts/ that is a draft
    python3 scripts/check_queue.py <slug> ...   # only those slugs (draft or not)

For each post: all 11 languages present, front matter parses, slug == folder name, `draft` identical in all files,
`date:` line present (publish_post.py needs it), no `published` stamp on a draft, description <= build_site.DESC_MAX,
ko body inside build_site.KO_BODY_MIN..MAX, and publish_post.rewrite() accepts every file. The length rules come from
build_site.length_problems(), so this check and the build can never disagree. Body length (publish_post.BODY_FLOOR/BODY_TARGET):
below the floor (latin 300 words, ja/zh 600 chars) is an ERROR, below the target (400 words / 800 chars, ko too) is a WARN line
and does not change the exit code. Exit 1 when anything is wrong. The build itself does not check these (published posts may be short).
"""
import argparse
import datetime as dt
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_site  # noqa: E402
import publish_post  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent


def check_post(post_dir):
    """-> list of problems for one posts/<slug>/ folder (empty = ready to queue / publish)."""
    name = Path(post_dir).name
    errors, langs = [], {}
    for c in build_site.CODES:
        f = Path(post_dir) / (c + ".md" if c in ("ko", "en") else "translations/%s.md" % c)
        if not f.is_file():
            errors.append("%s: missing language file %s" % (name, c))
            continue
        try:
            m = build_site.parse_post_file(f)
            publish_post.rewrite(f.read_text(encoding="utf-8"), dt.datetime.now(publish_post.KST))
        except ValueError as ex:
            errors.append("%s/%s: %s" % (name, c, ex))
            continue
        if m["slug"] != name:
            errors.append("%s/%s: slug %r must equal the folder name" % (name, c, m["slug"]))
        langs[c] = m
    if not langs:
        return errors
    if len({m["draft"] for m in langs.values()}) > 1:
        errors.append("%s: `draft` differs between languages" % name)
    if len({m["date"] for m in langs.values()}) > 1:
        errors.append("%s: `date` differs between languages" % name)
    for c, m in langs.items():
        if m["draft"] and m.get("published"):
            errors.append("%s/%s: a draft must not carry `published` (publish_post.py stamps it at publish time)" % (name, c))
    return errors + build_site.length_problems(name, langs) + publish_post.body_length_findings(name, langs)[0]


def post_warnings(post_dir):
    """-> body-below-target warnings for one posts/<slug>/ folder (unreadable files are skipped: check_post reports them)."""
    name, langs = Path(post_dir).name, {}
    for c in build_site.CODES:
        f = Path(post_dir) / (c + ".md" if c in ("ko", "en") else "translations/%s.md" % c)
        try:
            langs[c] = build_site.parse_post_file(f)
        except (ValueError, OSError):
            pass
    return publish_post.body_length_findings(name, langs)[1]


def check_queue(root, slugs=None):
    checked, errors, _ = scan(root, slugs)
    return checked, errors


def scan(root, slugs=None):
    """-> (checked slugs, errors, warnings). Without slugs only queued drafts are scanned; naming slugs explicitly also checks
    already published posts against the floor (verify mode)."""
    base = Path(root) / "posts"
    dirs = [base / s for s in slugs] if slugs else sorted(d for d in base.iterdir() if d.is_dir())
    errors, checked, warnings = [], [], []
    for d in dirs:
        if not d.is_dir():
            errors.append("%s: no such post folder" % d.name)
            continue
        if not slugs:
            ko = d / "ko.md"
            try:
                if not (ko.is_file() and build_site.parse_post_file(ko)["draft"]):
                    continue
            except ValueError:
                pass  # broken ko.md: let check_post report it
        checked.append(d.name)
        errors.extend(check_post(d))
        warnings.extend(post_warnings(d))
    return checked, errors, warnings


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("slugs", nargs="*")
    ap.add_argument("--root", default=str(ROOT))
    a = ap.parse_args(argv)
    checked, errors, warnings = scan(a.root, a.slugs)
    for w in warnings:
        print("check_queue: WARN " + w)
    if errors:
        print("check_queue: %d problem(s)" % len(errors))
        for e in errors:
            print("  " + e)
        return 1
    print("check_queue: OK — %d queued post(s): %s" % (len(checked), ", ".join(checked) or "none"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
