from pathlib import Path
import json
import unittest


ROOT = Path(__file__).resolve().parents[1]


class DiffSpecIntegrationTests(unittest.TestCase):
    def test_workspace_clone_manifest_contains_diffspec(self) -> None:
        script = (ROOT / "scripts" / "clone-workspace-repos.sh").read_text(
            encoding="utf-8"
        )
        self.assertIn(
            "vllm-ascend-hust-diffspec|git@github.com:vLLM-HUST/"
            "vllm-ascend-hust-diffspec.git",
            script,
        )

    def test_quickstart_supports_plugins_scope(self) -> None:
        script = (ROOT / "scripts" / "quickstart.sh").read_text(
            encoding="utf-8"
        )
        self.assertIn('"plugins"', script)
        self.assertIn(
            '$WORKSPACE_ROOT/vllm-ascend-hust-diffspec',
            script,
        )

    def test_workspace_contains_diffspec_repository(self) -> None:
        workspace = json.loads(
            (ROOT / "vllm-hust-dev-hub.code-workspace").read_text(
                encoding="utf-8"
            )
        )
        paths = {folder["path"] for folder in workspace["folders"]}
        self.assertIn("../vllm-ascend-hust-diffspec", paths)

    def test_profile_enables_ascend_and_diffspec(self) -> None:
        profile = (
            ROOT / "profiles" / "diffspec-smoke-npu1.env"
        ).read_text(encoding="utf-8")
        self.assertIn("VLLM_PLUGINS=ascend,diffspec", profile)
        self.assertIn(
            "VLLM_OPTIMIZATION_REPO_CONTAINER="
            "/workspace/vllm-ascend-hust-diffspec",
            profile,
        )
        self.assertIn("VLLM_ENGINE_MAX_NUM_SEQS=1", profile)
        self.assertIn("VLLM_ENGINE_ENFORCE_EAGER=1", profile)


if __name__ == "__main__":
    unittest.main()
