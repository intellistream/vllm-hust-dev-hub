from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
ENGINE = REPO_ROOT / "scripts/run_vllm_hust_engine.sh"
HELPER = REPO_ROOT / "scripts/secure_api_credential.py"
MANAGE = REPO_ROOT / "manage.sh"
MARKER = "fake_ephemeral_token_marker_0123456789abcdef"


class SecureCredentialIntegrationTests(unittest.TestCase):
    def _credential(self, root: Path, name: str = "credential") -> Path:
        path = root / name
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(MARKER.encode("ascii"))
        return path

    def _helper(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(HELPER), *args],
            text=True,
            capture_output=True,
            check=False,
        )

    def test_helper_rejects_missing_symlink_hardlink_and_mode_drift(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            missing = self._helper(
                "validate", "--path", str(root / "missing"),
                "--expected-uid", str(os.getuid()),
            )
            self.assertNotEqual(missing.returncode, 0)

            target = self._credential(root, "target")
            link = root / "link"
            link.symlink_to(target)
            linked = self._helper(
                "validate", "--path", str(link),
                "--expected-uid", str(os.getuid()),
            )
            self.assertNotEqual(linked.returncode, 0)

            hardlink = root / "hardlink"
            os.link(target, hardlink)
            hardlinked = self._helper(
                "validate", "--path", str(target),
                "--expected-uid", str(os.getuid()),
            )
            self.assertNotEqual(hardlinked.returncode, 0)
            hardlink.unlink()

            target.chmod(0o640)
            wrong_mode = self._helper(
                "validate", "--path", str(target),
                "--expected-uid", str(os.getuid()),
            )
            self.assertNotEqual(wrong_mode.returncode, 0)

    def test_exact_unit_and_container_construction_keeps_marker_out_of_text(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fake_bin = root / "bin"
            fake_bin.mkdir()
            fake_root = root / "fake-container"
            fake_root.mkdir()
            capture = root / "commands.jsonl"
            runtime = root / "runtime"
            runtime.mkdir()
            credential = self._credential(root)
            service_result = root / "service-result.json"
            systemd_capture = root / "systemctl.jsonl"
            xdg_config = root / "config"

            fake_engine = root / "fake_engine.py"
            fake_engine.write_text(
                textwrap.dedent(
                    """
                    import hashlib, json, os, sys
                    token = os.environ.get("VLLM_API_KEY", "")
                    result = {
                        "auth_enabled": bool(token),
                        "token_sha256": hashlib.sha256(token.encode()).hexdigest(),
                        "argv_contains_token": any(token and token in item for item in sys.argv),
                        "argv": sys.argv,
                    }
                    with open(os.environ["VLLM_TEST_DIGEST_PATH"], "w", encoding="utf-8") as f:
                        json.dump(result, f, sort_keys=True)
                    """
                ),
                encoding="utf-8",
            )

            fake_docker = fake_bin / "docker"
            fake_docker.write_text(
                textwrap.dedent(
                    """
                    #!/usr/bin/env python3
                    import json, os, shutil, subprocess, sys
                    from pathlib import Path

                    root = Path(os.environ["FAKE_DOCKER_ROOT"])
                    capture = Path(os.environ["FAKE_DOCKER_CAPTURE"])
                    args = sys.argv[1:]
                    with capture.open("a", encoding="utf-8") as f:
                        f.write(json.dumps(args) + "\\n")

                    def mapped(value: str) -> str:
                        if value == str(root) or value.startswith(str(root) + "/"):
                            return value
                        if value == "/run/vllm-hust":
                            return str(root / "run/vllm-hust")
                        if value.startswith("/run/vllm-hust/"):
                            return str(root / value.lstrip("/"))
                        if value.startswith("/tmp/"):
                            return str(root / value.lstrip("/"))
                        return value

                    if args[0] == "info":
                        raise SystemExit(0)
                    if args[0] == "inspect":
                        if "-f" in args:
                            print("true")
                        else:
                            print(json.dumps({"Config": {"Cmd": ["sleep", "infinity"]}, "Args": []}))
                        raise SystemExit(0)
                    if args[0] == "cp":
                        source, target = args[1], args[2]
                        destination = Path(mapped(target.split(":", 1)[1]))
                        destination.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copyfile(source, destination)
                        os.chmod(destination, 0o600)
                        raise SystemExit(0)
                    if args[0] != "exec":
                        raise SystemExit(0)
                    index = 1
                    child_env = os.environ.copy()
                    while index < len(args) and args[index] == "--env":
                        key, value = args[index + 1].split("=", 1)
                        child_env[key] = value
                        index += 2
                    index += 1  # container name
                    command = args[index:]
                    if command[:3] == ["install", "-d", "-m"]:
                        Path(mapped(command[-1])).mkdir(parents=True, exist_ok=True)
                        raise SystemExit(0)
                    if command and command[0] == "chown":
                        raise SystemExit(0)
                    if command and command[0] == "chmod":
                        mode = int(command[1], 8)
                        for item in command[2:]:
                            os.chmod(mapped(item), mode)
                        raise SystemExit(0)
                    if command[:2] == ["python3", "/run/vllm-hust/secure_api_credential.py"]:
                        command = [sys.executable, mapped(command[1]), *command[2:]]
                        command = [str(os.getuid()) if item == "0" else mapped(item) for item in command]
                        raise SystemExit(subprocess.run(command, env=child_env).returncode)
                    if command and command[0] == "rm":
                        for item in command[2:]:
                            Path(mapped(item)).unlink(missing_ok=True)
                        raise SystemExit(0)
                    if command[:2] == ["bash", command[1] if len(command) > 1 else ""]:
                        script = Path(mapped(command[1]))
                        text = script.read_text(encoding="utf-8")
                        text = text.replace("/run/vllm-hust/", str(root / "run/vllm-hust") + "/")
                        text = text.replace("--expected-uid 0", f"--expected-uid {os.getuid()}")
                        local_script = root / "tmp/inner-local.sh"
                        local_script.write_text(text, encoding="utf-8")
                        returncode = subprocess.run(["bash", str(local_script)], env=child_env).returncode
                        raise SystemExit(returncode)
                    raise SystemExit(0)
                    """
                ).lstrip(),
                encoding="utf-8",
            )
            fake_docker.chmod(0o755)

            fake_systemctl = fake_bin / "systemctl"
            fake_systemctl.write_text(
                "#!/usr/bin/env python3\n"
                "import json, os, sys\n"
                "with open(os.environ['FAKE_SYSTEMCTL_CAPTURE'], 'a') as f: "
                "f.write(json.dumps(sys.argv[1:]) + '\\n')\n",
                encoding="utf-8",
            )
            fake_systemctl.chmod(0o755)

            env = os.environ.copy()
            env.update(
                {
                    "PATH": f"{fake_bin}:{env['PATH']}",
                    "XDG_RUNTIME_DIR": str(runtime),
                    "XDG_CONFIG_HOME": str(xdg_config),
                    "FAKE_DOCKER_ROOT": str(fake_root),
                    "FAKE_DOCKER_CAPTURE": str(capture),
                    "FAKE_SYSTEMCTL_CAPTURE": str(systemd_capture),
                    "VLLM_ENGINE_AUTH_CREDENTIAL_FILE": str(credential),
                    "VLLM_ENGINE_CONTAINER": "fake-container",
                    "VLLM_ENGINE_AUTO_CREATE_CONTAINER": "false",
                    "VLLM_ENGINE_REPLACE_EXISTING": "false",
                    "VLLM_ENGINE_BIN": str(fake_engine),
                    "VLLM_ENGINE_SCRIPT": "serve-entry",
                    "VLLM_ENGINE_CONTAINER_LOG_FILE": str(root / "service.log"),
                    "VLLM_ENGINE_EXTRA_ENV_KEYS": "VLLM_TEST_DIGEST_PATH",
                    "VLLM_TEST_DIGEST_PATH": str(service_result),
                    "CONDA_PREFIX": "",
                }
            )

            installed = subprocess.run(
                [str(MANAGE), "install"], cwd=REPO_ROOT, env=env,
                text=True, capture_output=True, check=False,
            )
            self.assertEqual(installed.returncode, 0, installed.stderr)
            unit = xdg_config / "systemd/user/vllm-hust-dev-hub-engine.service"
            unit_env = unit.with_suffix(unit.suffix + ".env")
            for artifact in (unit, unit_env, systemd_capture):
                self.assertNotIn(MARKER, artifact.read_text(encoding="utf-8"))
            self.assertIn("ExecStart=", unit.read_text(encoding="utf-8"))

            launched = subprocess.run(
                [str(ENGINE)], cwd=REPO_ROOT, env=env,
                text=True, capture_output=True, check=False,
            )
            self.assertEqual(launched.returncode, 0, launched.stderr)
            self.assertFalse(credential.exists())
            result = json.loads(service_result.read_text(encoding="utf-8"))
            self.assertTrue(result["auth_enabled"])
            self.assertFalse(result["argv_contains_token"])
            self.assertEqual(
                result["token_sha256"], hashlib.sha256(MARKER.encode()).hexdigest()
            )
            self.assertNotIn("--api-key", result["argv"])

            collected = "\n".join(
                path.read_text(encoding="utf-8", errors="replace")
                for path in root.rglob("*") if path.is_file()
            )
            self.assertNotIn(MARKER, collected)
            command_text = capture.read_text(encoding="utf-8")
            self.assertNotIn(MARKER, command_text)
            self.assertNotIn("--api-key", command_text)


if __name__ == "__main__":
    unittest.main()
