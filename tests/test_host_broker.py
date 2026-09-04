"""Real CPU/AF_UNIX lifecycle and negative tests for the fixed host broker."""

import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from instance_control import ControlError, Store
from instance_control.host_broker import BrokerPolicy, HostBroker, _pid_state
from instance_control.host_client import request as broker_request


class HostBrokerTests(unittest.TestCase):
    def test_systemd_runtime_directory_uses_the_fixed_control_group(self):
        unit = (
            Path(__file__).resolve().parents[1]
            / "systemd"
            / "vllm-hust-host-broker.service"
        ).read_text()
        self.assertIn("RuntimeDirectoryMode=0750", unit)
        self.assertIn(
            "ExecStartPre=+/usr/bin/chown "
            "vllm-hust-broker:__CONTROL_GROUP__ /run/vllm-hust-host-broker",
            unit,
        )
        self.assertIn(
            "ExecStartPre=+/usr/bin/chmod 0750 /run/vllm-hust-host-broker", unit
        )
        self.assertNotIn("RuntimeDirectoryMode=0755", unit)
        self.assertNotIn("chmod 0755 /run/vllm-hust-host-broker", unit)
        mode = 0o750
        self.assertTrue(mode & 0o010, "fixed control group must traverse parent")
        self.assertFalse(mode & 0o007, "other users must not traverse or read parent")

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="host-broker-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.health = self.root / "run" / "canary.sock"
        self.config = self.root / "policy.json"
        self.worker = self.root / "instance_canary_worker.py"
        shutil.copyfile(
            Path(__file__).resolve().parents[1]
            / "scripts"
            / "instance_canary_worker.py",
            self.worker,
        )
        self.worker.chmod(0o500)
        policy = {
            "schema": "vllm-hust.host-broker-policy/v1",
            "enabled": True,
            "socket_path": str(self.root / "run" / "broker.sock"),
            "socket_gid": os.getgid(),
            "controller_uids": [os.geteuid()],
            "targets": [
                {
                    "instance_id": "inert-canary",
                    "owner_uids": [os.geteuid()],
                    "actions": ["start", "stop"],
                    "argv": [
                        str(Path(sys.executable).resolve()),
                        str(self.worker),
                        "--socket",
                        str(self.health),
                    ],
                    "cwd": str(self.root),
                    "environment": {"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8"},
                    "health_socket": str(self.health),
                    "artifacts": [
                        {
                            "path": str(Path(sys.executable).resolve()),
                            "sha256": __import__("hashlib")
                            .sha256(Path(sys.executable).resolve().read_bytes())
                            .hexdigest(),
                            "owner_uid": Path(sys.executable).resolve().stat().st_uid,
                            "mode": Path(sys.executable).resolve().stat().st_mode
                            & 0o777,
                        },
                        {
                            "path": str(self.worker),
                            "sha256": __import__("hashlib")
                            .sha256(self.worker.read_bytes())
                            .hexdigest(),
                            "owner_uid": os.geteuid(),
                            "mode": self.worker.stat().st_mode & 0o777,
                        },
                    ],
                }
            ],
        }
        self.config.write_text(json.dumps(policy))
        self.config.chmod(0o600)
        self.store = Store(self.root / "state", initialize=True)
        self.policy = BrokerPolicy.load(str(self.config))
        self.broker = HostBroker(self.store, self.policy)
        self.left, self.right = socket.socketpair(socket.AF_UNIX)
        self.addCleanup(self.left.close)
        self.addCleanup(self.right.close)
        self.operation = self.seed("start", fence=1, generation=0)

    def seed(self, action, *, fence, generation):
        operation_id = ("1" if action == "start" else "2") * 32
        baseline = "a" * 64
        candidate = "b" * 64 if action == "start" else "c" * 64
        registration = {
            "instance_id": "inert-canary",
            "owner_id": "host-broker",
            "profile_id": "inert",
            "backend_id": "fixed-process",
            "actions": ["apply", "disable", "rollback"],
            "owner_uids": [os.geteuid()],
            "fencing_receipt_sha256": "d" * 64,
        }
        operation = {
            "id": operation_id,
            "plan_id": "e" * 64,
            "instance_id": "inert-canary",
            "fence": fence,
            "phase": "reserved",
            "administrator_uid": os.geteuid(),
            "baseline": baseline,
            "candidate": candidate,
            "deadline": time.time() + 60,
            "recovery_deadline": time.time() + 120,
            "executor": action + "-executor",
        }
        instance = {
            "generation": generation,
            "fence": fence,
            "spec": baseline,
            "observation": {},
            "operation": operation_id,
            "status": "changing",
        }
        with self.store.transaction() as db:
            self.store.put(db, "registration", "inert-canary", registration)
            self.store.put(db, "operation", operation_id, operation)
            self.store.put(db, "instance", "inert-canary", instance)
        return operation

    def call(self, value):
        return self.broker.handle(self.left, json.dumps(value).encode())

    def grant(self, operation, action):
        return self.call(
            {
                "schema": "vllm-hust.host-broker/v1",
                "action": "issue",
                "instance_id": "inert-canary",
                "lifecycle_action": action,
                "operation": operation,
            }
        )["grant"]

    def execute(self, grant, action):
        return self.call(
            {
                "schema": "vllm-hust.host-broker/v1",
                "action": "execute",
                "instance_id": "inert-canary",
                "lifecycle_action": action,
                "grant": grant,
            }
        )

    def test_real_start_health_stop_and_no_residual(self):
        started = self.execute(self.grant(self.operation, "start"), "start")
        self.assertTrue(started["healthy"])
        identity = started["identity"]
        self.assertEqual(_pid_state(identity["pid"], identity["startTicks"]), "live")
        with self.store.transaction() as db:
            current = self.store.get(db, "instance", "inert-canary")
            current.update(
                generation=1,
                operation=None,
                spec=self.operation["candidate"],
                status="ready",
            )
            operation = self.store.get(db, "operation", self.operation["id"])
            operation["phase"] = "committed"
            self.store.put(db, "instance", "inert-canary", current)
            self.store.put(db, "operation", operation["id"], operation)
        stop = self.seed("stop", fence=2, generation=1)
        stopped = self.execute(self.grant(stop, "stop"), "stop")
        self.assertEqual(stopped["state"], "stopped")
        self.assertFalse(stopped["healthy"])
        self.assertEqual(_pid_state(identity["pid"], identity["startTicks"]), "absent")
        self.assertFalse(self.health.exists())

    def test_replay_and_action_substitution_are_rejected(self):
        grant = self.grant(self.operation, "start")
        with self.assertRaisesRegex(ControlError, "binding_mismatch"):
            self.execute(grant, "stop")
        started = self.execute(grant, "start")
        with self.assertRaisesRegex(ControlError, "replayed"):
            self.execute(grant, "start")
        # Clean up using the original committed lease path followed by a fenced stop.
        with self.store.transaction() as db:
            current = self.store.get(db, "instance", "inert-canary")
            current.update(
                generation=1,
                operation=None,
                spec=self.operation["candidate"],
                status="ready",
            )
            operation = self.store.get(db, "operation", self.operation["id"])
            operation["phase"] = "committed"
            self.store.put(db, "instance", "inert-canary", current)
            self.store.put(db, "operation", operation["id"], operation)
        stop = self.seed("stop", fence=2, generation=1)
        self.execute(self.grant(stop, "stop"), "stop")
        self.assertFalse(started["identity"] is None)

    def test_request_cannot_supply_command_owner_or_pid(self):
        for extra in ("argv", "owner_id", "pid", "uid", "image"):
            request = {
                "schema": "vllm-hust.host-broker/v1",
                "action": "describe",
                "instance_id": "inert-canary",
                extra: "attacker",
            }
            with (
                self.subTest(extra=extra),
                self.assertRaisesRegex(ControlError, "invalid_fields"),
            ):
                self.call(request)

    def test_reopen_preserves_policy_resource_and_consumed_grant(self):
        grant = self.grant(self.operation, "start")
        started = self.execute(grant, "start")
        restarted = HostBroker(
            Store(self.root / "state"), BrokerPolicy.load(str(self.config))
        )
        description = restarted.handle(
            self.left,
            json.dumps(
                {
                    "schema": "vllm-hust.host-broker/v1",
                    "action": "describe",
                    "instance_id": "inert-canary",
                }
            ).encode(),
        )
        self.assertTrue(description["healthy"])
        with self.assertRaisesRegex(ControlError, "replayed"):
            restarted.handle(
                self.left,
                json.dumps(
                    {
                        "schema": "vllm-hust.host-broker/v1",
                        "action": "execute",
                        "instance_id": "inert-canary",
                        "lifecycle_action": "start",
                        "grant": grant,
                    }
                ).encode(),
            )
        with self.store.transaction() as db:
            current = self.store.get(db, "instance", "inert-canary")
            current.update(
                generation=1,
                operation=None,
                spec=self.operation["candidate"],
                status="ready",
            )
            operation = self.store.get(db, "operation", self.operation["id"])
            operation["phase"] = "committed"
            self.store.put(db, "instance", "inert-canary", current)
            self.store.put(db, "operation", operation["id"], operation)
        stop = self.seed("stop", fence=2, generation=1)
        self.execute(self.grant(stop, "stop"), "stop")
        self.assertIsNotNone(started["identity"])

    def test_disabled_policy_makes_issue_fail_closed(self):
        value = json.loads(self.config.read_text())
        value["enabled"] = False
        self.config.write_text(json.dumps(value))
        disabled = HostBroker(self.store, BrokerPolicy.load(str(self.config)))
        with self.assertRaisesRegex(ControlError, "disabled"):
            disabled.handle(
                self.left,
                json.dumps(
                    {
                        "schema": "vllm-hust.host-broker/v1",
                        "action": "issue",
                        "instance_id": "inert-canary",
                        "lifecycle_action": "start",
                        "operation": self.operation,
                    }
                ).encode(),
            )

    def test_group_writable_installed_artifact_is_rejected(self):
        self.worker.chmod(0o720)
        with self.assertRaisesRegex(ControlError, "untrusted_broker_configuration"):
            BrokerPolicy.load(str(self.config))

    def test_real_daemon_socket_round_trip(self):
        process = subprocess.Popen(
            [
                sys.executable,
                "-I",
                str(
                    Path(__file__).resolve().parents[1]
                    / "scripts"
                    / "instance_host_broker.py"
                ),
                "--config",
                str(self.config),
                "--state",
                str(self.root / "state"),
            ],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        self.addCleanup(lambda: process.poll() is None and process.kill())
        deadline = time.monotonic() + 3
        while (
            time.monotonic() < deadline and not Path(self.policy.socket_path).exists()
        ):
            time.sleep(0.02)
        self.assertIsNone(process.poll())
        described = broker_request(
            self.policy.socket_path,
            {
                "schema": "vllm-hust.host-broker/v1",
                "action": "describe",
                "instance_id": "inert-canary",
            },
        )
        self.assertTrue(described["ok"])
        process.terminate()
        process.wait(timeout=3)


if __name__ == "__main__":
    unittest.main()
