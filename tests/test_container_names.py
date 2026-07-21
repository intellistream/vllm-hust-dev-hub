from concurrent.futures import ThreadPoolExecutor
import os
from pathlib import Path
import shutil
import stat
import subprocess
import tempfile
import unittest


REPO_ROOT = Path(__file__).resolve().parents[1]
NAME_SCRIPT = REPO_ROOT / "scripts" / "container-name.sh"
CONTAINER_SCRIPT = REPO_ROOT / "scripts" / "ascend-official-container.sh"
QUICKSTART_SCRIPT = REPO_ROOT / "scripts" / "quickstart.sh"


class ContainerNameTests(unittest.TestCase):
    def run_name_shell(self, command: str, **env_overrides: str) -> subprocess.CompletedProcess[str]:
        env = os.environ.copy()
        env.update(env_overrides)
        return subprocess.run(
            ["bash", "-c", 'source "$1"; shift; eval "$@"', "bash", str(NAME_SCRIPT), command],
            cwd=REPO_ROOT,
            env=env,
            text=True,
            capture_output=True,
            check=False,
        )

    def test_default_name_uses_image_and_login_and_is_docker_legal(self) -> None:
        result = self.run_name_shell(
            "name=\"$(container_name_from_image_and_user "
            "'quay.io/ascend/vllm-ascend:v0.13.0-openeuler' 'gcw')\"; "
            'docker_container_name_is_valid "$name"; printf "%s" "$name"'
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "vllm-ascend-v0.13.0-openeuler-gcw")

    def test_invalid_names_are_rejected(self) -> None:
        for name in ("has spaces", "vllm:tag-user", "-starts-with-dash", "x"):
            with self.subTest(name=name):
                result = self.run_name_shell(f"validate_docker_container_name {name!r}")
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("Invalid container name", result.stderr)

    def test_generated_names_respect_docker_length_limit(self) -> None:
        result = self.run_name_shell(
            "name=\"$(container_name_from_image_and_user "
            "'registry.example/'\"$(printf 'a%.0s' {1..300})\"':tag' 'user')\"; "
            'validate_docker_container_name "$name"; printf "%s\\n%s" "${#name}" "$name"'
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        length, name = result.stdout.splitlines()
        self.assertEqual(length, "255")
        self.assertTrue(name.endswith("-user"))

    def test_canonical_name_wins_and_legacy_name_remains_compatible(self) -> None:
        canonical = self.run_name_shell(
            "configured_vllm_engine_container_name",
            VLLM_ENGINE_CONTAINER_NAME="canonical-instance",
            VLLM_ENGINE_CONTAINER="legacy-instance",
        )
        legacy = self.run_name_shell(
            "configured_vllm_engine_container_name",
            VLLM_ENGINE_CONTAINER_NAME="",
            VLLM_ENGINE_CONTAINER="legacy-instance",
        )

        self.assertEqual(canonical.stdout.strip(), "canonical-instance")
        self.assertIn("overrides deprecated", canonical.stderr)
        self.assertEqual(legacy.stdout.strip(), "legacy-instance")
        self.assertIn("deprecated", legacy.stderr)

    def test_parallel_instances_pass_distinct_names_to_manager(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            fake_python = temp / "python3"
            fake_python.write_text(
                "#!/usr/bin/env bash\nprintf '%s\\n' \"$@\" > \"$CAPTURE_FILE\"\n",
                encoding="utf-8",
            )
            fake_python.chmod(fake_python.stat().st_mode | stat.S_IXUSR)

            def invoke(name: str) -> list[str]:
                capture = temp / f"{name}.args"
                env = os.environ.copy()
                env.update(
                    {
                        "PATH": f"{temp}:{env['PATH']}",
                        "CAPTURE_FILE": str(capture),
                        "HUST_ASCEND_MANAGER_SRC": str(temp / "manager-src"),
                        "VLLM_ENGINE_CONTAINER_NAME": name,
                    }
                )
                subprocess.run(
                    [str(CONTAINER_SCRIPT), "status"],
                    cwd=REPO_ROOT,
                    env=env,
                    text=True,
                    capture_output=True,
                    check=True,
                )
                return capture.read_text(encoding="utf-8").splitlines()

            names = ("worker-one", "worker-two")
            with ThreadPoolExecutor(max_workers=2) as executor:
                results = list(executor.map(invoke, names))

            for name, args in zip(names, results):
                index = args.index("--container-name")
                self.assertEqual(args[index + 1], name)

    def test_quickstart_menu_passes_the_entered_name(self) -> None:
        script = QUICKSTART_SCRIPT.read_text(encoding="utf-8")

        self.assertIn('container_name="$(prompt_for_ascend_container_name)"', script)
        self.assertIn(
            "Press Enter to use the default [$default_name], or input a container name:",
            script,
        )
        self.assertIn("ensure_ascend_container_manager_source", script)
        self.assertIn('VLLM_ENGINE_CONTAINER_NAME="$container_name"', script)

    def test_container_helper_reports_missing_manager_source(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            fake_python = temp / "python3"
            fake_python.write_text("#!/usr/bin/env bash\nexit 1\n", encoding="utf-8")
            fake_python.chmod(fake_python.stat().st_mode | stat.S_IXUSR)
            env = os.environ.copy()
            env.update(
                {
                    "PATH": f"{temp}:{env['PATH']}",
                    "HUST_ASCEND_MANAGER_SRC": str(temp / "missing-manager-src"),
                }
            )

            result = subprocess.run(
                [str(CONTAINER_SCRIPT), "status"],
                cwd=REPO_ROOT,
                env=env,
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("找不到 hust_ascend_manager", result.stderr)
            self.assertIn("HUST_ASCEND_MANAGER_SRC", result.stderr)

    def test_run_name_shell_works_with_spaced_repo_path(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            spaced_root = Path(temp_dir) / "spaced checkout path"
            spaced_root.mkdir()
            scripts_dir = spaced_root / "scripts"
            scripts_dir.mkdir()
            name_script = scripts_dir / "container-name.sh"
            shutil.copy2(NAME_SCRIPT, name_script)

            result = subprocess.run(
                ["bash", "-c", 'source "$1"; shift; eval "$@"', "bash",
                 str(name_script),
                 "name=\"$(container_name_from_image_and_user 'quay.io/ascend/vllm-ascend:v0.13.0-openeuler' 'gcw')\"; "
                 'docker_container_name_is_valid "$name"; printf "%s" "$name"'],
                cwd=str(spaced_root),
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout, "vllm-ascend-v0.13.0-openeuler-gcw")

    def test_container_script_help_works_without_manager_module(self) -> None:
        env = os.environ.copy()
        env["HUST_ASCEND_MANAGER_SRC"] = "/nonexistent/manager/path"

        result = subprocess.run(
            [str(CONTAINER_SCRIPT), "--help"],
            cwd=REPO_ROOT,
            env=env,
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Usage:", result.stdout)
        self.assertIn("install", result.stdout)
        self.assertIn("VLLM_ENGINE_CONTAINER_NAME", result.stdout)


if __name__ == "__main__":
    unittest.main()
