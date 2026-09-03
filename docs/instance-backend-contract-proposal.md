# Backend / foreground contract proposal for Sage Mate

Status: additive generic helper; no production binding enabled.
Baseline dev-hub `b6e56e1`, Sage Mate owner consumer `d310686`; Sage acceptance
and product feedback read from committed `405ff08` / `docs/mod-producer-acceptance.md`.
Existing adapter signatures agree. Authenticated transport, executor grants and
daemon fencing remain an unaccepted future integration, not supplied by this helper.

## Ownership (coordinator confirmed)

- Workstation task: `dev-hub/scripts/instance_control/*`, generic transaction,
  backend protocol and foreground helper, tests/docs; Workstation UI/client.
- Sage Mate task: product adapter, owner entry, bypass audit, its gitlink.
- No edits to Sage Mate files by Workstation; no second product backend in dev-hub.
- Existing owner-entry/v1 and instance-control/v1 wire fields stay unchanged.
  Any subsequent shared schema change needs updated contract and fixtures before
  consumer adoption. Producer main is pushed first, consumers then repin.

## Existing v1 adapter API (unchanged signatures)

All methods are trusted Python calls, not remotely callable JSON dispatch. The
adapter is selected by server-owned `backend_id`, never an import path from a
request. An implementation must not call the owner shell entry recursively.

| Method | Return | Preconditions / responsibility |
| --- | --- | --- |
| `qualify(registration, spec)` | exact bool | read-only: verify complete resolved spec, pinned Manager/Provider evidence and OS writer exclusion; unknown -> false |
| `inspect(registration)` | observation dict below | read-only fresh exact runtime; never silently start/reconcile |
| `owns(registration, operation, expected_identity, *, restore)` | exact bool | read-only fresh operation-specific ownership; owner ID alone insufficient |
| `deploy(registration, spec, operation, deadline, *, restore)` | None | synchronous bounded effect while controller holds authoritative fence; no queued/untracked writer may survive return |
| `verify(registration, spec_hash, operation, deadline)` | observation | bounded process/component/model evidence, not only HTTP health |
| `quiescent(registration, operation)` | exact bool | prove old effects terminated or externally fenced; not PID absence/lease expiry |

`deadline` is epoch seconds in current v1, imposed by a private server-side
operation. Adapters should convert remaining time once to monotonic budgets for
subprocess waits and enforce it on every external command. Failure must not
continue mutating in the background. Long-lived serving supervision is **not** a
single call to `deploy` holding SQLite forever.

## Full inputs / identity

`DeploymentSpec` is the schema in `scripts/instance_control/schema.py`, not an
image/hash locator: original manifests, source/wheel hashes, immutable image,
model revision/files, devices/TP/PP/graph, ports/mounts, serving Python/full argv,
environment/allowlist/resolved options, Provider config/rendered bytes/hash,
qualification receipt and versioned secret references. The adapter must resolve
and compare all actual defaults; JSON structural validity is not completeness.
No live `.env` lookup or Manager reconfiguration after approval.

Observation exact fields:

```text
instance_id, spec_hash, captured_at, healthy,
components_executed, inference_verified,
identity = {boot_id, supervisor_generation, resource_id, started_at,
            processes: [{pid, start_ticks, role, rank}]}
```

`components_executed` contains exact extension IDs only after domain-specific
execution evidence. BidKV scheduler materialization/execution differs from a
DiffSpec worker witness. Both require bounded inference and complete expected
process/rank membership. `healthy`/`inference_verified` are trusted adapter outputs,
never client assertions; retain the underlying evidence in private adapter storage.

Registered `instance_id/owner_id/profile_id/backend_id` are locators. Registered
`owner_uids` and host admin policy require independent OS peer identification.
Caller owner/invocation IDs or Web login are not grants. Three gates remain host
new-operation gate + instance action allowlist + plan/action/generation/expiry
approval. Recovery requires original scope and current operation ownership.

The current operation contains `id`, `executor`, `fence`, `plan_id`, `instance_id`,
`baseline`, `candidate`, `deadline`, `recovery_deadline`, `administrator_uid`,
`phase`. These are server-owned. `plan.generation` is the CAS generation;
`operation.fence` is the monotonically advanced writer epoch; runtime
`identity.supervisor_generation` is the actual launch generation. They are not
interchangeable. A token dictionary alone is not authority: every effect must
validate the current store fence and executor in the same critical section.

## Foreground helper delivered for isolated use

Generic `run_foreground` supervises a single direct child from a pre-resolved
trusted command, inherit foreground output, keep the parent present, forward
TERM/INT/HUP, reaps the child and bounds shutdown/escalation. It accepts a trusted
context-manager guard that revalidates ownership around **each spawn/signal**;
it must not hold the deployment transaction during the whole serve lifetime.
Guard failure stops further signals, rather than touching a possibly replaced
occupant. No automatic restart. No Docker/systemd commands in the helper.

Tests use only isolated Python children. They must prove default-off zero spawn,
exit-code propagation, real signals, shutdown escalation, denied spawn/signal,
exception cleanup and bounded exit. This does not prove container/daemon fencing,
kill-of-descendants, control-plane wiring or host permissions installation.
Unmanaged grandchildren/daemonization are unsupported; the product adapter must
provide a correctly supervised leaf/cgroup before qualification.

API: `run_foreground(FrozenCommand(argv, cwd, environment), guard, enabled=False,
shutdown_grace=5.0, kill_wait=5.0, poll_interval=0.05) -> ForegroundResult`.
Command/working directory are absolute, environment is explicit and not inherited,
output is inherited, stdin is closed, no shell is invoked. Environment/command are
private trusted adapter inputs and must never be reflected in public errors.
TERM/INT start the shutdown budget; HUP only forwards. Escalation rechecks the same
guard. Runtime normal exit reaps the direct child and restores signal handlers.

The caller must exclusively own child waiting, run on the main thread and retain
default SIGCHLD handling. `waitid(WNOWAIT)` keeps an exited child unreaped until
signalling is over to prevent ordinary PID reuse. It does not fence a malicious
same-process thread/guard that reaps children, or an external privileged writer.

`ForegroundResult` contains `reason`, `returncode`, `child_pid`, `child_reaped` and
derived `exit_code` (signal exit -> 128+signal; unconfirmed -> 2). `spawn_refused`
means no child was created. `spawn_guard_failed`, `signal_authority_lost`,
`cleanup_unconfirmed`, `child_exit_unconfirmed` and `child_wait_ownership_lost`
must not be treated as proof that the child is gone; inspect `child_reaped` and
reconcile through the authoritative owner. The helper never restarts/retries.

Reproduction (CPU-only):

```bash
python3 -m pytest -q tests/test_instance_foreground.py tests/test_instance_transactions.py tests/test_deployment_receipt.py tests/test_optimization_profile.py
python3 -m ruff check scripts/instance_control scripts/instance_owner_entry.py scripts/instance_control_entry.py tests/test_instance_transactions.py tests/test_instance_foreground.py
```

Result: **52 passed, 37 subtests passed**. New foreground checks cover real
TERM/INT/HUP, non-terminating HUP, SIGKILL escalation/reaping, clean environment,
guard denial on spawn/signal/exception cleanup, post-spawn guard failure retaining
identity, handler restoration, invalid inputs and closed error codes. Tests clean
up their own children by pidfd; production helper has no guard-bypassing cleanup.
Neither production CLI imports this helper or enrolls a backend. Existing wire
contracts/default-off errors are byte-for-byte unchanged from `b6e56e1`.

## Safe errors

Public adapter failures use closed codes, not raw argv/env/exception text:
`backend_unqualified`, `identity_drift`, `ownership_lost`, `deadline_exceeded`,
`configuration_drift`, `evidence_incomplete`, `old_executor_live`,
`nested_owner_entry`, `backend_failed`. Unknown errors map to `backend_failed`.
No exception message containing secrets enters Web output or shared logs.
No error authorizes a retry, fallback, topology change or rollback without fence.

## Product integration gates (Sage feedback received; still unmet)

1. Can the product adapter implement these read-only identity/qualification
   methods and synchronous mutation semantics? Which daemon calls can outlive
   their client, and how will those be fenced?
2. Can serving be supervised through a direct non-recursive leaf process while
   start/stop/reconcile/cleanup re-enter without SQLite/systemd deadlock?
3. Which OS principal identifies the owner and approver; how will the product
   bind supervisor invocation to current operation without trusting request IDs?
4. Are complete spec capture, model/TP4/graph invariants and process/rank execution
   evidence available? Unknown evidence must remain unavailable, not successful.

Actual socket/unit/permission installation and enablement remain separately
approved host operations. No changes to current model, TP4, graph or shared tasks.

Sage `405ff08` explicitly reports no trusted broker executor identity, no qualified
synchronous deployment primitive and no old-writer quiescence evidence yet.
These are genuine qualification gaps, not reasons to substitute caller tickets,
PID absence or CLI completion. A generic authenticated broker and durable launch
grants need a separate contract/fixture review before any product binding.
