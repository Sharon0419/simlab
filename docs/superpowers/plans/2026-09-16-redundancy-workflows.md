# Redundancy and Support Workflows Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans. Execute tasks continuously; user approved the design and development on 2026-09-16.

**Goal:** Deliver both approved P0 capabilities with legacy compatibility and desktop release evidence.

**Architecture:** Recursive group capability separate from fault/maintenance state. A shared DAG executor acquires each node's resources atomically and integrates through activity-specific adapters without duplicating physical transitions.

**Tech Stack:** Python, SimPy, NumPy, PySide6, SQLite, pytest, PyInstaller.

Spec: `docs/superpowers/specs/2026-09-16-redundancy-support-workflows-design.md` (approved).
Global constraints: original dictionary unchanged; no mixed formations; no standby; no activity preemption; existing models retain trajectories. Necessary fixes are in scope. Existing feature checkout is clean; work on this feature branch and preserve old installed binaries.

## Task 1: Redundancy config and runtime

Files: create `simlab/redundancy.py`, `tests/test_redundancy.py`; modify `simlab/extensions.py`, `compiler.py`, `hierarchy.py`, `components.py`, `aging_components.py`, `engine.py`, `m3_engine.py`, `service.py`, mission integration as necessary.

- [x] Add failing boundary tests using existing sample projects: 3 healthy of 3 with k=2 succeeds, second fault stops capability; SRU 2取1 propagates only on second fault; mixed types all required; separate physical parent instances do not share counts.
- [x] Run `.venv/Scripts/python.exe -m pytest tests/test_redundancy.py -q`, observe failure before implementation.
- [x] Add `SimLabRedundancy` fields `PARENT`, `IID`, `K`; n resolves from structure, integer 1..n, absent k=n. Compile `config['redundancy']` keyed by `(parent,iid)`.
- [x] Implement recursive capability independent of pending repairs; expose `capable(parts, token, rules)` and `asset_capable(parts, asset, rules)` and count summaries. Parent's derived broken flag must not mask healthy redundant children, actual leaf faults must remain repairable.
- [x] Active task with capability retains mission; below threshold uses existing failure return semantics. Every physical fault queues repair, and all queued/active repairs block new departures. Only functioning installed branches accrue exposure. Legacy and M3 must consume config or explicitly use a tested compatibility path, never ignore it.
- [x] Regression tests for mission continuation, second failure return, deferred maintenance, root repairs, same instant boundaries, PM/retirement, unchanged unconfigured models. Run targeted tests then full pytest. Commit implementation, report evidence.

Boundary assertion shape:
```python
assert asset_capable(parts, asset, rules)
parts.fail(root, first_leaf)
assert asset_capable(parts, asset, rules)
parts.fail(root, second_leaf)
assert not asset_capable(parts, asset, rules)
```

## Task 2: Workflow compiler and common executor

Files: create `simlab/workflows.py`, `simlab/workflow_config.py`, `tests/test_workflows.py`; modify extensions/compiler.

- [x] Define extension tables `SimLabWorkflow`, `SimLabWorkflowStep`, `SimLabWorkflowBinding`: scheme ID; per-node ID/action/duration/distribution/task/predecessors; activity kind and existing rule binding (plus method/station/item for service).
- [x] Fail tests on cycle, self-edge, dangling edge, malformed durations, resource capacity, duplicate binding and missing/misordered required actions. Derive successors rather than store twice.
- [x] Compile normalized plans, retaining stable input order. Per node: `id,name,action,duration,random,resources,predecessors`. Plans immutable per run; instances hold mutable states.
- [x] Build SimPy executor with node completion events; acquire all resources via ResourcePool only after all dependencies and pre-action prerequisites; release on completion. Existing resource shift grants enforce start windows; work never pauses mid-node. Callback hooks before/after action integrate physical semantics; normal CUSTOM no physical changes.
- [x] Snapshot includes dependency-ready/start/end/status, dependency/shift/resource/prerequisite waits; cutoff leaves running nodes unfinished. Deterministic seeded sampling, zero duration settles before departure decisions. Safety bound for runaway result records.
- [x] Verify analytic DAG: A=1 then B=2 and C=3 parallel then D=1 => 5h; shared single resource B/C =>7h. Verify release, shift crossing, cutoff and invalid graph tests. Commit and review.

Example accepted graph:
```python
nodes = [('A', 1, []), ('B', 2, ['A']), ('C', 3, ['A']), ('D', 1, ['B','C'])]
# unlimited resources: D ends at 5, activity duration != sum(1,2,3,1)
```

## Task 3: Workflow activity adapters

Files: create `simlab/service_workflows.py`; modify `service.py`, `ground.py`, `planned.py`, `flight.py`, `engine.py`, `m3_engine.py`, `service_config.py`; tests `tests/test_workflow_activities.py`.

- [x] Add integration failure tests for repair IN_PLACE/REPLACE/OFF_ITEM, PREPARATION, CALENDAR, INSPECTION and retirement replacement.
- [x] Instantiate one executor per replication; route bound activities to it while unbound activities retain old paths/RNG draws.
- [x] Repair adapter preserves single method draw, destination routing, child repair, detach/dispose exactly once, off-item launch after removal, spare eligibility recheck, installation/test and actual repair counters. Wait for spare before INSTALL resource request. Handle overdue spare replacement without deadlock.
- [x] Ground/check adapters own complete activity lifetime, mutual exclusion per aircraft, priority/nonpreemption, planned inspections reset once, post-check preparation, DAILY_READY semantics.
- [x] Verify same-aircraft serial activities and internal DAG parallelism; detached item can repair after aircraft returns to task. Test cutoff/resource conservation and combined redundancy scenario. Commit and review.

## Task 4: Desktop, persistence, results and sample

Files: `simlab/ui/modeling_labels.py`, `modeling.py`, `structure.py`, `window.py`, `m3_results.py`, `simlab/m3_results.py`, `flight_results.py`, sample/smoke files, `tests/test_modeling_chinese.py`, `tests/test_workflow_results.py`.

- [x] Bump extension format to 12 once for combined release; old 1..11 readable, old code refuses 12. Register all new tables/Chinese field labels, dropdowns and reference validation.
- [x] Show k beside structure n and workflow editing via tables. Show derived successors without duplicate editable source; keep help on demand.
- [x] Add workflow result tabs and all-rep CSV rows; count/timing aggregation uses activity elapsed not sum of parallel work. Add group count fault evidence.
- [x] Add demonstrable 3取2 plus two-level redundancy and branched workflow sample via new-project action; tests require actual workflow execution, not merely populated inputs.
- [x] Verify project save/load/export/import, all activities, source desktop smoke screenshots and old models. Commit.

## Task 5: Release verification and delivery

Files: version files, `docs/V0.12.md`, `docs/VERIFICATION.md`, roadmap, `tools/verify_v012_release.py`, release cases and launcher.

- [x] Run `.venv/Scripts/python.exe -m pytest -q` and targeted analytic/integration scenarios. Review all changes since 8bc3e6b; fix confirmed issues and rerun relevant checks.
- [x] Run source desktop smoke with QT_QPA_PLATFORM=offscreen and QT_SCALE_FACTOR=1; inspect screenshots.
- [x] Build via `tools/build_windows.ps1` into isolated staging, run EXE smoke and compare deterministic new/old cases, package via existing release tool.
- [x] Install side-by-side v0.12.0, update launcher, verify installed file hashes and executable smoke. Preserve user project library.
- [ ] Document measured counts and limits, commit and push approved feature branch; verify remote hash. Update Obsidian progress and report completed artifacts without claiming unrun checks.
