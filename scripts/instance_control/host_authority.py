"""Default-off durable launch grants bound to Linux peer credentials and fences.

This is a generic broker library, not a socket server or host policy installer.
Callers must obtain PeerIdentity from an accepted AF_UNIX connection; request JSON
fields are never converted into identities. Product adapters remain responsible
for cgroup/resource identity and complete external-writer exclusion.
"""

from contextlib import contextmanager
from dataclasses import dataclass, field
import os
from pathlib import PurePath
import secrets
import socket
import struct
import time
import uuid

from .schema import digest, fields, hash_value, identifier, require

_PEER_SEAL = object()


@dataclass(frozen=True, init=False)
class PeerIdentity:
    uid: int
    pid: int
    start_ticks: int
    _seal: object = field(repr=False, compare=False)

    def __init__(self, *_args, **_kwargs):
        raise ValueError("peer_identity_requires_unix_transport")

    @classmethod
    def _from_kernel(cls, uid, pid, start_ticks):
        value = object.__new__(cls)
        object.__setattr__(value, "uid", uid)
        object.__setattr__(value, "pid", pid)
        object.__setattr__(value, "start_ticks", start_ticks)
        object.__setattr__(value, "_seal", _PEER_SEAL)
        return value


def _process_start_ticks(pid):
    require(type(pid) is int and pid > 0, "invalid_peer_process")
    try:
        # comm may contain spaces and ')'; fields after its final ')' begin at 3.
        with open(f"/proc/{pid}/stat", encoding="utf-8") as stream:
            tail = stream.read().rsplit(")", 1)[1].split()
        value = int(tail[19])
    except (OSError, ValueError, IndexError) as exc:
        raise ValueError("peer_process_unavailable") from exc
    require(value > 0, "invalid_peer_process")
    return value


def peer_from_unix_socket(connection):
    """Derive identity from Linux SO_PEERCRED and a PID-reuse-resistant start tick."""
    require(connection.family == socket.AF_UNIX and hasattr(socket, "SO_PEERCRED"),
            "authenticated_unix_transport_required")
    raw = connection.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize("3i"))
    pid, uid, _gid = struct.unpack("3i", raw)
    return PeerIdentity._from_kernel(uid, pid, _process_start_ticks(pid))


def validate_fencing_receipt(receipt, expected_sha256, required_writers):
    """Validate a pinned declaration; a backend must still prove OS enforcement."""
    fields(receipt, "schema instance_id broker writers captured_at")
    require(receipt["schema"] == "vllm-hust.host-fencing-receipt/v1", "invalid_fencing_receipt")
    identifier(receipt["instance_id"])
    fields(receipt["broker"], "uid executable_sha256 socket")
    require(type(receipt["broker"]["uid"]) is int and receipt["broker"]["uid"] >= 0,
            "invalid_fencing_receipt")
    hash_value(receipt["broker"]["executable_sha256"])
    require(_absolute(receipt["broker"]["socket"]), "invalid_fencing_receipt")
    require(type(receipt["captured_at"]) in (int, float), "invalid_fencing_receipt")
    require(isinstance(receipt["writers"], list) and receipt["writers"], "incomplete_writer_inventory")
    seen = set()
    for writer in receipt["writers"]:
        fields(writer, "id kind path mode policy_sha256")
        identifier(writer["id"])
        require(writer["id"] not in seen and writer["kind"] in
                {"broker", "systemd", "docker", "monitor", "installer", "cleanup"}
                and _absolute(writer["path"]) and writer["mode"] == "broker-only",
                "invalid_fencing_receipt")
        hash_value(writer["policy_sha256"])
        seen.add(writer["id"])
    require(seen == set(required_writers), "incomplete_writer_inventory")
    hash_value(expected_sha256)
    require(digest(receipt) == expected_sha256, "fencing_receipt_mismatch")
    return True


def _absolute(value):
    return (isinstance(value, str) and value.startswith("/") and "\0" not in value
            and ".." not in PurePath(value).parts)


class LaunchGrantAuthority:
    """Persist one-use launch grants and leases in the controller's private store."""

    def __init__(self, store, *, admin_uids=(), enabled=False, clock=time.time):
        self.store = store
        self.admin_uids = frozenset(admin_uids)
        self.enabled = enabled
        self.clock = clock

    def _gate(self):
        require(self.enabled is True, "host_authority_disabled")

    def _admin(self):
        require(os.geteuid() in self.admin_uids, "administrator_os_identity_required")

    def mint(self, operation_token, command_sha256, owner_uid, *, ttl=60):
        """Mint after Controller.begin; the raw secret is returned exactly once."""
        self._gate()
        self._admin()
        hash_value(command_sha256)
        require(type(owner_uid) is int and owner_uid >= 0 and type(ttl) is int and 1 <= ttl <= 300,
                "invalid_launch_grant")
        nonce = secrets.token_urlsafe(32)
        grant_id = digest(nonce)
        with self.store.transaction() as db:
            operation, instance, registration = self._owned(db, operation_token)
            require(owner_uid in registration["owner_uids"], "owner_os_identity_not_allowed")
            grant = {"id": grant_id, "instance_id": operation["instance_id"],
                     "operation_id": operation["id"], "fence": operation["fence"],
                     "executor": operation["executor"], "target_generation": instance["generation"] + 1,
                     "target_spec": operation["candidate"], "command_sha256": command_sha256,
                     "owner_uid": owner_uid, "issued_at": self.clock(),
                     "expires_at": self.clock() + ttl, "consumed": False}
            self.store.put(db, "launch_grant", grant_id, grant, immutable=True)
            self.store.event(db, operation["id"], "launch_grant_issued",
                             {"grant": grant_id, "fence": operation["fence"]})
        return nonce

    def claim(self, nonce, peer, command_sha256):
        """Atomically consume a grant using transport-derived peer identity."""
        self._gate()
        require(isinstance(nonce, str) and len(nonce) <= 256, "invalid_launch_grant")
        require(isinstance(peer, PeerIdentity) and peer._seal is _PEER_SEAL,
                "authenticated_unix_transport_required")
        require(_process_start_ticks(peer.pid) == peer.start_ticks, "peer_process_identity_changed")
        hash_value(command_sha256)
        grant_id = digest(nonce)
        with self.store.transaction() as db:
            grant = self.store.get(db, "launch_grant", grant_id)
            require(not grant["consumed"] and self.clock() < grant["expires_at"],
                    "launch_grant_expired_or_replayed")
            require(grant["owner_uid"] == peer.uid and grant["command_sha256"] == command_sha256,
                    "launch_grant_binding_mismatch")
            operation = self.store.get(db, "operation", grant["operation_id"])
            instance = self.store.get(db, "instance", grant["instance_id"])
            require(instance["operation"] == operation["id"] and instance["fence"] == grant["fence"]
                    and operation["fence"] == grant["fence"]
                    and operation["executor"] == grant["executor"], "fence_lost")
            lease_id = uuid.uuid4().hex
            grant["consumed"] = True
            lease = {"id": lease_id, "grant_id": grant_id, "instance_id": grant["instance_id"],
                     "operation_id": grant["operation_id"], "fence": grant["fence"],
                     "executor": grant["executor"], "target_generation": grant["target_generation"],
                     "target_spec": grant["target_spec"], "command_sha256": command_sha256,
                     "peer": {"uid": peer.uid, "pid": peer.pid, "start_ticks": peer.start_ticks},
                     "claimed_at": self.clock(), "retired": False}
            self.store.put(db, "launch_grant", grant_id, grant)
            self.store.put(db, "launch_lease", lease_id, lease, immutable=True)
            self.store.event(db, operation["id"], "launch_grant_claimed",
                             {"lease": lease_id, "fence": grant["fence"], "peer_uid": peer.uid})
        return lease_id

    @contextmanager
    def guard(self, lease_id, peer):
        """Hold the same DB transaction through one spawn/signal critical section."""
        with self.guard_store(lease_id, peer) as (lease, _db):
            yield lease

    @contextmanager
    def guard_store(self, lease_id, peer):
        """Trusted adapter variant exposing the already-held authority transaction.

        This exists so a host adapter can atomically persist the exact resource
        identity created by a spawn.  It is never reachable from wire data.
        """
        self._gate()
        require(isinstance(peer, PeerIdentity) and peer._seal is _PEER_SEAL,
                "authenticated_unix_transport_required")
        require(_process_start_ticks(peer.pid) == peer.start_ticks, "peer_process_identity_changed")
        with self.store.transaction() as db:
            lease = self.store.get(db, "launch_lease", lease_id)
            require(not lease["retired"] and lease["peer"] ==
                    {"uid": peer.uid, "pid": peer.pid, "start_ticks": peer.start_ticks},
                    "launch_lease_identity_mismatch")
            instance = self.store.get(db, "instance", lease["instance_id"])
            operation = self.store.get(db, "operation", lease["operation_id"])
            changing = (instance["operation"] == lease["operation_id"]
                        and instance["fence"] == lease["fence"]
                        and operation["executor"] == lease["executor"])
            committed = (instance["operation"] is None and instance["fence"] == lease["fence"]
                         and instance["generation"] == lease["target_generation"]
                         and instance["spec"] == lease["target_spec"]
                         and operation["phase"] == "committed")
            require(changing or committed, "fence_lost")
            yield lease.copy(), db

    def retire(self, lease_id, peer):
        """Retire only the exact peer lease; never infer quiescence or kill resources."""
        self._gate()
        require(isinstance(peer, PeerIdentity) and peer._seal is _PEER_SEAL,
                "authenticated_unix_transport_required")
        require(_process_start_ticks(peer.pid) == peer.start_ticks, "peer_process_identity_changed")
        with self.store.transaction() as db:
            lease = self.store.get(db, "launch_lease", lease_id)
            require(not lease["retired"] and lease["peer"] ==
                    {"uid": peer.uid, "pid": peer.pid, "start_ticks": peer.start_ticks},
                    "launch_lease_identity_mismatch")
            instance = self.store.get(db, "instance", lease["instance_id"])
            operation = self.store.get(db, "operation", lease["operation_id"])
            require(instance["fence"] == lease["fence"] and
                    ((instance["operation"] == lease["operation_id"] and
                      operation["executor"] == lease["executor"]) or
                     (instance["operation"] is None and operation["phase"] == "committed" and
                      instance["generation"] == lease["target_generation"] and
                      instance["spec"] == lease["target_spec"])), "fence_lost")
            lease["retired"] = True
            self.store.put(db, "launch_lease", lease_id, lease)

    def _owned(self, db, token):
        fields(token, "id plan_id instance_id fence phase administrator_uid baseline candidate deadline recovery_deadline executor")
        operation = self.store.get(db, "operation", token["id"])
        instance = self.store.get(db, "instance", operation["instance_id"])
        registration = self.store.get(db, "registration", operation["instance_id"])
        require(operation["fence"] == token["fence"] and operation["executor"] == token["executor"]
                and instance["fence"] == token["fence"] and instance["operation"] == token["id"],
                "fence_lost")
        return operation, instance, registration
