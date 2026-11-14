"""테마 토큰 — 킷 UI(assets/ipe-kit.css)는 `--ipe-*` CSS 변수만 본다. 웹이 넘기지 않은 토큰은 기본값.

    theme_style({"accent": "var(--gold)", "font-sans": "Inter, sans-serif"})
    -> '<style id="ipe-theme">:root{--ipe-accent:var(--gold);--ipe-font-sans:Inter, sans-serif}</style>'

웹의 기존 변수를 그대로 가리키게(`var(--gold)`) 넘기면 디자인이 웹을 따른다. 모르는 토큰 이름 · 위험한 값은 거절한다.
"""
import re

# 이름 -> (라이트 기본, 다크 기본). 기본은 라이트만 — 다크 기본은 웹이 <html data-ipe-scheme="auto"> (기기 따라) 또는
# data-ipe-scheme="dark" 로 고를 때만 쓴다(라이트 전용 웹에서 킷 조각만 어두워지지 않게). 웹이 넘긴 토큰은 언제나 이긴다(기본은 :where 로 0 명시도).
TOKENS = {
    "bg": ("#ffffff", "#111214"),
    "surface": ("#f6f6f4", "#1b1c1f"),
    "text": ("#1a1a1a", "#ececec"),
    "muted": ("#6b6b6b", "#a0a0a0"),
    "line": ("#e3e3df", "#2e3034"),
    "accent": ("#2f5d50", "#8cc7b4"),
    "accent-text": ("#ffffff", "#0f1a17"),
    "font-sans": ("system-ui, -apple-system, 'Segoe UI', Roboto, sans-serif", None),
    "font-mono": ("ui-monospace, SFMono-Regular, Menlo, monospace", None),
    "radius": ("12px", None),
    "gap": ("16px", None),
    "max": ("960px", None),
}

_BAD_VALUE = re.compile(r"[;{}<>]|/\*|\*/|\\")


def token_var(name):
    if name not in TOKENS:
        raise KeyError("unknown ipe theme token: %r (known: %s)" % (name, ", ".join(TOKENS)))
    return "--ipe-" + name


def theme_css(overrides=None):
    """`:root{--ipe-…:…}` 한 줄(넘긴 토큰만). 비면 빈 글자 — 기본값은 ipe-kit.css 안에 있다."""
    decls = []
    for name, value in (overrides or {}).items():
        var = token_var(name)
        v = str(value).strip()
        if not v or _BAD_VALUE.search(v):
            raise ValueError("bad value for %s: %r" % (var, value))
        decls.append("%s:%s" % (var, v))
    return ":root{%s}" % ";".join(decls) if decls else ""


def theme_style(overrides=None):
    css = theme_css(overrides)
    return '<style id="ipe-theme">%s</style>' % css if css else ""


def default_css():
    """ipe-kit.css 머리의 기본 토큰 블록(라이트 + 다크). 시험 · 문서용 — 손으로 고친 CSS 와 어긋나지 않게 시험이 비교한다."""
    light = ";".join("--ipe-%s:%s" % (n, l) for n, (l, _) in TOKENS.items())
    dark = ";".join("--ipe-%s:%s" % (n, d) for n, (_, d) in TOKENS.items() if d)
    return (":where(:root){%s}\n@media (prefers-color-scheme: dark){:where(:root[data-ipe-scheme=\"auto\"]){%s}}\n"
            ":where(:root[data-ipe-scheme=\"dark\"]){%s}\n" % (light, dark, dark))
