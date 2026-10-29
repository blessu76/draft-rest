#!/usr/bin/env python3
"""Publish a queued post: drop `draft: true` from all language files and stamp the real publish time.

    python3 scripts/publish_post.py <slug> [--at 2026-10-24T16:00:00+09:00]
    then: python3 scripts/build_site.py && python3 scripts/build_site.py --check && python3 scripts/check_sitemap.py && python3 -m unittest discover -s tests

Sets `date` (KST day) and `published` (KST, e.g. 2026-10-24T16:00:00+09:00) in every language file — default: now (KST).
Run it right before the commit that is pushed to main; if the push slips, re-run scripts/stamp_published.py.
Validates every file first and writes nothing if any file is bad. A future time is refused.

After publishing it prints SEO warnings (never an error, the exit code stays 0): body shorter than the target (latin/cyrillic
400 words, CJK ko/ja/zh 800 characters without spaces), rendered <title> longer than 60 (CJK 40) characters, description longer
than 160 (CJK 110), and a title that another post already uses in the same language. A body below the FLOOR (300 words; ja/zh
600 characters) additionally prints a loud banner - the post is still published (a length problem must never drop the 16:00 post);
scripts/check_queue.py is where a floor breach is an error (before the post goes into the queue). A shared image is NOT warned
about: there is no per-post image yet (follow-up P1-2).
"""
import argparse
import datetime as dt
import re
import sys
import unicodedata
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_site  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
KST = dt.timezone(dt.timedelta(hours=9))

CJK_LANGS = ("ko", "ja", "zh")  # no word spaces: size is counted in characters, and the title/description limits are tighter
# Body length (Davy 2026-10-29): target = warning, floor = error for NEW posts (check_queue.py) but only a banner at publish time.
# latin = words (en es pt id ru vi fr de); cjk = characters without whitespace (ko ja zh). ko's floor is build_site.KO_BODY_MIN (raw chars).
BODY_TARGET = {"latin": 400, "cjk": 800}
BODY_FLOOR = {"latin": 300, "cjk": 600}
TITLE_MAX = {"latin": 60, "cjk": 40}  # rendered <title>
DESC_MAX = {"latin": 160, "cjk": 110}


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


def _kind(lang):
    return "cjk" if lang in CJK_LANGS else "latin"


def visible_text(body):
    """Markdown body -> the text a reader sees: no fenced code blocks, images, link URLs (the link text stays), HTML tags,
    heading / quote / list markers (incl. '1.' numbers), horizontal rules or emphasis marks. (build_site.markdown()/word_count() are
    not reused: the build keeps code blocks and counts punctuation differently; the length lint wants the prose only.)"""
    lines, in_code = [], False
    for line in body.split("\n"):
        st = line.strip()
        if st.startswith("```"):
            in_code = not in_code
            continue
        if in_code or re.match(r"^(-{3,}|\*{3,}|_{3,})$", st):
            continue
        st = re.sub(r"^(>\s*)+", "", st)
        st = re.sub(r"^(#{1,6}\s+|[-*+]\s+|\d+[.)]\s+)", "", st)
        lines.append(st)
    t = "\n".join(lines)
    t = re.sub(r"!\[[^\]]*\]\([^)]*\)", " ", t)
    t = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", t)
    t = re.sub(r"<[^>]+>", " ", t)
    return t.replace("*", "").replace("`", "")


def body_size(body, lang):
    """(count, unit) of the visible text (see visible_text): characters without whitespace for ko/ja/zh, else words
    (tokens without a letter or digit, like a stray '-' or '&', do not count)."""
    text = visible_text(body)
    if lang in CJK_LANGS:
        return len(re.sub(r"\s", "", text)), "chars"
    return sum(1 for t in text.split() if any(unicodedata.category(ch)[0] in "LN" for ch in t)), "words"


class FloorWarning(str):
    """A below-the-floor message (a plain str otherwise): is_floor_warning() tells floor from target by type, not by wording."""


def body_length_findings(slug, langs):
    """(floor_msgs, target_msgs) for {lang: parsed post file}. Below the floor -> floor_msgs (FloorWarning); floor <= n < target -> target_msgs.
    ko has no floor here (build_site.KO_BODY_MIN, an error in the build, owns it) - only the 800-character target."""
    floor, target = [], []
    for lang, m in sorted(langs.items()):
        n, unit = body_size(m["_body"], lang)
        kind = _kind(lang)
        where = "%s/%s" % (slug, lang)
        if lang != "ko" and n < BODY_FLOOR[kind]:
            floor.append(FloorWarning("%s: body is %d %s (< %d floor)" % (where, n, unit, BODY_FLOOR[kind])))
        elif n < BODY_TARGET[kind]:
            target.append("%s: body is %d %s (< %d target)" % (where, n, unit, BODY_TARGET[kind]))
    return floor, target


def is_floor_warning(w):
    return isinstance(w, FloorWarning)


def _norm_title(t):
    return " ".join(t.casefold().split())


def lint_post(root, slug):
    """SEO warnings for one post folder (list of strings, empty = fine). Warning only: never raises for a bad file, never blocks publishing."""
    base = Path(root) / "posts"
    warnings, mine = [], {}
    for f in post_files(root, slug):
        lang = f.stem
        try:
            mine[lang] = build_site.parse_post_file(f)
        except ValueError as ex:
            warnings.append("%s/%s: cannot lint (%s)" % (slug, lang, ex))
    others = {}  # lang -> {normalised title: other slug}
    for d in sorted(x for x in base.iterdir() if x.is_dir() and x.name != slug):
        for f in post_files(root, d.name):
            try:
                others.setdefault(f.stem, {}).setdefault(_norm_title(build_site.parse_post_file(f)["title"]), d.name)
            except ValueError:
                pass
    floor, target = body_length_findings(slug, mine)
    warnings.extend(floor + target)
    for lang, m in sorted(mine.items()):
        where = "%s/%s" % (slug, lang)
        shown = build_site.post_title(m["title"])
        if len(shown) > TITLE_MAX[_kind(lang)]:
            warnings.append("%s: <title> is %d chars (> %d): %r" % (where, len(shown), TITLE_MAX[_kind(lang)], shown))
        if len(m["description"]) > DESC_MAX[_kind(lang)]:
            warnings.append("%s: description is %d chars (> %d)" % (where, len(m["description"]), DESC_MAX[_kind(lang)]))
        twin = others.get(lang, {}).get(_norm_title(m["title"]))
        if twin:
            warnings.append("%s: title is identical to the %s title of post %r" % (where, lang, twin))
    return warnings


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
    try:
        warns = lint_post(a.root, a.slug)
    except Exception as ex:  # lint is advisory: the post is already published, so nothing here may change the exit code
        print("publish_post: WARN lint skipped (%s: %s)" % (type(ex).__name__, ex), file=sys.stderr)
        return 0
    for w in warns:
        print("publish_post: WARN " + w, file=sys.stderr)
    try:
        below = [w for w in warns if is_floor_warning(w)]
        if below:
            print("publish_post: !!! LENGTH FLOOR: %d file(s) below the minimum body length - published anyway, expand within 24h" % len(below), file=sys.stderr)
            for w in below:
                print("publish_post: !!!   " + w, file=sys.stderr)
    except Exception as ex:  # the banner is advisory too
        print("publish_post: WARN length banner skipped (%s: %s)" % (type(ex).__name__, ex), file=sys.stderr)
    if warns:
        print("publish_post: %d SEO warning(s) - the post is published anyway (warnings never fail)" % len(warns), file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
