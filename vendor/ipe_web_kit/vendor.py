#!/usr/bin/env python3
"""웹이 킷을 받는 방법 — git 태그 하나를 웹의 vendor/ipe_web_kit/ 로 복사하고, 고쳐지지 않았는지 시험이 확인한다.

    # 킷 repo 에서(태그 고정):
    python3 -m ipe_web_kit.vendor list
    python3 -m ipe_web_kit.vendor install ~/Developer/draft-rest --tag v0.1.0
    python3 -m ipe_web_kit.vendor status ~/Developer/draft-rest
    python3 -m ipe_web_kit.vendor update ~/Developer/draft-rest --tag v0.1.1     # 올림 · 내림 모두
    # 웹에서(시험 · CI — 네트워크 · 토큰 없이):
    python3 vendor/ipe_web_kit/vendor.py verify .
    # 앱 repo 에도 같은 복사본(릴리즈노트 도구) — 놓을 자리를 --into 로(마지막 폴더 이름은 ipe_web_kit):
    python3 -m ipe_web_kit.vendor install ~/Developer/draft-app --tag v0.4.0 --into tool/ipe_web_kit
    python3 tool/ipe_web_kit/vendor.py verify . --into tool/ipe_web_kit

킷 repo 는 비공개라 웹 CI 가 submodule 로 받으려면 토큰이 든다 — 그래서 복사본을 커밋한다(ipe-localtime 바이트 사본 ·
앱 킷 packages/ipe_kit 복사와 같은 방식). 복사본은 고치지 않는다: 바꿀 것은 킷에서 고쳐 새 태그로 다시 install.
"""
import argparse
import hashlib
import io
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

PKG = "ipe_web_kit"
STAMP = "KIT_VERSION"
MANIFEST = "MANIFEST.sha256"
SKIP_DIRS = {"__pycache__"}
TAG_RE = re.compile(r"^v(\d+)\.(\d+)\.(\d+)$")
DEFAULT_INTO = "vendor/" + PKG


def _target(web_root, into=None):
    """복사본이 놓일 폴더 — 기본 vendor/ipe_web_kit. into 는 repo 안 상대 경로(마지막 폴더 이름은 ipe_web_kit · .. 금지)."""
    into = (into or DEFAULT_INTO).strip()
    into = into if into.startswith("/") else into.rstrip("/")
    parts = Path(into).parts
    if not parts or Path(into).is_absolute() or ".." in parts or parts[-1] != PKG:
        raise SystemExit("--into must be a relative path inside the repo whose last folder is %s (got %r)" % (PKG, into))
    return Path(web_root).joinpath(*parts)


def _files(pkg_dir):
    pkg_dir = Path(pkg_dir)
    out = []
    for p in sorted(pkg_dir.rglob("*")):
        if p.is_file() and not (set(p.relative_to(pkg_dir).parts) & SKIP_DIRS) and p.name not in (STAMP, MANIFEST) \
                and p.suffix != ".pyc":
            out.append(p.relative_to(pkg_dir).as_posix())
    return out


def manifest_text(pkg_dir):
    pkg_dir = Path(pkg_dir)
    return "".join("%s  %s\n" % (hashlib.sha256((pkg_dir / f).read_bytes()).hexdigest(), f) for f in _files(pkg_dir))


def _git(kit_repo, *args, binary=False):
    r = subprocess.run(["git", "-C", str(kit_repo)] + list(args), capture_output=True, check=False)
    if r.returncode != 0:
        raise SystemExit("git %s failed: %s" % (" ".join(args), r.stderr.decode("utf-8", "replace").strip()))
    return r.stdout if binary else r.stdout.decode("utf-8").strip()


def _tag_key(tag):
    return tuple(int(x) for x in TAG_RE.match(tag).groups())


def tags(kit_repo=None):
    """킷의 vX.Y.Z 태그를 오름차순으로."""
    kit_repo = Path(kit_repo or Path(__file__).resolve().parent.parent)
    names = _git(kit_repo, "tag", "--list", "v*").split()
    return sorted((t for t in names if TAG_RE.match(t)), key=_tag_key)


def _check_tag(kit_repo, tag):
    if not TAG_RE.match(tag or ""):
        raise SystemExit("tag only: %r is not vX.Y.Z (branches and commit hashes are refused)" % (tag,))
    if tag not in tags(kit_repo):
        raise SystemExit("unknown tag: %s (see `vendor list`)" % tag)


def changelog_line(kit_repo, tag):
    """태그 시점 CHANGELOG.md 의 그 버전 절 첫 글줄 — 없으면 빈 글자."""
    try:
        text = _git(kit_repo, "show", "refs/tags/%s:CHANGELOG.md" % tag)
    except SystemExit:
        return ""
    want = "## " + tag.lstrip("v")
    take = False
    for line in text.splitlines():
        if line.startswith("## "):
            if take:
                break
            take = line[3:].split()[0:1] == [want[3:]]
            continue
        if take and line.strip():
            return line.strip().lstrip("- ").strip()
    return ""


def list_tags(kit_repo=None):
    """[(tag, 커밋 7자, CHANGELOG 한 줄)] 오름차순."""
    kit_repo = Path(kit_repo or Path(__file__).resolve().parent.parent)
    return [(t, _git(kit_repo, "rev-list", "-n", "1", "--abbrev-commit", "refs/tags/" + t), changelog_line(kit_repo, t))
            for t in tags(kit_repo)]


def current(web_root, into=None):
    """웹이 쓰는 'tag 커밋' (정본: vendor/ipe_web_kit/KIT_VERSION) — 없으면 None."""
    f = _target(web_root, into) / STAMP
    return f.read_text(encoding="utf-8").strip() if f.is_file() else None


def _snapshot(pkg_dir):
    pkg_dir = Path(pkg_dir)
    return {f: hashlib.sha256((pkg_dir / f).read_bytes()).hexdigest() for f in _files(pkg_dir)} if pkg_dir.is_dir() else {}


def status(web_root, kit_repo=None, into=None):
    """(웹 태그 or None, 최신 태그 or None, 글 한 줄)."""
    cur = current(web_root, into)
    all_tags = tags(kit_repo)
    latest = all_tags[-1] if all_tags else None
    using = cur.split()[0] if cur else None
    if using is None:
        msg = "not installed (latest %s)" % latest
    elif using == latest:
        msg = "%s — up to date" % using
    elif using in all_tags and latest:
        msg = "%s — newer available: %s" % (using, latest)
    else:
        msg = "%s — unknown to this kit (latest %s)" % (using, latest)
    return using, latest, msg


def update(web_root, tag, kit_repo=None, into=None):
    """install 로 tag 를 받되 바뀐 파일을 센다. 돌려주는 값: (이전 stamp or None, 새 stamp, 요약 줄 목록)."""
    pkg = _target(web_root, into)
    before_stamp = current(web_root, into)
    before = _snapshot(pkg)
    new_stamp = install(web_root, tag, kit_repo, into)
    after = _snapshot(pkg)
    lines = []
    for n in sorted(set(before) | set(after)):
        if n not in before:
            lines.append("added: " + n)
        elif n not in after:
            lines.append("removed: " + n)
        elif before[n] != after[n]:
            lines.append("changed: " + n)
    return before_stamp, new_stamp, lines


def install(web_root, tag, kit_repo=None, into=None):
    """kit_repo 의 tag 를 web_root/vendor/ipe_web_kit/ 로(통째 교체). 돌려주는 값: 'v0.1.0 <커밋>'."""
    kit_repo = Path(kit_repo or Path(__file__).resolve().parent.parent)
    _check_tag(kit_repo, tag)
    commit = _git(kit_repo, "rev-list", "-n", "1", "refs/tags/" + tag)
    data = _git(kit_repo, "archive", "--format=tar", tag, PKG, binary=True)
    target = _target(web_root, into)
    with tempfile.TemporaryDirectory() as tmp:
        with tarfile.open(fileobj=io.BytesIO(data)) as tar:
            for m in tar.getmembers():
                if m.name.startswith("/") or ".." in Path(m.name).parts:
                    raise SystemExit("unsafe path in archive: " + m.name)
            tar.extractall(tmp, **({"filter": "data"} if hasattr(tarfile, "data_filter") else {}))
        staged = Path(tmp) / PKG
        stamp = "%s %s\n" % (tag, commit)
        (staged / STAMP).write_text(stamp, encoding="utf-8")
        (staged / MANIFEST).write_text(manifest_text(staged), encoding="utf-8")
        if target.exists():
            shutil.rmtree(target)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(staged, target)
    return stamp.strip()


def verify(web_root, into=None):
    """고쳐진 · 빠진 · 더해진 파일과 버전 어긋남을 글 목록으로 돌려준다. 비면 그대로다."""
    pkg_dir = _target(web_root, into)
    if not (pkg_dir / MANIFEST).is_file() or not (pkg_dir / STAMP).is_file():
        return ["%s: %s or %s missing — run install" % (pkg_dir.relative_to(web_root).as_posix(), STAMP, MANIFEST)]
    want = {}
    for line in (pkg_dir / MANIFEST).read_text(encoding="utf-8").splitlines():
        digest, _, name = line.partition("  ")
        want[name] = digest
    problems = []
    have = set(_files(pkg_dir))
    for name in sorted(set(want) | have):
        if name not in have:
            problems.append("missing: " + name)
        elif name not in want:
            problems.append("added: " + name)
        elif hashlib.sha256((pkg_dir / name).read_bytes()).hexdigest() != want[name]:
            problems.append("modified: " + name)
    tag = (pkg_dir / STAMP).read_text(encoding="utf-8").split()[0]
    init = (pkg_dir / "__init__.py").read_text(encoding="utf-8") if "__init__.py" in have else ""
    if '__version__ = "%s"' % tag.lstrip("v") not in init:
        problems.append("version mismatch: %s says %s but __init__.__version__ differs" % (STAMP, tag))
    return problems


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    i = sub.add_parser("install", help="copy a kit tag into <web>/vendor/ipe_web_kit")
    i.add_argument("web_root")
    i.add_argument("--tag", required=True)
    i.add_argument("--kit", default=None, help="kit repo (default: the repo this file is in)")
    i.add_argument("--into", default=None, help="where inside the repo (default vendor/ipe_web_kit)")
    sub.add_parser("list", help="kit tags with one CHANGELOG line each").add_argument("--kit", default=None)
    u = sub.add_parser("update", help="replace <web>/vendor/ipe_web_kit with another tag (up or down)")
    u.add_argument("web_root")
    u.add_argument("--tag", required=True)
    u.add_argument("--kit", default=None)
    u.add_argument("--into", default=None)
    st = sub.add_parser("status", help="tag the web uses vs latest kit tag")
    st.add_argument("web_root", nargs="?", default=os.getcwd())
    st.add_argument("--kit", default=None)
    st.add_argument("--into", default=None)
    v = sub.add_parser("verify", help="check <web>/vendor/ipe_web_kit against its manifest")
    v.add_argument("web_root", nargs="?", default=os.getcwd())
    v.add_argument("--into", default=None)
    a = ap.parse_args(argv)
    if a.cmd == "install":
        print("installed " + install(a.web_root, a.tag, a.kit, a.into))
        return 0
    if a.cmd == "list":
        for t, c, line in list_tags(a.kit):
            print("%s  %s  %s" % (t, c, line))
        return 0
    if a.cmd == "status":
        using, latest, msg = status(a.web_root, a.kit, a.into)
        print(msg)
        return 0 if using == latest else 2
    if a.cmd == "update":
        old, new, lines = update(a.web_root, a.tag, a.kit, a.into)
        print("updated %s -> %s" % (old.split()[0] if old else "(none)", new))
        for l in lines:
            print("  " + l)
        print("  %d file(s) differ" % len(lines))
        return 0
    problems = verify(a.web_root, a.into)
    for p in problems:
        print(p, file=sys.stderr)
    print("ipe_web_kit vendor: " + ("OK" if not problems else "%d problem(s)" % len(problems)))
    return 0 if not problems else 1


if __name__ == "__main__":
    sys.exit(main())
