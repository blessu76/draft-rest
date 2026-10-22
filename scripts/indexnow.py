#!/usr/bin/env python3
"""Notify IndexNow (Bing, Naver, Yandex, ...) about new or changed URLs.

Run AFTER the site is published (the key file must already be live):

    python3 scripts/indexnow.py                 # every <loc> in sitemap.xml
    python3 scripts/indexnow.py URL [URL ...]   # only these URLs
    python3 scripts/indexnow.py --dry-run       # print the payload, send nothing

The key is the repo-root file named <32 hex>.txt whose single line is the key
itself. It is a public file (not a secret). Standard library only.
"""
import argparse
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
LOC_TAG = "{http://www.sitemaps.org/schemas/sitemap/0.9}loc"


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


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("urls", nargs="*", help="URLs to submit (default: every <loc> in sitemap.xml)")
    ap.add_argument("--root", default=str(ROOT), help="site root (default: this repo)")
    ap.add_argument("--dry-run", action="store_true", help="print the payload, send nothing")
    a = ap.parse_args(argv)

    root = Path(a.root)
    urls = a.urls or sitemap_urls(root / "sitemap.xml")
    payload = build_payload(find_key(root), urls)
    if a.dry_run:
        print("POST " + ENDPOINT)
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return 0
    status = send(payload)
    print("IndexNow %s: HTTP %d (%d URLs)" % (payload["host"], status, len(urls)))
    if status in (200, 202):
        return 0
    print("200/202 = ok; 403 = key file not live yet / key mismatch; 422 = URL host mismatch; 429 = too many requests", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
