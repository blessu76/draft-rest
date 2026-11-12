#!/usr/bin/env python3
"""릴리즈노트 — 원문(`ipe.release-note/1`) 읽기 · 작성 규칙 lint(RN01~RN14) · 사이트 병합 · 카드/번들 생성 · 웹 repo 게시(publish/flush) · 감사.

앱 repo 가 원문 `release_notes/<build>.json` 을 쓰고, 이 모듈이 (1) 규칙을 검사하고 (2) 웹 releases.json 에 항목 하나를 끼워 넣고
(3) 앱 번들 `assets/release_notes.json` 을 만든다. 정본 설계: _ipe/kit/release-notes-module-design.md · 규칙 정본: RELEASE_NOTES_GUIDE.md.
규칙 값은 data/release_rules.json. Python 표준 라이브러리만(웹·앱 repo 가 vendor 해서 쓴다).

    python3 <kit>/releases.py check   <file|dir|releases.json> [--build N] [--langs ko,en] [--require-langs ko,en] [--strict] [--all]
    python3 <kit>/releases.py draft   --build N --version 1.0.0 [--since <git-ref>] --out release_notes/N.json
    python3 <kit>/releases.py bundle  release_notes/ --out assets/release_notes.json
    python3 <kit>/releases.py publish --note release_notes/N.json --web-dir <dir> [--dry-run] [--app <name>]
    python3 <kit>/releases.py backlog --notes release_notes/ --web-dir <dir> [--max-age 24h] [--exclude-build N]
    python3 <kit>/releases.py flush
    python3 <kit>/releases.py audit   --apps <apps.tsv>

종료 코드: 0 통과 · 2 규칙 오류 · 3 원문 없음(초안 만들었음) · 4 밀린 노트. publish 는 0 + 상태 줄
`RELEASE_NOTE_PUBLISHED|QUEUED|PENDING build=N …` (웹 사정으로 업로드를 막지 않는다).
"""
import argparse
import copy
import datetime as dt
import fnmatch
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from collections import namedtuple
from pathlib import Path

if __package__ in (None, ""):  # `python3 tool/ipe_web_kit/releases.py` 로 바로 돌 때
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    __package__ = "ipe_web_kit"

from ipe_web_kit import ASSETS  # noqa: E402
from ipe_web_kit.localtime import with_localtime  # noqa: E402
from ipe_web_kit.seo import KST, esc  # noqa: E402
from ipe_web_kit.ui import inline_css, release_card  # noqa: E402
from ipe_web_kit.version import AppVersion  # noqa: E402

SCHEMA = "ipe.release-note/1"
RULES_FILE = Path(__file__).resolve().parent / "data" / "release_rules.json"
ID_RE = re.compile(r"^[A-Za-z0-9._-]+$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
DEFAULT_BLACKOUT = ["10:00-11:00", "13:00-14:30"]
BUNDLE_DROP = ("schema", "draft", "shots")

Problem = namedtuple("Problem", "level code lang index msg")


def _P(level, code, msg, lang=None, index=None):
    return Problem(level, code, lang, index, msg)


def rules():
    return json.loads(RULES_FILE.read_text(encoding="utf-8"))


# ── 모델 ────────────────────────────────────────────────────────────────────────

class Release:
    """릴리즈노트 항목 하나(원문 · 사이트 항목 공통). raw 는 원래 JSON(없는 칸·모르는 칸을 그대로 보존하려고 든다)."""

    def __init__(self, raw=None, source=None):
        self.raw = copy.deepcopy(raw) if raw else {}
        self.source = source
        self.legacy = False       # 일통기 .md · entries 처럼 옛 모양에서 읽었다

    # 칸 읽기 ────────────────────────────────────────────────────────────────
    @property
    def id(self):
        return str(self.raw.get("id") or "")

    @property
    def version(self):
        return str(self.raw.get("version") or "")

    @property
    def build(self):
        return str(self.raw.get("build") or "")

    @property
    def status(self):
        return str(self.raw.get("status") or "")

    @property
    def date(self):
        return str(self.raw.get("date") or "")

    @property
    def draft(self):
        return bool(self.raw.get("draft"))

    @property
    def notes(self):
        n = self.raw.get("notes")
        return n if isinstance(n, dict) else {}

    @property
    def build_int(self):
        return int(self.build) if self.build.isdigit() else -1

    def lines(self, lang, fallback="en"):
        """lang 의 항목, 없으면 fallback(en), 그것도 없으면 첫 언어 — 앱 linesFor 와 같은 폴백."""
        n = self.notes
        for k in (lang, fallback):
            if isinstance(n.get(k), list) and n[k]:
                return n[k]
        for v in n.values():
            if isinstance(v, list) and v:
                return v
        return []

    def to_dict(self):
        return copy.deepcopy(self.raw)

    def __repr__(self):
        return "Release(%s)" % (self.id or "?")


def _fill_ids(raw):
    """id 에서 version·build 를, version·build 에서 id 를 채운다(build 칸 없는 옛 사이트용)."""
    i = str(raw.get("id") or "")
    if i and (not raw.get("version") or not raw.get("build")):
        v, _, b = i.rpartition("-")
        if v and b.isdigit():
            raw.setdefault("version", v)
            raw.setdefault("build", b)
    if not raw.get("id") and raw.get("version") and raw.get("build"):
        raw["id"] = "%s-%s" % (raw["version"], raw["build"])
    return raw


def load_note(path):
    p = Path(path)
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise ValueError("%s: %s" % (p, e))
    if not isinstance(raw, dict):
        raise ValueError("%s: not an object" % p)
    return Release(raw, str(p))


_MD_BULLET = re.compile(r"^\s*(?:[-*•]\s+)(.+?)\s*$")


def _pubspec_version(start):
    """start(디렉터리) 와 그 위 두 단계에서 pubspec.yaml 의 `version: X+N` → AppVersion · 없으면 None."""
    d = Path(start).resolve()
    for cand in (d, d.parent, d.parent.parent):
        f = cand / "pubspec.yaml"
        if f.is_file():
            m = re.search(r"^version:\s*(\S+)", f.read_text(encoding="utf-8"), re.M)
            if m:
                return AppVersion.parse(m.group(1))
    return None


def _load_md_pair(d, build, langs, default_version):
    notes = {}
    for lang in langs:
        f = d / ("%s.%s.md" % (build, lang))
        items = []
        for line in f.read_text(encoding="utf-8").splitlines():
            m = _MD_BULLET.match(line)
            if m:
                items.append(m.group(1))
        notes[lang] = items
    mtime = dt.datetime.fromtimestamp(max((d / ("%s.%s.md" % (build, l))).stat().st_mtime for l in langs), KST)
    r = Release({"schema": SCHEMA, "id": "%s-%s" % (default_version, build), "version": default_version, "build": str(build),
                 "status": "testflight", "date": mtime.strftime("%Y-%m-%d"), "notes": notes}, str(d / ("%s.ko.md" % build)))
    r.legacy = True
    return r


def load_notes(directory, default_version=None):
    """디렉터리의 원문 → build 오름차순 Release 목록. `<N>.json` 이 있으면 그것, 없고 `<N>.ko.md`+`<N>.en.md` 면 일통기 어댑터."""
    d = Path(directory)
    out = {}
    if not d.is_dir():
        return []
    for f in d.glob("*.json"):
        if f.stem.isdigit():
            out[int(f.stem)] = load_note(f)
    mds = {}
    for f in d.glob("*.md"):
        m = re.match(r"^(\d+)\.([a-z]{2,3}(?:-[A-Za-z]+)?)\.md$", f.name)
        if m:
            mds.setdefault(int(m.group(1)), set()).add(m.group(2))
    for n, langs in mds.items():
        if n not in out and {"ko", "en"} <= langs:
            ps = _pubspec_version(d)
            ver = default_version or (ps.version if ps else "1.0.0")
            out[n] = _load_md_pair(d, n, sorted(langs, key=lambda x: (x not in ("ko", "en"), x)), ver)
    return [out[k] for k in sorted(out)]


class SiteDoc:
    """사이트 릴리즈 파일(`releases[]` 또는 일통기 `entries[]`) — raw 위에 Release 목록을 얹은 것."""

    def __init__(self, raw, key, releases, source=None):
        self.raw, self.key, self.releases, self.source = raw, key, releases, source

    @property
    def style(self):
        return self.key

    def by_id(self, rid):
        for r in self.releases:
            if r.id == rid:
                return r
        return None


def _split_lines(v):
    if isinstance(v, list):
        return v
    return [m.group(1) if m else s.strip() for s in str(v).splitlines() if s.strip()
            for m in [_MD_BULLET.match(s)]]


def _entry_to_release(e):
    """일통기 entries 항목 `{"build":"1.0.0+83","at":…,"ko":…,"en":…}` → Release(사이트 항목 모양)."""
    av = AppVersion.parse(e.get("build", ""))
    raw = {"id": "%s-%s" % (av.version, av.build) if av.build else av.version, "version": av.version, "build": av.build,
           "status": "testflight", "date": str(e.get("at", ""))[:10]}
    raw["notes"] = {k: _split_lines(v) for k, v in e.items() if k not in ("build", "at") and isinstance(v, (str, list))}
    r = Release(raw)
    r.legacy = True
    r.entry = copy.deepcopy(e)
    return r


def parse_site(text, source=None, default_key="releases"):
    raw = json.loads(text) if text.strip() else {}
    if not isinstance(raw, dict):
        raise ValueError("%s: top level must be an object" % (source or "releases file"))
    key = "entries" if ("entries" in raw and "releases" not in raw) else ("releases" if "releases" in raw else default_key)
    items = raw.get(key, [])
    if not isinstance(items, list):
        raise ValueError("%s: %r must be a list" % (source or "releases file", key))
    if key == "entries":
        rels = [_entry_to_release(e) for e in items]
    else:
        rels = [Release(_fill_ids(dict(e)), source) for e in items]
    return SiteDoc(raw, key, rels, source)


def load_site(path, style=None):
    p = Path(path)
    if not p.exists():
        return SiteDoc({}, style or "releases", [], str(p))
    return parse_site(p.read_text(encoding="utf-8"), str(p), style or "releases")


# ── lint ───────────────────────────────────────────────────────────────────────

_MD_PATTERNS = [(re.compile(r"\*\*|__"), "굵게(**)"), (re.compile(r"`"), "백틱"), (re.compile(r"^\s*#{1,6}\s"), "제목(#)"),
                (re.compile(r"\[[^\]]*\]\([^)]*\)"), "마크다운 링크"), (re.compile(r"^\s*[-*•]\s"), "앞머리 글머리표"),
                (re.compile(r"</?[A-Za-z][^>]*>"), "HTML 태그"), (re.compile(r"https?://|www\."), "URL")]


def _word_hit(text, words):
    for w in words:
        if re.search(r"(?<![A-Za-z0-9])%s(?![A-Za-z0-9])" % re.escape(w), text, re.I):
            return w
    return None


def _term_hit(text, table):
    for w in table.get("substr", []):
        if w in text:
            return w
    w = _word_hit(text, table.get("word", []))
    if w:
        return w
    for rx in table.get("regex", []):
        m = re.search(rx, text, re.I)
        if m:
            return m.group(0)
    return None


def _is_fix(text, lang, R):
    p = R["fix_prefix"].get(lang)
    return bool(p) and text.lstrip().startswith(p)


def lint(note, langs=None, rules_=None, strict=False, prev=None, site=False, content=True):
    """Release → [Problem]. langs = 필수 언어(기본 ko,en). site=True 면 사이트 항목(schema 칸 · 옛 status 허용).
    content=False 면 구조 규칙(RN01~RN04)만 — 사이트 옛 항목 전체를 검사할 때."""
    R = rules_ or rules()
    langs = tuple(langs or R["required_langs"])
    P = []
    raw = note.raw
    # RN01 스키마·칸
    if not site and raw.get("schema") != SCHEMA:
        P.append(_P("error", "RN01", "schema 는 %r 이어야 한다(지금 %r)" % (SCHEMA, raw.get("schema"))))
    for k in ("id", "version", "build", "status", "date"):
        if not raw.get(k):
            P.append(_P("error", "RN01", "필수 칸 %s 없음" % k))
    if note.id and not ID_RE.match(note.id):
        P.append(_P("error", "RN01", "id 에 허용되지 않은 글자(A-Z a-z 0-9 . _ - 만)"))
    if note.build and not note.build.isdigit():
        P.append(_P("error", "RN01", "build 는 숫자 문자열이어야 한다(%r)" % note.build))
    if note.id and note.version and note.build and note.id != "%s-%s" % (note.version, note.build):
        P.append(_P("error", "RN01", "id %r 가 version-build(%s-%s) 와 다름" % (note.id, note.version, note.build)))
    allowed = list(R["statuses"]) + (R["site_extra_statuses"] if site else [])
    if note.status and note.status not in allowed:
        P.append(_P("error", "RN01", "status %r 는 %s 중 하나여야 한다" % (note.status, "·".join(allowed))))
    if note.date and not DATE_RE.match(note.date):
        P.append(_P("error", "RN01", "date 는 YYYY-MM-DD(KST) 여야 한다(%r)" % note.date))
    if not isinstance(raw.get("notes"), dict):
        P.append(_P("error", "RN01", "notes 는 {언어: [문장…]} 이어야 한다"))
    for lang, v in note.notes.items():
        if not (isinstance(v, list) and all(isinstance(s, str) for s in v)):
            P.append(_P("error", "RN01", "notes.%s 는 문장 목록이어야 한다" % lang, lang))
    # RN02 draft
    if note.draft:
        P.append(_P("error", "RN02", "draft: true 가 남아 있다 — 문장을 직접 쓰고 draft 칸을 지운다(검토 끝 표시)"))
    notes = {k: v for k, v in note.notes.items() if isinstance(v, list) and all(isinstance(s, str) for s in v)}
    # RN03 필수 언어
    for lang in langs:
        if not notes.get(lang):
            P.append(_P("error", "RN03", "필수 언어 %s 의 항목이 없다" % lang, lang))
    # RN04 언어별 항목 수
    counts = {k: len(v) for k, v in notes.items() if v}
    if len(set(counts.values())) > 1:
        P.append(_P("error", "RN04", "언어별 항목 수가 다르다: " + ", ".join("%s=%d" % kv for kv in sorted(counts.items()))))
    if not content:
        return P
    mn, mx = R["items"]["min"], R["items"]["max"]
    for lang, items in notes.items():
        if not items:
            continue
        # RN05
        if len(items) > mx:
            P.append(_P("error", "RN05", "항목이 %d개 — %d개를 넘으면 합치거나 줄인다" % (len(items), mx), lang))
        elif len(items) < mn:
            P.append(_P("error" if strict else "warn", "RN05", "항목이 %d개 — %d~%d개가 권장" % (len(items), mn, mx), lang))
        limit = R["max_chars"].get(lang, R["max_chars"]["default"])
        for i, t in enumerate(items):
            s = t.strip()
            # RN06
            if len(s) > limit:
                P.append(_P("error", "RN06", "%d자 — %s 는 %d자 이하" % (len(s), lang, limit), lang, i))
            # RN07
            for rx, label in _MD_PATTERNS:
                if rx.search(t):
                    P.append(_P("error", "RN07", "%s 는 쓰지 않는다(앱·웹이 일반 글자로 그린다)" % label, lang, i))
                    break
            # RN08
            w = _term_hit(t, R["internal_words"])
            if w:
                P.append(_P("error", "RN08", "내부 말 %r — 테스터가 읽는 말만 쓴다" % w, lang, i))
            # RN09
            w = _term_hit(t, R["hype_words"])
            if w:
                P.append(_P("warn", "RN09", "과장 말 %r" % w, lang, i))
            # RN12
            if lang == "ko" and not s.endswith(tuple(R["ko_endings"])):
                P.append(_P("warn", "RN12", "ko 는 존댓말(…요. / …니다.)로 끝낸다", lang, i))
            if lang == "en" and s[:1].islower():
                P.append(_P("warn", "RN12", "en 은 대문자로 시작한다", lang, i))
    # RN10 수정 접두어 짝 · RN11 순서
    ko, en = notes.get("ko") or [], notes.get("en") or []
    if len(ko) == len(en):
        for i, (a, b) in enumerate(zip(ko, en)):
            if _is_fix(a, "ko", R) != _is_fix(b, "en", R):
                P.append(_P("warn", "RN10", "수정 접두어(%s / %s)가 ko·en 짝이 안 맞는다" % (R["fix_prefix"]["ko"], R["fix_prefix"]["en"]), None, i))
    for lang in ("ko", "en"):
        seen_fix = False
        for i, t in enumerate(notes.get(lang) or []):
            if _is_fix(t, lang, R):
                seen_fix = True
            elif seen_fix:
                P.append(_P("warn", "RN11", "추가·개선 항목이 수정 항목 뒤에 있다(추가 → 개선 → 수정 순)", lang, i))
                break
    # RN13 바로 앞 빌드와 같은 문장
    if prev is not None:
        for lang in ("ko", "en"):
            before = {s.strip() for s in prev.notes.get(lang, []) if isinstance(s, str)}
            for i, t in enumerate(notes.get(lang) or []):
                if t.strip() in before:
                    P.append(_P("warn", "RN13", "앞 빌드(%s)와 같은 문장 — 복사 실수?" % prev.id, lang, i))
    return P


def todo(site, langs):
    """번역이 안 된 (id, lang) — 웹 방 할 일. prep 는 뺀다."""
    out = []
    for r in site.releases:
        if r.status == "prep":
            continue
        for lang in langs:
            if not (isinstance(r.notes.get(lang), list) and r.notes.get(lang)):
                out.append((r.id, lang))
    return out


def lint_site(site, langs=None, rules_=None, strict=False, build=None, check_all=False, site_langs=None):
    """사이트 파일 검사 — 모든 항목에 구조 규칙, 고른 항목(--build / 최신 / --all)에 전체 규칙, 번역 누락은 RN14 경고."""
    R = rules_ or rules()
    P = []
    ordered = sorted(site.releases, key=lambda r: r.build_int)
    chosen = ordered if check_all else ([r for r in ordered if r.build == str(build)] if build is not None else ordered[-1:])
    if build is not None and not chosen:
        P.append(_P("error", "RN01", "build %s 항목이 사이트에 없다" % build))
    seen = {}
    for r in ordered:
        for p in lint(r, langs, R, strict, prev=None, site=True, content=False) if r not in chosen else \
                lint(r, langs, R, strict, prev=_prev_of(ordered, r), site=True):
            P.append(Problem(p.level, p.code, p.lang, p.index, "%s: %s" % (r.id or "?", p.msg)))
        if r.id in seen:
            P.append(_P("error", "RN01", "%s: id 가 중복이다" % r.id))
        seen[r.id] = 1
    for rid, lang in todo(site, site_langs or ()):
        P.append(_P("warn", "RN14", "%s: %s 번역 없음 — 웹 방 할 일(en 으로 보인다)" % (rid, lang), lang))
    return P


def _prev_of(ordered, r):
    i = ordered.index(r)
    return ordered[i - 1] if i > 0 else None


# ── 병합 · 쓰기 ────────────────────────────────────────────────────────────────

def _site_item(note):
    d = copy.deepcopy(note.raw)
    for k in list(d):
        if k in BUNDLE_DROP or k.startswith("_"):
            del d[k]
    return d


def merge(site, note):
    """원문 → 사이트 upsert(id 기준). 원문에 없는 언어(번역)·모르는 칸은 보존. 바뀌었으면 True."""
    item = _site_item(note)
    cur = site.by_id(note.id)
    if cur is None:
        r = Release(item)
        r.legacy = site.key == "entries"
        if r.legacy:
            r.entry = None
        rels = site.releases
        pos = len(rels)
        for i, o in enumerate(rels):          # 최신(큰 빌드)이 위로
            if o.build_int < r.build_int:
                pos = i
                break
        rels.insert(pos, r)
        return True
    before = copy.deepcopy(cur.raw)
    for k, v in item.items():
        if k in ("notes", "title", "intro") and isinstance(v, dict) and isinstance(cur.raw.get(k), dict):
            for lang, val in v.items():
                cur.raw[k][lang] = val
        else:
            cur.raw[k] = v
    if cur.raw == before:
        return False
    if getattr(cur, "entry", None) is not None:
        cur.entry = None                       # 다시 만들어 쓴다
    return True


def _entry_of(r):
    e = copy.deepcopy(getattr(r, "entry", None)) or {}
    if r.legacy and getattr(r, "entry", None) is not None and _entry_to_release(e).raw["notes"] == r.notes:
        return e
    av = AppVersion(r.version, r.build)
    e["build"] = "%s+%s" % (r.version, r.build) if r.build else r.version
    e.setdefault("at", r.date)
    for lang, items in r.notes.items():
        e[lang] = items if not isinstance(e.get(lang), str) else "\n".join(items)
    return e


def dumps_site(site, style=None):
    style = style or site.key
    doc = copy.deepcopy(site.raw)
    doc.pop("releases", None)
    doc.pop("entries", None)
    if style == "entries":
        doc["entries"] = [_entry_of(r) for r in site.releases]
    else:
        doc["releases"] = [r.to_dict() for r in site.releases]
    return json.dumps(doc, ensure_ascii=False, indent=2) + "\n"


def dump_site(site, path, style=None):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(dumps_site(site, style), encoding="utf-8")


# ── 그리기 · 번들 ──────────────────────────────────────────────────────────────

_EN_FIRST = {"ko": "일부 항목은 영어로 먼저 보여 드려요", "en": "Some notes are shown in English first"}


def _when(r):
    """게시 시각 aware datetime + 날짜만 있으면 보일 글자."""
    at = str(r.raw.get("at") or r.date or "")
    for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M%z", "%Y-%m-%d %H:%M:%S%z"):
        try:
            return dt.datetime.strptime(at, fmt), None
        except ValueError:
            pass
    try:
        d = dt.datetime.strptime(at[:10], "%Y-%m-%d").replace(tzinfo=KST)
    except ValueError:
        d = dt.datetime(1970, 1, 1, tzinfo=KST)
    return d, at[:10]


def visible(site):
    return sorted((r for r in site.releases if r.status != "prep" and not r.draft), key=lambda r: -r.build_int)


def cards_html(site, lang, strings=None):
    """`ui.release_card` 반복 — 사이트 템플릿에 끼운다. lang 원문이 없으면 en 문장을 `<li lang="en">` 로."""
    out = []
    fell_back = False
    for r in visible(site):
        own = r.notes.get(lang)
        if isinstance(own, list) and own:
            items = list(own)
        else:
            items = [(t, "en") for t in r.lines(lang)] if lang != "en" else list(r.lines("en"))
            fell_back = fell_back or lang != "en"
        when, text = _when(r)
        out.append(release_card(AppVersion(r.version, r.build), when, items, at_text=text))
    if fell_back:
        s = (strings or {}).get("en_first") or _EN_FIRST.get(lang) or _EN_FIRST["en"]
        out.insert(0, '<p class="ipe-rel__note">%s</p>' % esc(s))
    return "\n".join(out)


def page_html(site, lang, site_title, strings=None):
    """빌더 없는 사이트용 완성 페이지(릴리즈 노트 한 장)."""
    strings = strings or {}
    head = strings.get("heading") or "Release notes"
    page = ('<!doctype html>\n<html lang="%s">\n<head>\n<meta charset="utf-8">\n'
            '<meta name="viewport" content="width=device-width,initial-scale=1">\n<title>%s — %s</title>\n%s\n</head>\n<body>\n'
            '<main>\n<h1>%s</h1>\n%s\n</main>\n</body>\n</html>\n'
            % (esc(lang), esc(head), esc(site_title), inline_css(), esc(head), cards_html(site, lang, strings)))
    return with_localtime(page)


def bundle(notes, path=None, keep=None):
    """원문 목록 → 앱 번들 `{"releases":[…]}` (status != prep · draft 제외 · build 내림차순 최신 keep 개). path 가 있으면 쓴다."""
    keep = keep or rules()["bundle_keep"]
    rels = sorted((n for n in notes if n.status != "prep" and not n.draft), key=lambda n: -n.build_int)[:keep]
    items = []
    for n in rels:
        d = n.to_dict()
        for k in list(d):
            if k in BUNDLE_DROP or k.startswith("_"):
                del d[k]
        items.append(d)
    doc = {"releases": items}
    if path:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return doc


def make_draft(build, version, since=None, repo=None):
    """초안 — git log 제목을 옮기지 않는다. 자리표 문장 + `draft: true` (RN02 로 반드시 실패 → 사람이 문장을 쓰고 표시를 지운다)."""
    d = {"schema": SCHEMA, "id": "%s-%s" % (version, build), "version": version, "build": str(build), "status": "testflight",
         "date": dt.datetime.now(KST).strftime("%Y-%m-%d"), "draft": True,
         "notes": {"ko": ["여기에 테스터가 알아챌 변화를 쓰세요."] * 3, "en": ["Write here what testers will notice."] * 3}}
    if since:
        r = subprocess.run(["git", "-C", str(repo or "."), "rev-list", "--count", "%s..HEAD" % since], capture_output=True, text=True)
        if r.returncode == 0:
            d["_hint"] = "%s 이후 커밋 %s개 — 제목을 옮기지 말고 테스터가 알아챌 변화만 쓴다" % (since, r.stdout.strip())
    return d


# ── 웹 repo 게시 ───────────────────────────────────────────────────────────────

PublishResult = namedtuple("PublishResult", "status build detail")


def _line(res):
    d = " ".join("%s=%s" % kv for kv in res.detail.items())
    return "RELEASE_NOTE_%s build=%s%s" % (res.status, res.build, " " + d if d else "")


PublishResult.line = _line


def _git(cwd, *args, check=True):
    env = dict(os.environ, GIT_TERMINAL_PROMPT="0")
    r = subprocess.run(["git", "-C", str(cwd)] + list(args), capture_output=True, text=True, env=env)
    if check and r.returncode != 0:
        raise RuntimeError("git %s: %s" % (" ".join(args), (r.stderr or r.stdout).strip()))
    return r


def default_config():
    return {"releases_file": "content/releases.json", "style": "releases", "langs": ["en", "ko"], "build": "", "check": "",
            "commit_paths": ["content/releases.json"], "push_blackout": None, "branch": "main"}


def web_config(text):
    cfg = default_config()
    if text:
        cfg.update(json.loads(text))
    if not cfg.get("push_blackout"):
        cfg["push_blackout"] = rules().get("push_blackout") or DEFAULT_BLACKOUT
    return cfg


def _web_config_at(web_dir, ref):
    r = _git(web_dir, "show", "%s:ipe_release.json" % ref, check=False)
    return web_config(r.stdout if r.returncode == 0 else "")


def _aware(t):
    """시간대 없는 시각은 KST(+09:00) 로 본다 — aware 인 값은 그대로."""
    return t.replace(tzinfo=KST) if t.tzinfo is None else t


def _parse_window(w):
    """`HH:MM-HH:MM`(KST) → (시작, 끝). 자정을 넘는 창(`23:00-01:00`)도 된다. 모양이 틀리거나 시작=끝이면 ValueError."""
    m = re.match(r"^\s*(\d{1,2}):(\d{2})\s*-\s*(\d{1,2}):(\d{2})\s*$", str(w))
    if not m:
        raise ValueError("push_blackout 창 %r: HH:MM-HH:MM 모양이어야 한다" % (w,))
    h1, m1, h2, m2 = (int(x) for x in m.groups())
    if h1 > 23 or h2 > 23 or m1 > 59 or m2 > 59:
        raise ValueError("push_blackout 창 %r: 시각 범위 밖" % (w,))
    a, b = dt.time(h1, m1), dt.time(h2, m2)
    if a == b:
        raise ValueError("push_blackout 창 %r: 시작과 끝이 같다" % (w,))
    return a, b


def blackout_until(now, windows):
    """now 가 금지 창 안이면 끝나는 시각 글자(KST HH:MM), 아니면 None. 시간대 없는 now 는 KST. 창이 틀리면 ValueError."""
    t = _aware(now).astimezone(KST).time().replace(second=0, microsecond=0)
    hit = None
    for w in windows:
        a, b = _parse_window(w)
        if (a <= t < b) if a < b else (t >= a or t < b):
            hit = hit or b.strftime("%H:%M")
    return hit


def queue_dir():
    return Path(os.environ.get("IPE_RELEASE_QUEUE_DIR") or Path.home() / ".ipe" / "release-queue")


def _now():
    v = os.environ.get("IPE_RELEASE_NOW")
    return _aware(dt.datetime.fromisoformat(v)) if v else dt.datetime.now(KST)


def _run_shell(cmd, cwd):
    """⚠️ 웹 repo `ipe_release.json` 의 build·check 글자를 **shell=True 로 그대로 실행**한다(그 repo origin/main 에 쓸 수 있는 사람은 이 머신에서 명령을
    돌릴 수 있다). 웹 repo 가 우리 것일 때만 쓴다 — 남의 repo 를 `--web-dir` 로 가리키지 않는다. 동작은 바꾸지 않았다(필요한 build 가 셸 문장이라서)."""
    r = subprocess.run(cmd, shell=True, cwd=str(cwd), capture_output=True, text=True, timeout=600)
    return r.returncode == 0, (r.stdout + r.stderr).strip()


def _fetch_config(web):
    """origin/main 을 받아 웹 설정(ipe_release.json)을 읽고, 설정의 branch 가 main 이 아니면 그 브랜치도 받아 거기서 다시 읽는다.
    origin/<branch> 가 없으면 None."""
    _git(web, "fetch", "-q", "origin", "main", check=False)
    has_main = _git(web, "rev-parse", "--verify", "-q", "origin/main", check=False).returncode == 0
    cfg = _web_config_at(web, "origin/main") if has_main else default_config()
    branch = cfg["branch"]
    if branch != "main" or not has_main:
        _git(web, "fetch", "-q", "origin", branch, check=False)
        if _git(web, "rev-parse", "--verify", "-q", "origin/%s" % branch, check=False).returncode != 0:
            return None
        cfg = _web_config_at(web, "origin/%s" % branch)
        cfg["branch"] = branch
    return cfg


LINK_IGNORED_DEFAULT = ("vendor", "node_modules")
_SECRET_NAME = re.compile(r"(^\.env($|\.)|\.env$|\.(key|pem|p12|pfx)$|^id_(rsa|dsa|ecdsa|ed25519)|secret|credential)", re.I)


def _link_ignored(web, wt, extra=()):
    """웹 작업 트리의 gitignore 된 설치물은 새 worktree 에 따라오지 않는다 — build·check 가 쓰므로 **허용 목록**만 원본으로 심볼릭 링크를 건다
    (기본 vendor·node_modules + 웹 `ipe_release.json` 의 `link_ignored` 목록). .env·*.key·*.pem 같은 비밀 이름과 repo 밖을 가리키는 경로(절대·..)는
    목록에 있어도 거부한다. gitignore 된 경로·원본에 있는 경로만, 이미 worktree 에 있으면 건드리지 않는다.
    ⚠️ 링크 동안 build·check 가 그 폴더에 쓰면 원본이 바뀐다. 돌려주는 값: 만든 링크(끝나면 `_unlink`)."""
    made = []
    for rel in list(LINK_IGNORED_DEFAULT) + [str(x) for x in (extra or ())]:
        rel = rel.strip().strip("/")
        parts = rel.split("/")
        if not rel or rel.startswith("/") or ".." in parts or ".git" in parts or any(_SECRET_NAME.search(x) for x in parts):
            continue
        src, dst = Path(web) / rel, Path(wt) / rel
        if dst.exists() or dst.is_symlink() or not src.exists():
            continue
        if _git(web, "check-ignore", "-q", rel + "/" if src.is_dir() else rel, check=False).returncode != 0:
            continue
        try:
            dst.parent.mkdir(parents=True, exist_ok=True)
            os.symlink(str(src.resolve()), str(dst))
            made.append(dst)
        except OSError:
            continue
    return made


def _unlink(links):
    for l in links:
        try:
            os.unlink(str(l))
        except OSError:
            pass


def _allowed(path, patterns):
    return any(fnmatch.fnmatch(path, p) for p in patterns)


def _publish_once(note, web_dir, cfg, app, dry_run, clock=None):
    """origin/<branch> 위 임시 worktree 에서 한 번. 돌려주는 값: PublishResult · 'retry'(push 거절) · 'queue:HH:MM'(push 직전 금지 창에 들어섬 — build 가 오래 걸린 경우)."""
    web = Path(web_dir)
    branch = cfg["branch"]
    common = Path(_git(web, "rev-parse", "--path-format=absolute", "--git-common-dir").stdout.strip())
    wt = common / "ipe-release-wt" / ("%s-%d" % (re.sub(r"[^A-Za-z0-9._-]", "_", note.id), os.getpid()))
    wt.parent.mkdir(parents=True, exist_ok=True)
    _git(web, "worktree", "add", "--detach", str(wt), "origin/%s" % branch)
    try:
        site = load_site(wt / cfg["releases_file"], cfg["style"])
        if not (wt / cfg["releases_file"]).exists():
            site.key = cfg["style"]
        if not merge(site, note):
            return PublishResult("PUBLISHED", note.build, {"web": "noop"})
        dump_site(site, wt / cfg["releases_file"], cfg["style"])
        links = _link_ignored(web, wt, cfg.get("link_ignored")) if (cfg.get("build") or cfg.get("check")) else []
        try:
            for step in ("build", "check"):
                if cfg.get(step):
                    ok, out = _run_shell(cfg[step], wt)
                    if not ok:
                        return PublishResult("PENDING", note.build, {"reason": "check" if step == "check" else "build"})
        finally:
            _unlink(links)
        changed = [l[3:].strip().strip('"') for l in _git(wt, "status", "--porcelain", "--untracked-files=all").stdout.splitlines()]
        bad = [c for c in changed if not _allowed(c, cfg["commit_paths"])]
        if bad:
            return PublishResult("PENDING", note.build, {"reason": "paths", "files": ",".join(bad[:5])})
        if dry_run:
            return PublishResult("DRYRUN", note.build, {"files": ",".join(changed)})
        until = blackout_until((clock or _now)(), cfg["push_blackout"])
        if until:
            return "queue:" + until
        _git(wt, "add", "--", *changed)
        ident = []
        if not _git(wt, "config", "user.email", check=False).stdout.strip():
            ident = ["-c", "user.name=ipe-release", "-c", "user.email=release@ipe.rest"]
        _git(wt, *ident, "commit", "-q", "-m", "release: %s+%s 릴리즈노트 (from %s)" % (note.version, note.build, app))
        p = _git(wt, "push", "origin", "HEAD:%s" % branch, check=False)
        if p.returncode != 0:
            return "retry"
        return PublishResult("PUBLISHED", note.build, {"web": _git(wt, "rev-parse", "--short", "HEAD").stdout.strip()})
    finally:
        _git(web, "worktree", "remove", "--force", str(wt), check=False)
        shutil.rmtree(str(wt), ignore_errors=True)
        _git(web, "worktree", "prune", check=False)


def publish(note, web_dir, app=None, dry_run=False, now=None, queue=True):
    """원문 하나를 웹 repo origin/main 에 반영. 웹 사정(검사 실패·경로 밖·금지 창·push 실패)은 PENDING/QUEUED 로 돌려줄 뿐 raise 하지 않는다."""
    injected = now is not None or bool(os.environ.get("IPE_RELEASE_NOW"))
    now = _aware(now) if now is not None else _now()
    web = Path(web_dir)
    app = app or Path(note.source or ".").resolve().parent.parent.name
    if note.status == "prep":
        return PublishResult("PUBLISHED", note.build, {"web": "skipped-prep"})
    try:
        cfg = _fetch_config(web)
        if cfg is None:
            return PublishResult("PENDING", note.build, {"reason": "no-origin-main"})
        branch = cfg["branch"]

        def enqueue(until):
            if queue:
                q = queue_dir()
                q.mkdir(parents=True, exist_ok=True)
                f = q / ("%s-%s.json" % (web.resolve().name, note.id))
                f.write_text(json.dumps({"web_dir": str(web.resolve()), "app": app, "queued_at": now.isoformat(),
                                         "note": note.to_dict()}, ensure_ascii=False, indent=2), encoding="utf-8")
            return PublishResult("QUEUED", note.build, {"until": until})

        until = blackout_until(now, cfg["push_blackout"])
        if until and not dry_run:
            return enqueue(until)
        clock = (lambda: now) if injected else _now
        for _ in range(3):
            res = _publish_once(note, web, cfg, app, dry_run, clock)
            if isinstance(res, str) and res.startswith("queue:"):
                return enqueue(res[6:])
            if res != "retry":
                return res
            _git(web, "fetch", "-q", "origin", branch, check=False)
        return PublishResult("PENDING", note.build, {"reason": "push"})
    except (RuntimeError, OSError, ValueError, subprocess.TimeoutExpired) as e:
        return PublishResult("PENDING", note.build, {"reason": "error", "msg": str(e).replace("\n", " ")[:120]})


def flush(now=None):
    """큐의 노트를 금지 창 밖일 때 게시 — [(파일, PublishResult)]. PUBLISHED 는 큐에서 지운다. 깨진 큐 파일은 PENDING reason=queue-file 로 남기고 건드리지 않는다."""
    now = _aware(now) if now is not None else _now()
    out = []
    q = queue_dir()
    for f in sorted(q.glob("*.json")) if q.is_dir() else []:
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
            if not isinstance(d, dict) or not isinstance(d.get("note"), dict) or not d.get("web_dir"):
                raise ValueError("queue file shape")
            note = Release(d["note"], str(f))
            res = publish(note, d["web_dir"], app=d.get("app"), now=now, queue=False)
        except (OSError, ValueError, KeyError, TypeError) as e:
            out.append((f, PublishResult("PENDING", "?", {"reason": "queue-file", "msg": str(e)[:80]})))
            continue
        if res.status == "PUBLISHED":
            f.unlink()
        out.append((f, res))
    return out


def web_site_at_origin(web_dir):
    """웹 origin/<설정 branch> 의 사이트 파일 → (SiteDoc 또는 None, cfg). 호출 전에 fetch 했다고 본다."""
    cfg = _web_config_at(web_dir, "origin/main")
    ref = "origin/%s" % cfg["branch"]
    if ref != "origin/main":
        cfg = _web_config_at(web_dir, ref)
    r = _git(web_dir, "show", "%s:%s" % (ref, cfg["releases_file"]), check=False)
    return (parse_site(r.stdout, cfg["releases_file"], cfg["style"]) if r.returncode == 0 else None), cfg


def backlog(notes, web_dir, max_age=dt.timedelta(hours=24), exclude_build=None, now=None, fetch=True):
    """웹에 아직 없는 원문 [(Release, 나이)] — 나이 = 지금 − 원문 date 00:00 KST. 나이가 max_age 를 넘은 것만 `blocking` 으로."""
    now = _aware(now) if now is not None else _now()
    if fetch:
        _fetch_config(Path(web_dir))
    site, _ = web_site_at_origin(web_dir)
    have = {r.id for r in site.releases} if site else set()
    missing = []
    for n in notes:
        if n.status == "prep" or n.draft or n.id in have or (exclude_build is not None and n.build == str(exclude_build)):
            continue
        try:
            born = dt.datetime.strptime(n.date, "%Y-%m-%d").replace(tzinfo=KST)
        except ValueError:
            born = now
        missing.append((n, now - born))
    return missing, [m for m in missing if m[1] > max_age]


def read_apps(tsv):
    """apps.tsv — `이름<TAB>앱 repo 경로<TAB>웹 repo 경로` (# 주석)."""
    rows = []
    for line in Path(tsv).read_text(encoding="utf-8").splitlines():
        if line.strip() and not line.lstrip().startswith("#"):
            p = line.split("\t")
            if len(p) >= 3:
                rows.append((p[0].strip(), Path(p[1].strip()).expanduser(), Path(p[2].strip()).expanduser()))
    return rows


def audit(rows, now=None, queue_max_age=dt.timedelta(hours=6)):
    """앱별 origin/main pubspec 빌드 vs 웹 origin/main 최신 id · 큐 6시간+ · 번역 누락 수 → [(이름, 줄, 문제 있음?)]."""
    now = _aware(now) if now is not None else _now()
    out = []
    for name, app, web in rows:
        notes = []
        try:
            _git(app, "fetch", "-q", "origin", check=False)
            r = _git(app, "show", "origin/main:pubspec.yaml", check=False)
            text = r.stdout if r.returncode == 0 else (app / "pubspec.yaml").read_text(encoding="utf-8")
            m = re.search(r"^version:\s*(\S+)", text, re.M)
            app_av = AppVersion.parse(m.group(1)) if m else AppVersion("")
            _fetch_config(web)
            site, cfg = web_site_at_origin(web)
        except (OSError, RuntimeError) as e:
            out.append((name, "%s ERROR %s" % (name, str(e)[:80]), True))
            continue
        bad = False
        latest = max(visible(site), key=lambda r: r.build_int) if site and visible(site) else None
        web_build = latest.build_int if latest else -1
        if app_av.build.isdigit() and int(app_av.build) > web_build:
            bad = True
            notes.append("BEHIND 앱 %s / 웹 %s" % (app_av.build, latest.build if latest else "-"))
        else:
            notes.append("앱 %s / 웹 %s" % (app_av.build or "-", latest.build if latest else "-"))
        q = queue_dir()
        for f in sorted(q.glob("%s-*.json" % web.resolve().name)) if q.is_dir() else []:
            try:
                age = now - _aware(dt.datetime.fromisoformat(json.loads(f.read_text(encoding="utf-8"))["queued_at"]))
            except (OSError, ValueError, KeyError, TypeError):
                continue
            if age > queue_max_age:
                bad = True
                notes.append("QUEUE %s %dh" % (f.stem.split("-", 1)[1], age.total_seconds() // 3600))
        miss = todo(site, cfg["langs"]) if site else []
        if miss:
            notes.append("번역 누락 %d" % len(miss))
        out.append((name, "%s %s %s" % ("WARN" if bad else "OK", name, " · ".join(notes)), bad))
    return out


# ── CLI ────────────────────────────────────────────────────────────────────────

def _report(problems, label):
    for p in problems:
        where = (" %s" % p.lang if p.lang else "") + ("#%d" % (p.index + 1) if p.index is not None else "")
        print("  %s %s%s: %s" % ("ERROR" if p.level == "error" else "WARN ", p.code, where, p.msg))
    errs = sum(1 for p in problems if p.level == "error")
    warns = len(problems) - errs
    print("%s %s — %d error(s) · %d warning(s)" % ("FAIL" if errs else "OK", label, errs, warns))
    return 2 if errs else 0


def _langs(s):
    return tuple(x.strip() for x in s.split(",") if x.strip()) if s else None


def _parse_age(s):
    m = re.match(r"^(\d+)\s*([hmd])$", s.strip())
    if not m:
        raise SystemExit("--max-age: 24h · 90m · 2d")
    return dt.timedelta(**{{"h": "hours", "m": "minutes", "d": "days"}[m.group(2)]: int(m.group(1))})


def _cmd_check(a):
    p = Path(a.path)
    req = _langs(a.require_langs) or _langs(a.langs)
    if p.is_dir():
        notes = load_notes(p)
        if a.build is not None:
            chosen = [n for n in notes if n.build == str(a.build)]
            if not chosen:
                ps = _pubspec_version(p)
                if ps and ps.build == str(a.build):
                    out = p / ("%s.json" % a.build)
                    p.mkdir(parents=True, exist_ok=True)
                    out.write_text(json.dumps(make_draft(a.build, ps.version), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
                    print("MISSING %s — 초안을 만들었다(draft). 문장을 직접 쓰고 draft 칸을 지운다." % out)
                else:
                    print("MISSING %s/%s.json — 원문이 없다" % (p, a.build))
                return 3
        else:
            chosen = notes if a.all else notes[-1:]
        if not chosen:
            print("MISSING %s — 원문이 하나도 없다" % p)
            return 3
        rc = 0
        by_build = {n.build_int: n for n in notes}
        for n in chosen:
            prev = max((b for b in by_build if b < n.build_int), default=None)
            probs = lint(n, req, strict=a.strict, prev=by_build.get(prev))
            if n.source and Path(n.source).stem.split(".")[0].isdigit() and Path(n.source).stem.split(".")[0] != n.build:
                probs.append(_P("error", "RN01", "파일 이름의 빌드(%s)와 build 칸(%s)이 다르다" % (Path(n.source).stem.split(".")[0], n.build)))
            rc = max(rc, _report(probs, "%s%s" % (n.id, " (옛 .md)" if n.legacy else "")))
        return rc
    text = p.read_text(encoding="utf-8")
    top = json.loads(text)
    if isinstance(top, dict) and top.get("schema") == SCHEMA:
        n = load_note(p)
        return _report(lint(n, req, strict=a.strict), n.id or str(p))
    site = parse_site(text, str(p))
    probs = lint_site(site, req, strict=a.strict, build=a.build, check_all=a.all, site_langs=_langs(a.site_langs))
    return _report(probs, "%s (%d releases)" % (p, len(site.releases)))


def main(argv=None):
    ap = argparse.ArgumentParser(description="ipe 릴리즈노트 — lint · 게시 · 번들", formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("check")
    c.add_argument("path")
    c.add_argument("--build")
    c.add_argument("--langs")
    c.add_argument("--require-langs")
    c.add_argument("--site-langs", help="번역 누락(RN14)을 셀 언어 — 사이트 파일 검사용")
    c.add_argument("--strict", action="store_true")
    c.add_argument("--all", action="store_true")
    d = sub.add_parser("draft")
    d.add_argument("--build", required=True)
    d.add_argument("--version", required=True)
    d.add_argument("--since")
    d.add_argument("--out", required=True)
    b = sub.add_parser("bundle")
    b.add_argument("notes")
    b.add_argument("--out", required=True)
    b.add_argument("--keep", type=int)
    pb = sub.add_parser("publish")
    pb.add_argument("--note", required=True)
    pb.add_argument("--web-dir", required=True)
    pb.add_argument("--app")
    pb.add_argument("--dry-run", action="store_true")
    bl = sub.add_parser("backlog")
    bl.add_argument("--notes", required=True)
    bl.add_argument("--web-dir", required=True)
    bl.add_argument("--max-age", default="24h")
    bl.add_argument("--exclude-build")
    sub.add_parser("flush")
    au = sub.add_parser("audit")
    au.add_argument("--apps", required=True)
    a = ap.parse_args(argv)

    if a.cmd == "check":
        return _cmd_check(a)
    if a.cmd == "draft":
        out = Path(a.out)
        if out.exists():
            print("refuse to overwrite %s" % out, file=sys.stderr)
            return 2
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(make_draft(a.build, a.version, a.since), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print("wrote %s (draft — 문장을 쓰고 draft 칸을 지운다)" % out)
        return 0
    if a.cmd == "bundle":
        doc = bundle(load_notes(a.notes), a.out, a.keep)
        print("wrote %s (%d releases)" % (a.out, len(doc["releases"])))
        return 0
    if a.cmd == "publish":
        p = Path(a.note)
        if not p.is_file():
            print("MISSING %s" % p)
            return 3
        note = load_note(p)
        probs = lint(note)
        if any(x.level == "error" for x in probs):
            return _report(probs, note.id)
        res = publish(note, a.web_dir, app=a.app, dry_run=a.dry_run)
        print(res.line())
        return 0
    if a.cmd == "backlog":
        missing, blocking = backlog(load_notes(a.notes), a.web_dir, _parse_age(a.max_age), a.exclude_build)
        for n, age in missing:
            print("%s build=%s id=%s age=%dh" % ("BLOCKING" if (n, age) in blocking else "pending ", n.build, n.id, age.total_seconds() // 3600))
        if blocking:
            print("BACKLOG %d note(s) older than %s not on web — publish 를 먼저 다시 시도한다" % (len(blocking), a.max_age))
            return 4
        print("BACKLOG none")
        return 0
    if a.cmd == "flush":
        for f, res in flush():
            print("%s %s" % (f.name, res.line()))
        return 0
    rows = audit(read_apps(a.apps))
    for _, line, _ in rows:
        print(line)
    return 4 if any(bad for _, _, bad in rows) else 0


if __name__ == "__main__":
    sys.exit(main())
