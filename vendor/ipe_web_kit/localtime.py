"""ipe-localtime — 게시 시각(KST)을 보는 기기 시간대로 바꿔 보이는 인라인 스크립트.

assets/ipe-localtime.js 는 ipe-rest/shared/ipe-localtime.js v2 와 바이트가 같다(웹들이 이미 쓰는 CSP 해시가 그대로 맞는다).
삽입 규칙(ipe-rest/shared/README.md): `<script>` + 파일 바이트 전체 + `</script>` — 사이에 줄바꿈·공백을 더하지 않는다.
"""
import base64
import hashlib
import html

from . import ASSETS

LOCALTIME_JS = ASSETS / "ipe-localtime.js"
LOCALTIME_SHA256 = "57326449ddf5050eabadd1394d69eb2b0f61c88f084ec83ee4aff6fcad0f74b8"  # v2 (ipe-rest c466827)
MARKER = " data-ipe-time"


def source():
    """파일 바이트 그대로(utf-8). 해시가 정본과 다르면 멈춘다 — 사본을 고친 것이다."""
    raw = LOCALTIME_JS.read_bytes()
    if hashlib.sha256(raw).hexdigest() != LOCALTIME_SHA256:
        raise ValueError("ipe-localtime.js bytes changed (sha256 mismatch) — never edit the kit copy")
    return raw.decode("utf-8")


def script_tag():
    return "<script>" + source() + "</script>"


def csp_hash():
    """CSP script-src 에 넣을 값 — `'sha256-…'`."""
    return "'sha256-%s'" % base64.b64encode(hashlib.sha256(LOCALTIME_JS.read_bytes()).digest()).decode("ascii")


def with_localtime(page):
    """`<time data-ipe-time>` 가 있는 페이지면 마지막 </body> 바로 앞에 스크립트를 넣는다. 없으면 그대로. 이미 들어 있으면 그대로."""
    if MARKER not in page or source() in page:
        return page
    i = page.rfind("</body>")
    if i == -1:
        raise ValueError("no </body> to put ipe-localtime before")
    return page[:i] + script_tag() + "\n" + page[i:]


def time_tag(when, text=None):
    """`<time data-ipe-time datetime="2026-11-06T17:35+09:00">2026-11-06 17:35 KST</time>` — when 은 aware datetime.

    정적 글자는 KST 로 적고(스크립트가 없거나 실패해도 읽힌다), datetime 은 분까지 +09:00 오프셋.
    """
    if when.tzinfo is None:
        raise ValueError("time_tag needs an aware datetime")
    from .seo import KST

    k = when.astimezone(KST)
    iso = k.strftime("%Y-%m-%dT%H:%M") + "+09:00"
    shown = text if text is not None else k.strftime("%Y-%m-%d %H:%M KST")
    return '<time data-ipe-time datetime="%s">%s</time>' % (iso, html.escape(shown, quote=False))
