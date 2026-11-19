"""Guards the publish -> deploy wiring. GITHUB_TOKEN pushes don't trigger deploy.yml, so the
publish workflow must start Deploy itself (workflow_dispatch) -- and only after a real publish."""
import re
import unittest
from pathlib import Path

WF = Path(__file__).resolve().parent.parent / ".github" / "workflows"


def step_block(text, name_fragment):
    """Text of the step whose `- name:` contains name_fragment (up to the next `- name:` or EOF)."""
    parts = re.split(r"(?m)^      - name: ", text)
    hits = [p for p in parts[1:] if name_fragment in p.splitlines()[0]]
    return hits[0] if hits else None


class PublishTriggersDeploy(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pub = (WF / "publish-scheduled.yml").read_text(encoding="utf-8")
        cls.dep = (WF / "deploy.yml").read_text(encoding="utf-8")

    def test_deploy_has_workflow_dispatch(self):
        self.assertRegex(self.dep, r"(?m)^  workflow_dispatch:")

    def test_permissions_allow_dispatch(self):
        top = self.pub.split("concurrency:")[0]
        self.assertRegex(top, r"(?m)^  actions: write")
        self.assertRegex(top, r"(?m)^  contents: write")

    def test_no_pat_or_new_secret(self):
        self.assertNotIn("secrets.", self.pub)

    def test_deploy_step_exists_and_runs_after_publish(self):
        step = step_block(self.pub, "Trigger Deploy")
        self.assertIsNotNone(step)
        self.assertIn("gh workflow run deploy.yml --ref main", step)
        self.assertIn("GH_TOKEN: ${{ github.token }}", step)
        self.assertLess(self.pub.index("- name: Auto-publish"), self.pub.index("- name: Trigger Deploy"))

    def test_deploy_only_on_real_publish(self):
        step = step_block(self.pub, "Trigger Deploy")
        # only a final `RESULT: publish <slug>` proceeds; hold/skip fall to the exit-0 branch
        self.assertIn('"RESULT: publish "*) ;;', step)
        self.assertRegex(step, r"\*\) echo .*exit 0")
        self.assertIn("Auto-Publish:", step)  # HEAD must be the auto-publish commit
        self.assertNotIn("always()", step)  # no failure/unconditional path
        # the dispatch call comes after the publish guard
        self.assertLess(step.index("RESULT: publish"), step.index("gh workflow run"))
        # workflow never passes --dry-run (a dry run's RESULT: publish must not deploy)
        self.assertNotIn("--dry-run", self.pub.split("- name: Auto-publish")[1].split("- name: Trigger Deploy")[0])


class G7CleanTreeGuards(unittest.TestCase):
    """Importing scripts/ writes scripts/__pycache__, which made G7 (dirty tree) fail on every CI tick."""
    ROOT = WF.parent.parent

    def test_deploy_has_no_workflow_run_but_keeps_dispatch(self):
        dep = (WF / "deploy.yml").read_text(encoding="utf-8")
        self.assertNotIn("workflow_run", dep)
        self.assertRegex(dep, r"(?m)^  workflow_dispatch:")
        self.assertRegex(dep, r"(?m)^  push:")

    def test_gitignore_covers_pycache(self):
        lines = (self.ROOT / ".gitignore").read_text(encoding="utf-8").split()
        self.assertIn("__pycache__/", lines)
        self.assertIn("*.pyc", lines)

    def test_publish_workflow_disables_bytecode(self):
        pub = (WF / "publish-scheduled.yml").read_text(encoding="utf-8")
        self.assertIn("PYTHONDONTWRITEBYTECODE: '1'", pub)

    def test_clean_tree_ignores_pycache_with_repo_gitignore(self):
        import shutil
        import subprocess
        import sys
        import tempfile
        sys.path.insert(0, str(self.ROOT / "scripts"))
        import auto_publish
        with tempfile.TemporaryDirectory() as d:
            subprocess.run(["git", "-C", d, "init", "-q"], check=True)
            shutil.copy(self.ROOT / ".gitignore", d)
            subprocess.run(["git", "-C", d, "add", ".gitignore"], check=True)
            subprocess.run(["git", "-C", d, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "i"], check=True)
            (Path(d) / "scripts" / "__pycache__").mkdir(parents=True)
            (Path(d) / "scripts" / "__pycache__" / "x.cpython-312.pyc").write_bytes(b"\0")
            self.assertTrue(auto_publish.clean_tree(Path(d), "queue"))
            (Path(d) / "stray.txt").write_text("x")
            self.assertFalse(auto_publish.clean_tree(Path(d), "queue"))


if __name__ == "__main__":
    unittest.main()
