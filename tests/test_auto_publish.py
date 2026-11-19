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
        self.assertTrue(any("근거 없음" in x for x in problems))
        self.assertTrue(any("iris-review.json" in x for x in problems))

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
        self.assertTrue(auto_publish.alert_due(self.at("13:00"), self.at("12:00")))  # future stamp never mutes


class DryRunContract(Base):
    def test_real_run_rejects_backdated_now(self):
        code, _, _ = run_main("--queue-dir", str(self.queue), "--schedule", str(self.sched), "--now", "2026-11-19T15:20:00+09:00")
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


def sidecar(root, post, **over):
    """posts/<slug>/iris-review.json for the files as they are now."""
    rec = {"slug": post, "reviewer": "iris", "date": "2026-11-19"}
    for lang in ("ko", "en"):
        rec[lang + "_sha256"] = hashlib.sha256((Path(root) / "posts" / post / (lang + ".md")).read_bytes()).hexdigest()
    rec.update(over)
    (Path(root) / "posts" / post / "iris-review.json").write_text(__import__("json").dumps(rec), encoding="utf-8")


class IrisSidecar(Base):
    """W2: iris-review.json is an alternative evidence that survives a squash/rebase of the queue."""

    def test_sidecar_passes_without_trailer(self):
        add_queued_post(self.queue, "p1", trailer=False)
        sidecar(self.queue, "p1")
        commit_all(self.queue, "squashed queue")
        self.assertEqual(auto_publish.check_copy_review(self.queue, "p1"), [])

    def test_sidecar_hash_mismatch_holds(self):
        add_queued_post(self.queue, "p1", trailer=False)
        sidecar(self.queue, "p1")
        ko = self.queue / "posts" / "p1" / "ko.md"
        ko.write_text(ko.read_text(encoding="utf-8") + "\n수정\n", encoding="utf-8")
        problems = auto_publish.check_copy_review(self.queue, "p1")
        self.assertTrue(any("ko_sha256" in x for x in problems))

    def test_sidecar_en_mismatch_holds(self):
        add_queued_post(self.queue, "p1", trailer=False)
        sidecar(self.queue, "p1", en_sha256="0" * 64)
        self.assertTrue(any("en_sha256" in x for x in auto_publish.check_copy_review(self.queue, "p1")))

    def test_stamp_only_still_holds(self):
        add_queued_post(self.queue, "p1", trailer=False)  # marks, no trailer, no sidecar
        self.assertTrue(auto_publish.check_copy_review(self.queue, "p1"))

    def test_sidecar_without_marks_still_holds(self):
        add_queued_post(self.queue, "p1", marks=False, trailer=False)
        sidecar(self.queue, "p1")
        self.assertTrue(any("copy_review" in x for x in auto_publish.check_copy_review(self.queue, "p1")))

    def test_sidecar_wrong_reviewer_or_slug_holds(self):
        add_queued_post(self.queue, "p1", trailer=False)
        sidecar(self.queue, "p1", reviewer="kim")
        self.assertTrue(auto_publish.check_copy_review(self.queue, "p1"))
        sidecar(self.queue, "p1", slug="other")
        self.assertTrue(auto_publish.check_copy_review(self.queue, "p1"))

    def test_corrupt_sidecar_holds(self):
        add_queued_post(self.queue, "p1", trailer=False)
        (self.queue / "posts" / "p1" / "iris-review.json").write_text("{nope", encoding="utf-8")
        self.assertTrue(auto_publish.check_copy_review(self.queue, "p1"))

    def test_sidecar_rescues_edit_after_trailer_when_rehashed(self):
        add_queued_post(self.queue, "p1")
        ko = self.queue / "posts" / "p1" / "ko.md"
        ko.write_text(ko.read_text(encoding="utf-8") + "\n수정\n", encoding="utf-8")
        commit_all(self.queue, "fix")
        self.assertTrue(auto_publish.check_copy_review(self.queue, "p1"))  # trailer voided
        sidecar(self.queue, "p1")  # Iris re-reviewed the new bytes
        self.assertEqual(auto_publish.check_copy_review(self.queue, "p1"), [])


class AlertState(Base):
    """W1: hold alerts are suppressed for 3 hours through a JSON state file."""

    def hold_run(self, now):
        return run_main("--dry-run", "--queue-dir", str(self.queue), "--schedule", str(self.sched), "--main-dir", str(self.main),
                        "--state-file", str(self.tmp / "st" / "state.json"), "--now", now)

    def test_second_hold_within_three_hours_is_muted_then_repeats(self):
        make_post(self.queue, "p1")
        commit_all(self.queue, "plain draft")
        write_schedule(self.sched, [("p1", "2026-11-19T12:30:00+09:00")])
        _, out, last = self.hold_run("2026-11-19T15:00:00+09:00")
        self.assertEqual(last, "RESULT: hold p1 G1")
        self.assertIn("ALERT ⏸ Iris 검수 대기: p1", out)
        _, out, _ = self.hold_run("2026-11-19T17:30:00+09:00")  # 2h30 later
        self.assertNotIn("ALERT ⏸", out)
        self.assertIn("ALERT 억제", out)
        _, out, _ = self.hold_run("2026-11-19T18:00:00+09:00")  # 3h later
        self.assertIn("ALERT ⏸ Iris 검수 대기: p1", out)

    def test_state_cleared_when_gate_passes(self):
        make_post(self.queue, "p1")
        commit_all(self.queue, "plain draft")
        write_schedule(self.sched, [("p1", "2026-11-19T12:30:00+09:00")])
        self.hold_run("2026-11-19T15:00:00+09:00")
        add_queued_post(self.queue, "p1")  # Iris marks it
        _, _, last = self.hold_run("2026-11-19T15:10:00+09:00")
        self.assertEqual(last, "RESULT: publish p1")
        self.assertNotIn("p1:G1", auto_publish.load_state(self.tmp / "st" / "state.json"))

    def test_corrupt_state_file_alerts_instead_of_crashing(self):
        make_post(self.queue, "p1")
        commit_all(self.queue, "plain draft")
        write_schedule(self.sched, [("p1", "2026-11-19T12:30:00+09:00")])
        (self.tmp / "st").mkdir()
        (self.tmp / "st" / "state.json").write_text("{broken", encoding="utf-8")
        _, out, last = self.hold_run("2026-11-19T15:00:00+09:00")
        self.assertEqual(last, "RESULT: hold p1 G1")
        self.assertIn("ALERT ⏸", out)


class RealPublish(Base):
    """Stage 3 against a temp main repo with a local bare remote (never a real remote)."""

    NOW = dt.datetime(2026, 11, 10, 15, 20, tzinfo=KST)

    def setUp(self):
        super().setUp()
        self.bare = self.tmp / "remote.git"
        subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(self.bare)], check=True)
        init_repo(self.main)
        git(self.main, "checkout", "-q", "-b", "main")
        (self.main / "README.md").write_text("main\n", encoding="utf-8")
        make_post(self.main, "old", extra="published: 2026-11-01T16:00:00+09:00\n")
        commit_all(self.main, "init")
        git(self.main, "remote", "add", "origin", str(self.bare))
        git(self.main, "push", "-q", "origin", "main")
        add_queued_post(self.queue, "p1")
        write_schedule(self.sched, [("p1", "2026-11-10T12:30:00+09:00")])
        self.patches = [mock.patch.object(auto_publish, "now_kst", return_value=self.NOW),
                        mock.patch.object(auto_publish, "gate_cmds", return_value=[])]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        super().tearDown()

    def run_real(self, *extra):
        return run_main("--queue-dir", str(self.queue), "--schedule", str(self.sched), "--main-dir", str(self.main), *extra)

    def remote_head(self):
        return subprocess.run(["git", "-C", str(self.bare), "rev-parse", "main"], capture_output=True, text=True).stdout.strip()

    def test_publishes_commits_and_pushes(self):
        code, out, last = self.run_real()
        self.assertEqual((code, last), (0, "RESULT: publish p1"))
        self.assertEqual(self.remote_head(), subprocess.run(["git", "-C", str(self.main), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip())
        files = publish_post.post_files(str(self.main), "p1")
        self.assertEqual(len(files), len(build_site.CODES))
        stamps = set()
        for f in files:
            meta = auto_publish.front_matter(f.read_text(encoding="utf-8"))
            self.assertNotIn("draft", meta)
            self.assertEqual(meta["date"], "2026-11-10")
            stamps.add(meta["published"])
        self.assertEqual(stamps, {"2026-11-10T15:20:00+09:00"})
        msg = subprocess.run(["git", "-C", str(self.main), "log", "-1", "--format=%B"], capture_output=True, text=True).stdout
        self.assertIn("Auto-Publish: p1 2026-11-10T12:30+09:00", msg)
        self.assertEqual(subprocess.run(["git", "-C", str(self.main), "diff", "--stat", "HEAD~1", "HEAD", "--diff-filter=D"],
                                        capture_output=True, text=True).stdout.strip(), "")
        self.assertFalse((self.main / "posts" / "p1" / "iris-review.json").exists())

    def test_second_run_same_day_does_nothing(self):
        self.run_real()
        before = self.remote_head()
        _, _, last = self.run_real()
        self.assertEqual(last, "RESULT: skip 오늘 이미 발행됨")
        self.assertEqual(self.remote_head(), before)

    def test_no_iris_evidence_holds_and_main_untouched(self):
        add_queued_post(self.queue, "p2", trailer=False)  # marks only
        write_schedule(self.sched, [("p2", "2026-11-10T12:30:00+09:00")])
        head, remote = git_out(self.main, "rev-parse", "HEAD"), self.remote_head()
        _, _, last = self.run_real()
        self.assertEqual(last, "RESULT: hold p2 G1")
        self.assertEqual(git_out(self.main, "rev-parse", "HEAD"), head)
        self.assertEqual(self.remote_head(), remote)
        self.assertFalse((self.main / "posts" / "p2").exists())

    def test_gate_failure_rolls_back_and_does_not_commit(self):
        head = git_out(self.main, "rev-parse", "HEAD")
        with mock.patch.object(auto_publish, "run_cmds", return_value=["G6 unittest 실패 (exit 1)"]):
            _, out, last = self.run_real()
        self.assertEqual(last, "RESULT: hold p1 G4~G6")
        self.assertEqual(git_out(self.main, "rev-parse", "HEAD"), head)
        self.assertEqual(git_out(self.main, "status", "--porcelain"), "")
        self.assertFalse((self.main / "posts" / "p1").exists())

    def test_deleted_file_blocks_commit(self):
        head = git_out(self.main, "rev-parse", "HEAD")

        calls = []

        def sabotage(main_dir, cmds):
            calls.append(1)
            if len(calls) == 2:  # the confirmed-stamp re-check: a build step deleted a tracked file
                (Path(main_dir) / "README.md").unlink()
            return []
        with mock.patch.object(auto_publish, "run_cmds", side_effect=sabotage):
            _, _, last = self.run_real()
        self.assertEqual(last, "RESULT: hold p1 G4~G7")
        self.assertEqual(git_out(self.main, "rev-parse", "HEAD"), head)
        self.assertTrue((self.main / "README.md").exists())

    def test_push_rejection_rewinds_and_restamps(self):
        other = self.tmp / "other"
        subprocess.run(["git", "clone", "-q", str(self.bare), str(other)], check=True)
        calls = {"n": 0}
        real_run = subprocess.run

        def racing(argv, *a, **kw):
            if isinstance(argv, list) and "push" in argv and calls["n"] == 0:
                calls["n"] += 1
                (other / "x.txt").write_text("x\n", encoding="utf-8")
                commit_all(other, "someone else")
                git(other, "push", "-q", "origin", "main")
            return real_run(argv, *a, **kw)
        with mock.patch.object(auto_publish.subprocess, "run", side_effect=racing):
            _, out, last = self.run_real()
        self.assertEqual(last, "RESULT: publish p1")
        self.assertIn("push 거절(1/3)", out)
        self.assertTrue((self.main / "x.txt").exists())
        self.assertEqual(self.remote_head(), git_out(self.main, "rev-parse", "HEAD"))

    def test_push_rejection_with_other_post_today_stops(self):
        """되감기 뒤 원격에 오늘자 다른 글이 있으면 하루 1편 규칙으로 중단한다."""
        other = self.tmp / "other"
        subprocess.run(["git", "clone", "-q", str(self.bare), str(other)], check=True)
        calls = {"n": 0}
        real_run = subprocess.run

        def racing(argv, *a, **kw):
            if isinstance(argv, list) and "push" in argv and calls["n"] == 0:
                calls["n"] += 1
                make_post(other, "x", extra="published: 2026-11-10T13:00:00+09:00\n")
                commit_all(other, "other today")
                git(other, "push", "-q", "origin", "main")
            return real_run(argv, *a, **kw)
        with mock.patch.object(auto_publish.subprocess, "run", side_effect=racing):
            _, out, last = self.run_real()
        self.assertEqual(last, "RESULT: hold p1 dup")
        self.assertIn("오늘(KST) 다른 글이 발행됨", out)
        self.assertFalse((self.main / "posts" / "p1").exists())
        self.assertEqual(calls["n"], 1)

    def test_push_blocked_recheck_before_push(self):
        """push 직전 금지 시간대에 들어서면 push 하지 않고 커밋을 되돌린다."""
        remote, head = self.remote_head(), git_out(self.main, "rev-parse", "HEAD")
        real_blocked = auto_publish.in_push_blocked
        n = {"c": 0}

        def blocked_late(when):
            n["c"] += 1
            return True if n["c"] >= 3 else real_blocked(when)
        with mock.patch.object(auto_publish, "in_push_blocked", side_effect=blocked_late):
            _, out, last = self.run_real()
        self.assertEqual(last, "RESULT: hold p1 G8")
        self.assertEqual(self.remote_head(), remote)
        self.assertEqual(git_out(self.main, "rev-parse", "HEAD"), head)
        self.assertFalse((self.main / "posts" / "p1").exists())

    def test_push_rejected_three_times_holds(self):
        real = subprocess.run

        def always_reject(argv, *a, **kw):
            if isinstance(argv, list) and "push" in argv:
                return subprocess.CompletedProcess(argv, 1, "", "rejected")
            return real(argv, *a, **kw)
        with mock.patch.object(auto_publish.subprocess, "run", side_effect=always_reject):
            _, _, last = self.run_real()
        self.assertEqual(last, "RESULT: hold p1 push")

    def test_no_push_keeps_commit_local(self):
        remote = self.remote_head()
        _, _, last = self.run_real("--no-push")
        self.assertEqual(last, "RESULT: publish p1")
        self.assertEqual(self.remote_head(), remote)
        self.assertNotEqual(git_out(self.main, "rev-parse", "HEAD"), remote)

    def test_dirty_main_tree_refuses(self):
        (self.main / "stray.txt").write_text("x\n", encoding="utf-8")
        _, _, last = self.run_real()
        self.assertEqual(last, "RESULT: hold p1 G7")

    def test_existing_main_post_dir_is_never_overwritten(self):
        make_post(self.main, "p1")  # leftover non-published folder in main
        commit_all(self.main, "leftover")
        _, _, last = self.run_real()
        self.assertEqual(last, "RESULT: hold p1 G7")

    def test_queue_checkout_inside_main_is_ignored_and_not_committed(self):
        inner = self.main / "queue"
        shutil.copytree(self.queue, inner)
        write_schedule(self.sched, [("p1", "2026-11-10T12:30:00+09:00")])
        _, _, last = self.run_real("--queue-dir", str(inner))
        self.assertEqual(last, "RESULT: publish p1")
        tracked = git_out(self.main, "ls-files")
        self.assertNotIn("queue/", tracked)
        self.assertTrue((inner / "posts" / "p1").is_dir())

    def test_auto_publish_trailer_in_recent_history_skips(self):
        git(self.main, "commit", "-q", "--allow-empty", "-m", "publish: p1\n\nAuto-Publish: p1 2026-11-10T12:30+09:00")
        _, _, last = self.run_real()
        self.assertEqual(last, "RESULT: skip 이미 발행됨")

    def test_paused_real_run_writes_nothing(self):
        head = git_out(self.main, "rev-parse", "HEAD")
        with mock.patch.dict(os.environ, {"PUBLISH_PAUSED": "1"}):
            _, _, last = self.run_real()
        self.assertEqual(last, "RESULT: skip PUBLISH_PAUSED")
        self.assertEqual(git_out(self.main, "rev-parse", "HEAD"), head)


class GateCommands(unittest.TestCase):
    def test_gate_cmds_shape(self):
        full = auto_publish.gate_cmds("/x", full=True)
        fast = auto_publish.gate_cmds("/x", full=False)
        self.assertEqual([n for n, _ in full][-1], "G6 unittest")
        self.assertEqual(len(full), len(fast) + 1)
        self.assertTrue(all(argv[1].startswith("/x/scripts/") for n, argv in fast))

    def test_run_cmds_reports_failures_with_output_tail(self):
        ok = ("ok", [sys.executable, "-c", "pass"])
        bad = ("G4 bad", [sys.executable, "-c", "import sys;print('boom');sys.exit(3)"])
        problems = auto_publish.run_cmds(".", [ok, bad])
        self.assertEqual(len(problems), 1)
        self.assertIn("exit 3", problems[0])
        self.assertIn("boom", problems[0])


def git_out(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True).stdout.strip()


if __name__ == "__main__":
    unittest.main()
