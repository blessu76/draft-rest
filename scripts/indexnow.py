#!/usr/bin/env python3
"""Notify IndexNow (Bing, Naver, Yandex, ...) about new or changed URLs.

Run AFTER the site is published (the key file must already be live):

    python3 scripts/indexnow.py                 # every <loc> in sitemap.xml
    python3 scripts/indexnow.py URL [URL ...]   # only these URLs
    python3 scripts/indexnow.py --changed-today # only URLs whose sitemap <lastmod> is today (KST) + sitemap.xml
    python3 scripts/indexnow.py --dry-run       # print the payload, send nothing

--changed-today is what the deploy workflow runs after every deploy. It sends nothing when no page changed today.
A network problem is reported (exit 1) instead of raising, so a caller can treat it as a warning.

The key is the repo-root file named <32 hex>.txt whose single line is the key
itself. It is a public file (not a secret). Standard library only.
"""
import argparse
import datetime as dt
import json
import re
import sys
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent.parent
ENDPOINT = "https://api.indexnow.org/indexnow"
KEY_FILE_RE = re.compile(r"^([0-9a-f]{32})\.txt$")
NS = "{http://www.sitemaps.org/schemas/sitemap/0.9}"
LOC_TAG = NS + "loc"
KST = dt.timezone(dt.timedelta(hours=9))


def find_key(root):
    """Return the key whose <key>.txt file in `root` contains exactly that key."""
    for p in sorted(Path(root).iterdir()):
        m = KEY_FILE_RE.match(p.name)
        if m and p.read_text(encoding="utf-8").strip() == m.group(1):
            return m.group(1)
    raise SystemExit("no IndexNow key file (<32 hex>.txt containing its own name) in " + str(root))


def sitemap_urls(sitemap_path):
    """All <loc> values of a sitemap (xhtml:link alternates are not included)."""
    tree = ET.parse(sitemap_path)
    urls = [e.text.strip() for e in tree.iter(LOC_TAG) if e.text and e.text.strip()]
    return list(dict.fromkeys(urls))


def today_kst(now=None):
    return (now or dt.datetime.now(KST)).astimezone(KST).date()


def lastmod_day(value):
    """KST calendar day of a sitemap <lastmod> (a date, or a datetime with offset); None when it cannot be read."""
    value = (value or "").strip()
    try:
        if "T" not in value:
            return dt.date.fromisoformat(value)
        when = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if when.tzinfo is None:
        return when.date()
    return when.astimezone(KST).date()


def changed_urls(sitemap_path, day):
    """<loc> values whose <lastmod> falls on `day` (KST), plus the sitemap's own URL (hosts must agree, so it is derived from the first <loc>)."""
    tree = ET.parse(sitemap_path)
    urls = []
    for u in tree.getroot().iter(NS + "url"):
        loc, mod = u.find(LOC_TAG), u.find(NS + "lastmod")
        if loc is not None and loc.text and mod is not None and lastmod_day(mod.text) == day:
            urls.append(loc.text.strip())
    urls = list(dict.fromkeys(urls))
    if not urls:
        return []
    parts = urlsplit(urls[0])
    return urls + ["%s://%s/sitemap.xml" % (parts.scheme, parts.netloc)]


def build_payload(key, urls):
    if not urls:
        raise SystemExit("no URLs to submit")
    hosts = {urlsplit(u).netloc for u in urls}
    if len(hosts) != 1 or "" in hosts:
        raise SystemExit("all URLs must share one host, got: " + ", ".join(sorted(hosts)))
    host = hosts.pop()
    return {
        "host": host,
        "key": key,
        "keyLocation": "https://%s/%s.txt" % (host, key),
        "urlList": list(urls),
    }


def send(payload, endpoint=ENDPOINT, timeout=30):
    req = urllib.request.Request(
        endpoint,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status
    except urllib.error.HTTPError as e:
        return e.code
    except (urllib.error.URLError, OSError, ValueError) as e:  # DNS, refused, timeout, TLS ... (TimeoutError is an OSError)
        print("IndexNow: network error: %s" % e, file=sys.stderr)
        return None


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("urls", nargs="*", help="URLs to submit (default: every <loc> in sitemap.xml)")
    ap.add_argument("--root", default=str(ROOT), help="site root (default: this repo)")
    ap.add_argument("--changed-today", action="store_true",
                    help="submit only URLs whose sitemap <lastmod> is today (KST) plus sitemap.xml; nothing when none changed")
    ap.add_argument("--date", metavar="YYYY-MM-DD", help="with --changed-today: use this KST day instead of today")
    ap.add_argument("--dry-run", action="store_true", help="print the payload, send nothing")
    a = ap.parse_args(argv)

    root = Path(a.root)
    if a.changed_today:
        if a.urls:
            raise SystemExit("--changed-today cannot be combined with explicit URLs")
        day = dt.date.fromisoformat(a.date) if a.date else today_kst()
        urls = changed_urls(root / "sitemap.xml", day)
        if not urls:
            print("IndexNow: no page has lastmod %s (KST) - nothing to submit" % day.isoformat())
            return 0
    else:
        urls = a.urls or sitemap_urls(root / "sitemap.xml")
    payload = build_payload(find_key(root), urls)
    if a.dry_run:
        print("POST " + ENDPOINT)
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return 0
    status = send(payload)
    if status is None:
        print("IndexNow %s: not sent (%d URLs)" % (payload["host"], len(urls)), file=sys.stderr)
        return 1
    print("IndexNow %s: HTTP %d (%d URLs)" % (payload["host"], status, len(urls)))
    if status in (200, 202):
        return 0
    print("200/202 = ok; 403 = key file not live yet / key mismatch; 422 = URL host mismatch; 429 = too many requests", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
