"""킷 UI 조각 — 마크업은 여기서, 모양은 assets/ipe-kit.css 가 `--ipe-*` 토큰으로만 그린다(theme.py).

웹은 CSS 를 두 방법 중 하나로 싣는다:
- inline_css()  → `<style id="ipe-kit">…</style>`(작다 · 캐시 걱정 없음 · CSP 가 style-src 를 막는 웹은 못 쓴다)
- copy_css(dir) → `<dir>/ipe-kit.css` 로 복사하고 `?v=<킷 버전>-<내용 해시 8>` 붙은 href 를 돌려준다(캐시버스팅)
"""
import hashlib
import shutil
from pathlib import Path

from . import ASSET_REV, ASSETS
from .localtime import time_tag
from .seo import esc

CSS = ASSETS / "ipe-kit.css"
STUDIO_URL = "https://ipe.rest/"


def css_text():
    return CSS.read_text(encoding="utf-8")


def inline_css():
    return '<style id="ipe-kit">%s</style>' % css_text()


def css_version():
    return "%s-%s" % (ASSET_REV, hashlib.sha256(CSS.read_bytes()).hexdigest()[:8])


def copy_css(dest_dir, url_prefix="/assets/"):
    dest = Path(dest_dir) / CSS.name
    dest.parent.mkdir(parents=True, exist_ok=True)
    if not dest.exists() or dest.read_bytes() != CSS.read_bytes():
        shutil.copyfile(CSS, dest)
    return "%s%s?v=%s" % (url_prefix, CSS.name, css_version())


def studio_line(label="an ipe studio app", year=None, version=None, release_url=None, studio="ipe studio"):
    """푸터 아래 회사 서명 줄 — `© 2026 ipe studio · an ipe studio app · v1.0.0 (73)`.

    version 은 version.AppVersion. release_url 이 있으면 버전 글자가 그 주소(앵커 포함)로 간다.
    글자(label · studio)는 웹이 번역해 넘긴다. year 가 None 이면 © 부분을 빼고 studio 링크만.
    """
    head = '<a href="%s">%s</a>' % (STUDIO_URL, esc(studio))
    parts = ['<span class="ipe-studio__org">%s%s</span>' % ("© %d " % int(year) if year else "", head)]
    if label:
        parts.append('<span class="ipe-studio__label">%s</span>' % esc(label))
    if version is not None and version.version:
        text = "v" + version.label
        ver = ('<a class="ipe-studio__ver" href="%s">%s</a>' % (esc(release_url), esc(text)) if release_url
               else '<span class="ipe-studio__ver">%s</span>' % esc(text))
        parts.append(ver)
    sep = '<span class="ipe-studio__sep" aria-hidden="true">·</span>'
    return '<p class="ipe-studio" dir="ltr">%s</p>' % sep.join(parts)


def release_card(version, at, items, legacy_build_id=True, strict=False):
    """릴리스 노트 카드 하나 — id 는 ipe_kit 앵커 규칙(`1.0.0-73`), 머리는 화면 글자(`1.0.0 (73)`).

    at 은 aware datetime(게시 시각 · ipe-localtime 이 보는 기기 시간대로 바꾼다). items 는 이미 escape 된 HTML 줄이 아니라
    평문 목록이다(여기서 escape). legacy_build_id 면 옛 링크(`#b73`)용 빈 span 을 함께 둔다(iltonggi 웹이 이미 쓰는 모양).
    """
    anchor = version.anchor(strict)
    if anchor is None:
        raise ValueError("release_card needs a version (and a build when strict)")
    legacy = '<span id="b%s"></span>' % esc(version.build) if legacy_build_id and version.build else ""
    lis = "\n".join("    <li>%s</li>" % esc(t) for t in items)
    return ('<article class="ipe-rel" id="%s">%s\n'
            '  <h2 class="ipe-rel__head"><span class="ipe-rel__build">%s</span></h2>\n'
            '  <p class="ipe-rel__at">%s</p>\n'
            '  <ul>\n%s\n  </ul>\n'
            '</article>' % (esc(anchor), legacy, esc(version.label), time_tag(at), lis))
