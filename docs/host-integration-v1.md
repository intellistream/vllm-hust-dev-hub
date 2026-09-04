# Host integration v1: default-off design and approval boundary

Status: generic library and CPU/AF_UNIX fixtures only. Nothing in this commit
creates a socket, user, group, unit, sudo/polkit rule, Docker permission, instance
registration or production backend. Existing owner/control wire JSON is unchanged
and both production entrypoints remain fail closed.

## Security objective

One host broker is the only principal allowed to mutate an enrolled instance.
Every product entry, monitor, recovery path, installer and cleanup path must ask
that broker; no caller ID, Web session, PID absence, timeout or receipt string is
authority. The broker binds a complete immutable DeploymentSpec to the controller's
operation ID, generation, executor and monotonically increasing fence.

This design protects against stale cooperative writers only after OS policy makes
the broker the sole writer. It is not a sandbox against root or a user who retains
the Docker socket, unit write access or an equivalent privileged bypass.

## Components and flow

1. A product adapter captures and qualifies the complete current DeploymentSpec,
   host writer inventory, container/cgroup identity and Manager/Provider evidence.
2. The existing Controller performs plan, approval and atomic `begin`, producing
   the server-owned operation/executor/fence. No new wire fields are accepted.
3. Trusted broker code calls `LaunchGrantAuthority.mint` for an exact command hash
   and registered owner UID. The raw random grant is returned once; only its hash
   and full binding are persisted in the mode-0600 authority database.
4. A serving leaf connects to an AF_UNIX socket. Broker code derives UID/PID from
   Linux `SO_PEERCRED` and PID start ticks from `/proc`; request JSON cannot create
   a `PeerIdentity`. `claim` atomically checks UID, command, expiry and current
   operation fence, consumes the grant once and persists a lease.
5. Each direct-child spawn or signal enters `LaunchGrantAuthority.guard` and holds
   the same SQLite authority transaction for that short critical section. A lease
   remains valid after commit only for the exact resulting generation/spec/fence.
   Any new takeover or drift invalidates it.
6. Long-lived waiting holds no database lock. The broker, not the old supervisor,
   handles a later approved stop/takeover against a cgroup/resource identity owned
   by the new operation. The old supervisor must stop forwarding signals after its
   lease loses authority; it may not use an emergency bypass.

`LaunchGrantAuthority` is deliberately a library, not another coordinator or a
Sage-specific adapter. Sage Mate owns its product mapping; Workstation owns only
preparation/evidence/approval UI and a pinned thin client.

## Durable state and recovery

Launch grants contain the exact instance, operation, fence, executor, target
generation/spec, command SHA, registered owner UID and short claim deadline.
Leases additionally persist kernel-derived UID/PID/start-ticks and claim time.
Reopening the private Store after broker process failure preserves consumed grants
and active leases; replay remains rejected.

A lease is not a liveness or quiescence certificate. Broker recovery must first
prove the recorded cgroup/container resource and all in-flight daemon requests are
terminated or fenced, then use the existing Controller recovery path to advance
the fence. A newer fence makes every old lease guard fail. `retire` only marks the
exact currently authorized peer lease and never kills a process or authorizes
takeover.

## Writer inventory and qualification

`validate_fencing_receipt` accepts an immutable declaration only when its digest
matches the enrollment pin and its writer IDs exactly equal a server-owned required
set. Each entry must say `broker-only` and carry a policy artifact hash. This is a
format/CAS check, **not proof of OS enforcement**. The product backend must inspect
actual ownership, ACLs, unit content/digests, socket reachability and live queued
daemon work before `qualify` may return true.

At minimum the target-specific required set should enumerate:

- broker socket/service and executable;
- serving systemd unit, drop-ins and environment/config sources;
- Docker/container runtime socket or another resource supervisor;
- monitors/watchdogs/boot recovery;
- ExecStopPost/cleanup helpers;
- release/quickstart/install/update paths that can edit configuration or launch;
- secret, deployment registry, Manager-rendered config and model pointer writers.

An unknown, omitted, writable or advisory path makes qualification false. Docker
CLI exit does not prove daemon completion: mutations must be synchronous and
bounded, or carry an operation/fence into an independently enforced daemon queue.
If the daemon cannot cancel or reject stale queued work, the backend is unqualified.

## Threat and failure cases

| Case | Required result |
| --- | --- |
| Caller supplies owner/admin/PID fields | Ignored/rejected; only OS peer credentials and server registry count |
| Grant stolen by another command or UID | Binding mismatch; grant remains unconsumed |
| Grant replay or post-expiry claim | Rejected atomically |
| Broker crashes after claim | Persisted consumed grant/lease survive reopening; no automatic new grant |
| Old leaf revives after generation/fence changes | Every guard fails before spawn/signal |
| PID reused | Start-ticks mismatch; lease cannot enter guard |
| Monitor observes failure | Read/report only; it cannot mint approval or recover autonomously |
| Rollback fails or ownership changes | Recovery-required; never kill or restore a newer occupant |
| Incomplete external-writer receipt | Qualification rejected |
| Broker SIGKILL during child wait | External cgroup supervisor and next approved recovery must reconcile; Python cleanup is not evidence |

CPU fixtures cover disabled zero-state behavior, unconstructable caller peer IDs,
actual AF_UNIX peer derivation, wrong-command rejection, replay, expiry, stale fence,
generation drift, crash/reopen persistence, exact lease retirement and incomplete/
tampered writer receipts. They do not call Docker, systemd, NPU tools or a service.

## Installation checklist — all items require separate operator approval

1. Create a dedicated broker OS principal and private state/runtime directories;
   record exact UID/GID/modes and prohibit shared interactive login.
2. Install a root-owned broker executable by digest plus socket/service units;
   configure AF_UNIX owner/group/mode, request size/timeouts and peer allowlist.
3. Make serving units call the non-recursive broker/leaf contract. Remove direct
   lifecycle fallbacks, name/port-based kills and blocking systemd re-entry.
4. Remove product/service users from direct Docker/runtime control. Restrict
   sudo/polkit and unit/drop-in/env/config/model-pointer writes to broker-mediated
   operations. Audit equivalent root helpers before claiming exclusivity.
5. Put each instance/generation in an owned cgroup/container resource with a stable
   identity. Define bounded start/verify/stop/kill and daemon-request completion.
6. Route monitor, watchdog, boot recovery, cleanup, release and installer mutations
   through the same fence. Unknown paths keep the instance unqualified.
7. Capture a host fencing receipt and independently verify every listed live OS
   rule against its policy hash. Register the complete baseline only afterward.
8. Run isolated local negative/chaos tests, then a separately approved disposable
   CPU service acceptance. Production model/TP4/graph/NPU acceptance is a later,
   explicitly scheduled operation with rollback ownership evidence.
9. Enable host/controller/product gates independently, default false. Record the
   approved instance/action/window. Never infer permission from a Web password.

No item above is performed by repository checkout, commit, submodule pin or Web
deployment. Until all target-specific evidence exists, lifecycle availability and
Mod application remain false.
