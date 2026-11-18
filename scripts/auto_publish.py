#!/usr/bin/env python3
"""Scheduled publish orchestrator (design: _ipe F-006 docs/auto-publish-design.md §4·§5·§6).

    python3 scripts/auto_publish.py --dry-run [--queue-dir queue] [--schedule queue/posts/SCHEDULE.tsv] [--now 2026-11-20T15:20:00+09:00]

Stage 1·2 only: --dry-run is required (without it the run is refused with exit code 2, stage 3 is not built yet).
Nothing is written, committed or pushed. The last line is always `RESULT: publish <slug>|hold <slug> <gate>|skip <reason>`.

Schedule file: one `slug<TAB>slot_kst` per line (e.g. `one-more-slip<TAB>2026-11-20T15:20+09:00`), `#` comments allowed.
A missing schedule file is a normal exit (skip). PUBLISH_PAUSED=1 exits at once.

Gates (a failing gate holds the slug; nothing is written):
  G1  Iris mark: ko.md and en.md front matter have `copy_review: iris` and `copy_review_date: YYYY-MM-DD`, AND git
      history of the queue checkout has a commit with the trailer `Iris-Review: <slug>` (a stamp alone never passes),
      AND no later commit touched ko.md/en.md (editing after the mark voids it). G1 runs first; on failure nothing else runs.
  G2  check_queue (read-only).   G3  publish_post.rewrite() accepts every file (read-only, nothing written).
  G4-G7 (build, --check, sitemap, unittest, deletion check) are [dry-run 생략] here; the real run executes them.
  G8  push-blocked hours (10:00~11:00, 13:00~14:30 KST): defer to the next tick (skip, not a failure).
  G9  slot <= now and slot inside the window 12:00~17:59 excluding 13:00~14:30.

Stock: fewer than 3 drafts in the queue prints `WARN stock<3`.
"""
import argparse
import datetime as dt
import os
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import check_queue  # noqa: E402
import publish_post  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
KST = dt.timezone(dt.timedelta(hours=9))
STOCK_MIN = 3
ALERT_WINDOW = dt.timedelta(hours=3)
PUSH_BLOCKED = ((10 * 60, 11 * 60), (13 * 60, 14 * 60 + 30))  # minutes of day, [start, end)
SLOT_WINDOW = (12 * 60, 18 * 60)  # [start, end), minus PUSH_BLOCKED
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
    return last_alert is None or now - last_alert >= ALERT_WINDOW


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


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true", help="required in this stage: validate and log only")
    ap.add_argument("--queue-dir", default=str(ROOT / "queue"), help="checkout of origin/blog/queue (default: ./queue)")
    ap.add_argument("--main-dir", default=str(ROOT), help="checkout of main, for the remote-published check (default: repo root)")
    ap.add_argument("--schedule", help="slot file (default: <queue-dir>/posts/SCHEDULE.tsv)")
    ap.add_argument("--now", help="ISO time with offset, for tests (default: now, KST)")
    a = ap.parse_args(argv)

    if os.environ.get("PUBLISH_PAUSED") == "1":
        log("PUBLISH_PAUSED=1 — 즉시 종료")
        result("skip PUBLISH_PAUSED")
        return 0
    if not a.dry_run:
        print("auto_publish: 3단계 전이라 거부 — 이번 단계에서는 --dry-run 만 동작한다", file=sys.stderr)
        return 2

    try:
        now = parse_aware(a.now, "--now") if a.now else now_kst()
    except ValueError as ex:
        print("auto_publish: " + str(ex), file=sys.stderr)
        return 2
    queue, main_dir = Path(a.queue_dir), Path(a.main_dir)
    log("기준 시각 %s (dry-run)" % now.isoformat(timespec="minutes"))

    drafts = draft_slugs(queue)
    if len(drafts) < STOCK_MIN:
        log("WARN stock<3 — 대기열 draft %d편 (기준 %d편 미만, Davy·방장에게 보충 요청)" % (len(drafts), STOCK_MIN))
    else:
        log("대기열 draft %d편" % len(drafts))

    sched = Path(a.schedule) if a.schedule else queue / "posts" / "SCHEDULE.tsv"
    if not sched.is_file():
        log("슬롯 파일 없음: %s" % sched)
        result("skip 슬롯 파일 없음")
        return 0
    try:
        rows, problems = load_schedule(sched)
    except ValueError as ex:
        log("ERROR " + str(ex))
        result("skip 슬롯 파일 형식 오류")
        return 0
    for p in problems:
        log("WARN " + p)

    today_done = published_today([main_dir, queue], now.date())
    if today_done:
        log("오늘(KST) 이미 발행된 글 있음: %s" % ", ".join(sorted(today_done)))
        result("skip 오늘 이미 발행됨")
        return 0

    due = sorted((slot, slug) for slug, slot in rows if slot <= now)
    if not due:
        log("도래한 슬롯 없음 (슬롯 %d건)" % len(rows))
        result("skip 도래한 슬롯 없음")
        return 0

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
        result("skip 발행할 draft 슬롯 없음")
        return 0
    slot, slug = candidate
    log("후보: %s (슬롯 %s)" % (slug, slot.isoformat(timespec="minutes")))

    if in_push_blocked(now):
        log("G8 푸시 금지 시간 — 이월(다음 틱 재시도)")
        result("skip 푸시 금지 시간 이월")
        return 0
    if not in_slot_window(slot):
        log("G9 슬롯 시각 %s 가 창(12:00~17:59, 13:00~14:30 제외) 밖" % slot.strftime("%H:%M"))
        result("hold %s 슬롯창" % slug)
        return 0

    problems = check_copy_review(queue, slug)
    if problems:
        for p in problems:
            log("G1 실패: " + p)
        if alert_due(None, now):
            log("ALERT ⏸ Iris 검수 대기: %s (Slack 미연결 — 로그만)" % slug)
        result("hold %s G1" % slug)
        return 0
    log("G1 통과: Iris 검수 근거 확인 (ko·en 마크 + trailer, 마크 뒤 수정 없음)")

    when = now.replace(second=0, microsecond=0)
    gate, problems = post_gates(queue, slug, when)
    if gate:
        for p in problems:
            log("%s 실패: %s" % (gate, p))
        result("hold %s %s" % (slug, gate))
        return 0
    log("G2·G3 통과 (check_queue·rewrite, 읽기 전용)")
    log("[dry-run 생략] G4~G7 build·--check·check_sitemap·unittest·삭제 0 확인 (실행 단계에서 수행)")
    log("would publish: %s — date=%s, published=%s, draft 플래그 제거 (쓰기·commit·push 없음)"
        % (slug, when.date().isoformat(), when.isoformat(timespec="seconds")))
    result("publish %s" % slug)
    return 0


if __name__ == "__main__":
    sys.exit(main())
