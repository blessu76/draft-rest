"""앱 버전 표시 · 릴리스 노트 앵커 — 앱 킷 ipe_kit(Flutter) 의 IpeAppVersion · IpeReleaseAnchor 와 글자 하나까지 같은 규칙.

- 화면 글자(label): `1.0.0 (21)` · 빌드가 없으면 `1.0.0`
- 앵커(anchor):    `1.0.0-21` · 빌드가 없으면 `1.0.0` · 버전이 없으면 None   (ipe_kit versionBuild)
- strict:          버전 · 빌드가 둘 다 있을 때만 `1.0.0-21`                (ipe_kit versionBuildStrict)
- 릴리스 노트 주소: `https://<host>/<lang>/releases/#1.0.0-21` · langs 에 없는 언어는 `https://<host>/releases/…`
"""
import re
from collections import namedtuple

_BUILD_SUFFIX = re.compile(r"^(?P<v>[^+\s()]+)\s*(?:\+\s*(?P<b1>\S+)|\(\s*(?P<b2>[^)]*)\))?$")


class AppVersion(namedtuple("AppVersion", "version build")):
    """버전 · 빌드 글자(`1.0.0` · `21`). build 는 없으면 빈 글자."""

    __slots__ = ()

    def __new__(cls, version, build=""):
        return super().__new__(cls, str(version or "").strip(), str(build or "").strip())

    @classmethod
    def parse(cls, text):
        """`1.0.0+21`(pubspec) · `1.0.0 (21)`(화면) · `1.0.0-21`(앵커가 아닌 버전 글자는 그대로) · `1.0.0` → AppVersion."""
        t = str(text or "").strip()
        m = _BUILD_SUFFIX.match(t)
        if not m:
            return cls(t, "")
        return cls(m.group("v"), m.group("b1") or m.group("b2") or "")

    @property
    def label(self):
        return self.version if not self.build else "%s (%s)" % (self.version, self.build)

    def anchor(self, strict=False):
        if not self.version:
            return None
        if strict:
            return "%s-%s" % (self.version, self.build) if self.build else None
        return self.version if not self.build else "%s-%s" % (self.version, self.build)


def lang_of_tag(tag, langs):
    """`ko` · `zh-Hans` · `pt_BR` → 앞 언어 코드(소문자)가 langs 에 있으면 그것, 없으면 None."""
    code = re.split(r"[-_]", str(tag or "").strip())[0].lower()
    return code if code in langs else None


def page_url(host, langs, tag, path):
    lang = lang_of_tag(tag, langs)
    return "https://%s/%s" % (host, path) if lang is None else "https://%s/%s/%s" % (host, lang, path)


def release_notes_url(host, langs, tag, version=None, path="releases/", strict=False):
    base = page_url(host, langs, tag, path)
    a = version.anchor(strict) if version is not None else None
    return base if a is None else base + "#" + a
