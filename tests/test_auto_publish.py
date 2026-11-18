import contextlib
import datetime as dt
import hashlib
import io
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import auto_publish  # noqa: E402
import build_site  # noqa: E402
import publish_post  # noqa: E402
import stamp_published  # noqa: E402

KST = auto_publish.KST
FM = "---\ntitle: T %s\ndescription: %s\ndate: 2026-10-28\nslug: %s\n%s---\n\n%s\n"
MARKS = "copy_review: iris\ncopy_review_date: 2026-11-18\n"
GIT = ["-c", "user.name=test", "-c", "user.email=test@example.invalid", "-c", "commit.gpgsign=false"]


def make_post(root, slug, extra="draft: true\n", skip=()):
    """Synthetic post folder with all 13 languages, sized so check_queue passes."""
    for c in build_site.CODES:
        if c in skip:
            continue
        f = Path(root) / "posts" / slug / (c + ".md" if c in ("ko", "en") else "translations/%s.md" % c)
        f.parent.mkdir(parents=True, exist_ok=True)
        body = "가" * 1400 if c == "ko" else "字" * 800 if c in ("ja", "zh") else "word " * 400
        f.write_text(FM % (c, "short description " + c, slug, extra, body), encoding="utf-8")


def git(repo, *args):
    subprocess.run(["git", "-C", str(repo), *GIT, *args], check=True, capture_output=True, text=True)


def init_repo(path):
    Path(path).mkdir(parents=True, exist_ok=True)
    git(path, "init", "-q")


def commit_all(repo, message):
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "--allow-empty", "-m", message)


def add_queued_post(repo, slug, marks=True, trailer=True, skip=()):
    """One queued draft, committed the way the review is recorded: marks + `Iris-Review: <slug>` trailer."""
    make_post(repo, slug, extra="draft: true\n" + (MARKS if marks else ""), skip=skip)
    msg = "review: %s" % slug + ("\n\nIris-Review: %s" % slug if trailer else "")
    commit_all(repo, msg)


def snapshot(root):
    out = {}
    for f in sorted(Path(root).rglob("*")):
        if f.is_file() and ".git" not in f.parts:
            out[str(f.relative_to(root))] = hashlib.sha256(f.read_bytes()).hexdigest()
    return out


def run_main(*args):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(io.StringIO()):
        code = auto_publish.main(list(args))
    lines = buf.getvalue().strip().splitlines()
    return code, buf.getvalue(), (lines[-1] if lines else "")


def write_schedule(path, rows):
    Path(path).write_text("".join("%s\t%s\n" % r for r in rows), encoding="utf-8")


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.queue = self.tmp / "queue"
        self.main = self.tmp / "main"
        init_repo(self.queue)
        self.main.mkdir()
        self.sched = self.tmp / "SCHEDULE.tsv"

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)


class IrisGate(Base):
    """G1 — design §7-1 plus decision 11-19 ③ (stamp without evidence) and ④ (edit after mark)."""

    def test_no_mark_holds(self):
        make_post(self.queue, "p1")
        commit_all(self.queue, "plain draft")
        problems = auto_publish.check_copy_review(self.queue, "p1")
        self.assertTrue(problems)
        self.assertIn("copy_review", " ".join(problems))

    def test_mark_without_date_holds(self):
        make_post(self.queue, "p1", extra="draft: true\ncopy_review: iris\n")
        commit_all(self.queue, "review: p1\n\nIris-Review: p1")
        problems = auto_publish.check_copy_review(self.queue, "p1")
        self.assertTrue(any("copy_review_date" in p for p in problems))

    def test_mark_value_not_iris_holds(self):
        make_post(self.queue, "p1", extra="draft: true\ncopy_review: kim\ncopy_review_date: 2026-11-18\n")
        commit_all(self.queue, "review: p1\n\nIris-Review: p1")
        problems = auto_publish.check_copy_review(self.queue, "p1")
        self.assertTrue(any("iris" in p for p in problems))

    def test_only_ko_marked_holds(self):
        make_post(self.queue, "p1", extra="draft: true\n" + MARKS)
        # en.md without marks
        en = self.queue / "posts" / "p1" / "en.md"
        en.write_text(en.read_text(encoding="utf-8").replace(MARKS, ""), encoding="utf-8")
        commit_all(self.queue, "review: p1\n\nIris-Review: p1")
        problems = auto_publish.check_copy_review(self.queue, "p1")
        self.assertTrue(any(p.startswith("en.md") for p in problems))

    def test_stamp_without_evidence_holds(self):
        """③ front matter stamp only, no commit carries the Iris-Review trailer."""
        add_queued_post(self.queue, "p1", trailer=False)
        problems = auto_publish.check_copy_review(self.queue, "p1")
        self.assertEqual(len(problems), 1)
        self.assertIn("근거 없음", problems[0])

    def test_edit_after_mark_holds(self):
        """④ marks and trailer present, but ko.md changed afterwards -> mark void."""
        add_queued_post(self.queue, "p1")
        ko = self.queue / "posts" / "p1" / "ko.md"
        ko.write_text(ko.read_text(encoding="utf-8") + "\n수정\n", encoding="utf-8")
        commit_all(self.queue, "fix: typo")
        problems = auto_publish.check_copy_review(self.queue, "p1")
        self.assertTrue(any("무효" in p for p in problems))

    def test_passes_with_marks_and_trailer(self):
        add_queued_post(self.queue, "p1")
        self.assertEqual(auto_publish.check_copy_review(self.queue, "p1"), [])

    def test_unrelated_later_commit_does_not_void(self):
        add_queued_post(self.queue, "p1")
        (self.queue / "README.md").write_text("x\n", encoding="utf-8")
        commit_all(self.queue, "docs: readme")
        self.assertEqual(auto_publish.check_copy_review(self.queue, "p1"), [])


class SlotRules(unittest.TestCase):
    """§7-3 push-blocked hours (boundaries) and the slot window."""

    def at(self, hhmm):
        h, m = map(int, hhmm.split(":"))
        return dt.datetime(2026, 11, 19, h, m, tzinfo=KST)

    def test_push_blocked_boundaries(self):
        for t in ("10:00", "10:30", "10:59", "13:00", "13:10", "14:29"):
            self.assertTrue(auto_publish.in_push_blocked(self.at(t)), t)
        for t in ("09:59", "11:00", "12:59", "14:30", "15:00"):
            self.assertFalse(auto_publish.in_push_blocked(self.at(t)), t)

    def test_slot_window(self):
        for t in ("12:00", "12:30", "14:30", "17:59"):
            self.assertTrue(auto_publish.in_slot_window(self.at(t)), t)
        for t in ("11:59", "13:00", "14:29", "18:00"):
            self.assertFalse(auto_publish.in_slot_window(self.at(t)), t)

    def test_alert_suppressed_within_three_hours(self):
        """§7-7 hold alert spam suppression."""
        last = self.at("12:00")
        self.assertFalse(auto_publish.alert_due(last, self.at("14:59")))
        self.assertTrue(auto_publish.alert_due(last, self.at("15:00")))
        self.assertTrue(auto_publish.alert_due(None, self.at("12:00")))


class DryRunContract(Base):
    def test_refuses_without_dry_run(self):
        code, _, _ = run_main("--queue-dir", str(self.queue), "--schedule", str(self.sched))
        self.assertEqual(code, 2)

    def test_paused_exits_at_once(self):
        with mock.patch.dict(os.environ, {"PUBLISH_PAUSED": "1"}), mock.patch.object(auto_publish, "load_schedule") as ls:
            code, _, last = run_main("--dry-run", "--queue-dir", str(self.tmp / "nope"), "--schedule", str(self.sched))
        self.assertEqual(code, 0)
        self.assertEqual(last, "RESULT: skip PUBLISH_PAUSED")
        ls.assert_not_called()

    def test_missing_schedule_is_normal_skip(self):
        code, _, last = run_main("--dry-run", "--queue-dir", str(self.queue), "--schedule", str(self.tmp / "none.tsv"))
        self.assertEqual(code, 0)
        self.assertEqual(last, "RESULT: skip 슬롯 파일 없음")

    def test_stock_warning_below_three(self):
        add_queued_post(self.queue, "p1")
        write_schedule(self.sched, [])
        _, out, last = run_main("--dry-run", "--queue-dir", str(self.queue), "--schedule", str(self.sched), "--main-dir", str(self.main))
        self.assertIn("WARN stock<3", out)
        self.assertEqual(last, "RESULT: skip 도래한 슬롯 없음")

    def test_g1_failure_calls_no_check_or_build_and_writes_nothing(self):
        make_post(self.queue, "p1")  # no marks, no trailer
        commit_all(self.queue, "plain draft")
        write_schedule(self.sched, [("p1", self.slot("12:30"))])
        before = snapshot(self.queue)
        with mock.patch.object(auto_publish.check_queue, "scan") as scan, mock.patch.object(publish_post, "rewrite") as rw:
            code, _, last = run_main("--dry-run", "--queue-dir", str(self.queue), "--schedule", str(self.sched),
                                     "--main-dir", str(self.main), "--now", "2026-11-19T15:20:00+09:00")
        self.assertEqual(code, 0)
        self.assertEqual(last, "RESULT: hold p1 G1")
        scan.assert_not_called()
        rw.assert_not_called()
        self.assertEqual(snapshot(self.queue), before)

    def test_g2_failure_holds(self):
        add_queued_post(self.queue, "p1", skip=("ja",))  # a language missing -> check_queue error
        write_schedule(self.sched, [("p1", self.slot("12:30"))])
        _, _, last = run_main("--dry-run", "--queue-dir", str(self.queue), "--schedule", str(self.sched),
                              "--main-dir", str(self.main), "--now", "2026-11-19T15:20:00+09:00")
        self.assertEqual(last, "RESULT: hold p1 G2")

    def test_success_publishes_in_dry_run_without_writing(self):
        add_queued_post(self.queue, "p1")
        write_schedule(self.sched, [("p1", self.slot("12:30"))])
        before = snapshot(self.queue)
        code, out, last = run_main("--dry-run", "--queue-dir", str(self.queue), "--schedule", str(self.sched),
                                   "--main-dir", str(self.main), "--now", "2026-11-19T15:20:00+09:00")
        self.assertEqual(code, 0)
        self.assertEqual(last, "RESULT: publish p1")
        self.assertIn("would publish: p1", out)
        self.assertEqual(snapshot(self.queue), before)
        self.assertEqual(subprocess.run(["git", "-C", str(self.queue), "status", "--porcelain"], capture_output=True, text=True).stdout, "")

    def slot(self, hhmm):
        return dt.datetime.fromisoformat("2026-11-19T%s:00+09:00" % hhmm)


class Selection(Base):
    """§7-2 slot selection and §7-4 remote-published completion."""

    def run_at(self, now="2026-11-19T15:20:00+09:00"):
        return run_main("--dry-run", "--queue-dir", str(self.queue), "--schedule", str(self.sched),
                        "--main-dir", str(self.main), "--now", now)

    def test_future_slot_not_selected_and_earliest_due_chosen(self):
        add_queued_post(self.queue, "early")
        add_queued_post(self.queue, "late")
        write_schedule(self.sched, [("late", "2026-11-19T14:40:00+09:00"), ("early", "2026-11-19T12:30:00+09:00")])
        self.assertEqual(self.run_at()[2], "RESULT: publish early")
        write_schedule(self.sched, [("early", "2026-11-19T16:00:00+09:00")])
        self.assertEqual(self.run_at()[2], "RESULT: skip 도래한 슬롯 없음")

    def test_already_published_today_is_not_selected(self):
        add_queued_post(self.queue, "p1")
        make_post(self.main, "done", extra="published: 2026-11-19T10:00:00+09:00\n")
        write_schedule(self.sched, [("p1", "2026-11-19T12:30:00+09:00")])
        self.assertEqual(self.run_at()[2], "RESULT: skip 오늘 이미 발행됨")

    def test_non_draft_slot_is_skipped(self):
        add_queued_post(self.queue, "p1")
        add_queued_post(self.queue, "p2")
        make_post(self.queue, "p1", extra="published: 2026-11-10T10:00:00+09:00\n")  # p1 already out (draft false)
        commit_all(self.queue, "publish: p1 (old)")
        write_schedule(self.sched, [("p1", "2026-11-19T12:30:00+09:00"), ("p2", "2026-11-19T14:40:00+09:00")])
        self.assertEqual(self.run_at("2026-11-19T15:20:00+09:00")[2], "RESULT: publish p2")

    def test_remote_published_completes_and_moves_on(self):
        add_queued_post(self.queue, "a")
        add_queued_post(self.queue, "b")
        make_post(self.main, "a", extra="published: 2026-11-10T10:00:00+09:00\n")
        write_schedule(self.sched, [("a", "2026-11-19T12:30:00+09:00"), ("b", "2026-11-19T12:40:00+09:00")])
        code, out, last = self.run_at()
        self.assertIn("완료 처리: a", out)
        self.assertEqual(last, "RESULT: publish b")

    def test_blocked_hour_defers(self):
        add_queued_post(self.queue, "p1")
        write_schedule(self.sched, [("p1", "2026-11-19T12:30:00+09:00")])
        self.assertEqual(self.run_at("2026-11-19T13:10:00+09:00")[2], "RESULT: skip 푸시 금지 시간 이월")
        self.assertEqual(self.run_at("2026-11-19T14:30:00+09:00")[2], "RESULT: publish p1")

    def test_slot_outside_window_holds(self):
        add_queued_post(self.queue, "p1")
        write_schedule(self.sched, [("p1", "2026-11-19T09:00:00+09:00")])
        self.assertEqual(self.run_at()[2], "RESULT: hold p1 슬롯창")


class StampInvariants(Base):
    """§7-5: the provisional stamp and the confirmed re-stamp keep date and published consistent across 13 files."""

    def test_restamp_keeps_thirteen_files_consistent(self):
        make_post(self.queue, "p1")
        first = dt.datetime(2026, 11, 10, 15, 20, tzinfo=KST)
        second = dt.datetime(2026, 11, 10, 15, 24, tzinfo=KST)
        publish_post.publish(str(self.queue), "p1", first)
        stamp_published.stamp(str(self.queue), "p1", second)
        files = publish_post.post_files(str(self.queue), "p1")
        self.assertEqual(len(files), len(build_site.CODES))
        stamps = {auto_publish.front_matter(f.read_text(encoding="utf-8"))["published"] for f in files}
        dates = {auto_publish.front_matter(f.read_text(encoding="utf-8"))["date"] for f in files}
        self.assertEqual(stamps, {second.isoformat(timespec="seconds")})
        self.assertEqual(dates, {"2026-11-10"})


if __name__ == "__main__":
    unittest.main()
