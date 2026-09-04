# Host broker v1

Status: production-shaped execution plane with a disabled example policy. The
only bundled target is an inert CPU health canary. No shared inference instance,
container, service unit, model, device or Mod is registered by this repository.

The broker listens on an administrator-selected AF_UNIX socket and derives every
caller UID, PID and process start tick with `SO_PEERCRED` and `/proc`. Its root-owned
policy maps an `instance_id` and `start`/`stop` action to one exact argv, cwd,
environment, health socket and policy digest. Requests cannot carry commands,
paths, images, PIDs, UIDs, owner claims or environment values.

## Protocol

All requests and replies are bounded JSON objects using
`vllm-hust.host-broker/v1`:

- `describe(instance_id)` is read-only and returns the registered policy digest,
  exact PID/start-ticks identity and live health result.
- `issue(instance_id, lifecycle_action, operation)` is accepted only from a
  policy-pinned controller UID. `operation` must exactly match the Controller's
  durable reserved operation. The broker returns one short-lived raw grant once.
- `execute(instance_id, lifecycle_action, grant)` is accepted only from the fixed
  target owner UID. Claim atomically consumes the grant and binds it to that peer,
  action digest, operation, generation, target spec, executor and fence.

The fixed process adapter persists PID/start-ticks and the policy digest inside
the same SQLite transaction that guards spawn. Stop signals only that exact live
session leader while holding the same guard, then persists stopped evidence after
absence is verified. A broker restart reads the durable identity; it does not
create a new grant, infer ownership from PID absence, or automatically take over.

## Consumer boundary

Sage Mate's `vllm-hust.instance-owner-entry/v1` remains the consumer-facing
protocol. Its identifiers and `new_operations_enabled` value are routing hints,
not authority. A future qualified owner adapter must resolve those values through
a server-owned registration, run Controller plan/approve/begin, use this broker,
verify the worker, then commit or perform the operation-owned rollback. The Web
application is only a thin client and never runs shell, systemctl or Docker.

`prepared`, `installed`, `configured`, `enabled intent`, `compatible`, `running`
and `effective` are distinct evidence states. The inert canary proves only broker
lifecycle behavior and must always report `effective=false` for Mods.

## Installation and qualification

`scripts/install_instance_host_broker.sh UID GID GROUP` creates a non-login
`vllm-hust-broker` principal, installs root-owned code and a hardened systemd unit,
and writes an **enabled=false** canary-only policy. It neither starts the broker nor
enrolls a shared service. Enabling even the canary is a separate recorded operator
action. A shared target additionally requires a complete immutable DeploymentSpec,
live writer-fencing receipt, owner adapter, compatibility evidence and rollback
qualification; none is supplied here.

For the isolated host acceptance only, root may use
`scripts/set_inert_canary_gate.py --enabled true|false`. The tool refuses every
policy containing anything except the bundled `inert-canary`; it cannot authorize,
register or operate a shared service.
