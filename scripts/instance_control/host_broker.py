"""Bounded AF_UNIX execution broker for fixed, host-registered commands.

The broker is an execution plane, not an approval service.  A controller first
reserves an operation and supplies its exact durable token to ``issue``.  The
resulting one-use grant is bound to the kernel-authenticated caller and one fixed
registry action.  ``execute`` consumes that grant before touching a process.

No request field can supply an argv, environment, path, PID, UID, owner or image.
Shared-service adapters need their own qualification; the built-in process leaf
is intended for inert host acceptance and similarly bounded foreground workers.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import os
from pathlib import Path, PurePath
import signal
import socket
import stat
import subprocess
import time

from .host_authority import LaunchGrantAuthority, _process_start_ticks, peer_from_unix_socket
from .schema import ControlError, canonical, decode, digest, fields, hash_value, identifier, require

PROTOCOL = "vllm-hust.host-broker/v1"
ACTIONS = frozenset({"start", "stop", "restart"})
MAX_REQUEST = 4096


def _absolute(value: object) -> bool:
    return (isinstance(value, str) and value.startswith("/") and "\0" not in value
            and ".." not in PurePath(value).parts and value != "/")


def _regular_file(path: Path, *, trusted_uids: frozenset[int]) -> os.stat_result:
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        info = os.fstat(descriptor)
    finally:
        os.close(descriptor)
    require(stat.S_ISREG(info.st_mode) and info.st_uid in trusted_uids
            and stat.S_IMODE(info.st_mode) & 0o022 == 0, "untrusted_broker_configuration")
    return info


@dataclass(frozen=True)
class FixedTarget:
    instance_id: str
    owner_uids: frozenset[int]
    actions: frozenset[str]
    argv: tuple[str, ...]
    cwd: str
    environment: tuple[tuple[str, str], ...]
    health_socket: str
    policy_sha256: str

    def command_sha256(self, action: str) -> str:
        require(action in self.actions, "lifecycle_action_not_allowed")
        return digest({"instance_id": self.instance_id, "action": action,
                       "policy_sha256": self.policy_sha256})


@dataclass(frozen=True)
class BrokerPolicy:
    enabled: bool
    socket_path: str
    socket_gid: int
    controller_uids: frozenset[int]
    targets: dict[str, FixedTarget]
    sha256: str

    @classmethod
    def load(cls, path: str, *, trusted_uids: frozenset[int] | None = None):
        config_path = Path(path)
        require(config_path.is_absolute() and config_path.resolve() == config_path,
                "invalid_broker_configuration")
        trusted = trusted_uids or frozenset({0, os.geteuid()})
        info = _regular_file(config_path, trusted_uids=trusted)
        require(info.st_size <= 65536, "invalid_broker_configuration")
        value = decode(config_path.read_text(encoding="utf-8"))
        fields(value, "schema enabled socket_path socket_gid controller_uids targets")
        require(value["schema"] == "vllm-hust.host-broker-policy/v1"
                and type(value["enabled"]) is bool and _absolute(value["socket_path"])
                and type(value["socket_gid"]) is int and value["socket_gid"] >= 0,
                "invalid_broker_configuration")
        require(isinstance(value["controller_uids"], list)
                and value["controller_uids"]
                and all(type(uid) is int and uid >= 0 for uid in value["controller_uids"]),
                "invalid_broker_configuration")
        require(isinstance(value["targets"], list) and value["targets"],
                "invalid_broker_configuration")
        targets: dict[str, FixedTarget] = {}
        for item in value["targets"]:
            fields(item, "instance_id owner_uids actions argv cwd environment health_socket artifacts")
            identifier(item["instance_id"])
            require(item["instance_id"] not in targets
                    and isinstance(item["owner_uids"], list) and item["owner_uids"]
                    and all(type(uid) is int and uid >= 0 for uid in item["owner_uids"])
                    and isinstance(item["actions"], list) and item["actions"]
                    and set(item["actions"]) <= ACTIONS,
                    "invalid_broker_target")
            require(isinstance(item["argv"], list) and item["argv"]
                    and all(isinstance(arg, str) and arg and "\0" not in arg for arg in item["argv"])
                    and _absolute(item["argv"][0]) and _absolute(item["cwd"])
                    and _absolute(item["health_socket"]), "invalid_broker_target")
            require(isinstance(item["environment"], dict)
                    and all(isinstance(key, str) and key and "=" not in key and "\0" not in key
                            and isinstance(val, str) and "\0" not in val
                            and not any(part in key.upper() for part in ("SECRET", "PASSWORD", "TOKEN", "API_KEY"))
                            for key, val in item["environment"].items()), "invalid_broker_target")
            require(not any(any(flag in arg.lower() for flag in
                                ("--api-key", "--password", "--token", "--enforce-eager"))
                            for arg in item["argv"]), "invalid_broker_target")
            require(isinstance(item["artifacts"], list) and item["artifacts"],
                    "invalid_broker_target")
            for artifact in item["artifacts"]:
                fields(artifact, "path sha256 owner_uid mode")
                require(_absolute(artifact["path"]), "invalid_broker_artifact")
                hash_value(artifact["sha256"])
                require(type(artifact["owner_uid"]) is int and artifact["owner_uid"] >= 0
                        and type(artifact["mode"]) is int and 0 <= artifact["mode"] <= 0o777,
                        "invalid_broker_artifact")
                artifact_path = Path(artifact["path"])
                artifact_info = _regular_file(artifact_path, trusted_uids=frozenset({artifact["owner_uid"]}))
                require(stat.S_IMODE(artifact_info.st_mode) == artifact["mode"]
                        and hashlib.sha256(artifact_path.read_bytes()).hexdigest() == artifact["sha256"],
                        "broker_artifact_drift")
            policy_sha = digest(item)
            targets[item["instance_id"]] = FixedTarget(
                item["instance_id"], frozenset(item["owner_uids"]), frozenset(item["actions"]),
                tuple(item["argv"]), item["cwd"], tuple(sorted(item["environment"].items())),
                item["health_socket"], policy_sha)
        return cls(value["enabled"], value["socket_path"], value["socket_gid"],
                   frozenset(value["controller_uids"]), targets, hashlib.sha256(
                       canonical(value).encode()).hexdigest())


def _pid_state(pid: int, start_ticks: int) -> str:
    try:
        actual = _process_start_ticks(pid)
    except (ControlError, ValueError, OSError):
        return "absent"
    return "live" if actual == start_ticks else "identity_lost"


class FixedProcessAdapter:
    """Exact process/start-ticks adapter; never discovers by name or port."""

    def __init__(self, store, *, clock=time.time, sleep=time.sleep):
        self.store = store
        self.clock = clock
        self.sleep = sleep
        self._children: dict[int, subprocess.Popen] = {}

    def _read_resource(self, instance_id: str):
        try:
            return self.store.read("host_resource", instance_id)
        except ControlError as exc:
            if str(exc) == "not_found":
                return None
            raise

    def inspect(self, target: FixedTarget) -> dict:
        resource = self._read_resource(target.instance_id)
        if resource is None:
            return {"state": "stopped", "healthy": False, "identity": None,
                    "policySha256": target.policy_sha256}
        state = _pid_state(resource["pid"], resource["start_ticks"])
        healthy = state == "live" and self._health(target, resource)
        reported = "stopped" if resource.get("state") == "stopped" and state == "absent" else state
        return {"state": "running" if healthy else reported, "healthy": healthy,
                "identity": {"pid": resource["pid"], "startTicks": resource["start_ticks"],
                             "startedAt": resource["started_at"]},
                "policySha256": target.policy_sha256}

    @staticmethod
    def _health(target: FixedTarget, resource: dict) -> bool:
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
                client.settimeout(0.25)
                client.connect(target.health_socket)
                client.sendall(b'{"action":"health"}\n')
                raw = client.recv(1025)
            value = decode(raw)
            return (isinstance(value, dict) and value.get("status") == "ok"
                    and value.get("pid") == resource["pid"]
                    and value.get("start_ticks") == resource["start_ticks"])
        except (OSError, ControlError, ValueError):
            return False

    def _persist(self, instance_id: str, operation: str, phase: str, value: dict, *, db=None):
        def write(transaction):
            self.store.put(transaction, "host_resource", instance_id, value)
            self.store.event(transaction, operation, phase, {
                "instance_id": instance_id,
                "pid": value.get("pid"),
                "start_ticks": value.get("start_ticks"),
                "policy_sha256": value.get("policy_sha256"),
            })
        if db is not None:
            write(db)
        else:
            with self.store.transaction() as transaction:
                write(transaction)

    def start(self, target: FixedTarget, operation: dict, lease_id: str, peer,
              authority: LaunchGrantAuthority, *, timeout=5.0) -> dict:
        current = self._read_resource(target.instance_id)
        if current is not None:
            require(_pid_state(current["pid"], current["start_ticks"]) == "absent",
                    "resource_already_live_or_identity_lost")
        Path(target.health_socket).parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        try:
            os.unlink(target.health_socket)
        except FileNotFoundError:
            pass
        with authority.guard_store(lease_id, peer) as (lease, db):
            child = subprocess.Popen(target.argv, cwd=target.cwd, env=dict(target.environment),
                                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                     stderr=subprocess.DEVNULL, close_fds=True, start_new_session=True)
            self._children[child.pid] = child
            ticks = _process_start_ticks(child.pid)
            resource = {"instance_id": target.instance_id, "pid": child.pid,
                        "start_ticks": ticks, "started_at": self.clock(),
                        "policy_sha256": target.policy_sha256,
                        "operation_id": operation["id"], "fence": lease["fence"],
                        "lease_id": lease_id, "state": "starting"}
            self._persist(target.instance_id, operation["id"], "host_process_spawned", resource, db=db)
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self._health(target, resource):
                resource["state"] = "running"
                self._persist(target.instance_id, operation["id"], "host_process_healthy", resource)
                return self.inspect(target)
            if child.poll() is not None:
                break
            self.sleep(0.05)
        # Cleanup is still fenced and exact; failure remains durable for recovery.
        try:
            with authority.guard(lease_id, peer):
                if _pid_state(child.pid, ticks) == "live":
                    os.killpg(child.pid, signal.SIGKILL)
            child.wait(timeout=2)
            self._children.pop(child.pid, None)
        except (OSError, subprocess.SubprocessError, ControlError):
            resource["state"] = "recovery_required"
            self._persist(target.instance_id, operation["id"], "host_start_cleanup_failed", resource)
            raise ControlError("host_start_cleanup_failed")
        resource["state"] = "stopped"
        self._persist(target.instance_id, operation["id"], "host_start_failed", resource)
        raise ControlError("host_health_failed")

    def stop(self, target: FixedTarget, operation: dict, lease_id: str, peer,
             authority: LaunchGrantAuthority, *, timeout=5.0) -> dict:
        resource = self._read_resource(target.instance_id)
        require(resource is not None, "resource_not_running")
        require(resource["policy_sha256"] == target.policy_sha256, "resource_policy_drift")
        require(_pid_state(resource["pid"], resource["start_ticks"]) == "live",
                "resource_identity_lost")
        with authority.guard(lease_id, peer):
            require(os.getpgid(resource["pid"]) == resource["pid"], "resource_group_identity_lost")
            os.killpg(resource["pid"], signal.SIGTERM)
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline and _pid_state(resource["pid"], resource["start_ticks"]) == "live":
            try:
                os.waitpid(resource["pid"], os.WNOHANG)
            except ChildProcessError:
                pass
            self.sleep(0.05)
        if _pid_state(resource["pid"], resource["start_ticks"]) == "live":
            with authority.guard(lease_id, peer):
                require(os.getpgid(resource["pid"]) == resource["pid"], "resource_group_identity_lost")
                os.killpg(resource["pid"], signal.SIGKILL)
            deadline = time.monotonic() + 2
            while time.monotonic() < deadline and _pid_state(resource["pid"], resource["start_ticks"]) == "live":
                try:
                    os.waitpid(resource["pid"], os.WNOHANG)
                except ChildProcessError:
                    pass
                self.sleep(0.05)
        require(_pid_state(resource["pid"], resource["start_ticks"]) == "absent",
                "host_stop_unconfirmed")
        child = self._children.pop(resource["pid"], None)
        if child is not None:
            try:
                child.wait(timeout=0)
            except subprocess.TimeoutExpired:
                raise ControlError("host_stop_unconfirmed")
        try:
            os.unlink(target.health_socket)
        except FileNotFoundError:
            pass
        resource["state"] = "stopped"
        resource["stopped_at"] = self.clock()
        resource["stop_operation_id"] = operation["id"]
        with authority.guard_store(lease_id, peer) as (_lease, db):
            require(_pid_state(resource["pid"], resource["start_ticks"]) == "absent",
                    "host_stop_unconfirmed")
            self._persist(target.instance_id, operation["id"], "host_process_stopped", resource, db=db)
        return self.inspect(target)


class HostBroker:
    def __init__(self, store, policy: BrokerPolicy, *, clock=time.time):
        self.store = store
        self.policy = policy
        self.clock = clock
        self.authority = LaunchGrantAuthority(store, admin_uids=[os.geteuid()],
                                              enabled=policy.enabled, clock=clock)
        self.adapter = FixedProcessAdapter(store, clock=clock)
        self._canary_coordinator = None

    def _canary(self):
        require(self.policy.enabled is True and set(self.policy.targets) == {"inert-canary"},
                "canary_control_not_available")
        target = self._target("inert-canary")
        require(target.owner_uids == frozenset({os.geteuid()}),
                "canary_owner_identity_not_fixed")
        if self._canary_coordinator is None:
            from .canary_coordinator import CanaryCoordinator
            self._canary_coordinator = CanaryCoordinator(
                self.store, target, self.adapter, self.authority, clock=self.clock)
        return self._canary_coordinator

    def _target(self, instance_id: str) -> FixedTarget:
        identifier(instance_id)
        require(instance_id in self.policy.targets, "instance_not_registered")
        return self.policy.targets[instance_id]

    def handle(self, connection: socket.socket, raw: bytes) -> dict:
        require(len(raw) <= MAX_REQUEST, "request_too_large")
        peer = peer_from_unix_socket(connection)
        request = decode(raw)
        require(isinstance(request, dict) and request.get("schema") == PROTOCOL,
                "unsupported_protocol")
        action = request.get("action")
        if action == "describe":
            fields(request, "schema action instance_id")
            target = self._target(request["instance_id"])
            require(peer.uid in target.owner_uids or peer.uid in self.policy.controller_uids,
                    "peer_not_allowed")
            return {"protocol": PROTOCOL, "enabled": self.policy.enabled,
                    "instanceId": target.instance_id, "actions": sorted(target.actions),
                    "policySha256": target.policy_sha256, **self.adapter.inspect(target)}
        if action == "canary_status":
            fields(request, "schema action instance_id")
            require(peer.uid in self.policy.controller_uids, "controller_peer_not_allowed")
            require(request["instance_id"] == "inert-canary", "canary_only_target_required")
            return {"protocol": PROTOCOL, "enabled": True,
                    "instanceId": "inert-canary", **self._canary().status()}
        if action == "canary_lifecycle":
            fields(request, "schema action instance_id lifecycle_action")
            require(peer.uid in self.policy.controller_uids, "controller_peer_not_allowed")
            require(request["instance_id"] == "inert-canary", "canary_only_target_required")
            return {"protocol": PROTOCOL, "enabled": True,
                    "instanceId": "inert-canary",
                    **self._canary().run(request["lifecycle_action"])}
        if action == "issue":
            fields(request, "schema action instance_id lifecycle_action operation")
            require(peer.uid in self.policy.controller_uids, "controller_peer_not_allowed")
            target = self._target(request["instance_id"])
            lifecycle_action = request["lifecycle_action"]
            require(lifecycle_action in target.actions, "lifecycle_action_not_allowed")
            require(len(target.owner_uids) == 1, "ambiguous_owner_identity")
            nonce = self.authority.mint(request["operation"],
                                        target.command_sha256(lifecycle_action),
                                        next(iter(target.owner_uids)))
            return {"protocol": PROTOCOL, "grant": nonce, "expiresInSeconds": 60,
                    "policySha256": target.policy_sha256}
        if action == "execute":
            fields(request, "schema action instance_id lifecycle_action grant")
            target = self._target(request["instance_id"])
            require(peer.uid in target.owner_uids, "owner_peer_not_allowed")
            lifecycle_action = request["lifecycle_action"]
            require(lifecycle_action in target.actions, "lifecycle_action_not_allowed")
            lease = self.authority.claim(request["grant"], peer,
                                         target.command_sha256(lifecycle_action))
            lease_record = self.store.read("launch_lease", lease)
            operation = self.store.read("operation", lease_record["operation_id"])
            if lifecycle_action == "start":
                result = self.adapter.start(target, operation, lease, peer, self.authority)
            elif lifecycle_action == "stop":
                result = self.adapter.stop(target, operation, lease, peer, self.authority)
            else:
                self.adapter.stop(target, operation, lease, peer, self.authority)
                result = self.adapter.start(target, operation, lease, peer, self.authority)
            self.authority.retire(lease, peer)
            return {"protocol": PROTOCOL, "operationId": operation["id"], **result}
        raise ControlError("unsupported_action")


def serve(store, policy: BrokerPolicy):
    require(policy.enabled is True, "host_authority_disabled")
    broker = HostBroker(store, policy)
    if set(policy.targets) == {"inert-canary"}:
        # Enrollment happens during privileged service startup, never as a
        # side effect of a Workstation status request.
        broker._canary()
    path = Path(policy.socket_path)
    path.parent.mkdir(mode=0o750, parents=True, exist_ok=True)
    try:
        path.unlink()
    except FileNotFoundError:
        pass
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        server.bind(policy.socket_path)
        os.chown(policy.socket_path, os.geteuid(), policy.socket_gid)
        os.chmod(policy.socket_path, 0o660)
        server.listen(16)
        while True:
            connection, _ = server.accept()
            with connection:
                connection.settimeout(2)
                try:
                    chunks = []
                    size = 0
                    while True:
                        chunk = connection.recv(min(1024, MAX_REQUEST + 1 - size))
                        if not chunk:
                            break
                        chunks.append(chunk)
                        size += len(chunk)
                        require(size <= MAX_REQUEST, "request_too_large")
                    raw = b"".join(chunks)
                    require(raw and len(raw) <= MAX_REQUEST, "request_too_large")
                    result = broker.handle(connection, raw)
                    payload = {"ok": True, **result}
                except (ControlError, OSError, ValueError, subprocess.SubprocessError) as exc:
                    code = str(exc) if isinstance(exc, ControlError) else "broker_operation_failed"
                    payload = {"ok": False, "protocol": PROTOCOL, "error": code}
                connection.sendall((canonical(payload) + "\n").encode())
    finally:
        server.close()
        try:
            path.unlink()
        except FileNotFoundError:
            pass
