"""community — 댓글·좋아요·신고 위젯(Firestore REST · SDK 없음 · 로그인 없음). **기본 OFF · 댓글·좋아요·신고 한 세트(`enabled`).**

Firebase 프로젝트 하나를 모든 ipe 웹이 함께 쓴다. 데이터는 사이트별 경로에 나뉜다:

    sites/{siteId}/posts/{slug}                    {count}                                          좋아요 수(처음 1, 그 뒤 +1 만)
    sites/{siteId}/posts/{slug}/comments/{id}      {name, text, lang, by, createdAt, reports, hidden} 댓글(신고 +1 만 · hideAt 에서 자동 숨김)
    sites/{siteId}/clients/{token}                 {lastAt}                                         브라우저별 등록 시계(최소 간격)

웹 빌더(OFF 면 세 함수 모두 빈 글자 · copy_assets 는 아무것도 복사하지 않는다 → 사이트 출력이 그대로):

    cfg = community.load(ROOT / "community.json")          # 또는 community.SiteConfig(site_id="ipe.rest", ...)
    hrefs = community.copy_assets(cfg, OUT / "assets")     # {"css": "/assets/ipe-community.css?v=…", "js": …} · OFF 면 {}
    community.head(cfg, hrefs)     # <link rel="stylesheet" …>
    community.mount(cfg, slug, lang)  # <section class="ipe-cm" data-…></section>
    community.script(cfg, hrefs)   # <script src="…" defer></script>

규칙(firestore.rules)은 킷 repo 의 firebase/sites.json(모든 사이트의 서버 쪽 설정)에서 rules_text() 로 만든다:

    python3 -m ipe_web_kit.community rules firebase/sites.json > firebase/firestore.rules
    python3 -m ipe_web_kit.community check <web>/community.json    # 사이트 설정 검사 + sites.json 에 넣을 줄

위젯(assets/ipe-community.js)과 규칙의 상수(HIDE_AT · GAP · 금칙어 · 링크 · 글자 수)는 이 모듈이 정본 — 시험이 셋의 어긋남을 잡는다.
"""
import hashlib
import json
import re
import shutil
import sys
import warnings
from pathlib import Path

from . import ASSETS
from .seo import esc

CSS = ASSETS / "ipe-community.css"
JS = ASSETS / "ipe-community.js"
# 위젯 자산 개정 — ?v= 글자. 위젯 파일이 바뀔 때만 올린다(ipe-kit.css 의 ASSET_REV 와 따로).
COMMUNITY_REV = "2"

# 공유 Firebase 프로젝트(하나). 웹 설정값은 공개 전제(규칙이 막는다) — 그래도 실값은 Davy 가 프로젝트를 만든 뒤 여기 한 곳에만.
PLACEHOLDER = "REPLACE"
# 공유 Firebase 프로젝트(ipe-web-engage)의 웹 config — 공개값(보안은 firestore.rules). 사이트 community.json 의 firebase 가 덮어쓴다.
# 정본: _ipe/site/community-firebase-web-config.json
FIREBASE = {"projectId": 'ipe-web-engage', "apiKey": 'AIzaSyBc_WT9ePfFkeocoBulH-N56qmENMtJp1M'}

# 위젯이 글자를 가진 언어(ipe-community.js 의 T) — 사이트 langs 는 이 안에서 고른다.
LANGS = ("en", "ko", "ja", "zh", "es", "fr", "de", "pt", "ru", "ar", "hi", "id")
FEATURES = ("comments", "likes", "reports")
HIDE_AT = 3          # 신고 몇 번이면 자동 숨김(기본)
MIN_GAP = 30         # 같은 브라우저 두 댓글 사이 최소 초(기본)
NAME_MAX = 30
TEXT_MAX = 500
PAGE = 20
# 링크 금지 · 기본 금칙어(대소문자 무시 · 부분 일치). 짧은 낱말은 정상 낱말 안에 든다("ass" → "class") — 넣지 않는다.
LINK_RE = r"https?:|www\.|://"
BANNED_BASE = ("fuck", "shit", "bitch", "asshole", "porn", "casino", "viagra", "씨발", "시발", "병신", "개새끼")

SITE_RE = re.compile(r"^[a-z0-9](?:[a-z0-9.-]{0,61}[a-z0-9])?$")
POST_RE = re.compile(r"^[a-z0-9][a-z0-9-]{2,99}$")
WORD_RE = re.compile(r"^[^\W_](?:[\w -]{0,28}[^\W_])?$")


class SiteConfig:
    """사이트 하나의 커뮤니티 설정. **댓글·좋아요·신고는 한 세트** — `enabled` 하나로 셋이 함께 켜지고 꺼진다(기본 OFF).
    (kit-0003) 신고만 따로 끄는 길은 없다. 옛 `features` 는 하위 호환: 하나라도 true 면 세트 ON(+경고) · 모두 false 면 OFF.

    firebase: {"projectId", "apiKey"} — 비우면 킷의 공유 프로젝트(FIREBASE). 켰는데 자리표시(REPLACE)면 ValueError.
    langs: 위젯 언어(LANGS 안에서) · banned_extra: 이 사이트만의 금칙어(기본 목록에 더함).
    hide_at · min_gap: 규칙(firebase/sites.json)과 같은 값이어야 한다.
    """

    def __init__(self, site_id, firebase=None, features=None, langs=LANGS, banned_extra=(), hide_at=HIDE_AT,
                 min_gap=MIN_GAP, enabled=None):
        if not isinstance(site_id, str) or not SITE_RE.match(site_id):
            raise ValueError("bad siteId: %r (lowercase host-like: ipe.rest, idle.ipe.rest)" % (site_id,))
        self.site_id = site_id
        fb = dict(FIREBASE)
        fb.update(firebase or {})
        unknown = set(fb) - set(FIREBASE)
        if unknown:
            raise KeyError("unknown firebase keys: %s" % ", ".join(sorted(unknown)))
        self.firebase = fb
        if features is not None:
            if enabled is not None:
                raise ValueError("use `enabled` only — `features` is the old per-feature form (deprecated)")
            on = False
            for k, v in features.items():
                if k not in FEATURES:
                    raise KeyError("unknown feature: %r (known: %s)" % (k, ", ".join(FEATURES)))
                if not isinstance(v, bool):
                    raise ValueError("feature %s must be true/false" % k)
                on = on or v
            warnings.warn("community `features` is deprecated (comments·likes·reports are one set): use \"enabled\": %s"
                          % ("true" if on else "false"), DeprecationWarning, stacklevel=3)
            enabled = on
        if enabled is None:
            enabled = False
        if not isinstance(enabled, bool):
            raise ValueError("enabled must be true/false")
        feats = dict.fromkeys(FEATURES, enabled)
        self.features = feats
        langs = list(langs)
        if not langs or len(set(langs)) != len(langs) or set(langs) - set(LANGS):
            raise ValueError("langs must be distinct and from %s: %r" % (" ".join(LANGS), langs))
        self.langs = langs
        words = []
        for w in banned_extra:
            w = str(w).strip().lower()
            if not WORD_RE.match(w) or len(w) < 2:
                raise ValueError("bad banned word %r (letters/digits, inner space or hyphen, 2-30 chars)" % (w,))
            if w not in words and w not in BANNED_BASE:
                words.append(w)
        self.banned_extra = words
        if not isinstance(hide_at, int) or isinstance(hide_at, bool) or not 1 <= hide_at <= 100:
            raise ValueError("hideAt must be 1..100")
        if not isinstance(min_gap, int) or isinstance(min_gap, bool) or not 5 <= min_gap <= 3600:
            raise ValueError("minGapSeconds must be 5..3600")
        self.hide_at = hide_at
        self.min_gap = min_gap
        if self.enabled:
            for k, v in self.firebase.items():
                if not v or PLACEHOLDER in v or not re.match(r"^[A-Za-z0-9_-]{4,100}$", v):
                    raise ValueError("community is ON for %s but firebase %s is not set (placeholder)" % (site_id, k))

    @property
    def enabled(self):
        return self.features["comments"]

    @classmethod
    def from_dict(cls, d):
        known = {"siteId", "firebase", "enabled", "features", "langs", "bannedExtra", "hideAt", "minGapSeconds"}
        extra = set(d) - known
        if extra:
            raise KeyError("unknown community keys: %s" % ", ".join(sorted(extra)))
        if "siteId" not in d:
            raise KeyError("community config needs siteId")
        return cls(d["siteId"], firebase=d.get("firebase"), enabled=d.get("enabled"),
                   features=d.get("features"), langs=d.get("langs", LANGS),
                   banned_extra=d.get("bannedExtra", ()), hide_at=d.get("hideAt", HIDE_AT),
                   min_gap=d.get("minGapSeconds", MIN_GAP))

    def server_entry(self):
        """firebase/sites.json 의 한 칸(규칙이 보는 값만 — Firebase 설정값은 넣지 않는다)."""
        return {"enabled": self.enabled, "langs": list(self.langs), "bannedExtra": list(self.banned_extra),
                "hideAt": self.hide_at, "minGapSeconds": self.min_gap}


def load(path):
    return SiteConfig.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))


# ---- 웹 마크업 (OFF 면 빈 글자) ----

def asset_version(path):
    return "%s-%s" % (COMMUNITY_REV, hashlib.sha256(Path(path).read_bytes()).hexdigest()[:8])


def copy_assets(cfg, dest_dir, url_prefix="/assets/"):
    """켜졌을 때만 ipe-community.css/js 를 dest_dir 로 복사하고 `?v=<개정>-<해시8>` 붙은 주소를 돌려준다. OFF 면 {}."""
    if not cfg.enabled:
        return {}
    out = {}
    for kind, src in (("css", CSS), ("js", JS)):
        dest = Path(dest_dir) / src.name
        dest.parent.mkdir(parents=True, exist_ok=True)
        if not dest.exists() or dest.read_bytes() != src.read_bytes():
            shutil.copyfile(src, dest)
        out[kind] = "%s%s?v=%s" % (url_prefix, src.name, asset_version(src))
    return out


def head(cfg, hrefs):
    if not cfg.enabled:
        return ""
    return '<link rel="stylesheet" href="%s">' % esc(hrefs["css"])


def script(cfg, hrefs):
    if not cfg.enabled:
        return ""
    return '<script src="%s" defer></script>' % esc(hrefs["js"])


def mount(cfg, post, lang):
    """글 아래 자리 — 한 글의 댓글·좋아요는 모든 언어 페이지가 함께 쓴다(post = slug). OFF 면 빈 글자."""
    if not cfg.enabled:
        return ""
    if not POST_RE.match(post or ""):
        raise ValueError("bad post slug %r (a-z 0-9 -, 3-100)" % (post,))
    if lang not in cfg.langs:
        raise ValueError("lang %r is not in this site's community langs" % (lang,))
    feats = " ".join(k for k in FEATURES if cfg.features[k])
    attrs = [("data-site", cfg.site_id), ("data-post", post), ("data-lang", lang), ("data-langs", " ".join(cfg.langs)),
             ("data-project", cfg.firebase["projectId"]), ("data-key", cfg.firebase["apiKey"]),
             ("data-features", feats), ("data-hide-at", str(cfg.hide_at)), ("data-gap", str(cfg.min_gap))]
    if cfg.banned_extra:
        attrs.append(("data-banned", "|".join(cfg.banned_extra)))
    return '<section class="ipe-cm" %s></section>' % " ".join('%s="%s"' % (k, esc(v)) for k, v in attrs)


def csp_sources():
    """켠 웹의 CSP 에 더할 값 — connect-src."""
    return {"connect-src": "https://firestore.googleapis.com"}


# ---- 규칙 (firebase/sites.json -> firestore.rules) ----

def load_sites(path):
    """firebase/sites.json → {siteId: SiteConfig}. 모양: {"sites": {"ipe.rest": {server_entry …}}}."""
    d = json.loads(Path(path).read_text(encoding="utf-8"))
    out = {}
    for site_id, entry in d.get("sites", {}).items():
        e = dict(entry)
        e["siteId"] = site_id
        # 서버 쪽 설정에는 Firebase 값이 없다 — 켠 사이트도 검사를 통과하게 자리값을 채운다(규칙에는 쓰지 않는다).
        e["firebase"] = {"projectId": "rules-only", "apiKey": "rules-only"}
        out[site_id] = SiteConfig.from_dict(e)
    return out


def _rq(s):
    return "'" + s.replace("\\", "\\\\").replace("'", "\\'") + "'"


def _site_map(sites):
    if not sites:
        return "{}"
    rows = []
    for site_id in sorted(sites):
        c = sites[site_id]
        rows.append("        %s: {%s, 'langs': [%s], 'banned': %s, 'hideAt': %d, 'minGap': %d}" % (
            _rq(site_id), ", ".join("%s: %s" % (_rq(k), "true" if c.features[k] else "false") for k in FEATURES),
            ", ".join(_rq(l) for l in c.langs), _rq("|".join(c.banned_extra)), c.hide_at, c.min_gap))
    return "{\n%s\n      }" % ",\n".join(rows)


RULES_TEMPLATE = r"""rules_version = '2';
// GENERATED by ipe_web_kit.community (rules_text) from firebase/sites.json — do not edit by hand:
//   python3 -m ipe_web_kit.community rules firebase/sites.json > firebase/firestore.rules
// One Firebase project for every ipe web; data is split per site. Anonymous, no login: these rules are the only line of defence.
//   sites/{site}/posts/{post}                {count}                                              like counter: create with 1, afterwards +1 only; no listing
//   sites/{site}/posts/{post}/comments/{id}  {name, text, lang, by, createdAt, reports, hidden}   create only; reports +1 only (auto-hide at hideAt); no client delete
//   sites/{site}/clients/{token}             {lastAt}                                             per-browser post clock — minimum gap between two comments
// A site works only when it is listed below AND its feature is true (all false by default). Hidden comments are never served.
// Admin hide/unhide/delete = Firebase console (bypasses rules). Everything else is denied.
service cloud.firestore {
  match /databases/{database}/documents {

    function sites() {
      return @SITES@;
    }
    function cfg(site) { return sites().get(site, {}); }
    function on(site, feature) { return cfg(site).get(feature, false) == true; }
    function hideAt(site) { return cfg(site).get('hideAt', @HIDE_AT@); }
    function minGap(site) { return cfg(site).get('minGap', @MIN_GAP@); }
    function validPost(post) { return post.matches('^[a-z0-9][a-z0-9-]{2,99}$'); }
    function noLink(s) { return !s.matches('(?is).*(@LINK@).*'); }
    function noBanned(s, site) {
      return !s.matches('(?is).*(@BANNED@).*')
        && (cfg(site).get('banned', '') == '' || !s.matches('(?is).*(' + cfg(site).get('banned', '') + ').*'));
    }
    function cleanText(s, max, site) {
      return s is string && s.size() >= 1 && s.size() <= max && s.matches('(?s).*\\S.*') && noLink(s) && noBanned(s, site);
    }

    match /sites/{site}/posts/{post} {
      allow get: if on(site, 'likes') && validPost(post);   // no list: posts cannot be enumerated

      allow create: if on(site, 'likes') && validPost(post)
        && request.resource.data.keys().hasOnly(['count'])
        && request.resource.data.keys().hasAll(['count'])
        && request.resource.data.count == 1;

      allow update: if on(site, 'likes') && validPost(post)
        && request.resource.data.diff(resource.data).affectedKeys().hasOnly(['count'])
        && request.resource.data.count == resource.data.count + 1;

      match /comments/{cid} {
        // hidden comments are never served: a query must filter hidden == false (index: firebase/firestore.indexes.json)
        allow get, list: if on(site, 'comments') && validPost(post) && resource.data.hidden == false;

        allow create: if on(site, 'comments') && validPost(post)
          && cid.matches('^[A-Za-z0-9]{10,40}$')
          && request.resource.data.keys().hasOnly(['name', 'text', 'lang', 'by', 'createdAt', 'reports', 'hidden'])
          && request.resource.data.keys().hasAll(['name', 'text', 'lang', 'by', 'createdAt', 'reports', 'hidden'])
          && cleanText(request.resource.data.name, @NAME_MAX@, site)
          && cleanText(request.resource.data.text, @TEXT_MAX@, site)
          && request.resource.data.lang in cfg(site).get('langs', [])
          && request.resource.data.by is string
          && request.resource.data.by.matches('^[a-z0-9]{20,40}$')
          && request.resource.data.createdAt == request.time
          && request.resource.data.reports == 0
          && request.resource.data.hidden == false
          // the same batch must stamp this browser's post clock (sites/{site}/clients/{by}.lastAt == request.time)
          && getAfter(/databases/$(database)/documents/sites/$(site)/clients/$(request.resource.data.by)).data.lastAt == request.time;

        // report: +1 and nothing else; the comment hides itself when the count reaches hideAt(site)
        allow update: if on(site, 'comments') && on(site, 'reports') && validPost(post)
          && resource.data.hidden == false
          && request.resource.data.diff(resource.data).affectedKeys().hasOnly(['reports', 'hidden'])
          && request.resource.data.reports == resource.data.reports + 1
          && request.resource.data.hidden == (request.resource.data.reports >= hideAt(site));

        allow delete: if false;   // admin deletes in the console
      }
    }

    match /sites/{site}/clients/{token} {
      allow create: if on(site, 'comments') && token.matches('^[a-z0-9]{20,40}$')
        && request.resource.data.keys().hasOnly(['lastAt'])
        && request.resource.data.lastAt == request.time;
      allow update: if on(site, 'comments')
        && request.resource.data.keys().hasOnly(['lastAt'])
        && request.resource.data.lastAt == request.time
        && request.time > resource.data.lastAt + duration.value(minGap(site), 's');
      allow read, delete: if false;
    }

    match /{document=**} {
      allow read, write: if false;
    }
  }
}
"""


def rules_text(sites):
    """sites = {siteId: SiteConfig} (load_sites) → firestore.rules 전체 글자."""
    rx = lambda s: s.replace("\\", "\\\\")  # rules 문자열 안의 정규식: \ 를 두 번
    return (RULES_TEMPLATE.replace("@SITES@", _site_map(sites))
            .replace("@HIDE_AT@", str(HIDE_AT)).replace("@MIN_GAP@", str(MIN_GAP))
            .replace("@LINK@", rx(LINK_RE)).replace("@BANNED@", "|".join(BANNED_BASE))
            .replace("@NAME_MAX@", str(NAME_MAX)).replace("@TEXT_MAX@", str(TEXT_MAX)))


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if len(argv) == 2 and argv[0] == "rules":
        sys.stdout.write(rules_text(load_sites(argv[1])))
        return 0
    if len(argv) == 2 and argv[0] == "check":
        cfg = load(argv[1])
        print("OK %s — %s" % (cfg.site_id, "ON (%s)" % " ".join(FEATURES) if cfg.enabled else "OFF"))
        print("firebase/sites.json entry:")
        print(json.dumps({cfg.site_id: cfg.server_entry()}, ensure_ascii=False, indent=2))
        return 0
    sys.stderr.write("usage: python3 -m ipe_web_kit.community rules <sites.json> | check <community.json>\n")
    return 2


if __name__ == "__main__":
    sys.exit(main())
