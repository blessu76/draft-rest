"""ipe 공통 지원 언어 — 12개 목록 · 기본 언어 · 기기/브라우저 언어 → 목록 언어 해석(kit-0029, 2026-11-12).

사이트·게임·앱이 언어를 따로 나열하지 않고 이 목록을 읽는다. 앱킷(Flutter)의 ipe_locales 와 같은 목록·규칙이다.
번역이 없는 키는 DEFAULT(en) 로 대체한다(fallback_chain).
"""
import re

# 이 순서가 선택기·hreflang·sitemap 의 순서다. 1군 en·ko·ja / 2군 zh-Hant·es·pt-BR·fr·de / 3군 id·th·vi·tr.
SUPPORTED = ("en", "ko", "ja", "zh-Hant", "es", "pt-BR", "fr", "de", "id", "th", "vi", "tr")
DEFAULT = "en"
# 지원 종료 — 지우지 않고 표시만(각 서비스가 정리). 이 코드는 resolve 결과로 나오지 않는다.
ENDED = ("zh-Hans", "ru", "ar", "hi")
# 선택기에 보일 자기 언어 이름
NAMES = {
    "en": "English", "ko": "한국어", "ja": "日本語", "zh-Hant": "繁體中文", "es": "Español", "pt-BR": "Português (Brasil)",
    "fr": "Français", "de": "Deutsch", "id": "Bahasa Indonesia", "th": "ไทย", "vi": "Tiếng Việt", "tr": "Türkçe",
}
TIERS = {"en": 1, "ko": 1, "ja": 1, "zh-Hant": 2, "es": 2, "pt-BR": 2, "fr": 2, "de": 2, "id": 3, "th": 3, "vi": 3, "tr": 3}

_ZH_HANT_REGIONS = {"tw", "hk", "mo"}
_ALIASES = {"in": "id"}  # 옛 인도네시아어 코드
# 위젯 문구·옛 사이트 설정의 옛 코드(kit-0029 이전 12개) → 지금 태그. 번역 문구 파일의 키는 옛 코드 그대로다.
LEGACY_TAGS = {"zh": "zh-Hans", "pt": "pt-BR"}
_ENDED_CODES = {"ru", "ar", "hi"}


def from_legacy(code):
    """옛 코드(zh·pt) → 지금 태그(zh-Hans·pt-BR), 그 밖은 그대로."""
    return LEGACY_TAGS.get(code, code)


def legacy_code(tag):
    """지금 태그(zh-Hans·pt-BR) → 번역 문구 파일의 옛 키(zh·pt), 그 밖은 그대로."""
    return {v: k for k, v in LEGACY_TAGS.items()}.get(tag, tag)


def is_supported(lang):
    return lang in SUPPORTED


def _zh_hant(rest):
    """zh 뒤 조각들 → 번체인가. 글자체(4자)가 있으면 그것만, 없으면 지역(TW·HK·MO)."""
    script = next((p for p in rest if len(p) == 4 and p.isalpha()), None)
    region = next((p for p in rest if len(p) == 2 and p.isalpha()), None)
    return script == "hant" or (script is None and region in _ZH_HANT_REGIONS)


def _split(tag):
    return [p for p in re.split(r"[-_]", str(tag or "").strip().lower()) if p]


def is_ended(tag):
    """지원 종료 언어인가 — 앱킷 ipeIsRetiredLanguage 와 같다. ru·ar·hi 는 지역이 붙어도 종료(`ru-RU`·`hi_IN`),
    중국어는 간체 계열(`zh`·`zh-CN`·`zh-SG`·`zh-Hans*`)만 종료이고 `zh-TW`·`zh-HK`·`zh-MO`·`zh-Hant*` 는 아니다.
    `_`·대소문자는 가리지 않는다."""
    parts = _split(tag)
    if not parts:
        return False
    if parts[0] == "zh":
        return not _zh_hant(parts[1:])
    return parts[0] in _ENDED_CODES


def resolve(tag):
    """기기/브라우저 언어 태그 → SUPPORTED 의 언어(항상 하나). `zh-TW`·`zh-HK`·`zh-Hant*` → zh-Hant, `zh-CN`·`zh-Hans`·`zh` → en,
    `pt*` → pt-BR, `es*` → es, 목록에 있는 언어는 그것, 나머지 → en. `_`·대소문자는 가리지 않는다."""
    parts = _split(tag)
    if not parts:
        return DEFAULT
    code = _ALIASES.get(parts[0], parts[0])
    rest = parts[1:]
    if code == "zh":
        return "zh-Hant" if _zh_hant(rest) else DEFAULT
    if code == "pt":
        return "pt-BR"
    for lang in SUPPORTED:
        if lang.lower() == code:
            return lang
    return DEFAULT


def resolve_accept_language(header):
    """HTTP `Accept-Language` → 첫 번째로 목록(resolve 가 en 으로 떨어뜨리지 않는 것)에 맞는 언어. 없으면 en.
    q 값이 큰 순(같으면 앞). `zh-CN` 처럼 목록 밖이라 en 이 되는 항목은 건너뛰고 다음 후보를 본다."""
    cands = []
    for i, item in enumerate(str(header or "").split(",")):
        bits = [b.strip() for b in item.split(";")]
        if not bits[0] or bits[0] == "*":
            continue
        q = 1.0
        for b in bits[1:]:
            if b.lower().startswith("q="):
                try:
                    q = float(b[2:])
                except ValueError:
                    q = 0.0
        if q > 0:
            cands.append((-q, i, bits[0]))
    for _, _, tag in sorted(cands):
        got = resolve(tag)
        if got != DEFAULT or _is_en(tag):
            return got
    return DEFAULT


def _is_en(tag):
    """tag 가 정말 영어(en·en-US …)인가 — zh-CN 처럼 목록 밖이라 en 으로 떨어진 것과 구분."""
    return re.split(r"[-_]", str(tag or "").strip().lower())[0] == "en"


def fallback_chain(lang):
    """번역 찾는 순서 — [lang, en] (lang 이 en 이면 [en])."""
    got = resolve(lang)
    return [got] if got == DEFAULT else [got, DEFAULT]


def hreflang(lang):
    """hreflang 값 — 목록 태그 그대로(zh-Hant · pt-BR 는 BCP47 유효)."""
    if lang not in SUPPORTED:
        raise ValueError("unsupported lang: %r" % (lang,))
    return lang
