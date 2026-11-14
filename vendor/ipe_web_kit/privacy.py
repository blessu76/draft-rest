"""privacy — 나라별 개인정보 처리방침(댓글) · 거주국 → 최소 연령. **기본 OFF.**

데이터와 글자를 나눈다 — 웹은 설정(privacy.json)만 바꿔 같은 방침을 쓴다.

    data/privacy_countries.json   나라별 기준(ISO 3166-1 alpha-2 키) — consent_age · under_age_handling · transfer_basis ·
                                  rights · authority_name/url · retention_legal · sources · review · comments_recommended …
    data/privacy_text.json        12개 언어 방침 글(본문·나라 절·표 머리) — {{SERVICE_NAME}} 같은 자리표시자
    사이트 privacy.json           서비스 이름 · 운영자 · 연락처 · 보관/숨김삭제/삭제요청 기간 · 처리자(firebase) · 기능 · 기본 연령

웹 빌더(댓글 OFF 면 render_section·script 는 빈 글자 · copy_assets 는 {} → 사이트 출력이 그대로):

    cfg = privacy.load(ROOT / "privacy.json")
    privacy.render_section(cfg, "ko")     # <section class="ipe-pp" …> 방침 본문 + 나라별 표
    privacy.render_page(cfg, "ko")        # 독립 페이지(HTML 문서 하나)
    hrefs = privacy.copy_assets(cfg, OUT / "assets")   # {"js": "/assets/ipe-privacy-age.js?v=…"}
    privacy.script(cfg, hrefs)            # <script src=… data-default-age="18" defer> → window.IpePrivacy.minAge("KR") == 15
    privacy.min_age("IN", cfg)            # 19 — 데이터 값이 먼저, 없는 나라는 cfg.default_age

검사·생성:

    python3 -m ipe_web_kit.privacy check <privacy.json> [--strict]   # strict: 근거 없는 나라(적용 18 제외)면 실패(1)
    python3 -m ipe_web_kit.privacy build <privacy.json> <outdir>     # <outdir>/<lang>/index.html (12개 언어)
    python3 -m ipe_web_kit.privacy js > ipe_web_kit/assets/ipe-privacy-age.js   # 연령표 → JS(시험이 커밋본과 대조)

나이 규칙(AI 보수적 검토 — 변호사 검토 아님): 적용 나이 consent_age = 법정 legal_age + 1, 출처를 못 찾거나 애매하면 18.
review="ai-conservative" + 근거 URL(sources) 이 있거나 적용 18 이면 strict 통과. review 가 비면 표에 「미검증」 표시와 경고 줄이 붙는다.
legalReviewed=false 면 「법률 검토 전」 줄은 그대로 보인다(AI 검토를 변호사 검토로 적지 않는다).
정본 문서: _ipe/site/community-comments-privacy-by-country.md.
"""
import datetime as dt
import hashlib
import json
import re
import shutil
import sys
from pathlib import Path

from . import ASSETS, languages
from .seo import esc

DATA = Path(__file__).resolve().parent / "data"
COUNTRIES_JSON = DATA / "privacy_countries.json"
TEXT_JSON = DATA / "privacy_text.json"
JS = ASSETS / "ipe-privacy-age.js"
PRIVACY_REV = "1"   # JS 자산 개정 — ?v= 글자

# 번역 문구·나라 이름이 실제로 들어 있는 옛 12개 코드(데이터 파일의 키). th·vi·tr·zh-Hant 는 아직 없어 en 문구로 보인다(text_lang).
TEXT_LANGS = ("en", "ko", "ja", "zh", "es", "fr", "de", "pt", "ru", "ar", "hi", "id")
# 사이트 langs 의 기본·권장(kit-0029 공통 12개). 종료 언어(zh-Hans·ru·ar·hi)와 옛 코드 zh·pt 는 문구가 남아 있어 계속 받는다(옛 설정이 깨지지 않게) — 코드는 있는 그대로 둔다.
LANGS = languages.SUPPORTED
ACCEPTED = languages.SUPPORTED + languages.ENDED + tuple(languages.LEGACY_TAGS)
RTL = ("ar",)
DEFAULT_AGE = 18    # 데이터에 없는 나라 — 인도·대만 등이 사실상 18세라 16세는 가장 엄격한 기준이 아니다. 사이트 설정 defaultAge 로 바꿀 수 있다
TEXT_NUMBERS_OK = {"30", "500", "3"}   # 템플릿에 남겨도 되는 숫자(닉네임·댓글 길이 · 신고 3회 · 리전 이름) — 나이 숫자는 허용 안 함
HANDLING = ("block", "block_or_parental_consent", "comments_disabled")
AGE_BASIS = ("statute", "guidance", "default")
REVIEWS = ("ai-conservative", "")     # ai-conservative = AI 보수적 검토(변호사 검토 아님) · "" = 아직
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
RIGHTS = ("access", "rectification", "erasure", "restriction", "objection", "portability", "suspension", "copy",
          "disclosure", "inquiry", "confirmation", "grievance", "parental_access", "parental_erasure")
REGIONS = ("EU", "EEA", "UK", "CH", "KR", "US", "CA", "OC", "AS", "LATAM", "RU", "MENA")
# 본문의 「어디에 저장」 문단은 Firebase(Firestore) 서울 리전을 적는다 — 다른 처리자는 글을 더한 뒤 연다.
PROCESSORS = {"firebase": ("asia-northeast3",)}
FEATURES = ("comments",)
CC_RE = re.compile(r"^[A-Z]{2}$")
SUB_RE = re.compile(r"^[A-Z0-9]{1,3}$")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[a-z]{2,}$", re.I)
PH_RE = re.compile(r"\{\{[A-Z_]+\}\}")
COUNTRY_KEYS = {"region", "legal_age", "consent_age", "age_basis", "law", "under_age_handling", "comments_recommended",
                "transfer_basis", "rights", "authority_name", "authority_url", "retention_legal", "sources",
                "review", "reviewed", "notes", "names", "subdivisions"}

_cache = {}


def _json(path):
    key = str(path)
    if key not in _cache:
        _cache[key] = json.loads(Path(path).read_text(encoding="utf-8"))
    return _cache[key]


def countries():
    return _json(COUNTRIES_JSON)["countries"]


def texts():
    return _json(TEXT_JSON)


# ---- 데이터 검사 ----

def _age_ok(v, allow_none=False):
    if v is None:
        return allow_none
    return isinstance(v, int) and not isinstance(v, bool) and 0 <= v <= 21


def _conservative(d):
    """적용 나이 = 법정 + 1 이상(법정 나이가 없으면 검사 안 함)."""
    la, ca = d.get("legal_age"), d.get("consent_age")
    return not (_age_ok(la) and _age_ok(ca)) or ca >= la + 1


def reviewed(d):
    """strict 통과 — AI 보수적 검토 + 근거 URL, 또는 적용 나이가 기본값(18)."""
    return bool(d.get("review") and d.get("sources")) or d.get("consent_age") == DEFAULT_AGE


def validate_countries(data):
    """나라 데이터 스키마 검사 — 문제 목록(빈 목록이면 통과)."""
    errs = []
    cs = data.get("countries")
    if not isinstance(cs, dict) or not cs:
        return ["countries must be a non-empty object"]
    for cc, d in cs.items():
        p = "%s: " % cc
        if not CC_RE.match(cc):
            errs.append(p + "key must be ISO alpha-2 (upper)")
        if not isinstance(d, dict):
            errs.append(p + "entry must be an object")
            continue
        missing = (COUNTRY_KEYS - {"subdivisions"}) - set(d)
        if missing:
            errs.append(p + "missing " + ", ".join(sorted(missing)))
        extra = set(d) - COUNTRY_KEYS
        if extra:
            errs.append(p + "unknown " + ", ".join(sorted(extra)))
        if d.get("region") not in REGIONS:
            errs.append(p + "bad region")
        if not _age_ok(d.get("consent_age")):
            errs.append(p + "consent_age must be int 0..21")
        if not _age_ok(d.get("legal_age"), allow_none=True):
            errs.append(p + "legal_age must be int 0..21 or null")
        if d.get("age_basis") not in AGE_BASIS:
            errs.append(p + "bad age_basis")
        if d.get("age_basis") == "default" and d.get("legal_age") is not None:
            errs.append(p + "age_basis default needs legal_age null")
        if d.get("under_age_handling") not in HANDLING:
            errs.append(p + "bad under_age_handling")
        if not isinstance(d.get("comments_recommended"), bool):
            errs.append(p + "comments_recommended must be true/false")
        if (d.get("comments_recommended") is False) != (d.get("under_age_handling") == "comments_disabled"):
            errs.append(p + "comments_recommended false <=> under_age_handling comments_disabled")
        for k in ("law", "transfer_basis", "authority_name", "retention_legal", "notes", "authority_url"):
            if not isinstance(d.get(k), str):
                errs.append(p + k + " must be a string")
        if not d.get("authority_name"):
            errs.append(p + "authority_name empty")
        url = d.get("authority_url")
        if url and not str(url).startswith("https://"):
            errs.append(p + "authority_url must be https:// (or empty)")
        rights = d.get("rights")
        if not isinstance(rights, list) or set(rights) - set(RIGHTS):
            errs.append(p + "rights must be codes from RIGHTS")
        srcs = d.get("sources")
        if not isinstance(srcs, list) or any(not str(s).startswith("https://") for s in srcs):
            errs.append(p + "sources must be a list of https:// URLs")
        if d.get("review") not in REVIEWS:
            errs.append(p + "review must be one of %s" % (REVIEWS,))
        if d.get("review") and not DATE_RE.match(str(d.get("reviewed"))):
            errs.append(p + "review needs reviewed (YYYY-MM-DD)")
        if not d.get("review") and d.get("reviewed"):
            errs.append(p + "reviewed without review")
        if d.get("review") and not srcs and d.get("consent_age") != DEFAULT_AGE:
            errs.append(p + "review needs sources (or consent_age %d)" % DEFAULT_AGE)
        if not _conservative(d):
            errs.append(p + "consent_age must be >= legal_age + 1")
        names = d.get("names")
        if not isinstance(names, dict) or set(names) != set(TEXT_LANGS) or not all(names.values()):
            errs.append(p + "names must have all 12 languages")
        for sk, sv in (d.get("subdivisions") or {}).items():
            if not SUB_RE.match(sk) or not isinstance(sv, dict) or not _age_ok(sv.get("consent_age")) \
                    or not _age_ok(sv.get("legal_age"), allow_none=True) or not _conservative(sv):
                errs.append(p + "bad subdivision %s" % sk)
    return errs


def validate_texts(data):
    errs = []
    for k in ("labels", "body", "country"):
        if set(data.get(k, {})) != set(TEXT_LANGS):
            errs.append("%s must have all 12 languages" % k)
    if errs:
        return errs
    lkeys = set(data["labels"]["en"])
    n = len(data["body"]["en"])
    kinds = [b[0] for b in data["body"]["en"]]
    for lang in TEXT_LANGS:
        if set(data["labels"][lang]) != lkeys:
            errs.append("%s: label keys differ from en" % lang)
        if [b[0] for b in data["body"][lang]] != kinds or len(data["body"][lang]) != n:
            errs.append("%s: body blocks differ from en" % lang)
        if set(data["country"][lang]) != {"heading", "conservative", "other"}:
            errs.append("%s: country needs heading, conservative, other" % lang)
        blob = json.dumps([data["body"][lang], data["country"][lang]], ensure_ascii=False)
        if re.search(r"\[(검토|결정 필요|review|미검증)", blob, re.I):
            errs.append("%s: review marker left in text" % lang)
        errs.extend(hardcoded_numbers(lang, data["body"][lang], data["country"][lang]))
    return errs


def hardcoded_numbers(lang, *parts):
    """템플릿에 손으로 쓴 숫자(나이 등) — 허용 목록(TEXT_NUMBERS_OK) 밖이면 문제. 나이는 {{MIN_AGE}} 한 곳에서만 나온다."""
    blob = PH_RE.sub(" ", json.dumps(parts, ensure_ascii=False))
    nums = {m.group(1) for m in re.finditer(r"(?<![A-Za-z0-9])([0-9]+)(?![0-9])", blob)}
    nums |= {m.group(0) for m in re.finditer(r"[\u0660-\u0669\u0966-\u096f]+", blob)}
    bad = sorted(nums - TEXT_NUMBERS_OK)
    return ["%s: hardcoded number(s) in text %s — use {{MIN_AGE}}/{{...}} placeholders" % (lang, bad)] if bad else []


# ---- 거주국 → 최소 연령 ----

def _default(cfg_or_age):
    if cfg_or_age is None:
        return DEFAULT_AGE
    if isinstance(cfg_or_age, int):
        return cfg_or_age
    return cfg_or_age.default_age


def min_age(cc, cfg=None):
    """거주국(「KR」·「ca-qc」) → 댓글 최소 만 나이. 데이터 값이 먼저(하위 지역 → 나라), 없으면 기본(cfg.default_age · 18)."""
    code = str(cc or "").strip().upper().replace("_", "-")
    base, _, sub = code.partition("-")
    d = countries().get(base)
    if d is None:
        return _default(cfg)
    s = (d.get("subdivisions") or {}).get(sub)
    return s["consent_age"] if s else d["consent_age"]


def comments_allowed(cc):
    d = countries().get(str(cc or "").strip().upper()[:2])
    return True if d is None else d["comments_recommended"]


def can_comment(cc, birth_year, birth_month, cfg=None, today=None):
    """생년·월만으로 보수적으로(같은 달은 생일 전으로 본다) — JS IpePrivacy.canComment 와 같다."""
    if not comments_allowed(cc):
        return False
    t = today or dt.date.today()
    age = t.year - int(birth_year) - (1 if t.month <= int(birth_month) else 0)
    return age >= min_age(cc, cfg)


# ---- 사이트 설정 ----

class SiteConfig:
    """사이트 하나의 방침 설정. 댓글이 꺼져 있으면 render_section/script 는 빈 글자."""

    def __init__(self, service, operator, contact_email, features=None, langs=LANGS, retention_years=3,
                 hidden_delete_days=90, delete_request_days=30, processors=None, primary_country="KR",
                 default_age=DEFAULT_AGE, countries_shown=None, legal_reviewed=False):
        for k, v in (("service", service), ("operator", operator)):
            if not isinstance(v, str) or not v.strip() or len(v) > 80:
                raise ValueError("%s must be a non-empty string (<= 80)" % k)
        if not isinstance(contact_email, str) or not EMAIL_RE.match(contact_email):
            raise ValueError("bad contactEmail %r" % (contact_email,))
        self.service, self.operator, self.contact_email = service.strip(), operator.strip(), contact_email
        feats = dict.fromkeys(FEATURES, False)
        for k, v in (features or {}).items():
            if k not in FEATURES:
                raise KeyError("unknown feature: %r (known: %s)" % (k, ", ".join(FEATURES)))
            if not isinstance(v, bool):
                raise ValueError("feature %s must be true/false" % k)
            feats[k] = v
        self.features = feats
        langs = list(langs)
        if not langs or len(set(langs)) != len(langs) or set(langs) - set(ACCEPTED):
            raise ValueError("langs must be distinct and from %s: %r" % (" ".join(ACCEPTED), langs))
        self.langs = langs
        for k, v, lo, hi in (("retentionYears", retention_years, 1, 10), ("hiddenDeleteDays", hidden_delete_days, 1, 365),
                             ("deleteRequestDays", delete_request_days, 1, 30), ("defaultAge", default_age, 13, 21)):
            if not isinstance(v, int) or isinstance(v, bool) or not lo <= v <= hi:
                raise ValueError("%s must be %d..%d" % (k, lo, hi))
        self.retention_years, self.hidden_delete_days = retention_years, hidden_delete_days
        self.delete_request_days, self.default_age = delete_request_days, default_age
        procs = processors if processors is not None else [{"id": "firebase", "region": "asia-northeast3"}]
        if not procs:
            raise ValueError("processors must not be empty")
        for p in procs:
            if not isinstance(p, dict) or set(p) != {"id", "region"} or p["region"] not in PROCESSORS.get(p["id"], ()):
                raise ValueError("unsupported processor %r (supported: %s)" % (p, PROCESSORS))
        self.processors = [dict(p) for p in procs]
        if primary_country not in countries():
            raise ValueError("primaryCountry %r is not in the country data" % (primary_country,))
        self.primary_country = primary_country
        if countries_shown is not None:
            bad = [c for c in countries_shown if c not in countries()]
            if bad or not countries_shown or len(set(countries_shown)) != len(countries_shown):
                raise ValueError("countries must be distinct codes from the data (bad: %s)" % ", ".join(bad))
        self.countries_shown = list(countries_shown) if countries_shown is not None else None
        if not isinstance(legal_reviewed, bool):
            raise ValueError("legalReviewed must be true/false")
        self.legal_reviewed = legal_reviewed

    @property
    def enabled(self):
        return any(self.features.values())

    @property
    def min_age(self):
        """본문 「아동」 문단의 나이 — 운영국(primaryCountry) 데이터 값(KR → 15)."""
        return min_age(self.primary_country, self)

    def shown(self):
        return list(self.countries_shown) if self.countries_shown is not None else sorted(countries())

    KEYS = {"service": "service", "operator": "operator", "contactEmail": "contact_email", "features": "features",
            "langs": "langs", "retentionYears": "retention_years", "hiddenDeleteDays": "hidden_delete_days",
            "deleteRequestDays": "delete_request_days", "processors": "processors",
            "primaryCountry": "primary_country", "defaultAge": "default_age", "countries": "countries_shown",
            "legalReviewed": "legal_reviewed"}

    @classmethod
    def from_dict(cls, d):
        d = {k: v for k, v in d.items() if not k.startswith("_")}   # 「_note」 같은 설명 칸은 무시
        extra = set(d) - set(cls.KEYS)
        if extra:
            raise KeyError("unknown privacy keys: %s" % ", ".join(sorted(extra)))
        for k in ("service", "operator", "contactEmail"):
            if k not in d:
                raise KeyError("privacy config needs %s" % k)
        return cls(**{cls.KEYS[k]: v for k, v in d.items()})


def load(path):
    return SiteConfig.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))


def problems(cfg, strict=False):
    """설정+데이터 검사 — (문제 목록). strict 면 표에 나오는 나라 중 근거 없는 나라(적용 18 제외)를 문제로 센다.
    legalReviewed 는 strict 에서 보지 않는다 — AI 보수적 검토로 대신하되, false 면 「법률 검토 전」 줄은 계속 보인다."""
    out = ["data: " + e for e in validate_countries(_json(COUNTRIES_JSON))]
    out += ["text: " + e for e in validate_texts(texts())]
    if strict:
        unv = [c for c in cfg.shown() if not reviewed(countries()[c])]
        if unv:
            out.append("countries without review evidence shown (%d): %s" % (len(unv), " ".join(unv)))
    return out


# ---- 그리기 ----

def _fill(s, cfg):
    vals = {"SERVICE_NAME": cfg.service, "OPERATOR": cfg.operator, "CONTACT_EMAIL": cfg.contact_email,
            "RETENTION_YEARS": cfg.retention_years, "HIDDEN_DELETE_DAYS": cfg.hidden_delete_days,
            "DELETE_REQUEST_DAYS": cfg.delete_request_days, "MIN_AGE": cfg.min_age, "DEFAULT_AGE": cfg.default_age}
    return PH_RE.sub(lambda m: str(vals.get(m.group(0)[2:-2], m.group(0))), s)


def _inline(s, cfg):
    h = esc(_fill(s, cfg))
    h = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", h)
    e = esc(cfg.contact_email)
    return h.replace(e, '<a href="mailto:%s">%s</a>' % (e, e))


def _age_cell(d, lab):
    if not d["comments_recommended"]:
        return esc(lab["comments_unavailable"])
    s = str(d["consent_age"])
    for sk, sv in sorted((d.get("subdivisions") or {}).items()):
        s += " · %s %d" % (sk, sv["consent_age"])
    return esc(s)


def text_lang(lang):
    """사이트 언어 태그 → 번역 문구가 있는 키(zh-Hans→zh · pt-BR→pt). 문구가 없는 언어(th·vi·tr·zh-Hant)는 en."""
    key = languages.legacy_code(lang)
    return key if key in TEXT_LANGS else languages.DEFAULT


def _country_block(cfg, lang):
    t, lab = texts()["country"][lang], texts()["labels"][lang]
    cs = countries()
    rows = sorted(cfg.shown(), key=lambda c: cs[c]["names"][lang].casefold())
    out = ['<h3 class="ipe-pp__h">%s</h3>' % esc(t["heading"])]
    if any(not cs[c]["review"] for c in rows):
        out.append('<p class="ipe-pp__warn" role="note">%s</p>' % esc(lab["unverified_banner"]))
    out.append('<div class="ipe-pp__scroll"><table class="ipe-pp__table"><thead><tr><th scope="col">%s</th>'
               '<th scope="col">%s</th><th scope="col">%s</th></tr></thead><tbody>'
               % (esc(lab["col_country"]), esc(lab["col_age"]), esc(lab["col_authority"])))
    for c in rows:
        d = cs[c]
        mark = '' if d["review"] else ' <span class="ipe-pp__unv">%s</span>' % esc(lab["unverified_mark"])
        auth = esc(d["authority_name"])
        if d["authority_url"]:
            auth = '<a href="%s" rel="noopener" target="_blank">%s</a>' % (esc(d["authority_url"]), auth)
        out.append('<tr data-cc="%s"><th scope="row">%s%s</th><td>%s</td><td>%s</td></tr>'
                   % (c, esc(d["names"][lang]), mark, _age_cell(d, lab), auth))
    out.append('</tbody></table></div>')
    out.append('<p>%s</p>' % _inline(t["conservative"], cfg))
    out.append('<p>%s</p>' % _inline(t["other"], cfg))
    return "".join(out)


def render_section(cfg, lang):
    """방침 본문 + 나라별 표(아동 문단 앞). 댓글 OFF 면 빈 글자."""
    if not cfg.enabled:
        return ""
    if lang not in cfg.langs:
        raise ValueError("lang %r is not in this site's privacy langs" % (lang,))
    tl = text_lang(lang)   # 문구가 없으면 en — lang·dir 속성도 실제 문구 언어로
    lab = texts()["labels"][tl]
    body = texts()["body"][tl]
    out = ['<section class="ipe-pp" lang="%s" dir="%s">' % (lang if tl == languages.legacy_code(lang) else tl, "rtl" if tl in RTL else "ltr")]
    if not cfg.legal_reviewed:
        out.append('<p class="ipe-pp__warn ipe-pp__draft" role="note">%s</p>' % esc(lab["legal_pending"]))
    out.append('<p class="ipe-pp__who">%s</p>' % _inline(lab["operator_line"], cfg))
    items = []
    last = len(body) - 1   # 마지막 문단 = 아동 — 나라별 표를 그 앞에 둔다
    for i, (kind, text) in enumerate(body):
        if kind != "li" and items:
            out.append("<ul>%s</ul>" % "".join(items))
            items = []
        if i == last:
            out.append(_country_block(cfg, tl))
        if kind == "h":
            out.append('<h2 class="ipe-pp__h">%s</h2>' % _inline(text, cfg))
        elif kind == "li":
            items.append("<li>%s</li>" % _inline(text, cfg))
        else:
            out.append("<p>%s</p>" % _inline(text, cfg))
    if items:
        out.append("<ul>%s</ul>" % "".join(items))
    out.append("</section>")
    return "".join(out)


CSS = """.ipe-pp{max-width:var(--ipe-max,960px);margin:0 auto;padding:var(--ipe-gap,16px);font-family:var(--ipe-font-sans,system-ui,sans-serif);color:var(--ipe-text,#1a1a1a);line-height:1.65;overflow-wrap:anywhere}
.ipe-pp__h{margin:1.6em 0 .5em;line-height:1.3}
.ipe-pp__who{color:var(--ipe-muted,#6b6b6b);font-size:.875rem}
.ipe-pp__warn{padding:10px 12px;border:1px solid #c98a00;border-radius:var(--ipe-radius,12px);background:rgba(201,138,0,.1);font-size:.875rem}
.ipe-pp__scroll{overflow-x:auto;margin:0 0 1em;border:1px solid var(--ipe-line,#e3e3df);border-radius:var(--ipe-radius,12px)}
.ipe-pp__table{width:100%;border-collapse:collapse;font-size:.875rem}
.ipe-pp__table th,.ipe-pp__table td{padding:6px 10px;text-align:start;vertical-align:top;border-bottom:1px solid var(--ipe-line,#e3e3df)}
.ipe-pp__table thead th{background:var(--ipe-surface,#f6f6f4);font-weight:600}
.ipe-pp__table tbody th{font-weight:500}
.ipe-pp__unv{display:inline-block;padding:0 6px;border-radius:999px;background:rgba(201,138,0,.15);color:#8a5d00;font-size:.75rem;font-weight:500}
.ipe-pp a{color:var(--ipe-accent,#2f5d50)}
.ipe-pp__langs{display:flex;flex-wrap:wrap;gap:4px 10px;max-width:var(--ipe-max,960px);margin:0 auto;padding:var(--ipe-gap,16px) var(--ipe-gap,16px) 0;font-family:var(--ipe-font-sans,system-ui,sans-serif);font-size:.8125rem}
.ipe-pp__langs a{color:var(--ipe-muted,#6b6b6b)}.ipe-pp__langs a[aria-current]{color:var(--ipe-text,#1a1a1a);font-weight:600}
@media (max-width:420px){.ipe-pp__table th,.ipe-pp__table td{padding:6px 8px}}"""


def render_page(cfg, lang, href=lambda lang: "../%s/" % lang):
    """독립 페이지(문서 하나) — 언어 링크 + render_section. 댓글 OFF 면 빈 글자."""
    sec = render_section(cfg, lang)
    if not sec:
        return ""
    tl = text_lang(lang)
    title = "%s — %s" % (texts()["labels"][tl]["title"], cfg.service)
    nav = "".join('<a href="%s" hreflang="%s"%s>%s</a>' % (esc(href(l)), l, ' aria-current="page"' if l == lang else "", l)
                  for l in cfg.langs)
    return ('<!doctype html><html lang="%s" dir="%s"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1"><title>%s</title><style>%s'
            'body{margin:0;background:var(--ipe-bg,#fff)}</style></head><body><nav class="ipe-pp__langs">%s</nav>%s'
            '</body></html>\n' % (lang if tl == languages.legacy_code(lang) else tl, "rtl" if tl in RTL else "ltr", esc(title), CSS, nav, sec))


def build(cfg, outdir):
    """<outdir>/<lang>/index.html 을 쓴다 — 쓴 경로 목록."""
    paths = []
    for lang in cfg.langs:
        html = render_page(cfg, lang)
        if not html:
            continue
        p = Path(outdir) / lang / "index.html"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(html, encoding="utf-8")
        paths.append(p)
    return paths


# ---- 연령 조회 JS ----

def js_text():
    """assets/ipe-privacy-age.js 의 정본 — 나라 데이터에서 만든다(시험이 커밋본과 같은지 본다)."""
    ages, blocked = {}, []
    for cc, d in sorted(countries().items()):
        ages[cc] = d["consent_age"]
        for sk, sv in sorted((d.get("subdivisions") or {}).items()):
            ages["%s-%s" % (cc, sk)] = sv["consent_age"]
        if not d["comments_recommended"]:
            blocked.append(cc)
    return ("/* ipe-privacy-age.js · ipe_web_kit.privacy — 생성 파일(python3 -m ipe_web_kit.privacy js). 손으로 고치지 않는다. */\n"
            "(function (root) {\n"
            "  'use strict';\n"
            "  var AGES = %s;\n"
            "  var BLOCKED = %s;\n"
            "  var DEFAULT_AGE = %d;\n"
            "  var tag = typeof document !== 'undefined' && document.currentScript;\n"
            "  var siteDefault = tag && parseInt(tag.getAttribute('data-default-age'), 10);\n"
            "  function code(cc) { return String(cc || '').trim().toUpperCase().replace('_', '-'); }\n"
            "  function minAge(cc, opts) {\n"
            "    var c = code(cc), base = c.split('-')[0];\n"
            "    if (Object.prototype.hasOwnProperty.call(AGES, c)) return AGES[c];\n"
            "    if (Object.prototype.hasOwnProperty.call(AGES, base)) return AGES[base];\n"
            "    var d = opts && opts.defaultAge;\n"
            "    return d > 0 ? d : (siteDefault > 0 ? siteDefault : DEFAULT_AGE);\n"
            "  }\n"
            "  function commentsAllowed(cc) { return BLOCKED.indexOf(code(cc).split('-')[0]) < 0; }\n"
            "  function canComment(cc, year, month, opts) {\n"
            "    if (!commentsAllowed(cc)) return false;\n"
            "    var now = (opts && opts.now) || new Date();\n"
            "    var age = now.getFullYear() - year - ((now.getMonth() + 1) <= month ? 1 : 0);\n"
            "    return age >= minAge(cc, opts);\n"
            "  }\n"
            "  var api = { minAge: minAge, commentsAllowed: commentsAllowed, canComment: canComment, AGES: AGES, DEFAULT_AGE: DEFAULT_AGE };\n"
            "  if (typeof module === 'object' && module.exports) module.exports = api; else root.IpePrivacy = api;\n"
            "})(typeof self !== 'undefined' ? self : this);\n"
            % (json.dumps(ages, separators=(",", ":"), sort_keys=True), json.dumps(blocked), DEFAULT_AGE))


def asset_version(path):
    return "%s-%s" % (PRIVACY_REV, hashlib.sha256(Path(path).read_bytes()).hexdigest()[:8])


def copy_assets(cfg, dest_dir, url_prefix="/assets/"):
    """댓글이 켜졌을 때만 ipe-privacy-age.js 를 복사하고 `?v=` 주소를 돌려준다. OFF 면 {}."""
    if not cfg.enabled:
        return {}
    dest = Path(dest_dir) / JS.name
    dest.parent.mkdir(parents=True, exist_ok=True)
    if not dest.exists() or dest.read_bytes() != JS.read_bytes():
        shutil.copyfile(JS, dest)
    return {"js": "%s%s?v=%s" % (url_prefix, JS.name, asset_version(JS))}


def script(cfg, hrefs):
    if not cfg.enabled:
        return ""
    return '<script src="%s" data-default-age="%d" defer></script>' % (esc(hrefs["js"]), cfg.default_age)


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv == ["js"]:
        sys.stdout.write(js_text())
        return 0
    if len(argv) in (2, 3) and argv[0] == "check" and (len(argv) == 2 or argv[2] == "--strict"):
        cfg = load(argv[1])
        strict = len(argv) == 3
        probs = problems(cfg, strict=strict)
        shown = cfg.shown()
        rev = sum(1 for c in shown if countries()[c]["review"])
        unv = sum(1 for c in shown if not reviewed(countries()[c]))
        print("%s %s — comments %s · %d countries (%d ai-reviewed) · min age %d (%s) · default %d"
              % ("FAIL" if probs else "OK", cfg.service, "ON" if cfg.enabled else "OFF", len(shown), rev,
                 cfg.min_age, cfg.primary_country, cfg.default_age))
        for p in probs:
            print("  - " + p)
        if not strict and unv:
            print("  ! %d countries without review evidence — `check --strict` fails until reviewed" % unv)
        return 1 if probs else 0
    if len(argv) == 3 and argv[0] == "build":
        cfg = load(argv[1])
        paths = build(cfg, argv[2])
        print("wrote %d pages%s" % (len(paths), "" if paths else " (comments OFF — nothing to render)"))
        return 0
    sys.stderr.write("usage: python3 -m ipe_web_kit.privacy check <privacy.json> [--strict] | build <privacy.json> <outdir> | js\n")
    return 2


if __name__ == "__main__":
    sys.exit(main())
