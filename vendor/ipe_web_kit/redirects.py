"""지원 종료 언어 주소 → 새 언어 주소 리다이렉트(정적 호스팅용 페이지 + 서버 규칙) — v0.7.0.

사이트가 `/<lang>/<경로>` 를 쓰는데 지원을 끝낸 언어(pt·zh·ar·hi·ru)의 옛 주소가 404 가 되는 것을 막는다.
연결 규칙(Davy 확정): pt→pt-BR · zh→zh-Hant · ar·hi·ru→en. 하위 경로는 유지한다. 영어가 루트(`/<경로>`)인 사이트는 en_root=True.

- 리다이렉트 페이지 = meta refresh + `rel=canonical`(새 주소) + `noindex,follow` + 눈에 보이는 이동 링크(자바스크립트 없음).
- sitemap·hreflang 에는 넣지 않는다 — 이 모듈은 둘 다 만들지 않고, `sitemap_leaks()` 로 새어 나갔는지 검사한다.
- 서버 리다이렉트를 쓸 수 있는 호스팅(Firebase 등)이면 `firebase_redirects()` 의 301 규칙을 같이 쓴다(페이지와 병행해도 된다).
- 사이트별 덮어쓰기: `overrides={"ru": "ko"}`(연결 대상 바꿈) · `overrides={"hi": None}`(그 언어는 만들지 않음).
"""
import re
from pathlib import Path
from urllib.parse import quote

from . import languages
from .seo import esc

# 옛(지원 종료) 언어 → 새 언어. 값이 "en" 이면 사이트의 영어 경로 규칙(en_root)을 따른다.
LEGACY_REDIRECTS = {"pt": "pt-BR", "zh": "zh-Hant", "ar": "en", "hi": "en", "ru": "en"}

_LANG = re.compile(r"^[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8})*$")


def _norm_path(path):
    """사이트 경로 → 앞 `/` 없고 `..`·`//` 없는 글자(`journal/x/` · 루트는 빈 글자). 쿼리·해시는 버린다."""
    p = str(path or "").split("#", 1)[0].split("?", 1)[0].strip().lstrip("/")
    if "\\" in p or any(seg in ("..", ".") for seg in p.split("/")):
        raise ValueError("bad path: %r" % (path,))
    return re.sub(r"/{2,}", "/", p)


def _mapping(overrides=None):
    """기본 규칙 + 사이트 덮어쓰기. 키는 서비스 중인 언어(languages.SUPPORTED)면 거부(살아 있는 주소를 덮지 못하게),
    대상은 SUPPORTED 에 있어야 한다. 값 None = 그 옛 언어는 만들지 않는다."""
    m = dict(LEGACY_REDIRECTS)
    for k, v in (overrides or {}).items():
        if not isinstance(k, str) or not _LANG.fullmatch(k) or k in languages.SUPPORTED:
            raise ValueError("bad or supported source lang: %r" % (k,))
        if v is None:
            m.pop(k, None)
            continue
        if v not in languages.SUPPORTED:
            raise ValueError("target lang not in SUPPORTED: %r" % (v,))
        m[k] = v
    return m


def target_path(old_lang, path="", en_root=False, overrides=None):
    """옛 언어 + 하위 경로 → 새 주소의 경로(`/pt-BR/journal/x/` · 영어 루트면 `/journal/x/`). 대상 없으면 None."""
    new = _mapping(overrides).get(old_lang)
    if new is None:
        return None
    rest = _norm_path(path)
    if new == "en" and en_root:
        return "/" + rest
    return "/%s/%s" % (new, rest)


def old_path(old_lang, path=""):
    return "/%s/%s" % (old_lang, _norm_path(path))


def redirect_page(new_url, lang="en", label=None, title=None):
    """리다이렉트 한 장 — 새 주소 new_url(절대 URL 권장). 스크립트·외부 파일 없이 혼자 돈다(375px·320px 에서도 한 줄씩 줄바꿈).

    canonical 은 새 주소, robots 는 noindex,follow. 화면에는 이동 링크가 보인다(refresh 가 막힌 환경 대비)."""
    u = esc(new_url)
    label = label or new_url
    title = title or "Redirecting…"
    return (
        '<!doctype html>\n<html lang="%s">\n<head>\n<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        '<title>%s</title>\n'
        '<meta name="robots" content="noindex,follow">\n'
        '<link rel="canonical" href="%s">\n'
        '<meta http-equiv="refresh" content="0; url=%s">\n'
        '<style>body{margin:0;padding:24px 16px;font:16px/1.6 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;'
        'color:#1a1a1a;background:#fff;text-align:center;overflow-wrap:anywhere}'
        'a{color:#2f5d50}@media(prefers-color-scheme:dark){body{color:#ececec;background:#111214}a{color:#8cc7b4}}</style>\n'
        '</head>\n<body>\n<p><a href="%s">%s</a></p>\n</body>\n</html>\n'
        % (esc(lang), esc(title), u, u, u, esc(label))
    )


def generate(paths, base_url, en_root=False, overrides=None, langs=None, available=None):
    """옛 언어 페이지 생성 — {출력 파일 경로: HTML}.

    paths: 사이트의 새 언어(영어) 쪽 경로들(언어 접두 없이: `""`(홈) · `journal/x/` …). 끝이 `/` 가 아니고 `.html` 같은 파일이면 그대로 쓴다.
    base_url: `https://site.ipe.rest`(끝 `/` 무관). langs: 만들 옛 언어(기본 전부). available(lang, path)→bool: 새 언어에 그 페이지가
    없으면 영어로 보낸다(예: pt-BR 에 없는 글). 출력 경로는 `ru/journal/x/index.html`(디렉터리형) 또는 파일형 그대로."""
    base = str(base_url).rstrip("/")
    m = _mapping(overrides)
    out = {}
    for lang in (langs or list(m)):
        if lang not in m:
            continue
        for raw in paths:
            rest = _norm_path(raw)
            new = m[lang]
            if new != "en" and available is not None and not available(new, rest):
                new = "en"
            if new == "en" and en_root:
                dest = "/" + rest
            else:
                dest = "/%s/%s" % (new, rest)
            url = base + quote(dest, safe="/%:@+~-._")
            fname = rest + "index.html" if (rest == "" or rest.endswith("/")) else rest
            out["%s/%s" % (lang, fname)] = redirect_page(url, lang=new)
    for key in out:  # `a`(파일)와 `a/`(폴더) 가 같이 오면 한 경로가 파일이자 폴더가 된다
        if any(o.startswith(key + "/") for o in out):
            raise ValueError("path conflict (file vs directory): %r" % (key,))
    return out


def write(out_dir, paths, base_url, **kw):
    """generate() 결과를 out_dir 아래에 쓴다 → 쓴 파일 상대경로 목록(정렬)."""
    root = Path(out_dir)
    done = []
    for rel, html in generate(paths, base_url, **kw).items():
        f = root / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(html, encoding="utf-8")
        done.append(rel)
    return sorted(done)


def firebase_redirects(overrides=None, en_root=False, permanent=True, unavailable=None):
    """firebase.json `hosting.redirects` 에 넣을 규칙 — 하위 경로 유지. 영어 루트면 `/ru` → `/`, `/ru/:path*` → `/:path*`.

    unavailable: `[(새 언어, 경로), …]` — 그 새 언어(pt-BR·zh-Hant)에 없는 글. 와일드카드 규칙 앞에 영어로 가는 개별 규칙을 둔다
    (`generate(available=…)` 의 영어 대체와 같다). 이걸 안 주면 와일드카드가 없는 글로 보내 404 가 난다 —
    available 대체를 쓰는 사이트는 **이 규칙을 쓰지 않거나 unavailable 을 같이 준다**(서버 규칙이 페이지보다 먼저 맞는다)."""
    code = 301 if permanent else 302
    rules = []
    m = _mapping(overrides)
    for old, new in m.items():
        if new == "en":
            continue
        for lang, path in (unavailable or ()):
            if lang != new:
                continue
            rest = _norm_path(path)
            if re.search(r"[*:{}]", rest):
                raise ValueError("bad firebase path: %r" % (path,))
            dest = "/" + rest if en_root else "/en/" + rest
            rules.append({"source": "/%s/%s" % (old, rest.rstrip("/")) if rest.rstrip("/") else "/%s" % old,
                          "destination": dest, "type": code})
    for old, new in m.items():
        if new == "en" and en_root:
            rules.append({"source": "/%s" % old, "destination": "/", "type": code})
            rules.append({"source": "/%s/:path*" % old, "destination": "/:path*", "type": code})
        else:
            rules.append({"source": "/%s" % old, "destination": "/%s" % new, "type": code})
            rules.append({"source": "/%s/:path*" % old, "destination": "/%s/:path*" % new, "type": code})
    return rules


def sitemap_leaks(sitemap_xml, overrides=None):
    """sitemap(또는 hreflang 이 든 HTML) 글자 안의 옛 언어 주소(`/ru/…`) 목록 — 비어 있어야 한다.
    호스트 바로 뒤 첫 경로 조각만 본다(`/en/journal/ru/` 같은 정상 주소는 잡지 않는다)."""
    langs = "|".join(re.escape(k) for k in _mapping(overrides))
    pat = re.compile(r"https?://[^/\s<>\"']+/(?:%s)(?:[/?#][^\s<>\"']*)?(?=[<\s\"']|$)" % langs)
    return [m.group(0) for m in pat.finditer(sitemap_xml)]
