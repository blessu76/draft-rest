"""상단 언어 선택(select) 공통 컴포넌트 + 브라우저 언어 감지 JS — v0.7.2.

모든 *.ipe.rest 웹이 같은 마크업·CSS·감지 규칙을 쓴다. 언어 목록은 languages.SUPPORTED(12개)만.

    from ipe_web_kit import langswitch
    sel = langswitch.select_html("ko", lambda l: "/%s/journal/" % l)   # <header> 안에 넣는다(햄버거 안 X)
    head_css = langswitch.CSS                                           # 또는 ipe-kit.css(같은 규칙 포함)
    root_script = langswitch.script(hrefs, redirect=True)               # 루트(x-default) 진입 페이지에만 redirect=True
    langswitch.copy_assets("out/assets")                                # ipe-lang.js 복사 → {"js": "/assets/ipe-lang.js?v=…"}

JS 파일은 생성물이다: python3 -m ipe_web_kit.langswitch js > ipe_web_kit/assets/ipe-lang.js (시험이 커밋본과 대조).
"""
import hashlib
import json
import shutil
import sys

from . import ASSETS, languages
from .seo import esc

JS = ASSETS / "ipe-lang.js"
SELECT_ID = "ipe-lang-select"
KEY = "ipe_lang"   # localStorage — 사용자가 고른 값(감지보다 우선)

LABEL = {"en": "Language", "ko": "언어", "ja": "言語", "zh-Hant": "語言", "es": "Idioma", "pt-BR": "Idioma", "fr": "Langue",
         "de": "Sprache", "id": "Bahasa", "th": "ภาษา", "vi": "Ngôn ngữ", "tr": "Dil"}
RTL = ()   # SUPPORTED 에 RTL 언어 없음 — 생기면 여기에 넣는다(dir_for 훅)

CSS = (".ipe-lang{display:inline-flex;align-items:center;max-width:100%;font-family:var(--ipe-font-sans,system-ui,sans-serif);font-size:.8125rem}"
       ".ipe-lang__label{position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0 0 0 0);white-space:nowrap}"
       ".ipe-lang__select{max-width:100%;min-height:44px;padding:0 8px;font:inherit;color:var(--ipe-text,#1a1a1a);"
       "background:var(--ipe-bg,#fff);border:1px solid var(--ipe-line,#e3e3df);border-radius:var(--ipe-radius,12px)}"
       ".ipe-lang__links{display:flex;flex-wrap:wrap;gap:4px 10px}.ipe-lang__links a{color:var(--ipe-muted,#6b6b6b)}"
       ".ipe-lang__links a[aria-current]{color:var(--ipe-text,#1a1a1a);font-weight:600}")


def dir_for(lang):
    return "rtl" if lang in RTL else "ltr"


def _name(l):
    """자기 언어 이름 — SUPPORTED 밖(옛 privacy 설정의 zh·ru 같은 코드)은 코드 그대로."""
    return languages.NAMES.get(l, l)


def select_html(lang, href, langs=None):
    """언어 select 한 덩어리. href(l) = 그 언어의 같은 페이지 주소. 고르면 localStorage 에 저장하고 이동한다.
    JS 없으면 <noscript> 안 링크 목록. 라벨은 눈에 안 보이게(스크린리더용) — 좁은 화면에서 자리를 아낀다."""
    langs = list(languages.SUPPORTED if langs is None else langs)
    if lang not in langs:
        raise ValueError("current lang %r not in langs" % (lang,))
    label = esc(LABEL.get(lang, "Language"))
    opts = "".join('<option value="%s" lang="%s"%s>%s</option>' % (esc(href(l)), l, " selected" if l == lang else "", esc(_name(l)))
                   for l in langs)
    links = "".join('<a href="%s" hreflang="%s"%s>%s</a>' % (esc(href(l)), l, ' aria-current="page"' if l == lang else "", esc(_name(l)))
                    for l in langs)
    onchange = ("var o=this.options[this.selectedIndex];try{localStorage.setItem('%s',o.lang)}catch(e){}"
                "if(o.value)location.href=o.value" % KEY)
    return ('<div class="ipe-lang"><label class="ipe-lang__label" for="%s">%s</label>'
            '<select class="ipe-lang__select" id="%s" aria-label="%s" onchange="%s">%s</select>'
            '<noscript><nav class="ipe-lang__links" aria-label="%s">%s</nav></noscript></div>'
            % (SELECT_ID, label, SELECT_ID, label, esc(onchange), opts, label, links))


# ---- 브라우저 언어 감지 JS ----

def js_text():
    """assets/ipe-lang.js 의 정본. 규칙은 languages.resolve / resolve_accept_language 와 같다(시험이 node 로 표를 대조)."""
    return ("/* ipe-lang.js · ipe_web_kit.langswitch — 생성 파일(python3 -m ipe_web_kit.langswitch js). 손으로 고치지 않는다. */\n"
            "(function (root) {\n"
            "  'use strict';\n"
            "  var SUPPORTED = %s;\n"
            "  var DEFAULT = %s;\n"
            "  var ALIASES = %s;\n"
            "  var ZH_HANT_REGIONS = %s;\n"
            "  var KEY = %s;\n"
            "  var BOT = /bot|crawl|spider|slurp|bingpreview|facebookexternalhit|lighthouse|pagespeed|preview/i;\n"
            "  function split(tag) { return String(tag == null ? '' : tag).trim().toLowerCase().split(/[-_]/).filter(Boolean); }\n"
            "  function zhHant(rest) {\n"
            "    var script = null, region = null, i, p;\n"
            "    for (i = 0; i < rest.length; i++) { p = rest[i]; if (script === null && p.length === 4 && /^[a-z]+$/.test(p)) script = p; }\n"
            "    for (i = 0; i < rest.length; i++) { p = rest[i]; if (region === null && p.length === 2 && /^[a-z]+$/.test(p)) region = p; }\n"
            "    return script === 'hant' || (script === null && ZH_HANT_REGIONS.indexOf(region) >= 0);\n"
            "  }\n"
            "  function resolve(tag) {\n"
            "    var parts = split(tag), code, rest, i;\n"
            "    if (!parts.length) return DEFAULT;\n"
            "    code = Object.prototype.hasOwnProperty.call(ALIASES, parts[0]) ? ALIASES[parts[0]] : parts[0];\n"
            "    rest = parts.slice(1);\n"
            "    if (code === 'zh') return zhHant(rest) ? 'zh-Hant' : DEFAULT;\n"
            "    if (code === 'pt') return 'pt-BR';\n"
            "    for (i = 0; i < SUPPORTED.length; i++) if (SUPPORTED[i].toLowerCase() === code) return SUPPORTED[i];\n"
            "    return DEFAULT;\n"
            "  }\n"
            "  function pick(tags) {\n"
            "    var i, got;\n"
            "    for (i = 0; i < (tags || []).length; i++) {\n"
            "      got = resolve(tags[i]);\n"
            "      if (got !== DEFAULT || split(tags[i])[0] === 'en') return got;\n"
            "    }\n"
            "    return DEFAULT;\n"
            "  }\n"
            "  function stored() {\n"
            "    try { var v = root.localStorage.getItem(KEY); return v ? resolve(v) : null; } catch (e) { return null; }\n"
            "  }\n"
            "  function run() {\n"
            "    var tag = root.document && root.document.currentScript;\n"
            "    if (!tag || tag.getAttribute('data-redirect') === null) return;\n"
            "    var nav = root.navigator || {};\n"
            "    if (BOT.test(nav.userAgent || '')) return;\n"
            "    var sel = root.document.getElementById(%s);\n"
            "    if (!sel) return;\n"
            "    var want = stored() || pick(nav.languages && nav.languages.length ? nav.languages : [nav.language]);\n"
            "    var cur = sel.options[sel.selectedIndex], i;\n"
            "    if (cur && cur.lang === want) return;\n"
            "    for (i = 0; i < sel.options.length; i++) {\n"
            "      if (sel.options[i].lang === want && sel.options[i].value) { root.location.replace(sel.options[i].value); return; }\n"
            "    }\n"
            "  }\n"
            "  root.IpeLang = { resolve: resolve, pick: pick, stored: stored, SUPPORTED: SUPPORTED };\n"
            "  run();\n"
            "})(typeof window !== 'undefined' ? window : this);\n"
            % (json.dumps(list(languages.SUPPORTED)), json.dumps(languages.DEFAULT), json.dumps(languages._ALIASES, sort_keys=True),
               json.dumps(sorted(languages._ZH_HANT_REGIONS)), json.dumps(KEY), json.dumps(SELECT_ID)))


def asset_version():
    return "1-" + hashlib.sha256(JS.read_bytes()).hexdigest()[:8]


def copy_assets(dest_dir, url_prefix="/assets/"):
    """ipe-lang.js 를 복사하고 `?v=` 주소를 돌려준다."""
    from pathlib import Path
    dest = Path(dest_dir) / JS.name
    dest.parent.mkdir(parents=True, exist_ok=True)
    if not dest.exists() or dest.read_bytes() != JS.read_bytes():
        shutil.copyfile(JS, dest)
    return {"js": "%s%s?v=%s" % (url_prefix, JS.name, asset_version())}


def script(hrefs, redirect=False):
    """`<script>` 태그. redirect=True 는 루트(x-default) 진입 페이지에만 — 언어 경로 페이지에는 붙이지 않는다(루프 방지)."""
    return '<script src="%s"%s defer></script>' % (esc(hrefs["js"]), " data-redirect" if redirect else "")


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv == ["js"]:
        sys.stdout.write(js_text())
        return 0
    sys.stderr.write("usage: python3 -m ipe_web_kit.langswitch js\n")
    return 2


if __name__ == "__main__":
    sys.exit(main())
