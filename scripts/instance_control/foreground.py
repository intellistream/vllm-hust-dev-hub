"""Opt-in direct-child supervision; no shell, service manager or automatic restart.

This utility is NOT an authorization service or a process-tree sandbox. The trusted
product adapter supplies the frozen command and owner guard, and must keep all
descendants in an approved cgroup/leaf contract. Never run a daemonizing command.
"""

from dataclasses import dataclass
import math
import os
from pathlib import PurePath
import signal
import subprocess
import threading
import time
from typing import Callable, ContextManager

from .schema import require


@dataclass(frozen=True)
class FrozenCommand:
    argv: tuple[str, ...]
    cwd: str
    environment: tuple[tuple[str, str], ...]

    def validate(self):
        require(type(self.argv) is tuple and 0 < len(self.argv) <= 4096,
                "invalid_supervisor_command")
        require(all(isinstance(arg, str) and "\0" not in arg and len(arg) <= 65536
                    for arg in self.argv), "invalid_supervisor_command")
        require(os.path.isabs(self.argv[0]) and ".." not in PurePath(self.argv[0]).parts,
                "absolute_executable_required")
        require(isinstance(self.cwd, str) and os.path.isabs(self.cwd) and "\0" not in self.cwd
                and ".." not in PurePath(self.cwd).parts, "absolute_working_directory_required")
        require(type(self.environment) is tuple and len(self.environment) <= 1024,
                "explicit_environment_required")
        keys = set()
        for pair in self.environment:
            require(type(pair) is tuple and len(pair) == 2, "invalid_supervisor_environment")
            key, value = pair
            require(isinstance(key, str) and key and "=" not in key and "\0" not in key
                    and isinstance(value, str) and "\0" not in value and key not in keys,
                    "invalid_supervisor_environment")
            keys.add(key)


@dataclass(frozen=True)
class ForegroundResult:
    reason: str
    returncode: int | None
    child_pid: int | None
    child_reaped: bool

    @property
    def exit_code(self):
        if self.returncode is not None:
            return self.returncode if self.returncode >= 0 else 128 - self.returncode
        return 2


def run_foreground(command: FrozenCommand, guard: Callable[[], ContextManager], *,
                   enabled=False, shutdown_grace=5.0, kill_wait=5.0,
                   poll_interval=0.05) -> ForegroundResult:
    """Supervise one foreground child; exact output goes to inherited stdio.

    `guard` must authenticate the current operation/fence and retain its critical
    section through each spawn/signal. It must return promptly; it is not a boolean
    assertion supplied by a caller. The helper does not retain the guard during
    ordinary child waits, so an owner control path can re-enter without deadlock.

    After guard failure, no further signal is sent. A live child is reported as
    unreaped and requires owner reconciliation; do not infer cleanup success.
    SIGKILL of this supervisor cannot run Python cleanup, so production requires
    external cgroup supervision and crash fencing independently of this helper.
    """
    if enabled is not True:
        return ForegroundResult("disabled", None, None, False)
    command.validate()
    require(threading.current_thread() is threading.main_thread(), "foreground_main_thread_required")
    for duration in (shutdown_grace, kill_wait, poll_interval):
        require(type(duration) in (int, float) and math.isfinite(duration) and duration > 0,
                "invalid_supervisor_timeout")
    require(poll_interval <= 1, "invalid_supervisor_timeout")
    pending = []
    handled = (signal.SIGTERM, signal.SIGINT, signal.SIGHUP)
    previous = {number: signal.getsignal(number) for number in handled}
    child = None
    # Keep child exit unreaped until signalling is finished. poll()/wait() may reap
    # a PID, allowing reuse between ownership validation and kill. waitid WNOWAIT
    # avoids that race, and is available on the Linux hosts supported here.
    require(hasattr(os, "WNOWAIT") and hasattr(os, "waitid"), "nonreaping_wait_required")
    require(signal.getsignal(signal.SIGCHLD) == signal.SIG_DFL,
            "exclusive_child_wait_required")

    def on_signal(number, _frame):
        if len(pending) < 32:
            pending.append(number)

    def exited():
        return os.waitid(os.P_PID, child.pid, os.WEXITED | os.WNOHANG | os.WNOWAIT) is not None

    def send(number):
        # The PID cannot be reused while our direct child remains unreaped. Do
        # not use Popen.send_signal(), which polls/reaps internally before kill.
        with guard():
            if not exited():
                os.kill(child.pid, number)

    def reap(reason):
        code = child.wait(timeout=kill_wait)
        return ForegroundResult(reason, code, child.pid, True)

    def abandon(reason):
        try:
            if exited():
                return reap(reason)
        except ChildProcessError:
            # Another waiter violated the exclusive-child contract. Do not use
            # the now potentially recycled PID for cleanup or claim it reaped.
            return ForegroundResult("child_wait_ownership_lost", None, child.pid, False)
        return ForegroundResult(reason, None, child.pid, False)

    try:
        for number in handled:
            signal.signal(number, on_signal)
        try:
            with guard():
                child = subprocess.Popen(command.argv, cwd=command.cwd,
                    env=dict(command.environment), stdin=subprocess.DEVNULL,
                    # Separate signal delivery from the wrapper's terminal group;
                    # this is still a direct child, never detached via double fork.
                    start_new_session=True, close_fds=True)
        except Exception:
            # A guard may fail on __exit__ after Popen succeeded. Never lose the
            # child identity or pretend that no process was started in that case.
            if child is not None:
                return abandon("spawn_guard_failed")
            return ForegroundResult("spawn_refused", None, None, False)
        shutdown_at = None
        kill_at = None
        reason = "exited"
        while True:
            if exited():
                return reap(reason)
            while pending:
                number = pending.pop(0)
                try:
                    send(number)
                except Exception:
                    return abandon("signal_authority_lost")
                if number in (signal.SIGTERM, signal.SIGINT) and shutdown_at is None:
                    shutdown_at = time.monotonic() + shutdown_grace
                    reason = "signalled"
            now = time.monotonic()
            if shutdown_at is not None and now >= shutdown_at and kill_at is None:
                try:
                    send(signal.SIGKILL)
                except Exception:
                    return abandon("signal_authority_lost")
                kill_at = now + kill_wait
                reason = "shutdown_escalated"
            if kill_at is not None and now >= kill_at:
                return abandon("child_exit_unconfirmed")
            time.sleep(poll_interval)
    except BaseException:
        if child is None:
            raise
        # Cleanup still goes through the same guard. Losing it never grants a
        # special emergency bypass to kill an unowned/new occupant.
        try:
            send(signal.SIGKILL)
            return reap("supervisor_failed")
        except Exception:
            return abandon("cleanup_unconfirmed")
    finally:
        for number, handler in previous.items():
            signal.signal(number, handler)
