#!/usr/bin/env python3
"""Pick a random KST publish time for a draft() journal post — stdlib only (Python 3.8+).

  python3 scripts/pick_publish_time.py 2026-11-15              # -> 2026-11-15 14:27
  python3 scripts/pick_publish_time.py 2026-11-14 --not-before 15:10

Window (KST): 12:00-17:59, one post a day (replaces the fixed 16:00 practice; modelled on still-rest's pick_publish_time.py).
Rules: never on :00 or :30 (round numbers look scheduled); never inside the clock hour the PREVIOUS day's post went out
(its `published:` time in posts/*/ko.md; none found -> no constraint); never inside an hour already used by a post on the
same day (a 16:00 post that is already live keeps 16:xx taken). `--not-before HH:MM` = pick at or after that time of day.
Output = `YYYY-MM-DD HH:MM`, then `python3 scripts/publish_post.py <slug> --at "<ISO>"` or publish at that time without --at.
Exit 1 when no time is left.
"""
import argparse
import datetime as dt
import random
import re
import sys
from pathlib import Path

KST = dt.timezone(dt.timedelta(hours=9))
WINDOW = (12 * 60, 17 * 60 + 59)  # minutes of the day, inclusive
AVOID_MINUTES = (0, 30)


def published_times(root):
    """-> [datetime (KST)] of every `published:` stamp in posts/<slug>/ko.md (drafts carry none)."""
    out = []
    for f in sorted((Path(root) / "posts").glob("*/ko.md")):
        try:
            head = f.read_text(encoding="utf-8").split("\n---", 1)[0]
            m = re.search(r"^published:\s*(\S+)", head, re.M)
            if m:
                out.append(dt.datetime.fromisoformat(m.group(1)).astimezone(KST))
        except (OSError, ValueError):
            continue
    return out


def hours_on(root, day):
    """clock hours (0-23) in which a post went out on `day` (datetime.date)."""
    return {w.hour for w in published_times(root) if w.date() == day}


def candidates(blocked_hours, not_before=None):
    lo = WINDOW[0] if not_before is None else max(WINDOW[0], not_before)
    return [m for m in range(lo, WINDOW[1] + 1) if m % 60 not in AVOID_MINUTES and m // 60 not in blocked_hours]


def pick(day, root=".", not_before=None, rng=None):
    """-> `YYYY-MM-DD HH:MM`. day = datetime.date; rng = random.Random (seed it in tests). ValueError when nothing is allowed."""
    rng = rng or random.SystemRandom()
    blocked = hours_on(root, day - dt.timedelta(days=1)) | hours_on(root, day)
    pool = candidates(blocked, not_before)
    if not pool:
        raise ValueError("no allowed time left in 12:00-17:59 (blocked hours %s, not-before=%s)" % (sorted(blocked), not_before))
    m = rng.choice(pool)
    return "%s %02d:%02d" % (day.isoformat(), m // 60, m % 60)


def parse_hhmm(s):
    m = re.fullmatch(r"(\d{1,2}):(\d{2})", s.strip())
    if not m or int(m.group(1)) > 23 or int(m.group(2)) > 59:
        raise argparse.ArgumentTypeError("HH:MM expected: %r" % s)
    return int(m.group(1)) * 60 + int(m.group(2))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0], formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("date", help="publication date YYYY-MM-DD (KST)")
    ap.add_argument("--not-before", type=parse_hhmm, metavar="HH:MM", help="pick at or after this time of day")
    ap.add_argument("--root", default=str(Path(__file__).resolve().parent.parent), help="site repo root (default: this repo)")
    ap.add_argument("--seed", type=int, help="fixed random seed (tests/debugging)")
    a = ap.parse_args(argv)
    try:
        print(pick(dt.date.fromisoformat(a.date), a.root, a.not_before, random.Random(a.seed) if a.seed is not None else None))
    except ValueError as ex:
        print("pick_publish_time: %s" % ex, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
