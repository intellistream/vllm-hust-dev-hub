from pathlib import Path
import re
import unittest


WORKFLOW_PATH = Path(__file__).resolve().parents[1] / ".github/workflows/quickstart-ci.yml"
SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts/ci/quickstart_ci.sh"


def _extract_block(text: str, anchor: str) -> str:
    marker = f"  {anchor}:\n"
    start = text.find(marker)
    if start == -1:
        raise AssertionError(f"Missing workflow block: {anchor}")

    remainder = text[start + len(marker):]
    next_job = re.search(r"^  [A-Za-z0-9_-]+:\s*$", remainder, re.MULTILINE)
    if next_job is None:
        return remainder
    return remainder[:next_job.start()]


class QuickstartWorkflowGuardTests(unittest.TestCase):
    def test_self_hosted_job_keeps_ssh_clone_guards(self) -> None:
        workflow_text = WORKFLOW_PATH.read_text()
        self_hosted_block = _extract_block(workflow_text, "quickstart-self-hosted")

        self.assertIn(
            "ssh-key: ${{ secrets.VLLM_HUST_CI_SSH_PRIVATE_KEY }}",
            self_hosted_block,
        )
        self.assertIn(
            "- name: Prepare GitHub SSH key for downstream clones",
            self_hosted_block,
        )
        self.assertIn("HUST_DEV_HUB_GIT_AUTH_MODE: ssh", self_hosted_block)

    def test_quickstart_ci_script_still_supports_ssh_mode(self) -> None:
        script_text = SCRIPT_PATH.read_text()

        self.assertIn(
            'if [[ "${HUST_DEV_HUB_GIT_AUTH_MODE:-https}" == "ssh" ]]; then',
            script_text,
        )
        self.assertIn(
            'log "Using SSH clone/auth mode for workspace repositories"',
            script_text,
        )


if __name__ == "__main__":
    unittest.main()