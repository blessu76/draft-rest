"""SEO 공통 — escape · 회사 Organization JSON-LD · meta description 자르기 · hreflang alternate.

규칙은 웹들이 이미 쓰는 것 그대로다(still-rest site_common.meta_desc · 5개 웹의 ORG @id · hreflang + x-default).
"""
import datetime as dt
import html
import json
import re

KST = dt.timezone(dt.timedelta(hours=9))

ORG_ID = "https://ipe.rest/#organization"
ORG_LOGO = {"@type": "ImageObject", "url": "https://ipe.rest/icon-512.png", "width": 512, "height": 512}
ORG = {"@type": "Organization", "@id": ORG_ID, "name": "ipe()", "url": "https://ipe.rest/", "logo": ORG_LOGO}

META_DESC_MAX = 160
_SENTENCE_END = re.compile(r"[.!?。！？](?=\s|$)|[。！？]")


def esc(s):
    return html.escape(str(s), quote=True)


def org_ref():
    """다른 JSON-LD 안에서 회사를 가리킬 때(publisher · author) — `{"@id": ORG_ID}`."""
    return {"@id": ORG_ID}


def org_jsonld():
    """페이지에 한 번 싣는 Organization 전체(@context 포함)."""
    return dict({"@context": "https://schema.org"}, **ORG)


def jsonld_script(obj):
    """`<script type="application/ld+json">…</script>` — `</` 를 `<\\/` 로 바꿔 본문이 script 를 닫지 못하게."""
    body = json.dumps(obj, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    return '<script type="application/ld+json">%s</script>' % body


def iso_kst(when):
    """JSON-LD datePublished · dateModified — `2026-11-06T17:35:00+09:00`(aware datetime 만)."""
    if when.tzinfo is None:
        raise ValueError("iso_kst needs an aware datetime")
    return when.astimezone(KST).replace(microsecond=0).isoformat()


def meta_desc(text, limit=META_DESC_MAX):
    """<meta name=description> / og:description / twitter:description 글자: limit 글자 이하, 문장 경계에서 자른다
    (들어가는 만큼의 온전한 문장들). 쓸 만한 문장 경계가 없으면 마지막 낱말 경계 + 말줄임표. 짧으면 그대로.
    보이는 요약 · JSON-LD · RSS 는 이것을 쓰지 않고 전체 글자를 쓴다."""
    text = " ".join(str(text).split())
    if len(text) <= limit:
        return text
    cut = 0
    for m in _SENTENCE_END.finditer(text):
        if m.end() <= limit:
            cut = m.end()
    if cut >= limit // 2:
        return text[:cut].rstrip()
    head = text[:limit - 1]
    sp = head.rfind(" ")
    if sp >= limit // 2:
        head = head[:sp]
    return head.rstrip(" ,;:—–-、，") + "…"


def alternate_links(urls, x_default=None):
    """`<link rel="alternate" hreflang=…>` 줄들 — urls 는 (언어, 주소) 의 순서 있는 목록 또는 dict. x_default 가 있으면 마지막에.
    같은 언어가 두 번 오면 거절한다(검색엔진이 둘 다 버린다)."""
    pairs = list(urls.items()) if isinstance(urls, dict) else list(urls)
    seen = set()
    out = []
    for lang, url in pairs:
        if lang in seen or lang == "x-default":
            raise ValueError("duplicate or reserved hreflang: %r" % lang)
        seen.add(lang)
        out.append('<link rel="alternate" hreflang="%s" href="%s">' % (esc(lang), esc(url)))
    if x_default:
        out.append('<link rel="alternate" hreflang="x-default" href="%s">' % esc(x_default))
    return "\n".join(out)
