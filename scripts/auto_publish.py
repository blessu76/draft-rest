#!/usr/bin/env python3
"""Scheduled publish orchestrator (design: _ipe F-006 docs/auto-publish-design.md §4·§5·§6).

    python3 scripts/auto_publish.py [--dry-run] [--queue-dir queue] [--schedule queue/posts/SCHEDULE.tsv] [--main-dir .]
        [--state-file STATE.json] [--no-push] [--remote origin] [--branch main] [--now 2026-11-20T15:20:00+09:00]

--dry-run: validate and log only; nothing is written, committed or pushed.
Without --dry-run (stage 3, real publish): the first candidate that passes every gate is moved from the queue checkout into
main_dir (provisional stamp -> G4~G7 -> confirmed re-stamp at the current KST time -> rebuild/--check/sitemap -> commit with
trailer `Auto-Publish: <slug> <slot>` -> push to <remote> <branch>). A rejected push rewinds main_dir to the remote and starts
over, at most 3 tries, then hold. --no-push keeps the commit local. In a real run --now may differ from the real clock by
5 minutes at most and the stamp is always the real current KST time. main_dir must be a clean git checkout (the queue checkout
inside it is ignored). Only the post's .md files are moved; posts/<slug>/iris-review.json stays in the queue.
The last line is always `RESULT: publish <slug>|hold <slug> <gate>|skip <reason>`.
--state-file (JSON, optional): remembers when each hold alert was last sent so the same hold alerts at most every 3 hours.

Schedule file: one `slug<TAB>slot_kst` per line (e.g. `one-more-slip<TAB>2026-11-20T15:20+09:00`), `#` comments allowed.
A missing schedule file is a normal exit (skip). PUBLISH_PAUSED=1 exits at once.

Gates (a failing gate holds the slug; nothing is written):
  G1  Iris mark: ko.md and en.md front matter have `copy_review: iris` and `copy_review_date: YYYY-MM-DD` (a stamp alone never
      passes), AND one of two pieces of evidence: (a) git history of the queue checkout has a commit with the trailer
      `Iris-Review: <slug>` and no later commit touched ko.md/en.md, or (b) posts/<slug>/iris-review.json
      {"slug","reviewer":"iris","date","ko_sha256","en_sha256"} whose sha256 equal the whole current ko.md / en.md bytes
      (survives a squash/rebase of the queue; any edit after the mark changes the hash and voids it).
      G1 runs first; on failure nothing else runs.
  G2  check_queue (read-only).   G3  publish_post.rewrite() accepts every file (read-only, nothing written).
  G4-G7 build_site, build_site --check, check_sitemap, unittest, no deleted files (real run only; [dry-run 생략] otherwise).
  G8  push-blocked hours (10:00~11:00, 13:00~14:30 KST): defer to the next tick (skip, not a failure).
  G9  slot <= now and slot inside the window 12:00~17:59 excluding 13:00~14:30.

Stock: fewer than 3 drafts in the queue prints `WARN stock<3`.
"""
import argparse
import datetime as dt
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import check_queue  # noqa: E402
import publish_post  # noqa: E402
import stamp_published  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
KST = dt.timezone(dt.timedelta(hours=9))
STOCK_MIN = 3
ALERT_WINDOW = dt.timedelta(hours=3)
PUSH_BLOCKED = ((10 * 60, 11 * 60), (13 * 60, 14 * 60 + 30))  # minutes of day, [start, end)
SLOT_WINDOW = (12 * 60, 18 * 60)  # [start, end), minus PUSH_BLOCKED
PUSH_TRIES = 3
MAX_NOW_SKEW = dt.timedelta(minutes=5)
BOT = ["-c", "user.name=draft-auto-publish", "-c", "user.email=auto-publish@users.noreply.github.com", "-c", "commit.gpgsign=false"]
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def log(msg):
    print("auto_publish: " + msg, flush=True)


def result(line):
    print("RESULT: " + line, flush=True)


def now_kst():
    return dt.datetime.now(KST).replace(second=0, microsecond=0)


def parse_aware(text, what):
    try:
        when = dt.datetime.fromisoformat(text.strip())
    except ValueError:
        raise ValueError("%s is not ISO time: %r" % (what, text))
    if when.tzinfo is None:
        raise ValueError("%s needs an offset, e.g. +09:00: %r" % (what, text))
    return when.astimezone(KST)


def minute_of_day(when):
    return when.hour * 60 + when.minute


def in_push_blocked(when):
    m = minute_of_day(when)
    return any(a <= m < b for a, b in PUSH_BLOCKED)


def in_slot_window(when):
    m = minute_of_day(when)
    return SLOT_WINDOW[0] <= m < SLOT_WINDOW[1] and not in_push_blocked(when)


def alert_due(last_alert, now):
    """Hold alerts repeat at most every 3 hours (design §5.1, §7-7). last_alert=None means never alerted."""
    return last_alert is None or now - last_alert >= ALERT_WINDOW or last_alert > now  # a future stamp (clock skew) never mutes


def load_state(path):
    """-> {alert_key: ISO time of the last alert}. Missing/corrupt file = empty (an alert is better than silence)."""
    if not path:
        return {}
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        alerts = data.get("alerts", {})
        return {str(k): str(v) for k, v in alerts.items()} if isinstance(alerts, dict) else {}
    except FileNotFoundError:
        return {}
    except (OSError, ValueError, AttributeError) as ex:
        log("WARN 알림 상태 파일을 읽지 못함(비우고 진행): %s" % ex)
        return {}


def save_state(path, alerts):
    if not path:
        return
    try:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps({"alerts": alerts}, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    except OSError as ex:
        log("WARN 알림 상태 파일을 쓰지 못함: %s" % ex)


def alert(state, key, message, now):
    """Log an ALERT line unless the same key alerted within 3 hours. Mutates state; -> True when emitted."""
    last = None
    if key in state:
        try:
            last = parse_aware(state[key], "state")
        except ValueError:
            last = None
    if not alert_due(last, now):
        log("ALERT 억제(3시간 이내 재알림 없음): " + key)
        return False
    log("ALERT " + message + " (Slack 미연결 — 로그만)")
    state[key] = now.isoformat(timespec="minutes")
    return True


def load_schedule(path):
    """-> (rows [(slug, slot_kst)], problems). Malformed lines are reported, not silently dropped."""
    rows, problems = [], []
    for n, line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        parts = line.split("\t")
        if len(parts) != 2 or not parts[0].strip():
            problems.append("SCHEDULE line %d: want `slug<TAB>slot`, got %r" % (n, line))
            continue
        try:
            rows.append((parts[0].strip(), parse_aware(parts[1], "SCHEDULE line %d slot" % n)))
        except ValueError as ex:
            problems.append(str(ex))
    return rows, problems


def front_matter(text):
    text = text.replace("\r\n", "\n")
    if not text.startswith("---\n"):
        return {}
    end = text.find("\n---", 4)
    if end == -1:
        return {}
    meta = {}
    for line in text[4:end].split("\n"):
        if ":" in line and not line.lstrip().startswith("#"):
            k, v = line.split(":", 1)
            meta[k.strip().lower()] = v.strip().strip("\"'")
    return meta


def read_meta(root, slug, lang="ko"):
    f = Path(root) / "posts" / slug / ("%s.md" % lang)
    try:
        return front_matter(f.read_text(encoding="utf-8"))
    except OSError:
        return {}


def published_at(meta):
    try:
        return parse_aware(meta["published"], "published") if meta.get("published") else None
    except (ValueError, KeyError):
        return None


def draft_slugs(queue):
    base = Path(queue) / "posts"
    if not base.is_dir():
        return []
    return sorted(d.name for d in base.iterdir() if d.is_dir() and read_meta(queue, d.name).get("draft") == "true")


def published_slugs(root):
    base = Path(root) / "posts"
    if not base.is_dir():
        return set()
    out = set()
    for d in base.iterdir():
        meta = read_meta(root, d.name) if d.is_dir() else {}
        if published_at(meta) and meta.get("draft") != "true":
            out.add(d.name)
    return out


def published_today(roots, today):
    slugs = set()
    for root in roots:
        base = Path(root) / "posts"
        if not base.is_dir():
            continue
        for d in base.iterdir():
            meta = read_meta(root, d.name) if d.is_dir() else {}
            when = published_at(meta)
            if when and when.date() == today and meta.get("draft") != "true":
                slugs.add(d.name)
    return slugs


def git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True).stdout


def check_copy_review(queue, slug):
    """G1. -> list of problems (empty = Iris review evidence is present and not voided). Read-only."""
    problems = []
    for lang in ("ko", "en"):
        meta = read_meta(queue, slug, lang)
        if meta.get("copy_review") != "iris":
            problems.append("%s.md copy_review 가 iris 가 아님 (값: %s)" % (lang, meta.get("copy_review") or "없음"))
        date = meta.get("copy_review_date", "")
        if not DATE_RE.match(date):
            problems.append("%s.md copy_review_date 없음/형식 오류 (값: %s)" % (lang, date or "없음"))
    if problems:
        return problems
    trailer = trailer_evidence(queue, slug)
    if not trailer:
        return []
    sidecar = sidecar_evidence(queue, slug)
    if not sidecar:
        return []
    return trailer + sidecar


def sidecar_evidence(queue, slug):
    """posts/<slug>/iris-review.json whose hashes equal the current ko.md/en.md bytes. -> problems (empty = valid)."""
    f = Path(queue) / "posts" / slug / "iris-review.json"
    try:
        rec = json.loads(f.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return ["iris-review.json 없음 (대체 근거)"]
    except (OSError, ValueError) as ex:
        return ["iris-review.json 읽기 실패: %s" % ex]
    if not isinstance(rec, dict):
        return ["iris-review.json 형식 오류"]
    if rec.get("slug") != slug or rec.get("reviewer") != "iris" or not DATE_RE.match(str(rec.get("date", ""))):
        return ["iris-review.json 의 slug/reviewer(iris)/date 가 맞지 않음"]
    problems = []
    for lang in ("ko", "en"):
        try:
            digest = hashlib.sha256((Path(queue) / "posts" / slug / (lang + ".md")).read_bytes()).hexdigest()
        except OSError as ex:
            return ["%s.md 읽기 실패: %s" % (lang, ex)]
        if str(rec.get(lang + "_sha256", "")).lower() != digest:
            problems.append("iris-review.json 의 %s_sha256 가 현재 %s.md 와 다름 — 마크 뒤 수정됨, 근거 무효" % (lang, lang))
    return problems


def trailer_evidence(queue, slug):
    """Evidence (a): commit trailer `Iris-Review: <slug>` and no later edit of ko/en. -> problems (empty = valid)."""
    problems = []
    try:
        out = git(queue, "log", "--format=%x1e%H%x00%B", "--", "posts/%s/ko.md" % slug, "posts/%s/en.md" % slug)
    except (subprocess.CalledProcessError, OSError) as ex:
        return ["git 이력 확인 불가: %s" % ex]
    commits = []
    for rec in out.split("\x1e"):
        if rec.strip():
            sha, _, body = rec.partition("\x00")
            commits.append((sha.strip(), body))
    pattern = re.compile(r"^Iris-Review:\s*%s\s*$" % re.escape(slug), re.M)
    idx = next((i for i, (_, body) in enumerate(commits) if pattern.search(body)), None)
    if idx is None:
        return ["Iris 검수 근거 없음: ko/en 을 건드린 커밋 중 trailer `Iris-Review: %s` 가 없다 (front matter 스탬프만으로는 통과 안 함)" % slug]
    if idx > 0:
        later = ", ".join(sha[:8] for sha, _ in commits[:idx])
        problems.append("마크(근거 커밋 %s) 뒤에 ko.md/en.md 가 수정됨: %s — 마크 무효" % (commits[idx][0][:8], later))
    return problems


def post_gates(queue, slug, when):
    """G2·G3 on the queue checkout, read-only. -> (gate, problems). gate is None when both pass."""
    _, errors, warnings = check_queue.scan(str(queue), [slug])
    for w in warnings:
        log("WARN " + w)
    if errors:
        return "G2", ["check_queue: " + e for e in errors]
    problems = []
    for f in publish_post.post_files(queue, slug):
        try:
            publish_post.rewrite(f.read_text(encoding="utf-8"), when)
        except ValueError as ex:
            problems.append("%s: %s" % (f.name, ex))
    if problems:
        return "G3", problems
    return None, []



def run_cmds(main_dir, cmds):
    """Run gate commands in main_dir. -> problems (empty = all passed). Separate function so tests can replace it."""
    problems = []
    for name, argv in cmds:
        r = subprocess.run(argv, cwd=str(main_dir), capture_output=True, text=True)
        if r.returncode != 0:
            tail = "\n".join((r.stdout + r.stderr).strip().splitlines()[-8:])
            problems.append("%s 실패 (exit %d)\n%s" % (name, r.returncode, tail))
    return problems


def gate_cmds(main_dir, full):
    py = sys.executable
    s = str(Path(main_dir) / "scripts")
    cmds = [("G4 build_site", [py, s + "/build_site.py"]),
            ("G4 build_site --check", [py, s + "/build_site.py", "--check"]),
            ("G5 check_sitemap", [py, s + "/check_sitemap.py"])]
    if full:
        cmds.append(("G6 unittest", [py, "-m", "unittest", "discover", "-s", "tests"]))
    return cmds


def queue_rel(main_dir, queue):
    """Path of the queue checkout relative to main_dir when it lives inside it (else None)."""
    try:
        return Path(queue).resolve().relative_to(Path(main_dir).resolve()).as_posix()
    except ValueError:
        return None


def clean_tree(main_dir, qrel):
    """True when main_dir has no changes (the queue checkout inside it is ignored)."""
    out = git(main_dir, "status", "--porcelain")
    return not [ln for ln in out.splitlines() if not (qrel and ln[3:].rstrip("/").split("/")[0] == qrel.split("/")[0])]


def rollback(main_dir, qrel):
    """Throw away everything the attempt wrote (the tree was clean at start)."""
    git(main_dir, "reset", "--hard", "-q", "HEAD")
    clean = ["clean", "-fdq"] + (["-e", qrel.split("/")[0]] if qrel else [])
    git(main_dir, *clean)


def deleted_files(main_dir):
    return git(main_dir, "diff", "--cached", "--diff-filter=D", "--name-only").split()


def copy_post(queue, main_dir, slug):
    """Copy only the post's .md files (ko, en, translations/*) from the queue into main_dir/posts/<slug>."""
    qroot = Path(queue) / "posts" / slug
    for f in publish_post.post_files(queue, slug):
        dest = Path(main_dir) / "posts" / slug / f.relative_to(qroot)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(f, dest)


def real_publish(a, queue, main_dir, slug, slot, when):
    """Stage 3. -> (ok, gate, problems). On any failure main_dir is rolled back to a clean tree."""
    qrel = queue_rel(main_dir, queue)
    ref = "%s/%s" % (a.remote, a.branch)
    for attempt in range(1, PUSH_TRIES + 1):
        if not clean_tree(main_dir, qrel):
            return False, "G7", ["main 작업 트리가 깨끗하지 않음 — 발행하지 않는다"]
        if (main_dir / "posts" / slug).exists():
            return False, "G7", ["main 에 posts/%s 가 이미 있음 — 덮어쓰지 않는다" % slug]
        try:
            copy_post(queue, main_dir, slug)
            publish_post.publish(str(main_dir), slug, when)  # provisional stamp (also refuses a future time)
            problems = run_cmds(main_dir, gate_cmds(main_dir, full=True))
            if problems:
                rollback(main_dir, qrel)
                return False, "G4~G6", problems
            stamp_time = now_kst()  # confirmed stamp: right before the commit that is pushed
            stamp_published.stamp(str(main_dir), slug, stamp_time)
            problems = run_cmds(main_dir, gate_cmds(main_dir, full=False))
            add = ["add", "-A", "--", "."] + ([":(exclude)" + qrel] if qrel else [])
            git(main_dir, *add)
            gone = deleted_files(main_dir)
            if gone:
                problems.append("G7 삭제된 파일 %d개: %s" % (len(gone), ", ".join(gone[:5])))
            if problems:
                rollback(main_dir, qrel)
                return False, "G4~G7", problems
            msg = "publish: %s (%s)\n\nAuto-Publish: %s %s" % (slug, stamp_time.date().isoformat(), slug, slot.isoformat(timespec="minutes"))
            git(main_dir, *BOT, "commit", "-q", "-m", msg)
        except (subprocess.CalledProcessError, OSError, SystemExit) as ex:
            try:
                rollback(main_dir, qrel)
            except (subprocess.CalledProcessError, OSError):
                pass
            return False, "G7", ["발행 단계 오류: %s" % (getattr(ex, "stderr", None) or ex)]
        log("커밋: %s (published=%s)" % (slug, stamp_time.isoformat(timespec="seconds")))
        if a.no_push:
            log("--no-push: push 생략 (로컬 커밋만)")
            return True, None, []
        if in_push_blocked(now_kst()):  # G8 재확인: 게이트·빌드에 걸린 시간 동안 금지 시간대에 들어섰을 수 있다
            try:
                git(main_dir, "reset", "--hard", "-q", "HEAD~1")
            except (subprocess.CalledProcessError, OSError) as ex:
                return False, "G8", ["push 직전 금지 시간 진입 — 커밋 되돌리기 실패: %s" % ex]
            return False, "G8", ["push 직전 푸시 금지 시간 진입 — 커밋을 되돌리고 이월"]
        r = subprocess.run(["git", "-C", str(main_dir), "push", a.remote, "HEAD:refs/heads/" + a.branch], capture_output=True, text=True)
        if r.returncode == 0:
            skew = now_kst() - stamp_time
            if skew > dt.timedelta(minutes=5):
                log("WARN published 와 push 시각 차이 %s (허용 5분 초과)" % skew)
            log("push 성공: %s" % ref)
            return True, None, []
        log("push 거절(%d/%d): %s — 원격으로 되감고 처음부터" % (attempt, PUSH_TRIES, r.stderr.strip().splitlines()[-1:] or r.stdout.strip()))
        try:
            git(main_dir, "fetch", "-q", a.remote, a.branch)
            git(main_dir, "reset", "--hard", "-q", "FETCH_HEAD")
        except (subprocess.CalledProcessError, OSError) as ex:
            return False, "push", ["원격 되감기 실패: %s" % ex]
        if slug in published_slugs(main_dir):
            log("완료 처리: %s — 그 사이 원격에 발행됨" % slug)
            return False, "dup", ["원격에 이미 발행됨"]
        done_today = published_today([main_dir, queue], when.date())
        if done_today:
            log("완료 처리: %s — 그 사이 오늘(KST) 다른 글이 발행됨: %s" % (slug, ", ".join(sorted(done_today))))
            return False, "dup", ["오늘 이미 발행됨(하루 1편): %s" % ", ".join(sorted(done_today))]
    return False, "push", ["push %d회 거절" % PUSH_TRIES]


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true", help="validate and log only (default: real publish)")
    ap.add_argument("--queue-dir", default=str(ROOT / "queue"), help="checkout of origin/blog/queue (default: ./queue)")
    ap.add_argument("--main-dir", default=str(ROOT), help="checkout of main (default: repo root)")
    ap.add_argument("--schedule", help="slot file (default: <queue-dir>/posts/SCHEDULE.tsv)")
    ap.add_argument("--state-file", help="JSON file that remembers the last alert time per hold (3-hour suppression)")
    ap.add_argument("--no-push", action="store_true", help="real run: commit locally, do not push")
    ap.add_argument("--remote", default="origin")
    ap.add_argument("--branch", default="main")
    ap.add_argument("--now", help="ISO time with offset, for tests (default: now, KST)")
    a = ap.parse_args(argv)

    if os.environ.get("PUBLISH_PAUSED") == "1":
        log("PUBLISH_PAUSED=1 — 즉시 종료")
        result("skip PUBLISH_PAUSED")
        return 0

    try:
        now = parse_aware(a.now, "--now") if a.now else now_kst()
    except ValueError as ex:
        print("auto_publish: " + str(ex), file=sys.stderr)
        return 2
    if a.now and not a.dry_run and abs(now_kst() - now) > MAX_NOW_SKEW:
        print("auto_publish: 실발행에서 --now 는 실제 시각과 5분 이상 다를 수 없다(소급·미래 발행 금지)", file=sys.stderr)
        return 2
    queue, main_dir = Path(a.queue_dir), Path(a.main_dir)
    log("기준 시각 %s (%s)" % (now.isoformat(timespec="minutes"), "dry-run" if a.dry_run else "실발행"))
    state = load_state(a.state_file)

    def finish(line):
        save_state(a.state_file, state)
        result(line)
        return 0

    drafts = draft_slugs(queue)
    if len(drafts) < STOCK_MIN:
        log("WARN stock<3 — 대기열 draft %d편 (기준 %d편 미만, Davy·방장에게 보충 요청)" % (len(drafts), STOCK_MIN))
    else:
        log("대기열 draft %d편" % len(drafts))

    sched = Path(a.schedule) if a.schedule else queue / "posts" / "SCHEDULE.tsv"
    if not sched.is_file():
        log("슬롯 파일 없음: %s" % sched)
        return finish("skip 슬롯 파일 없음")
    try:
        rows, problems = load_schedule(sched)
    except ValueError as ex:
        log("ERROR " + str(ex))
        return finish("skip 슬롯 파일 형식 오류")
    for p in problems:
        log("WARN " + p)

    today_done = published_today([main_dir, queue], now.date())
    if today_done:
        log("오늘(KST) 이미 발행된 글 있음: %s" % ", ".join(sorted(today_done)))
        return finish("skip 오늘 이미 발행됨")

    due = sorted((slot, slug) for slug, slot in rows if slot <= now)
    if not due:
        log("도래한 슬롯 없음 (슬롯 %d건)" % len(rows))
        return finish("skip 도래한 슬롯 없음")

    remote_done = published_slugs(main_dir)
    candidate = None
    for slot, slug in due:
        if slug in remote_done:
            log("완료 처리: %s — 원격(main)에 이미 published 있음" % slug)
            continue
        if slug not in drafts:
            log("건너뜀: %s — draft:true 가 아님(대기열에 없음)" % slug)
            continue
        candidate = (slot, slug)
        break
    if candidate is None:
        return finish("skip 발행할 draft 슬롯 없음")
    slot, slug = candidate
    log("후보: %s (슬롯 %s)" % (slug, slot.isoformat(timespec="minutes")))

    if in_push_blocked(now):
        log("G8 푸시 금지 시간 — 이월(다음 틱 재시도)")
        return finish("skip 푸시 금지 시간 이월")
    if not in_slot_window(slot):
        log("G9 슬롯 시각 %s 가 창(12:00~17:59, 13:00~14:30 제외) 밖" % slot.strftime("%H:%M"))
        alert(state, "%s:G9" % slug, "❌ 게이트 실패: %s / G9 슬롯창" % slug, now)
        return finish("hold %s 슬롯창" % slug)

    problems = check_copy_review(queue, slug)
    if problems:
        for p in problems:
            log("G1 실패: " + p)
        alert(state, "%s:G1" % slug, "⏸ Iris 검수 대기: %s" % slug, now)
        return finish("hold %s G1" % slug)
    state.pop("%s:G1" % slug, None)
    log("G1 통과: Iris 검수 근거 확인 (ko·en 마크 + trailer 또는 iris-review.json 해시, 마크 뒤 수정 없음)")

    when = now.replace(second=0, microsecond=0)
    gate, problems = post_gates(queue, slug, when)
    if gate:
        for p in problems:
            log("%s 실패: %s" % (gate, p))
        alert(state, "%s:%s" % (slug, gate), "❌ 게이트 실패: %s / %s" % (slug, gate), now)
        return finish("hold %s %s" % (slug, gate))
    log("G2·G3 통과 (check_queue·rewrite, 읽기 전용)")

    if a.dry_run:
        log("[dry-run 생략] G4~G7 build·--check·check_sitemap·unittest·삭제 0 확인 (실행 단계에서 수행)")
        log("would publish: %s — date=%s, published=%s, draft 플래그 제거 (쓰기·commit·push 없음)"
            % (slug, when.date().isoformat(), when.isoformat(timespec="seconds")))
        return finish("publish %s" % slug)

    try:
        recent = git(main_dir, "log", "-n", "50", "--format=%B")
    except (subprocess.CalledProcessError, OSError) as ex:
        log("ERROR main_dir 가 git 저장소가 아님: %s" % ex)
        return finish("hold %s main" % slug)
    if re.search(r"^Auto-Publish:\s*%s\s" % re.escape(slug), recent, re.M):
        log("완료 처리: %s — main 최근 이력에 Auto-Publish 트레일러 있음" % slug)
        return finish("skip 이미 발행됨")

    ok, gate, problems = real_publish(a, queue, main_dir, slug, slot, when)
    if not ok:
        for p in problems:
            log("%s 실패: %s" % (gate, p))
        alert(state, "%s:%s" % (slug, gate), "❌ 게이트 실패: %s / %s" % (slug, gate), now)
        return finish("hold %s %s" % (slug, gate))
    for k in [k for k in state if k.startswith(slug + ":")]:
        state.pop(k)
    log("발행 완료: %s%s" % (slug, " (push 생략)" if a.no_push else ""))
    return finish("publish %s" % slug)


if __name__ == "__main__":
    sys.exit(main())
