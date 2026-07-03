# Perfgate Scenario Rollout Plan

This document tracks the requirement and development plan for extending the
vLLM-HUST performance gate from the current smoke scenario to more benchmark
scenarios.

It is intended to be the durable handoff context for GitHub issues, PRs, and
future development sessions.

## Background

The current performance gate flow mainly validates the `random-online`
scenario. This is useful as a fast smoke gate, but it does not provide enough
coverage for real benchmark workloads.

The target direction is to let each important benchmark scenario have:

- a same-spec benchmark definition
- a perfgate baseline definition
- a workflow path that can run the scenario consistently
- a comparison result that can be used for PR gating or reporting
- published benchmark data that can be aggregated by the website

The rollout should be incremental. Each scenario should be added, observed, and
stabilized before the next scenario is enabled.

## Goals

- Extend performance gate coverage beyond `random-online`.
- Add scenarios in small PRs so data can appear continuously.
- Keep PR preview gates fast enough for normal development.
- Keep formal main benchmark runs comprehensive enough for release and website
  reporting.
- Use consistent spec selection across `vllm-hust` and `vllm-ascend-hust`.
- Avoid hard-coding a single perfgate spec file when multiple scenarios and
  hardware chips are supported.

## Non-Goals

- Do not enable every scenario in one PR.
- Do not mix emergency fixes, such as B2/B3 spec defaults, with broad scenario
  rollout work.
- Do not make PR preview gates publish formal benchmark results.
- Do not require every scenario to be blocking from day one. New scenarios can
  start in report mode while data quality is verified.

## Current State

### Implemented

- `random-online` is the current primary perfgate scenario.
- The GitHub self-hosted Ascend runner is expected to be 910B2.
- The B2 random-online perfgate spec exists in `vllm-hust-benchmark`:
  `docs/official-baselines/perfgate-ascend-qwen25-3b-910b2.json`.

### Recently Fixed Separately

The workflow default spec naming had a B3/B2 mismatch. That issue should stay
separate from scenario rollout work:

- `vllm-hust`: defaults were aligned with the B2 runner.
- `vllm-ascend-hust`: defaults should also align with the B2 runner.

### Known Gap

Only `random-online` has the complete gate path today. Other benchmark
scenarios do not yet have complete perfgate coverage.

## Target Mechanism

The desired mechanism is:

1. A workflow receives or derives the benchmark scenario.
2. The workflow resolves the hardware chip model, for example `910B2`.
3. A resolver maps `(scenario, hardware_chip_model)` to a spec file.
4. The workflow uses the resolved spec file for same-spec benchmark and
   perfgate comparison.
5. PR preview results stay separate from formal main benchmark results.
6. Aggregation and website display use only eligible formal benchmark data.

In other words, workflow code should move from a single default:

```text
PERFGATE_SPEC_FILE=docs/official-baselines/perfgate-ascend-qwen25-3b-910b2.json
```

to scenario-aware selection:

```text
scenario=random-online, chip=910B2 -> docs/official-baselines/perfgate-ascend-qwen25-3b-910b2.json
scenario=sharegpt-online, chip=910B2 -> docs/official-baselines/perfgate-ascend-sharegpt-online-qwen25-3b-910b2.json
```

Exact file names can change, but the naming must remain stable and should
include scenario, model family, model size, and hardware chip.

## Repository Scope

### vllm-hust-benchmark

Responsibilities:

- Own official same-spec and perfgate spec files.
- Add one spec per scenario and hardware target.
- Store or expose baseline data used by comparison jobs.
- Keep spec naming consistent and reviewable.

Expected changes per new scenario:

- add same-spec definition
- add perfgate definition
- add constraints file if the scenario needs special tolerances
- update tests or validation scripts for spec discoverability

### vllm-hust

Responsibilities:

- Run performance gate for the vLLM-HUST engine.
- Select the correct spec for the requested scenario.
- Keep PR preview behavior separate from formal main benchmark behavior.
- Publish only eligible formal data to downstream aggregation.

Expected changes per new scenario:

- workflow scenario selection
- spec resolver or registry update
- static tests for workflow wiring
- optional report-mode rollout before blocking mode

### vllm-ascend-hust

Responsibilities:

- Align the Ascend plugin benchmark gate with `vllm-hust`.
- Use the same scenario and chip selection model.
- Keep B2/B3 hardware naming consistent with the actual runner.

Expected changes per new scenario:

- workflow scenario selection
- spec resolver or registry update
- static tests for workflow wiring
- runner-specific defaults if required

### vllm-hust-website

Responsibilities:

- Aggregate and display formal benchmark data.
- Avoid mixing PR preview data into formal leaderboard results.
- Display multiple scenarios clearly.

Expected changes only if needed:

- aggregation filters
- scenario labels
- leaderboard/table display updates

## Rollout Strategy

Roll out one scenario at a time.

### Phase 0: Stabilize random-online

Status: in progress / mostly done.

Tasks:

- Ensure both `vllm-hust` and `vllm-ascend-hust` default to B2 specs for the
  current 910B2 self-hosted runner.
- Confirm `random-online` reruns successfully after B2 default fixes.
- Confirm PR preview results do not pollute formal main benchmark aggregation.

Exit criteria:

- PR gate can run with the B2 spec.
- Main benchmark can store baseline data.
- Website aggregation does not include new PR preview data as formal data.

### Phase 1: Add sharegpt-online in report mode

Status: planned.

Tasks:

- Add `sharegpt-online` specs in `vllm-hust-benchmark`.
- Add resolver entries in `vllm-hust`.
- Add resolver entries in `vllm-ascend-hust`.
- Run the scenario in report mode first.
- Compare runtime, stability, variance, and failure modes.

Exit criteria:

- Both repos can run `sharegpt-online` using the same scenario-aware mechanism.
- Results are available for review.
- No blocking gate is enabled until the baseline is considered stable.

### Phase 2: Make sharegpt-online eligible for gating

Status: planned.

Tasks:

- Tune thresholds and constraints based on observed data.
- Decide whether the scenario should block PRs or stay report-only.
- Ensure failure messages clearly show scenario, spec, baseline, and candidate
  metrics.

Exit criteria:

- The team agrees the data is stable enough for the chosen gate mode.
- The workflow failure mode is actionable.

### Phase 3: Repeat for additional scenarios

Status: planned.

Candidate scenarios should be selected based on product value, runtime cost,
and stability. Each scenario should follow the same pattern as
`sharegpt-online`.

## Spec Selection Requirements

The resolver should support:

- scenario name
- hardware chip model
- optional model family or model size
- repository-specific defaults
- explicit override through GitHub repository variables or workflow inputs

The resolver should fail clearly when no spec exists:

```text
No perfgate spec registered for scenario=<scenario>, hardware_chip_model=<chip>.
```

The resolver should not silently fall back to a different scenario. Fallback
from B3 to B2 or from one scenario to another can hide real data mismatches.

## Data Separation Requirements

PR preview and formal main benchmark data have different meanings.

PR preview data:

- validates a candidate change
- can be used for comments and gate decisions
- should not be treated as formal leaderboard data

Main benchmark data:

- represents merged code
- can update baselines or website-visible benchmark history
- can be aggregated for public display

Aggregation should filter by data source, event type, branch/ref, and publish
intent so PR preview data does not appear as formal benchmark data.

## Validation Plan

For each scenario PR, include:

- static workflow tests
- shell syntax checks for workflow scripts
- spec file validation
- one dry-run or report-mode workflow run when hardware is available
- benchmark result inspection for scenario, model, hardware, source, and metric
  fields

Suggested commands vary by repository, but common checks include:

```bash
python3 -m py_compile <changed-python-files>
bash -n <changed-shell-scripts>
git diff --check
```

When pytest cannot run locally because hardware or heavyweight dependencies are
missing, the PR must state that explicitly and rely on CI or workflow reruns.

## Risk Register

| Risk | Impact | Mitigation |
| --- | --- | --- |
| Spec file missing on `vllm-hust-benchmark@main` | Gate fails before benchmark starts | Add benchmark spec PR first, verify file exists on main before workflow PR |
| Hardware chip mismatch, for example B2 runner using B3 spec | Invalid comparison or file-not-found failure | Resolve spec by chip and assert defaults in tests |
| PR preview data enters website aggregation | Misleading leaderboard results | Keep publish flags and aggregation filters strict |
| New scenario is too slow for PR gating | Developer feedback becomes slow | Start in report mode and only gate selected scenarios |
| Baseline variance is high | Flaky gates | Observe first, tune thresholds, and gate only after stable |
| Cross-repo PRs merge in wrong order | CI failures | Use issue checklist and link dependent PRs |

## Tracking Checklist

- [ ] Create cross-repo tracking issue in `vllm-hust-dev-hub`.
- [ ] Link this document from the tracking issue.
- [ ] Link every scenario rollout PR back to the tracking issue.
- [ ] Confirm B2 default fixes are merged in `vllm-hust`.
- [ ] Confirm B2 default fixes are merged in `vllm-ascend-hust`.
- [ ] Confirm `random-online` runs successfully after B2 fixes.
- [ ] Add `sharegpt-online` specs in `vllm-hust-benchmark`.
- [ ] Add `sharegpt-online` resolver support in `vllm-hust`.
- [ ] Add `sharegpt-online` resolver support in `vllm-ascend-hust`.
- [ ] Run `sharegpt-online` in report mode.
- [ ] Decide whether `sharegpt-online` should become blocking.
- [ ] Select the next scenario.

## Suggested Tracking Issue Template

```markdown
## Goal

Extend vLLM-HUST performance gate coverage from `random-online` to more
benchmark scenarios through incremental, observable rollout.

## Current Status

- random-online: active
- sharegpt-online: next
- other scenarios: pending

## Plan

- [ ] Stabilize B2 defaults for current 910B2 runner
- [ ] Add sharegpt-online specs in vllm-hust-benchmark
- [ ] Wire sharegpt-online in vllm-hust
- [ ] Wire sharegpt-online in vllm-ascend-hust
- [ ] Run sharegpt-online in report mode
- [ ] Decide whether sharegpt-online should block PRs
- [ ] Repeat for the next scenario

## Related PRs

- vllm-hust-benchmark: TBD
- vllm-hust: TBD
- vllm-ascend-hust: TBD
- vllm-hust-website: TBD

## Decisions

- Roll out one scenario at a time.
- Use scenario + hardware chip to resolve perfgate specs.
- Keep PR preview data separate from formal main benchmark data.

## Reference

- Development document: `docs/perfgate-scenario-rollout.md`
```

## New Conversation Handoff

When continuing this work in a new conversation, start with:

```text
继续多场景性能门禁接入。
进度 issue: <issue-url>
开发文档: docs/perfgate-scenario-rollout.md
请先读取 issue 和文档，然后继续下一步。
```
