from pathlib import Path
import importlib.util
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import textwrap
import unittest


REPO_ROOT = Path(__file__).resolve().parents[1]
MANAGE_SCRIPT = REPO_ROOT / "manage.sh"
ENGINE_SCRIPT = REPO_ROOT / "scripts" / "run_vllm_hust_engine.sh"
CONTAINER_RUNTIME_SCRIPT = REPO_ROOT / "scripts" / "ascend-container-runtime.sh"
CONTAINER_RUNTIME_STAGER = REPO_ROOT / "scripts" / "stage_container_runtime.py"
CONTAINER_RUNTIME_PROOF = (
    REPO_ROOT / "scripts" / "prove_container_runtime_carrier.py"
)
OFFICIAL_CONTAINER_SCRIPT = REPO_ROOT / "scripts" / "ascend-official-container.sh"
ENV_TEMPLATE = REPO_ROOT / ".env.template"
README = REPO_ROOT / "README.md"
MULTILINE_IMPORT_PREFLIGHT = (
    REPO_ROOT / "tests/fixtures/kvdelta_multiline_import_preflight.py"
)


class ManageEngineGuardTests(unittest.TestCase):
    def test_management_scripts_are_executable_and_syntax_valid(self) -> None:
        for script in (MANAGE_SCRIPT, ENGINE_SCRIPT):
            mode = script.stat().st_mode
            self.assertTrue(mode & stat.S_IXUSR, f"{script} should be executable")
            subprocess.run(["bash", "-n", str(script)], check=True)
        subprocess.run(["bash", "-n", str(CONTAINER_RUNTIME_SCRIPT)], check=True)
        subprocess.run(
            ["python3", "-m", "py_compile", str(CONTAINER_RUNTIME_STAGER)],
            check=True,
        )
        subprocess.run(
            ["python3", "-m", "py_compile", str(CONTAINER_RUNTIME_PROOF)],
            check=True,
        )

    def test_runtime_carrier_removes_restrictive_checkout_dac_dependency(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            run_root = tmp_path / "managed-container-runs" / "fixture"
            run_root.mkdir(parents=True, mode=0o770)
            run_root.chmod(0o770)

            result = subprocess.run(
                [
                    "python3",
                    str(CONTAINER_RUNTIME_STAGER),
                    "--source",
                    str(CONTAINER_RUNTIME_SCRIPT),
                    "--run-root",
                    str(run_root),
                    "--expected-run-root",
                    str(run_root),
                ],
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)

            carrier = run_root / "container-runtime-carrier"
            staged = carrier / "scripts" / CONTAINER_RUNTIME_SCRIPT.name
            receipt = json.loads(
                (run_root / "container-runtime-carrier-receipt.json").read_text()
            )
            self.assertEqual(staged.read_bytes(), CONTAINER_RUNTIME_SCRIPT.read_bytes())
            self.assertEqual(stat.S_IMODE(carrier.stat().st_mode), 0o555)
            self.assertEqual(stat.S_IMODE(staged.parent.stat().st_mode), 0o555)
            self.assertEqual(stat.S_IMODE(staged.stat().st_mode), 0o555)
            self.assertEqual(receipt["source_sha256"], receipt["staged_sha256"])
            self.assertEqual(
                receipt["carrier_container"], "/opt/vllm-hust-runtime-carrier"
            )

            probe = subprocess.run(
                [str(staged)],
                env={**os.environ, "ASCEND_CONTAINER_RUNTIME_PROBE_ONLY": "1"},
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(probe.returncode, 0, probe.stderr)
            self.assertEqual(probe.stdout.strip(), "ASCEND_CONTAINER_RUNTIME_PROBE_OK")

            # Reproduce the consumed run's permission boundary without Docker:
            # uid 0 with no DAC capabilities is "other" for a uid-owned 0700
            # checkout and therefore cannot traverse it.
            legacy = tmp_path / "legacy-third-party"
            legacy_scripts = legacy / "vllm-hust-dev-hub" / "scripts"
            legacy_scripts.mkdir(parents=True)
            legacy.chmod(0o700)
            (legacy / "vllm-hust-dev-hub").chmod(0o700)
            legacy_scripts.chmod(0o700)
            legacy_runtime = legacy_scripts / CONTAINER_RUNTIME_SCRIPT.name
            legacy_runtime.write_bytes(CONTAINER_RUNTIME_SCRIPT.read_bytes())
            legacy_runtime.chmod(0o600)

            def permits_other(path: Path, mask: int) -> bool:
                return stat.S_IMODE(path.stat().st_mode) & mask == mask

            self.assertFalse(permits_other(legacy, stat.S_IXOTH))
            self.assertFalse(permits_other(legacy_runtime, stat.S_IROTH))
            self.assertTrue(permits_other(carrier, stat.S_IXOTH))
            self.assertTrue(permits_other(staged.parent, stat.S_IXOTH))
            self.assertTrue(permits_other(staged, stat.S_IROTH | stat.S_IXOTH))

    def test_official_container_forwards_runtime_carrier_before_pid1(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            calls = tmp_path / "python-argv.json"
            fake_python = tmp_path / "python"
            fake_python.write_text(
                "#!/usr/bin/env python3\n"
                "import json, os, sys\n"
                "open(os.environ['FAKE_MANAGER_ARGV'], 'w').write(json.dumps(sys.argv[1:]))\n",
                encoding="utf-8",
            )
            fake_python.chmod(0o700)
            fake_docker = tmp_path / "docker"
            fake_docker.write_text(
                "#!/usr/bin/env bash\n"
                "if [[ \"$1\" == info && \"$2\" == --format ]]; then "
                "printf '/data/docker\\n'; else exit 0; fi\n",
                encoding="utf-8",
            )
            fake_docker.chmod(0o700)
            run_root = tmp_path / "run"
            runtime_carrier = run_root / "container-runtime-carrier"
            runtime_carrier.mkdir(parents=True)
            optimization = tmp_path / "optimization"
            optimization.mkdir()
            env = os.environ.copy()
            env.update(
                {
                    "PATH": f"{tmp_path}:{env['PATH']}",
                    "HUST_ASCEND_MANAGER_PYTHON": str(fake_python),
                    "FAKE_MANAGER_ARGV": str(calls),
                    "HOST_WORKSPACE_ROOT": str(tmp_path),
                    "HOST_CACHE_DIR": str(tmp_path / "cache"),
                    "VLLM_HUST_ASCEND_CONTAINER_NON_INTERACTIVE": "1",
                    "VLLM_HUST_AUTO_ENABLE_CONTAINER_SSH": "0",
                    "VLLM_HUST_ASCEND_EXTRA_BIND_MOUNT": (
                        f"{run_root}:/run/kvdelta/fixture"
                    ),
                    "VLLM_HUST_ASCEND_RUNTIME_BIND_MOUNT": (
                        f"{runtime_carrier}:/opt/vllm-hust-runtime-carrier"
                    ),
                    "CONTAINER_WORKDIR": "/opt/vllm-hust-runtime-carrier",
                    "VLLM_HUST_ASCEND_OPTIMIZATION_BIND_MOUNT": (
                        f"{optimization}:/opt/vllm-optimization/fixture/src"
                    ),
                }
            )
            result = subprocess.run(
                [str(OFFICIAL_CONTAINER_SCRIPT), "start"],
                env=env,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            argv = json.loads(calls.read_text())
            binds = [
                argv[index + 1]
                for index, value in enumerate(argv)
                if value == "--extra-bind-mount"
            ]
            self.assertEqual(
                binds,
                [
                    f"{run_root}:/run/kvdelta/fixture",
                    f"{runtime_carrier}:/opt/vllm-hust-runtime-carrier",
                    f"{optimization}:/opt/vllm-optimization/fixture/src",
                ],
            )
            workdir_index = argv.index("--container-workdir")
            self.assertEqual(
                argv[workdir_index + 1], "/opt/vllm-hust-runtime-carrier"
            )
            manager = (
                REPO_ROOT.parent
                / "ascend-runtime-manager"
                / "src"
                / "hust_ascend_manager"
                / "container.py"
            ).read_text()
            self.assertIn(
                'return ["bash", "-lc", f"bash {shlex.quote(container_runtime_script_path(config))}"]',
                manager,
            )

    def test_cpu_container_proof_requires_disjoint_exact_final_create(self) -> None:
        spec = importlib.util.spec_from_file_location(
            "prove_container_runtime_carrier", CONTAINER_RUNTIME_PROOF
        )
        self.assertIsNotNone(spec)
        self.assertIsNotNone(spec.loader)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        self.assertTrue(
            module.target_is_disjoint(
                "/opt/vllm-hust-runtime-carrier", ("/workspace",)
            )
        )
        self.assertFalse(
            module.target_is_disjoint(
                "/workspace/vllm-hust-dev-hub", ("/workspace",)
            )
        )
        argv = module.build_create_argv(
            ["docker"],
            name="kvdelta-runtime-carrier-proof-fixture",
            image=(
                "quay.io/ascend/vllm-ascend@"
                "sha256:105834a38766a6b1b89a7eeb313a37351d098a69e8cdee87ad0ca3a6e090ce13"
            ),
            workspace=Path("/exact/workspace"),
            carrier=Path("/exact/carrier"),
        )
        joined = " ".join(argv)
        self.assertIn("--network none", joined)
        self.assertIn("--cap-drop ALL", joined)
        self.assertIn("--security-opt no-new-privileges:true", joined)
        self.assertIn(
            "/exact/carrier:/opt/vllm-hust-runtime-carrier:ro", joined
        )
        self.assertNotIn("--device", argv)
        self.assertNotIn("-p", argv)
        self.assertNotIn("--publish", argv)

    def test_empty_api_key_fails_before_docker_access(self) -> None:
        env = os.environ.copy()
        env.update(
            {
                "VLLM_ENGINE_CONTAINER": "dummy-container",
                "VLLM_HUST_API_KEY": "EMPTY",
            }
        )
        result = subprocess.run(
            [str(ENGINE_SCRIPT)],
            cwd=REPO_ROOT,
            env=env,
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("real API key", result.stderr)
        self.assertNotIn("Docker container", result.stderr)

    def test_env_template_exposes_host_managed_docker_knobs(self) -> None:
        template = ENV_TEMPLATE.read_text()

        self.assertIn("VLLM_ENGINE_CONTAINER=vllm-ascend-dev", template)
        self.assertIn("VLLM_ENGINE_AUTO_CREATE_CONTAINER=true", template)
        self.assertIn("VLLM_ENGINE_IMAGE=quay.io/ascend/vllm-ascend:v0.21.0rc1-openeuler", template)
        self.assertIn("VLLM_ENGINE_NPU_DEVICES=0,1,2,3", template)
        self.assertIn("VLLM_ENGINE_PYTHON=/usr/local/python3.12.13/bin/python", template)
        self.assertIn("VLLM_ENGINE_CONDA_ENV=vllm-hust-dev", template)
        self.assertIn("COMPILE_CUSTOM_KERNELS=0", template)
        self.assertIn("VLLM_ENGINE_COMPILATION_CONFIG", template)
        self.assertIn("VLLM_PLUGINS=ascend", template)
        self.assertIn("VLLM_ENGINE_BASE_PYTHONPATH", template)
        self.assertIn("VLLM_OPTIMIZATION_REPO_CONTAINER", template)
        self.assertIn("VLLM_OPTIMIZATION_PLUGIN", template)
        self.assertIn("VLLM_OPTIMIZATION_ENV_PREFIX", template)
        self.assertIn("VLLM_ENGINE_PYTHONPATH", template)
        self.assertIn("VLLM_ENGINE_EXTRA_ENV_KEYS", template)
        self.assertIn("VLLM_ENGINE_EXTRA_ENV_PREFIXES", template)

    def test_readme_documents_one_command_management(self) -> None:
        readme = README.read_text()

        self.assertIn("./manage.sh start", readme)
        self.assertIn("./manage.sh restart", readme)
        self.assertIn("scripts/run_vllm_hust_engine.sh", readme)
        self.assertIn("pulls/creates it automatically", readme)

    def test_engine_launcher_bootstraps_missing_container(self) -> None:
        script = ENGINE_SCRIPT.read_text()

        self.assertIn("VLLM_ENGINE_AUTO_CREATE_CONTAINER", script)
        self.assertIn("scripts/ascend-official-container.sh", script)
        self.assertIn("VLLM_HUST_ASCEND_CONTAINER_NON_INTERACTIVE", script)
        self.assertIn("EnvironmentFile=-", MANAGE_SCRIPT.read_text())
        self.assertIn("write_unit_environment", MANAGE_SCRIPT.read_text())
        self.assertIn('"KEY"', MANAGE_SCRIPT.read_text())
        self.assertIn("v0.21.0rc1-openeuler", script)
        self.assertIn("VLLM_ENGINE_COMPILATION_CONFIG", script)
        self.assertIn("VLLM_ENGINE_CONTAINER_LOG_FILE", script)
        self.assertIn("VLLM_ENGINE_HOST_LOG_FILE", script)
        self.assertIn("VLLM_ENGINE_LIFECYCLE_DIAGNOSTICS_FILE", script)
        self.assertIn("tee -a", script)
        self.assertIn("sed -u -E", script)
        self.assertIn("<redacted>", script)
        self.assertIn("__EXTRA_ENV_EXPORTS__", script)
        self.assertIn("TORCH_DEVICE_BACKEND_AUTOLOAD", script)
        self.assertIn("torch_npu_preflight", script)
        self.assertIn('export VLLM_API_KEY="__API_KEY__"', script)
        self.assertNotIn('--api-key "__API_KEY__"', script)
        self.assertIn('chmod 600 "$tmp_host_script"', script)
        self.assertIn('chmod 700 "$tmp_host_script"', script)
        self.assertNotIn('chmod +x "$tmp_host_script"', script)
        self.assertIn("tar --numeric-owner --owner=0 --group=0 --mode=0700", script)
        self.assertIn("container_script_stat=", script)
        self.assertIn('"0:0:700"', script)
        self.assertIn("container_default_user=", script)
        self.assertNotIn("script_uid_gid=", script)
        self.assertNotIn('--user "$script_uid_gid"', script)
        self.assertNotIn('HCCL_OP_EXPANSION_MODE="${HCCL_OP_EXPANSION_MODE:-AIV}"', script)
        manage = MANAGE_SCRIPT.read_text()
        self.assertIn("VLLM_ENGINE_EXTRA_ENV_KEYS", manage)
        self.assertIn('key != "VLLM_ENGINE_EXTRA_ENV_KEYS"', manage)
        self.assertIn(
            'key != "VLLM_ENGINE_EXTRA_ENV_KEYS"',
            script,
        )
        self.assertIn("VLLM_ENGINE_EXTRA_ENV_PREFIXES", manage)
        self.assertIn("VLLM_OPTIMIZATION_", manage)
        self.assertIn("TORCH_DEVICE_BACKEND_AUTOLOAD", manage)
        self.assertIn("VLLM_ENGINE_PYTHON", manage)
        self.assertLess(
            manage.index('load_dotenv "$repo_root/.env"'),
            manage.index('unit_name="${VLLM_ENGINE_SYSTEMD_UNIT'),
        )

    def test_failed_engine_preserves_bound_container_lifecycle_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            run_root = tmp_path / "managed-container-runs" / "fixture"
            run_root.mkdir(parents=True, mode=0o770)
            run_root.chmod(0o770)
            calls_path = tmp_path / "docker-calls.jsonl"
            diagnostics = run_root / "container-lifecycle-diagnostics.jsonl"
            fake_docker = tmp_path / "docker"
            fake_docker.write_text(textwrap.dedent(
                """\
                #!/usr/bin/env python3
                import io
                import json
                import os
                import sys
                import tarfile

                args = sys.argv[1:]
                with open(os.environ["FAKE_DOCKER_LOG"], "a") as handle:
                    handle.write(json.dumps(args) + "\\n")
                if args == ["info"]:
                    raise SystemExit(0)
                if args[:3] == ["inspect", "-f", "{{.State.Running}}"]:
                    print("true")
                    raise SystemExit(0)
                if args[:3] == ["inspect", "--format", "{{.Config.User}}"]:
                    print("")
                    raise SystemExit(0)
                if args[:2] == ["inspect", "--format"] and ".Mounts" in args[2]:
                    print(os.environ["EXPECTED_RUN_MOUNT"])
                    raise SystemExit(0)
                if args[:3] == ["inspect", "--format", "{{.Id}}"]:
                    print("a" * 64)
                    raise SystemExit(0)
                if args[:3] == ["inspect", "--format", "{{.State.StartedAt}}"]:
                    print("2026-07-23T11:00:00Z")
                    raise SystemExit(0)
                if args[:3] == ["inspect", "--format", "{{.State.Pid}}"]:
                    print(os.getppid())
                    raise SystemExit(0)
                if args[:2] == ["inspect", "--format"] and "container-inspect" in args[2]:
                    phase = "terminal" if '"terminal"' in args[2] else "start"
                    print(json.dumps({
                        "kind": "container-inspect",
                        "phase": phase,
                        "container_id": "a" * 64,
                        "name": "/fixture-container",
                        "state": {
                            "Status": "exited" if phase == "terminal" else "running",
                            "Running": phase == "start",
                            "OOMKilled": False,
                            "Dead": False,
                            "Pid": os.getppid() if phase == "start" else 0,
                            "ExitCode": 137 if phase == "terminal" else 0,
                            "Error": "",
                        },
                        "restart_count": 0,
                    }, sort_keys=True))
                    raise SystemExit(0)
                if args and args[0] == "events":
                    until = args[args.index("--until") + 1]
                    if "." not in until or not until.endswith("Z"):
                        raise SystemExit(
                            f"terminal event bound lacks nanoseconds: {until}"
                        )
                    if os.environ.get("FAKE_OMIT_TERMINAL_EVENT") == "1":
                        print(json.dumps({
                            "status": "start",
                            "id": "a" * 64,
                            "Actor": {"Attributes": {}},
                        }, sort_keys=True))
                        raise SystemExit(0)
                    print(json.dumps({
                        "status": "die",
                        "id": "a" * 64,
                        "Actor": {"Attributes": {
                            "exitCode": "137",
                            "execID": "fixture-exec-id",
                            "signal": "9",
                            "unsafe": "fixture-secret",
                        }},
                    }, sort_keys=True))
                    raise SystemExit(0)
                if args and args[0] == "logs":
                    if os.environ.get("FAKE_FAIL_RUNTIME_LOG") == "1":
                        print("runtime log unavailable", file=sys.stderr)
                        raise SystemExit(2)
                    print('{"kind":"container-runtime","event":"start","status":0}')
                    print('{"kind":"container-runtime","event":"exit","status":126}')
                    print("api-key=fixture-secret")
                    raise SystemExit(0)
                if args and args[0] == "cp":
                    payload = sys.stdin.buffer.read()
                    with tarfile.open(fileobj=io.BytesIO(payload), mode="r:") as archive:
                        assert len(archive.getmembers()) == 1
                    raise SystemExit(0)
                if args[:2] == ["exec", "--user"] and ".kvdelta-write-probe" in args[-1]:
                    raise SystemExit(0)
                if args[:2] == ["exec", "fixture-container"] and "stat" in args:
                    print("0:0:700")
                    raise SystemExit(0)
                if args and args[0] == "exec":
                    raise SystemExit(137)
                raise SystemExit(f"unexpected fake docker call: {args}")
                """
            ))
            fake_docker.chmod(0o700)
            env = os.environ.copy()
            env.update({
                "PATH": f"{tmp_path}:{env['PATH']}",
                "FAKE_DOCKER_LOG": str(calls_path),
                "EXPECTED_RUN_MOUNT": f"{run_root}:/run/kvdelta/fixture:true",
                "VLLM_ENGINE_CONTAINER": "fixture-container",
                "VLLM_ENGINE_REPLACE_EXISTING": "false",
                "VLLM_HUST_API_KEY": "fixture-secret",
                "VLLM_ENGINE_RUN_ROOT_HOST": str(run_root),
                "VLLM_ENGINE_RUN_ROOT_PARENT": str(tmp_path),
                "VLLM_ENGINE_RUN_ROOT_CONTAINER": "/run/kvdelta/fixture",
                "VLLM_ENGINE_RUN_ROOT_UID": str(os.getuid()),
                "VLLM_ENGINE_RUN_ROOT_GID": str(os.getgid()),
                "VLLM_ENGINE_LIFECYCLE_DIAGNOSTICS_FILE": str(diagnostics),
            })

            result = subprocess.run(
                [str(ENGINE_SCRIPT)], cwd=REPO_ROOT, env=env, text=True,
                capture_output=True, check=False,
            )

            self.assertEqual(result.returncode, 137, result.stderr)
            self.assertEqual(diagnostics.stat().st_mode & 0o777, 0o600)
            records = [
                json.loads(line) for line in diagnostics.read_text().splitlines()
            ]
            inspections = [
                item for item in records if item.get("kind") == "container-inspect"
            ]
            self.assertEqual(
                [item["phase"] for item in inspections], ["start", "terminal"]
            )
            self.assertFalse(inspections[-1]["state"]["OOMKilled"])
            self.assertEqual(inspections[-1]["state"]["ExitCode"], 137)
            self.assertEqual(
                {
                    item["phase"]
                    for item in records
                    if item.get("kind") == "host-pid-identity"
                },
                {"start", "terminal"},
            )
            event = next(
                item for item in records if item.get("kind") == "docker-event"
            )
            self.assertEqual(event["event"]["status"], "die")
            self.assertEqual(event["event"]["id"], "a" * 64)
            self.assertEqual(event["event"]["execID"], "fixture-exec-id")
            self.assertEqual(event["event"]["signal"], "9")
            self.assertNotIn("unsafe", event["event"])
            self.assertRegex(
                event["event"]["capture_until"],
                r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d+Z$",
            )
            runtime_log = run_root / "container-runtime.log"
            self.assertEqual(runtime_log.stat().st_mode & 0o777, 0o600)
            runtime_text = runtime_log.read_text(encoding="utf-8")
            self.assertIn('"event":"start"', runtime_text)
            self.assertIn('"event":"exit"', runtime_text)
            self.assertIn("api-key=<redacted>", runtime_text)
            self.assertNotIn("fixture-secret", runtime_text)
            runtime_receipt = next(
                item for item in records
                if item.get("kind") == "container-runtime-log"
            )
            self.assertEqual(runtime_receipt["status"], "PASS")
            self.assertEqual(runtime_receipt["bytes"], runtime_log.stat().st_size)
            self.assertRegex(runtime_receipt["sha256"], r"^[0-9a-f]{64}$")

            diagnostics.unlink()
            runtime_log.unlink()
            runtime_carrier = run_root / "container-runtime-carrier"
            runtime_carrier.chmod(0o700)
            (runtime_carrier / "scripts").chmod(0o700)
            shutil.rmtree(runtime_carrier)
            (run_root / "container-runtime-carrier-receipt.json").unlink()
            env["FAKE_OMIT_TERMINAL_EVENT"] = "1"
            env["FAKE_FAIL_RUNTIME_LOG"] = "1"
            missing = subprocess.run(
                [str(ENGINE_SCRIPT)], cwd=REPO_ROOT, env=env, text=True,
                capture_output=True, check=False,
            )
            self.assertEqual(missing.returncode, 137, missing.stderr)
            missing_records = [
                json.loads(line)
                for line in diagnostics.read_text().splitlines()
            ]
            gap = next(
                item for item in missing_records
                if item.get("status") == "UNAVAILABLE_NO_TERMINAL_EVENT"
            )
            self.assertRegex(
                gap["capture_until"],
                r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d+Z$",
            )
            runtime_gap = next(
                item for item in missing_records
                if item.get("kind") == "container-runtime-log"
            )
            self.assertEqual(
                runtime_gap["status"], "UNAVAILABLE_CAPTURE_FAILED"
            )
            self.assertFalse(runtime_log.exists())

    def test_managed_unit_defaults_to_no_restart_and_journal_is_bounded_redacted(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            fake_bin = tmp_path / "bin"
            fake_bin.mkdir()
            systemctl = fake_bin / "systemctl"
            systemctl.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            systemctl.chmod(0o700)
            journalctl = fake_bin / "journalctl"
            journalctl.write_text(
                "#!/bin/sh\n"
                "printf '%s\\n' \"fixture --api-key=$VLLM_HUST_API_KEY\"\n"
                "printf '%s\\n' \"$*\" >&2\n",
                encoding="utf-8",
            )
            journalctl.chmod(0o700)
            xdg = tmp_path / "xdg"
            secret = "fixture-journal-secret"
            env = {
                **os.environ,
                "PATH": f"{fake_bin}:{os.environ['PATH']}",
                "XDG_CONFIG_HOME": str(xdg),
                "VLLM_ENGINE_SYSTEMD_UNIT": "fixture-no-retry.service",
                "VLLM_HUST_API_KEY": secret,
            }
            installed = subprocess.run(
                [str(MANAGE_SCRIPT), "install"], cwd=REPO_ROOT, env=env,
                text=True, capture_output=True, check=False,
            )
            self.assertEqual(installed.returncode, 0, installed.stderr)
            unit = xdg / "systemd/user/fixture-no-retry.service"
            self.assertIn("Restart=no", unit.read_text(encoding="utf-8"))
            self.assertNotIn("Restart=on-failure", unit.read_text(encoding="utf-8"))

            snapshot = subprocess.run(
                [str(MANAGE_SCRIPT), "journal-snapshot"], cwd=REPO_ROOT, env=env,
                text=True, capture_output=True, check=False,
            )
            self.assertEqual(snapshot.returncode, 0, snapshot.stderr)
            self.assertIn("fixture --api-key=<redacted>", snapshot.stdout)
            self.assertNotIn(secret, snapshot.stdout + snapshot.stderr)
            self.assertIn("--lines 200", snapshot.stdout)

    def test_engine_script_is_root_owned_0700_without_secret_in_argv(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            log_path = tmp_path / "docker-calls.jsonl"
            copy_meta_path = tmp_path / "copy-meta.json"
            fake_docker = tmp_path / "docker"
            fake_docker.write_text(textwrap.dedent(
                """\
                #!/usr/bin/env python3
                import io
                import json
                import os
                import sys
                import tarfile

                args = sys.argv[1:]
                with open(os.environ["FAKE_DOCKER_LOG"], "a") as handle:
                    handle.write(json.dumps(args) + "\\n")
                if args == ["info"]:
                    raise SystemExit(0)
                if args[:3] == ["inspect", "-f", "{{.State.Running}}"]:
                    print("true")
                    raise SystemExit(0)
                if args[:3] == ["inspect", "--format", "{{.Config.User}}"]:
                    print("")
                    raise SystemExit(0)
                if args and args[0] == "cp":
                    payload = sys.stdin.buffer.read()
                    with tarfile.open(fileobj=io.BytesIO(payload), mode="r:") as archive:
                        members = archive.getmembers()
                        assert len(members) == 1
                        member = members[0]
                        content = archive.extractfile(member).read()
                    with open(os.environ["FAKE_COPY_META"], "w") as handle:
                        json.dump({
                            "uid": member.uid,
                            "gid": member.gid,
                            "mode": oct(member.mode),
                            "contains_secret": os.environ["FIXTURE_SECRET"].encode() in content,
                        }, handle)
                    raise SystemExit(0)
                if args[:2] == ["exec", "fixture-container"] and "stat" in args:
                    print("0:0:700")
                    raise SystemExit(0)
                if args and args[0] == "exec":
                    print("fixture docker exec stderr", file=sys.stderr)
                    raise SystemExit(0)
                raise SystemExit(f"unexpected fake docker call: {args}")
                """
            ))
            fake_docker.chmod(0o700)
            secret = "fixture-secret-must-not-enter-argv"
            host_log_path = tmp_path / "host-engine.log"
            env = os.environ.copy()
            env.update({
                "PATH": f"{tmp_path}:{env['PATH']}",
                "FAKE_DOCKER_LOG": str(log_path),
                "FAKE_COPY_META": str(copy_meta_path),
                "FIXTURE_SECRET": secret,
                "VLLM_ENGINE_CONTAINER": "fixture-container",
                "VLLM_ENGINE_REPLACE_EXISTING": "false",
                "VLLM_HUST_API_KEY": secret,
                "VLLM_ENGINE_REQUIRE_EXPLICIT_DEVICE_SECURITY": "1",
                "VLLM_ENGINE_CONTAINER_SECURITY_PROFILE": "explicit-devices-nonprivileged-v1",
                "VLLM_ENGINE_ASCEND_MANAGER_EXPECTED_COMMIT": "f" * 40,
                "VLLM_ENGINE_ASCEND_MANAGER_PYTHON": os.path.realpath(sys.executable),
                "VLLM_ENGINE_HOST_LOG_FILE": str(host_log_path),
            })
            result = subprocess.run(
                [str(ENGINE_SCRIPT)], cwd=REPO_ROOT, env=env, text=True,
                capture_output=True, check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            calls = [json.loads(line) for line in log_path.read_text().splitlines()]
            flattened = json.dumps(calls)
            self.assertNotIn(secret, flattened)
            final_exec = calls[-1]
            self.assertEqual(final_exec[0], "exec")
            self.assertNotIn("--user", final_exec)
            self.assertEqual(final_exec[-2], "bash")
            self.assertTrue(final_exec[-1].startswith("/tmp/vllm-hust-engine."))
            copy_meta = json.loads(copy_meta_path.read_text())
            self.assertEqual(copy_meta["uid"], 0)
            self.assertEqual(copy_meta["gid"], 0)
            self.assertEqual(copy_meta["mode"], "0o700")
            self.assertTrue(copy_meta["contains_secret"])
            self.assertIn("fixture docker exec stderr", host_log_path.read_text())
            self.assertNotIn(secret, host_log_path.read_text())
            self.assertEqual(host_log_path.stat().st_mode & 0o777, 0o600)
            launcher = ENGINE_SCRIPT.read_text()
            self.assertIn("HUST_ASCEND_MANAGER_CONTAINER_SECURITY_PROFILE", launcher)
            self.assertIn("HUST_ASCEND_MANAGER_EXPECTED_COMMIT", launcher)

    def test_exact_run_bind_is_rehearsed_and_used_without_workspace_writes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            run_root = tmp_path / "managed-container-runs" / "fixture"
            run_root.mkdir(parents=True, mode=0o770)
            run_root.chmod(0o770)
            calls_path = tmp_path / "docker-calls.jsonl"
            script_path = tmp_path / "container-script.sh"
            fake_docker = tmp_path / "docker"
            fake_docker.write_text(textwrap.dedent(
                """\
                #!/usr/bin/env python3
                import io
                import json
                import os
                import sys
                import tarfile

                args = sys.argv[1:]
                with open(os.environ["FAKE_DOCKER_LOG"], "a") as handle:
                    handle.write(json.dumps(args) + "\\n")
                if args == ["info"]:
                    raise SystemExit(0)
                if args[:3] == ["inspect", "-f", "{{.State.Running}}"]:
                    print("true")
                    raise SystemExit(0)
                if args[:3] == ["inspect", "--format", "{{.Config.User}}"]:
                    print("")
                    raise SystemExit(0)
                if args[:2] == ["inspect", "--format"] and ".Mounts" in args[2]:
                    print(os.environ["EXPECTED_RUN_MOUNT"])
                    raise SystemExit(0)
                if args and args[0] == "cp":
                    payload = sys.stdin.buffer.read()
                    with tarfile.open(fileobj=io.BytesIO(payload), mode="r:") as archive:
                        member = archive.getmembers()[0]
                        content = archive.extractfile(member).read()
                    with open(os.environ["FAKE_CONTAINER_SCRIPT"], "wb") as handle:
                        handle.write(content)
                    raise SystemExit(0)
                if args[:2] == ["exec", "--user"] and ".kvdelta-write-probe" in args[-1]:
                    raise SystemExit(0)
                if args[:2] == ["exec", "fixture-container"] and "stat" in args:
                    print("0:0:700")
                    raise SystemExit(0)
                if args and args[0] == "exec":
                    raise SystemExit(0)
                raise SystemExit(f"unexpected fake docker call: {args}")
                """
            ))
            fake_docker.chmod(0o700)
            env = os.environ.copy()
            env.update({
                "PATH": f"{tmp_path}:{env['PATH']}",
                "FAKE_DOCKER_LOG": str(calls_path),
                "FAKE_CONTAINER_SCRIPT": str(script_path),
                "EXPECTED_RUN_MOUNT": f"{run_root}:/run/kvdelta/fixture:true",
                "VLLM_ENGINE_CONTAINER": "fixture-container",
                "VLLM_ENGINE_REPLACE_EXISTING": "false",
                "VLLM_HUST_API_KEY": "fixture-secret",
                "VLLM_ENGINE_REQUIRE_EXPLICIT_DEVICE_SECURITY": "1",
                "VLLM_ENGINE_CONTAINER_SECURITY_PROFILE": "explicit-devices-nonprivileged-v1",
                "VLLM_ENGINE_ASCEND_MANAGER_EXPECTED_COMMIT": "f" * 40,
                "VLLM_ENGINE_ASCEND_MANAGER_PYTHON": os.path.realpath(sys.executable),
                "VLLM_ENGINE_RUN_ROOT_HOST": str(run_root),
                "VLLM_ENGINE_RUN_ROOT_PARENT": str(tmp_path),
                "VLLM_ENGINE_RUN_ROOT_CONTAINER": "/run/kvdelta/fixture",
                "VLLM_ENGINE_RUN_ROOT_UID": str(os.getuid()),
                "VLLM_ENGINE_RUN_ROOT_GID": str(os.getgid()),
                "VLLM_ENGINE_BIN": "/usr/local/python3.12.13/bin/vllm",
                "VLLM_ENGINE_SCRIPT": "",
                "VLLM_ENGINE_CONDA_PREFIX": "",
                "VLLM_ENGINE_PYTHON": "/usr/local/python3.12.13/bin/python3",
                "VLLM_ENGINE_IMPORT_PREFLIGHT": (
                    MULTILINE_IMPORT_PREFLIGHT.read_text(encoding="utf-8")
                ),
            })

            result = subprocess.run(
                [str(ENGINE_SCRIPT)], cwd=REPO_ROOT, env=env, text=True,
                capture_output=True, check=False,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            calls = [json.loads(line) for line in calls_path.read_text().splitlines()]
            self.assertTrue(any(".kvdelta-write-probe" in call[-1] for call in calls))
            final_exec = calls[-1]
            self.assertEqual(final_exec[:5], [
                "exec", "--user", f"0:{os.getgid()}", "--workdir",
                "/run/kvdelta/fixture",
            ])
            self.assertEqual(final_exec[-3], "fixture-container")
            container_script = script_path.read_text()
            syntax = subprocess.run(
                ["bash", "-n", str(script_path)],
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(syntax.returncode, 0, syntax.stderr)
            self.assertIn(
                'if [[ -n "$IMPORT_PREFLIGHT" ]]; then',
                container_script,
            )
            self.assertIn(
                '"$ENGINE_PYTHON" -c "$IMPORT_PREFLIGHT"',
                container_script,
            )
            self.assertNotIn(
                'if [[ -n "import importlib.util, json, pathlib, sys',
                container_script,
            )
            self.assertIn(
                "managed-container-software-compatibility-v2",
                container_script,
            )
            self.assertIn(
                '"/usr/local/python3.12.13/bin/vllm"',
                container_script,
            )
            self.assertIn(
                '"/usr/local/python3.12.13/bin/python3"',
                container_script,
            )
            self.assertIn(
                "exact engine Python selected; skipping conda activation",
                container_script,
            )
            self.assertIn("except OSError as exc", container_script)
            self.assertIn("type(exc).__name__", container_script)
            self.assertNotIn(
                "/workspace/vllm-hust-dev-container-env/bin/vllm-hust",
                container_script,
            )
            self.assertIn('export HOME="/run/kvdelta/fixture/home"', container_script)
            self.assertIn('cd "/run/kvdelta/fixture"', container_script)
            self.assertNotIn("mkdir /workspace", container_script)

    def test_exact_optimization_source_bind_proves_import_or_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            run_root = tmp_path / "managed-container-runs" / "fixture"
            run_root.mkdir(parents=True, mode=0o770)
            run_root.chmod(0o770)
            optimization_repo = tmp_path / "optimization-repo"
            optimization_src = optimization_repo / "src"
            package = optimization_src / "vllm_kvdelta"
            package.mkdir(parents=True)
            (package / "__init__.py").write_text("", encoding="utf-8")
            connector = package / "connector.py"
            connector.write_text("BOUNDARY_MARKER = 'PASS'\n", encoding="utf-8")
            target = "/opt/vllm-optimization/fixture/delta-producer/src"
            calls_path = tmp_path / "docker-calls.jsonl"
            proof_path = tmp_path / "import-proof.json"
            script_path = tmp_path / "container-script.sh"
            fake_docker = tmp_path / "docker"
            fake_docker.write_text(textwrap.dedent(
                """\
                #!/usr/bin/env python3
                import io
                import json
                import os
                import subprocess
                import sys
                import tarfile

                args = sys.argv[1:]
                with open(os.environ["FAKE_DOCKER_LOG"], "a") as handle:
                    handle.write(json.dumps(args) + "\\n")
                if args == ["info"]:
                    raise SystemExit(0)
                if args[:3] == ["inspect", "-f", "{{.State.Running}}"]:
                    print("true")
                    raise SystemExit(0)
                if args[:2] == ["inspect", "--format"] and ".Mounts" in args[2]:
                    if os.environ["OPTIMIZATION_TARGET"] in args[2]:
                        print(os.environ["EXPECTED_OPTIMIZATION_MOUNT"])
                    else:
                        print(os.environ["EXPECTED_RUN_MOUNT"])
                    raise SystemExit(0)
                if args[:3] == ["inspect", "--format", "{{.Config.User}}"]:
                    print("")
                    raise SystemExit(0)
                if args and args[0] == "cp":
                    payload = sys.stdin.buffer.read()
                    with tarfile.open(fileobj=io.BytesIO(payload), mode="r:") as archive:
                        member = archive.getmembers()[0]
                        content = archive.extractfile(member).read()
                    with open(os.environ["FAKE_CONTAINER_SCRIPT"], "wb") as handle:
                        handle.write(content)
                    raise SystemExit(0)
                if args[:2] == ["exec", "--user"] and ".kvdelta-write-probe" in args[-1]:
                    raise SystemExit(0)
                if args[:2] == ["exec", "fixture-container"] and "stat" in args:
                    print("0:0:700")
                    raise SystemExit(0)
                if args[:2] == ["exec", "--user"] and "-c" in args:
                    code_index = args.index("-c")
                    module = args[code_index + 2]
                    expected = args[code_index + 3]
                    if expected != os.environ["EXPECTED_CONTAINER_MODULE"]:
                        raise SystemExit("unexpected container module path")
                    child = dict(os.environ)
                    child["PYTHONPATH"] = os.environ["OPTIMIZATION_SRC"]
                    host_expected = os.path.join(
                        os.environ["OPTIMIZATION_SRC"], *module.split(".")
                    ) + ".py"
                    result = subprocess.run(
                        [sys.executable, "-c", args[code_index + 1], module, host_expected],
                        env=child,
                        text=True,
                        capture_output=True,
                    )
                    with open(os.environ["FAKE_IMPORT_PROOF"], "w") as handle:
                        json.dump({
                            "module": module,
                            "host_expected": host_expected,
                            "returncode": result.returncode,
                            "stderr": result.stderr,
                        }, handle, sort_keys=True)
                    raise SystemExit(result.returncode)
                if args and args[0] == "exec":
                    raise SystemExit(0)
                raise SystemExit(f"unexpected fake docker call: {args}")
                """
            ))
            fake_docker.chmod(0o700)
            env = os.environ.copy()
            env.update({
                "PATH": f"{tmp_path}:{env['PATH']}",
                "FAKE_DOCKER_LOG": str(calls_path),
                "FAKE_CONTAINER_SCRIPT": str(script_path),
                "FAKE_IMPORT_PROOF": str(proof_path),
                "OPTIMIZATION_SRC": str(optimization_src),
                "OPTIMIZATION_TARGET": target,
                "EXPECTED_CONTAINER_MODULE": f"{target}/vllm_kvdelta/connector.py",
                "EXPECTED_RUN_MOUNT": f"{run_root}:/run/kvdelta/fixture:true",
                "EXPECTED_OPTIMIZATION_MOUNT": f"{optimization_src}:{target}:true",
                "VLLM_ENGINE_CONTAINER": "fixture-container",
                "VLLM_ENGINE_REPLACE_EXISTING": "false",
                "VLLM_HUST_API_KEY": "fixture-secret",
                "VLLM_ENGINE_PYTHON": "/usr/local/python3.12.13/bin/python3",
                "VLLM_ENGINE_RUN_ROOT_HOST": str(run_root),
                "VLLM_ENGINE_RUN_ROOT_PARENT": str(tmp_path),
                "VLLM_ENGINE_RUN_ROOT_CONTAINER": "/run/kvdelta/fixture",
                "VLLM_ENGINE_RUN_ROOT_UID": str(os.getuid()),
                "VLLM_ENGINE_RUN_ROOT_GID": str(os.getgid()),
                "VLLM_ENGINE_OPTIMIZATION_REPO_HOST": str(optimization_repo),
                "VLLM_ENGINE_OPTIMIZATION_SRC_HOST": str(optimization_src),
                "VLLM_ENGINE_OPTIMIZATION_SRC_CONTAINER": target,
                "VLLM_ENGINE_OPTIMIZATION_IMPORT_MODULE": "vllm_kvdelta.connector",
                "VLLM_ENGINE_PYTHONPATH": target,
            })

            result = subprocess.run(
                [str(ENGINE_SCRIPT)], cwd=REPO_ROOT, env=env, text=True,
                capture_output=True, check=False,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            proof = json.loads(proof_path.read_text())
            self.assertEqual(proof["module"], "vllm_kvdelta.connector")
            self.assertEqual(proof["returncode"], 0)
            calls = [json.loads(line) for line in calls_path.read_text().splitlines()]
            import_exec = next(
                call for call in calls
                if call[:2] == ["exec", "--user"] and "-c" in call
            )
            self.assertIn(f"PYTHONPATH={target}", import_exec)
            self.assertIn("/usr/local/python3.12.13/bin/python3", import_exec)

            connector.unlink()
            failed = subprocess.run(
                [str(ENGINE_SCRIPT)], cwd=REPO_ROOT, env=env, text=True,
                capture_output=True, check=False,
            )
            self.assertNotEqual(failed.returncode, 0)
            self.assertIn(
                "optimization import module source is absent",
                failed.stderr,
            )

    def test_partial_exact_run_bind_rejects_before_docker_access(self) -> None:
        env = os.environ.copy()
        env.update({
            "VLLM_HUST_API_KEY": "host-free-fixture",
            "VLLM_ENGINE_RUN_ROOT_HOST": "/tmp/incomplete",
        })
        result = subprocess.run(
            [str(ENGINE_SCRIPT)], cwd=REPO_ROOT, env=env, text=True,
            capture_output=True, check=False,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("exact-run bind requires", result.stderr)
        self.assertNotIn("Docker container", result.stderr)

    def test_container_runtime_can_keep_alive_without_ssh_env(self) -> None:
        runtime = (REPO_ROOT / "scripts" / "ascend-container-runtime.sh").read_text()

        self.assertIn("CONTAINER_SSH_USER:=shuhao", runtime)
        self.assertNotIn("CONTAINER_SSH_USER:?Error", runtime)
        self.assertIn('runtime_event "start" 0', runtime)
        self.assertIn('runtime_event "wait-return" "$runtime_wait_status"', runtime)
        self.assertIn("trap 'runtime_signal TERM' TERM", runtime)
        self.assertIn("trap 'runtime_exit \"$?\"' EXIT", runtime)

    def test_engine_launcher_stays_repo_agnostic(self) -> None:
        script = ENGINE_SCRIPT.read_text()
        manage = MANAGE_SCRIPT.read_text()
        template = ENV_TEMPLATE.read_text()

        self.assertIn("VLLM_PLUGINS", script)
        self.assertIn("ENGINE_PYTHON", script)
        self.assertIn('"$ENGINE_PYTHON"', script)
        self.assertIn("VLLM_ENGINE_PYTHONPATH", script)
        self.assertIn("VLLM_OPTIMIZATION_REPO_CONTAINER", script)
        self.assertIn("VLLM_OPTIMIZATION_PLUGIN", script)
        self.assertIn("VLLM_OPTIMIZATION_ENV_PREFIX", script)
        for text in (script, manage, template):
            self.assertNotIn("segment_reuse", text)
            self.assertNotIn("SEGMENT_REUSE", text)

    def test_engine_launcher_has_generic_optimization_repo_overlay(self) -> None:
        script = ENGINE_SCRIPT.read_text()

        self.assertIn("optimization_repo_container", script)
        self.assertIn("optimization_src_subdir", script)
        self.assertIn("engine_base_pythonpath", script)
        self.assertIn('plugins="${plugins},${optimization_plugin}"', script)

    def test_exact_device_security_crosses_systemd_via_vllm_engine_carrier(self) -> None:
        manage = MANAGE_SCRIPT.read_text()
        launcher = ENGINE_SCRIPT.read_text()
        container = (REPO_ROOT / "scripts" / "ascend-official-container.sh").read_text()

        self.assertIn('prefixes = ("VLLM_ENGINE_",', manage)
        self.assertIn("VLLM_ENGINE_REQUIRE_EXPLICIT_DEVICE_SECURITY", launcher)
        self.assertIn("VLLM_ENGINE_CONTAINER_SECURITY_PROFILE", launcher)
        self.assertIn("HUST_ASCEND_MANAGER_CONTAINER_SECURITY_PROFILE", launcher)
        self.assertIn("HUST_ASCEND_MANAGER_EXPECTED_COMMIT", launcher)
        self.assertIn("HUST_ASCEND_MANAGER_EXPECTED_MODULE_ROOT", container)
        self.assertIn("HUST_ASCEND_MANAGER_PYTHON", container)

    def test_required_exact_device_profile_rejects_default_before_docker(self) -> None:
        env = os.environ.copy()
        env.update(
            {
                "VLLM_HUST_API_KEY": "host-free-fixture",
                "VLLM_ENGINE_REQUIRE_EXPLICIT_DEVICE_SECURITY": "1",
                "VLLM_ENGINE_CONTAINER_SECURITY_PROFILE": "default",
                "VLLM_ENGINE_ASCEND_MANAGER_EXPECTED_COMMIT": "f" * 40,
                "VLLM_ENGINE_ASCEND_MANAGER_PYTHON": "/bin/false",
            }
        )
        result = subprocess.run(
            [str(ENGINE_SCRIPT)], cwd=REPO_ROOT, env=env, text=True,
            capture_output=True, check=False,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("requires explicit-devices-nonprivileged-v1", result.stderr)
        self.assertNotIn("Docker container", result.stderr)


if __name__ == "__main__":
    unittest.main()
