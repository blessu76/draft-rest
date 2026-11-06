#!/usr/bin/env python3
"""웹이 킷을 받는 방법 — git 태그 하나를 웹의 vendor/ipe_web_kit/ 로 복사하고, 고쳐지지 않았는지 시험이 확인한다.

    # 킷 repo 에서(태그 고정):
    python3 -m ipe_web_kit.vendor install ~/Developer/draft-rest --tag v0.1.0
    # 웹에서(시험 · CI — 네트워크 · 토큰 없이):
    python3 vendor/ipe_web_kit/vendor.py verify .

킷 repo 는 비공개라 웹 CI 가 submodule 로 받으려면 토큰이 든다 — 그래서 복사본을 커밋한다(ipe-localtime 바이트 사본 ·
앱 킷 packages/ipe_kit 복사와 같은 방식). 복사본은 고치지 않는다: 바꿀 것은 킷에서 고쳐 새 태그로 다시 install.
"""
import argparse
import hashlib
import io
import os
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


def install(web_root, tag, kit_repo=None):
    """kit_repo 의 tag 를 web_root/vendor/ipe_web_kit/ 로(통째 교체). 돌려주는 값: 'v0.1.0 <커밋>'."""
    kit_repo = Path(kit_repo or Path(__file__).resolve().parent.parent)
    commit = _git(kit_repo, "rev-list", "-n", "1", tag)
    data = _git(kit_repo, "archive", "--format=tar", tag, PKG, binary=True)
    target = Path(web_root) / "vendor" / PKG
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


def verify(web_root):
    """고쳐진 · 빠진 · 더해진 파일과 버전 어긋남을 글 목록으로 돌려준다. 비면 그대로다."""
    pkg_dir = Path(web_root) / "vendor" / PKG
    if not (pkg_dir / MANIFEST).is_file() or not (pkg_dir / STAMP).is_file():
        return ["vendor/%s: %s or %s missing — run install" % (PKG, STAMP, MANIFEST)]
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
    v = sub.add_parser("verify", help="check <web>/vendor/ipe_web_kit against its manifest")
    v.add_argument("web_root", nargs="?", default=os.getcwd())
    a = ap.parse_args(argv)
    if a.cmd == "install":
        print("installed " + install(a.web_root, a.tag, a.kit))
        return 0
    problems = verify(a.web_root)
    for p in problems:
        print(p, file=sys.stderr)
    print("ipe_web_kit vendor: " + ("OK" if not problems else "%d problem(s)" % len(problems)))
    return 0 if not problems else 1


if __name__ == "__main__":
    sys.exit(main())
