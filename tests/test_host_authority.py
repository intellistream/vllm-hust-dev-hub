"""CPU/AF_UNIX-only attack and crash fixtures for durable launch grants."""

import os
from pathlib import Path
import socket
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from instance_control import ControlError, Store
from instance_control.controller import Controller
from instance_control.host_authority import (
    LaunchGrantAuthority,
    PeerIdentity,
    peer_from_unix_socket,
    validate_fencing_receipt,
)
from instance_control.schema import digest
from test_instance_transactions import FakeBackend, specification


class HostAuthorityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="host-authority-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "authority"
        self.store = Store(self.root, initialize=True)
        self.now = 1000.0
        self.baseline = specification()
        self.candidate = specification(True)
        self.backend = FakeBackend(lambda: self.now, self.baseline)
        self.controller = Controller(self.store, {"fixture": self.backend}, enabled=True,
                                     admin_uids=[os.geteuid()], clock=lambda: self.now)
        self.registration = {"instance_id": "fixture", "owner_id": "owner", "profile_id": "profile",
                             "backend_id": "fixture", "actions": ["apply", "disable", "rollback"],
                             "owner_uids": [os.geteuid()], "fencing_receipt_sha256": "a" * 64}
        self.controller.register(self.registration, self.baseline)
        plan = self.controller.plan("fixture", "apply", self.candidate)
        approval = self.controller.approve(plan["plan_id"])
        self.operation = self.controller.begin(plan["plan_id"], approval)
        self.authority = LaunchGrantAuthority(self.store, enabled=True,
                                              admin_uids=[os.geteuid()], clock=lambda: self.now)
        left, right = socket.socketpair(socket.AF_UNIX)
        self.addCleanup(left.close)
        self.addCleanup(right.close)
        self.peer = peer_from_unix_socket(left)
        self.command = "b" * 64

    def grant(self, ttl=60):
        return self.authority.mint(self.operation, self.command, os.geteuid(), ttl=ttl)

    def test_default_off_has_no_state_and_peer_cannot_be_built_from_request_fields(self):
        authority = LaunchGrantAuthority(self.store, enabled=False, admin_uids=[os.geteuid()])
        with self.assertRaisesRegex(ControlError, "host_authority_disabled"):
            authority.mint(self.operation, self.command, os.geteuid())
        with self.assertRaisesRegex(ValueError, "unix_transport"):
            PeerIdentity(uid=os.geteuid(), pid=os.getpid(), start_ticks=1)
        with self.store.transaction() as db:
            self.assertIsNone(db.execute("SELECT 1 FROM documents WHERE kind='launch_grant'").fetchone())

    def test_grant_is_one_use_and_bound_to_peer_uid_command_and_current_fence(self):
        nonce = self.grant()
        with self.assertRaisesRegex(ControlError, "binding_mismatch"):
            self.authority.claim(nonce, self.peer, "c" * 64)
        lease = self.authority.claim(nonce, self.peer, self.command)
        with self.assertRaisesRegex(ControlError, "expired_or_replayed"):
            self.authority.claim(nonce, self.peer, self.command)
        with self.authority.guard(lease, self.peer) as identity:
            self.assertEqual(identity["fence"], self.operation["fence"])
        with self.store.transaction() as db:
            current = self.store.get(db, "instance", "fixture")
            current["fence"] += 1
            self.store.put(db, "instance", "fixture", current)
        with self.assertRaisesRegex(ControlError, "fence_lost"):
            with self.authority.guard(lease, self.peer):
                self.fail("stale lease entered critical section")

    def test_forged_or_reused_process_identity_never_enters_claim_or_guard(self):
        nonce = self.grant()
        stale = PeerIdentity._from_kernel(self.peer.uid, self.peer.pid, self.peer.start_ticks + 1)
        with self.assertRaisesRegex(ControlError, "peer_process_identity_changed"):
            self.authority.claim(nonce, stale, self.command)
        lease = self.authority.claim(nonce, self.peer, self.command)
        with self.assertRaisesRegex(ControlError, "peer_process_identity_changed"):
            with self.authority.guard(lease, stale):
                self.fail("reused PID entered critical section")

    def test_expiry_and_stale_operation_reject_without_consuming_other_grants(self):
        expired = self.grant(ttl=1)
        self.now += 2
        with self.assertRaisesRegex(ControlError, "expired_or_replayed"):
            self.authority.claim(expired, self.peer, self.command)
        self.now = 1000.0
        stale = self.grant()
        with self.store.transaction() as db:
            current = self.store.get(db, "instance", "fixture")
            current["operation"] = "replacement"
            self.store.put(db, "instance", "fixture", current)
        with self.assertRaisesRegex(ControlError, "fence_lost"):
            self.authority.claim(stale, self.peer, self.command)

    def test_claim_and_guard_survive_broker_process_restart(self):
        lease = self.authority.claim(self.grant(), self.peer, self.command)
        reopened = Store(self.root)
        restarted = LaunchGrantAuthority(reopened, enabled=True,
                                         admin_uids=[os.geteuid()], clock=lambda: self.now)
        with restarted.guard(lease, self.peer) as identity:
            self.assertEqual(identity["command_sha256"], self.command)
        restarted.retire(lease, self.peer)
        with self.assertRaisesRegex(ControlError, "lease_identity_mismatch"):
            with restarted.guard(lease, self.peer):
                self.fail("retired lease entered critical section")

    def test_commit_keeps_exact_generation_lease_but_drift_revokes_it(self):
        lease = self.authority.claim(self.grant(), self.peer, self.command)
        with self.store.transaction() as db:
            current = self.store.get(db, "instance", "fixture")
            current.update(operation=None, status="ready", generation=1, spec=self.operation["candidate"])
            operation = self.store.get(db, "operation", self.operation["id"])
            operation["phase"] = "committed"
            self.store.put(db, "instance", "fixture", current)
            self.store.put(db, "operation", operation["id"], operation)
        with self.authority.guard(lease, self.peer):
            pass
        with self.store.transaction() as db:
            current = self.store.get(db, "instance", "fixture")
            current["generation"] = 2
            self.store.put(db, "instance", "fixture", current)
        with self.assertRaisesRegex(ControlError, "fence_lost"):
            with self.authority.guard(lease, self.peer):
                self.fail("generation-drifted lease entered critical section")

    def test_fencing_receipt_requires_exact_inventory_and_digest(self):
        writers = [
            {"id": "broker", "kind": "broker", "path": "/run/vllm-hust/broker.sock", "mode": "broker-only", "policy_sha256": "1" * 64},
            {"id": "systemd", "kind": "systemd", "path": "/etc/systemd/system/fixture.service", "mode": "broker-only", "policy_sha256": "2" * 64},
            {"id": "docker", "kind": "docker", "path": "/run/docker.sock", "mode": "broker-only", "policy_sha256": "3" * 64},
        ]
        receipt = {"schema": "vllm-hust.host-fencing-receipt/v1", "instance_id": "fixture",
                   "broker": {"uid": os.geteuid(), "executable_sha256": "4" * 64,
                              "socket": "/run/vllm-hust/broker.sock"},
                   "writers": writers, "captured_at": self.now}
        required = {"broker", "systemd", "docker"}
        self.assertTrue(validate_fencing_receipt(receipt, digest(receipt), required))
        for changed in (
            {**receipt, "writers": writers[:-1]},
            {**receipt, "writers": [{**writers[0], "mode": "advisory"}, *writers[1:]]},
            {**receipt, "broker": {**receipt["broker"], "socket": "relative.sock"}},
        ):
            with self.subTest(changed=changed), self.assertRaises(ControlError):
                validate_fencing_receipt(changed, digest(changed), required)
        with self.assertRaisesRegex(ControlError, "fencing_receipt_mismatch"):
            validate_fencing_receipt(receipt, "f" * 64, required)


if __name__ == "__main__":
    unittest.main()
