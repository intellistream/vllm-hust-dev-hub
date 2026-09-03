"""Real CPU-only direct-child supervision; never invoke a host service manager."""

from contextlib import contextmanager
from dataclasses import asdict
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from instance_control.backend import BackendFailure, ERROR_CODES
from instance_control.foreground import FrozenCommand, run_foreground
from instance_control.schema import ControlError


def write_json(path, value):
    # Rename ensures the test observer never consumes a partially written file.
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value))
    temporary.replace(path)


def child_fixture(mode, root):
    def handler(number, _frame):
        with (root / "signals").open("a") as stream:
            stream.write(str(number) + "\n")
        if number in (signal.SIGINT, signal.SIGTERM) and mode != "ignore":
            raise SystemExit(23)

    for number in (signal.SIGHUP, signal.SIGINT, signal.SIGTERM):
        signal.signal(number, handler)
    write_json(root / "ready", {"pid": os.getpid(), "ambient": os.getenv("SECRET_CANARY"),
                               "explicit": os.getenv("FIXTURE_VALUE"), "cwd": os.getcwd()})
    if mode == "exit":
        raise SystemExit(7)
    while True:
        time.sleep(0.02)


def supervisor_fixture(mode, root):
    calls = 0

    @contextmanager
    def guard():
        nonlocal calls
        calls += 1
        with (root / "guard").open("a") as stream:
            stream.write(f"enter:{calls}\n")
        if mode == "deny_spawn" or (mode in ("deny_signal", "fault_denied") and calls > 1):
            raise RuntimeError("SECRET_CANARY denied")
        try:
            yield
        finally:
            with (root / "guard").open("a") as stream:
                stream.write(f"exit:{calls}\n")
        if mode == "exit_guard":
            raise RuntimeError("SECRET_CANARY exit guard failed")

    command = FrozenCommand((sys.executable, "-I", str(Path(__file__).resolve()),
                             "--child", mode, str(root)), str(root), (("FIXTURE_VALUE", "set"),))
    original_sleep = time.sleep

    def fixture_sleep(seconds):
        if mode in ("fault", "fault_denied") and (root / "fault").exists():
            (root / "fault").unlink()
            raise RuntimeError("SECRET_CANARY supervisor fault")
        original_sleep(seconds)

    with patch("instance_control.foreground.time.sleep", side_effect=fixture_sleep):
        result = run_foreground(command, guard, enabled=True, shutdown_grace=0.15,
                                kill_wait=1.0, poll_interval=0.01)
    write_json(root / "result", {**asdict(result), "exit_code": result.exit_code})
    if result.child_pid and not result.child_reaped:
        # Only the test fixture owns this child. The TEST PARENT sends cleanup
        # via pidfd; the utility itself must not signal after its guard failed.
        os.waitpid(result.child_pid, 0)


class ForegroundTests(unittest.TestCase):
    def command(self):
        return FrozenCommand((sys.executable, "-I", "-c", "raise SystemExit(0)"), "/tmp", ())

    def wait_for(self, path, predicate=lambda value: True):
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            if path.exists():
                value = path.read_text()
                if predicate(value):
                    return value
            time.sleep(0.01)
        self.fail(f"fixture timeout: {path.name}")

    @contextmanager
    def fixture(self, mode):
        with tempfile.TemporaryDirectory(prefix="instance-foreground-") as temporary:
            root = Path(temporary)
            # No shell, no network, no container, no accelerator operations.
            with (root / "output").open("w+") as output:
                process = subprocess.Popen((sys.executable, "-I", str(Path(__file__).resolve()),
                                            "--supervisor", mode, str(root)),
                                           env={**os.environ, "SECRET_CANARY": "not inherited"},
                                           stdout=output, stderr=output, start_new_session=True)
                pidfd = None
                try:
                    if mode != "deny_spawn":
                        ready = json.loads(self.wait_for(root / "ready"))
                        if mode != "exit":
                            pidfd = os.pidfd_open(ready["pid"])
                    yield root, process
                finally:
                    if pidfd is not None:
                        try:
                            signal.pidfd_send_signal(pidfd, signal.SIGKILL)
                        except ProcessLookupError:
                            pass
                        os.close(pidfd)
                    try:
                        process.wait(timeout=3)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=3)
                    output.seek(0)
                    self.assertNotIn("SECRET_CANARY", output.read())

    def result(self, root):
        return json.loads(self.wait_for(root / "result"))

    def test_default_off_before_validation_or_guard(self):
        guard = Mock()
        with patch("instance_control.foreground.subprocess.Popen") as spawn:
            result = run_foreground(None, guard)
        self.assertEqual(result.reason, "disabled")
        guard.assert_not_called()
        spawn.assert_not_called()

    def test_command_rejects_implicit_or_ambiguous_inputs(self):
        for command in (FrozenCommand(("python",), "/tmp", ()),
                        FrozenCommand(("/bin/../bin/true",), "/tmp", ()),
                        FrozenCommand(("/bin/true",), "relative", ()),
                        FrozenCommand(("/bin/true",), "/tmp", None),
                        FrozenCommand(("/bin/true",), "/tmp", (("A", "1"), ("A", "2"))),
                        FrozenCommand(("/bin/true",), "/tmp", (("A=B", "1"),))):
            with self.subTest(command=command), self.assertRaises(ControlError):
                command.validate()

    def test_exits_reaped_with_explicit_environment_and_cwd(self):
        with self.fixture("exit") as (root, process):
            result = self.result(root)
            self.assertEqual(result["exit_code"], 7)
            self.assertTrue(result["child_reaped"])
            ready = json.loads((root / "ready").read_text())
            self.assertIsNone(ready["ambient"])
            self.assertEqual(ready["explicit"], "set")
            self.assertEqual(ready["cwd"], str(root))
            self.assertEqual(process.wait(timeout=3), 0)

    def test_term_and_int_forwarded_under_new_guard(self):
        for number in (signal.SIGTERM, signal.SIGINT):
            with self.subTest(signal=number), self.fixture("signals") as (root, process):
                # The owner critical section was released during serving.
                self.assertEqual((root / "guard").read_text(), "enter:1\nexit:1\n")
                process.send_signal(number)
                result = self.result(root)
                self.assertEqual(result["returncode"], 23)
                self.assertTrue(result["child_reaped"])
                self.assertIn(str(int(number)), (root / "signals").read_text().splitlines())
                self.assertIn("enter:2\nexit:2", (root / "guard").read_text())

    def test_hup_does_not_start_shutdown_timer(self):
        with self.fixture("signals") as (root, process):
            process.send_signal(signal.SIGHUP)
            self.wait_for(root / "signals", lambda text: str(int(signal.SIGHUP)) in text.splitlines())
            time.sleep(0.3)
            self.assertFalse((root / "result").exists())
            process.send_signal(signal.SIGTERM)
            self.assertEqual(self.result(root)["returncode"], 23)

    def test_ignored_term_escalates_and_reaps(self):
        with self.fixture("ignore") as (root, process):
            process.send_signal(signal.SIGTERM)
            result = self.result(root)
            self.assertEqual(result["reason"], "shutdown_escalated")
            self.assertEqual(result["returncode"], -signal.SIGKILL)
            self.assertEqual(result["exit_code"], 137)
            self.assertTrue(result["child_reaped"])
            self.assertIn("enter:3\nexit:3", (root / "guard").read_text())

    def test_denied_spawn_has_no_child(self):
        with self.fixture("deny_spawn") as (root, _process):
            result = self.result(root)
            self.assertEqual(result["reason"], "spawn_refused")
            self.assertIsNone(result["child_pid"])
            self.assertFalse((root / "ready").exists())

    def test_denied_signal_never_falls_back_to_kill(self):
        with self.fixture("deny_signal") as (root, process):
            process.send_signal(signal.SIGTERM)
            result = self.result(root)
            self.assertEqual(result["reason"], "signal_authority_lost")
            self.assertFalse(result["child_reaped"])
            self.assertIsNone(result["returncode"])
            self.assertFalse((root / "signals").exists())
            self.assertEqual((root / "guard").read_text().count("enter:"), 2)

    def test_spawn_guard_exit_failure_retains_child_identity(self):
        with self.fixture("exit_guard") as (root, _process):
            result = self.result(root)
            self.assertEqual(result["reason"], "spawn_guard_failed")
            self.assertEqual(result["child_pid"], json.loads((root / "ready").read_text())["pid"])
            self.assertFalse(result["child_reaped"])
            self.assertFalse((root / "signals").exists())

    def test_exception_cleanup_revalidates_guard(self):
        for mode, reaped, reason in (("fault", True, "supervisor_failed"),
                                    ("fault_denied", False, "cleanup_unconfirmed")):
            with self.subTest(mode=mode), self.fixture(mode) as (root, _process):
                (root / "fault").touch()
                result = self.result(root)
                self.assertEqual(result["reason"], reason)
                self.assertEqual(result["child_reaped"], reaped)
                self.assertEqual(result["returncode"], -signal.SIGKILL if reaped else None)
                self.assertEqual((root / "guard").read_text().count("enter:"), 2)

    def test_handlers_restored_and_timeout_validation(self):
        @contextmanager
        def guard():
            yield

        previous = {number: signal.getsignal(number)
                    for number in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP)}
        result = run_foreground(self.command(), guard, enabled=True)
        self.assertEqual(result.returncode, 0)
        for number, handler in previous.items():
            self.assertIs(signal.getsignal(number), handler)
        for duration in (0, -1, float("nan"), float("inf"), True):
            with self.subTest(duration=duration), self.assertRaises(ControlError):
                run_foreground(self.command(), guard, enabled=True, kill_wait=duration)

    def test_non_main_thread_and_external_child_waiter_rejected(self):
        errors = []

        def run():
            try:
                run_foreground(self.command(), Mock(), enabled=True)
            except ControlError as error:
                errors.append(str(error))

        thread = threading.Thread(target=run)
        thread.start()
        thread.join(timeout=3)
        self.assertEqual(errors, ["foreground_main_thread_required"])
        with patch("instance_control.foreground.signal.getsignal", return_value=signal.SIG_IGN):
            with self.assertRaisesRegex(ControlError, "exclusive_child_wait_required"):
                run_foreground(self.command(), Mock(), enabled=True)

    def test_backend_errors_are_closed_and_redacted(self):
        for code in ERROR_CODES:
            self.assertEqual(str(BackendFailure(code)), code)
        self.assertEqual(str(BackendFailure("SECRET_CANARY")), "backend_failed")


if __name__ == "__main__":
    if len(sys.argv) == 4 and sys.argv[1] == "--child":
        child_fixture(sys.argv[2], Path(sys.argv[3]))
    elif len(sys.argv) == 4 and sys.argv[1] == "--supervisor":
        supervisor_fixture(sys.argv[2], Path(sys.argv[3]))
    else:
        unittest.main()
