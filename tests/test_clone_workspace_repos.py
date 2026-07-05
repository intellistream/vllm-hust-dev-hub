from pathlib import Path
import shlex
import subprocess
import tempfile
import unittest


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts/clone-workspace-repos.sh"


def _run(cmd: list[str], cwd: Path | None = None) -> str:
    result = subprocess.run(
        cmd,
        cwd=cwd,
        check=True,
        text=True,
        capture_output=True,
    )
    return result.stdout.strip()


def _run_bash(script: str, repo: Path) -> str:
    result = subprocess.run(
        [
            "bash",
            "-lc",
            f"repo={shlex.quote(str(repo))}; {script}",
        ],
        check=True,
        text=True,
        capture_output=True,
    )
    return result.stdout.strip()


class CloneWorkspaceReposGuardTests(unittest.TestCase):
    def test_optional_workspace_repos_do_not_fail_bootstrap(self) -> None:
        script_text = SCRIPT_PATH.read_text()

        self.assertIn(
            "fcs-domestic-chip-llm-recsys|git@github.com:vLLM-HUST/"
            "fcs-domestic-chip-llm-recsys.git|optional",
            script_text,
        )
        self.assertIn('repo_is_optional "$entry"', script_text)
        self.assertIn("optional repository $relative_path is unavailable; skipping", script_text)

    def _create_repo_with_deleted_upstream(self, branch_name: str) -> Path:
        tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(tmpdir.cleanup)

        tmp_path = Path(tmpdir.name)
        source_repo = tmp_path / "source"
        remote_repo = tmp_path / "remote.git"
        work_repo = tmp_path / "work"

        _run(["git", "init", "-b", "main", str(source_repo)])
        _run(["git", "config", "user.name", "Quickstart Test"], cwd=source_repo)
        _run(["git", "config", "user.email", "quickstart-test@example.com"], cwd=source_repo)
        (source_repo / "README.md").write_text("seed\n")
        _run(["git", "add", "README.md"], cwd=source_repo)
        _run(["git", "commit", "-m", "seed"], cwd=source_repo)

        _run(["git", "clone", "--bare", str(source_repo), str(remote_repo)])
        _run(["git", "clone", str(remote_repo), str(work_repo)])
        _run(["git", "config", "user.name", "Quickstart Test"], cwd=work_repo)
        _run(["git", "config", "user.email", "quickstart-test@example.com"], cwd=work_repo)

        _run(["git", "checkout", "-b", branch_name], cwd=work_repo)
        (work_repo / "README.md").write_text("seed\nbranch\n")
        _run(["git", "add", "README.md"], cwd=work_repo)
        _run(["git", "commit", "-m", "branch commit"], cwd=work_repo)
        _run(["git", "push", "-u", "origin", branch_name], cwd=work_repo)
        _run(["git", "push", "origin", "--delete", branch_name], cwd=work_repo)
        _run(["git", "fetch", "--prune"], cwd=work_repo)

        return work_repo

    def test_missing_upstream_branch_does_not_leave_literal_at_u(self) -> None:
        branch_name = "ws/fix-actions-26145186169-26145186140"
        work_repo = self._create_repo_with_deleted_upstream(branch_name)

        old_behavior = _run_bash(
            "upstream_ref=$(git -C \"$repo\" rev-parse --abbrev-ref --symbolic-full-name '@{u}' 2>/dev/null || true); "
            'printf "%s" "$upstream_ref"',
            work_repo,
        )
        fixed_behavior = _run_bash(
            "upstream_ref=$(git -C \"$repo\" rev-parse --abbrev-ref --symbolic-full-name '@{u}' 2>/dev/null) || upstream_ref=\"\"; "
            'printf "%s" "$upstream_ref"',
            work_repo,
        )

        self.assertEqual(old_behavior, "@{u}")
        self.assertEqual(fixed_behavior, "")

    def test_deleted_upstream_branch_is_distinguished_from_missing_config(self) -> None:
        branch_name = "ws/fix-actions-26145186169-26145186140"
        work_repo = self._create_repo_with_deleted_upstream(branch_name)

        message = _run_bash(
            "branch_name=$(git -C \"$repo\" rev-parse --abbrev-ref HEAD 2>/dev/null || true); "
            "configured_remote=$(git -C \"$repo\" config --get \"branch.$branch_name.remote\" 2>/dev/null || true); "
            "configured_merge_ref=$(git -C \"$repo\" config --get \"branch.$branch_name.merge\" 2>/dev/null || true); "
            "upstream_ref=$(git -C \"$repo\" rev-parse --abbrev-ref --symbolic-full-name '@{u}' 2>/dev/null) || upstream_ref=\"\"; "
            "if [[ -z \"$upstream_ref\" ]]; then "
            "  if [[ -n \"$configured_remote\" && -n \"$configured_merge_ref\" ]]; then "
            "    configured_upstream_ref=\"$configured_remote/${configured_merge_ref#refs/heads/}\"; "
            '    printf "[skip] repo current branch %s tracks %s, but that upstream branch is unavailable" "$branch_name" "$configured_upstream_ref"; '
            "  else "
            '    printf "[skip] repo has no upstream tracking branch"; '
            "  fi; "
            "fi",
            work_repo,
        )

        self.assertEqual(
            message,
            f"[skip] repo current branch {branch_name} tracks origin/{branch_name}, but that upstream branch is unavailable",
        )


if __name__ == "__main__":
    unittest.main()
