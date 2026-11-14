"""저널 글 12개 언어판 헬퍼 — hreflang · sitemap · JSON-LD BlogPosting · 발행 검사 (v0.7.2).

글 하나 = 언어판 dict: {lang: {"url", "title", "copy_review": "iris", "copy_review_date": "2026-11-14", ...}}.
12개(languages.SUPPORTED) 언어판이 모두 있고 각각 Iris 카피 검수(copy_review=iris + 날짜)가 있어야 발행 대상이다.

    problems = journal.check_post(editions)          # [] 이면 발행 가능
    journal.assert_publishable(posts)                # {slug: editions} — 하나라도 문제면 ValueError(check 실패용)
    journal.hreflang_links(editions)                 # <head> 의 alternate 줄(+ x-default = en)
    journal.sitemap_entry(editions, lastmod=…)       # 언어판마다 <url> + xhtml:link 12개
    journal.blogposting(editions, "ko", …)           # inLanguage 가 들어간 BlogPosting dict → seo.jsonld_script
"""
import re

from . import languages
from .seo import alternate_links, esc

REVIEWER = "iris"
RTL = ()   # SUPPORTED 에 RTL 언어 없음 — 생기면 여기에 넣는다


def dir_for(lang):
    """dir 속성 훅 — 지금은 전부 ltr."""
    return "rtl" if lang in RTL else "ltr"


def check_post(editions):
    """발행 못 하는 이유 목록(빈 목록 = 발행 가능)."""
    out = []
    for l in editions:
        if l not in languages.SUPPORTED:
            out.append("지원 언어가 아님: %s" % l)
    for l in languages.SUPPORTED:
        e = editions.get(l)
        if not e:
            out.append("언어판 없음: %s" % l)
            continue
        if not e.get("url"):
            out.append("url 없음: %s" % l)
        if str(e.get("copy_review") or "").lower() != REVIEWER:
            out.append("copy_review 가 %s 아님: %s" % (REVIEWER, l))
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(e.get("copy_review_date") or "")):
            out.append("copy_review_date 없음/형식 오류: %s" % l)
    return out


def is_publishable(editions):
    return not check_post(editions)


def publishable(posts):
    """{slug: editions} 에서 발행 가능한 것만."""
    return {s: e for s, e in posts.items() if is_publishable(e)}


def assert_publishable(posts):
    """발행하려는 글에 문제가 있으면 한꺼번에 ValueError(사이트 check 스크립트가 실패하게)."""
    bad = ["%s: %s" % (s, "; ".join(check_post(e))) for s, e in posts.items() if check_post(e)]
    if bad:
        raise ValueError("12개 언어·카피 검수가 안 갖춰진 글:\n" + "\n".join(bad))


def _ordered(editions):
    return [(l, editions[l]["url"]) for l in languages.SUPPORTED if l in editions]


def hreflang_links(editions, x_default="en"):
    """`<head>` 용 alternate 줄 — SUPPORTED 순서, x-default 는 x_default 언어판 주소(없으면 생략)."""
    xd = editions.get(x_default, {}).get("url") if x_default else None
    return alternate_links(_ordered(editions), x_default=xd)


def sitemap_entry(editions, lastmod=None, x_default="en"):
    """언어판마다 `<url>` 하나 — 각각 모든 언어판을 xhtml:link 로 가리킨다(urlset 에 xmlns:xhtml 필요)."""
    links = ["<xhtml:link rel=\"alternate\" hreflang=\"%s\" href=\"%s\"/>" % (esc(l), esc(u)) for l, u in _ordered(editions)]
    if x_default and x_default in editions:
        links.append('<xhtml:link rel="alternate" hreflang="x-default" href="%s"/>' % esc(editions[x_default]["url"]))
    out = []
    for l, u in _ordered(editions):
        out.append("<url><loc>%s</loc>%s%s</url>" % (esc(u), "<lastmod>%s</lastmod>" % esc(lastmod) if lastmod else "", "".join(links)))
    return "\n".join(out)


def blogposting(editions, lang, date_published=None, date_modified=None, description=None, author=None, publisher=None, image=None):
    """BlogPosting JSON-LD dict — inLanguage = lang(BCP47), 같은 글의 다른 언어판은 workTranslation 이 아니라 hreflang 이 맡는다."""
    if lang not in languages.SUPPORTED:
        raise ValueError("unsupported lang: %r" % (lang,))
    e = editions[lang]
    obj = {"@context": "https://schema.org", "@type": "BlogPosting", "inLanguage": languages.hreflang(lang),
           "headline": e["title"], "url": e["url"], "mainEntityOfPage": e["url"]}
    for k, v in (("datePublished", date_published), ("dateModified", date_modified), ("description", description),
                 ("author", author), ("publisher", publisher), ("image", image)):
        if v:
            obj[k] = v
    return obj
