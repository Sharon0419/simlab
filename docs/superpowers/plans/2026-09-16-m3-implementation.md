# M3 Supply and Maintenance Implementation Plan

> **For agentic workers:** Use subagent-driven-development and test-driven-development for independent modules, then integrate and review. Parallel implementation is restricted to disjoint file ownership; shared interfaces below are binding.

**Goal:** Deliver the approved M3 supply and maintenance design as working Chinese desktop software, preserving old scenarios.

**Architecture:** Explicit MODE=M3 branches from legacy compilation/runtime. A single SupplyNetwork owns stock and demand allocation; a maintenance coordinator owns service jobs and physical preventive clocks. Existing physical parts, resources, mission managers, persistence and Qt tables are reused.

**Tech Stack:** Python 3.10, SimPy, NumPy, PySide6, SQLite, pytest, PyInstaller.

**Spec:** ../specs/2026-09-16-m3-supply-maintenance-design.md; user approved design and implementation on 2026-09-16.

## Global constraints

- Old models must keep old execution and random sequences. No silent field ignoring or feature claims.
- Routes explicit; shortest available supplier first; split permitted; pending orders persistent; no transport capacity.
- IP=available+unreceived orders-unmet demand; one upstream sponsorship per pending quantity; no duplicate requests.
- Corrective and preventive separate mode probabilities and steps. Pick once; lack of spare does not reroll.
- Preventive service resets actual leaf effective age only, preserving lifetime; normal inspections unchanged.
- Components are physical identities, assemblies retain healthy siblings, transport and stock cannot duplicate identities.
- No editing original schema dictionary; version10 reads legacy1–9, old reader rejects10.
- Design D1–D9 approved. The entire requested deliverable includes supply AND maintenance, tests, UI, examples and installed executable.

## File ownership and interfaces

Task1 owns extensions.py, schema.py, compiler.py, project.py, supply_config.py, service_config.py, tests/test_m3_config.py. Task2 owns supply.py, supply_ledger.py, tests/test_m3_supply.py. Task3 owns engine.py, maintenance.py, components.py, aging_components.py, flight.py, service.py, preventive.py, m3_engine.py (if necessary), tests/test_m3_service.py. Task4 owns UI/result/demo/smoke/release files. Avoid changing another task's files; coordinate additive contracts in messages.

Compiler contract: returned legacy config retains existing keys, and new mode adds `config['m3']={'tables': canonical_tables}`. Canonical tables include all defaults via schema.value/defaults, using original uppercase field names. Runtime modules may normalize locally; compiler validates all supported M3 contexts. `config['stock']` remains (station,iid)→integer and `config['children']` keeps existing structure. In M3 the legacy required-root checks are bypassed in favor of explicit service checks. Supply-only M3-A may use legacy repairs with explicit repair-location mapping; M3-B selects new rules when supplied, forbidding ambiguous overlaps.

Supply contract: `SupplyNetwork(env, components, config, stores=None, log=None)` uses config.m3.tables and config.stock. If stores supplied, use the existing physical stores without reseeding; otherwise seed initial stock through Components.create. `.stores` exposes stores for validation/read compatibility, not writes. `.start()` starts initial threshold and periodic evaluation once. `.request_part(station,iid,owner='')` returns SimPy Event yielding part ID, marking it held. `.return_part(station,part)` synchronously enters usable stock and wakes allocation. `.withdraw(part)` removes a stock token for quarantine; `.available(station,iid)` returns available IDs; `.snapshot()` JSON-safe; `.validate()` asserts physical/order conservation. Add eligibility callback / stock notifications by coordinating Task2/3 explicitly.

Result contract: each replication adds `supply` and `service` dicts, containing lists `orders`, `shipments`, `stocks`, `jobs`, `clocks` as appropriate and named totals/truncation flags. Existing `replication_results` includes these snapshots. UI will render available keys without changing physical state. Task3 supplies final column contract before Task4 wiring.

## Task 1: Inputs and compilation

- [ ] Write behavioral tests using demo_project: M3 triples allowed only with explicit mode; illegal route and duplicate policy rejected; legacy scenario still compiles; probabilities/resources/preventive fields reject invalid values; v10 package roundtrip.
- [ ] Run `.venv/Scripts/python.exe -m pytest tests/test_m3_config.py -q`, observe missing-feature failures.
- [ ] Implement the spec tables/Chinese metadata and strict compiler, including mode-aware repair validation and feasible resource/shift checks.
- [ ] Run focused tests plus test_core/test_modeling_chinese/test_project_library; record evidence and report any integration assumptions.

## Task 2: Supply ledger and runtime

- [ ] Encode S1–S10 as deterministic SimPy tests. Example: order6 with b stock2/2h and a stock10/5h must yield two arrivals (2,2) and (5,4), not six duplicates.
- [ ] Run `.venv/Scripts/python.exe -m pytest tests/test_m3_supply.py -q` before implementation.
- [ ] Implement single-writer ledger, shortest allocation, sponsorship, periodic/threshold, simultaneous receipts, finite-horizon snapshots, explicit caps, physical validation.
- [ ] Re-run focused tests; inspect full ledger conservation, including alternate-supplier arrival after sponsored parent replenishment.

## Task 3: Maintenance runtime and engine integration

- [ ] Write M1–M10 behavioral tests first, including direct leaf, parent+SRU, flight and continuous models; run to observe failures.
- [ ] Implement mode-gated engine path, supply wiring, independent mode RNG, onsite/offsite jobs, nested locks, leaf preventive clocks, CALENDAR quarantine and corrective coverage.
- [ ] Preserve legacy entry behavior and aggregate M3 snapshots across repetitions. Verify no-infinite-failure returns for FRT=0 preventive scenarios.
- [ ] Run `.venv/Scripts/python.exe -m pytest tests/test_m3_service.py tests/test_aging.py tests/test_maintenance.py tests/test_flight.py -q`.

## Task 4: UI, exchange, examples and integration acceptance

- [ ] Add Chinese M3 result tables and all-replication CSV with model/version/seed IDs; add a three-level demonstrator covering supply and both repair kinds.
- [ ] Test CSV values, package roundtrip, worker execution and visible tables; extend desktop smoke without weakening prior checks.
- [ ] Run full pytest and source smoke; correct issues with focused regression before rerunning relevant checks.
- [ ] Generate deterministic scenario report and 1000-repetition case, validate physical/order/time conservation and saved-result replay.

## Task 5: Review, build and install

- [ ] Independent review of actual diff versus approved design; fix important correctness/spec issues and add regression evidence.
- [ ] Build via tools/build_windows.ps1 into isolated output, run packaged smoke and compare source/EXE sample results.
- [ ] Preserve installed release as named backup, update original dist/SimLab without touching project databases; verify installed smoke and ZIP CRC.
- [ ] Update verification, feature guide, roadmap and Obsidian with actual results and any remaining limitations. Commit/push reviewed changes and verify remote hash.

## Interface conflict preflight

| Pair | Shared contract | Resolution |
|---|---|---|
| 1/2/3 | config.m3 | canonical raw uppercase rows with defaults, normalized locally |
| 2/3 | stock ownership | supply is sole writer, no direct Store writes in M3 |
| 3/4 | result lists | named supply/service snapshots, no UI callbacks into engine |
| 1/4 | Chinese labels | Task1 metadata, Task4 only result labels and enum display extras if needed |

## Progress ledger

- Baseline ada3f00: clean isolated worktree build/m3-worktree, branch codex/m3-supply-maintenance. Existing218 tests passed.
- Ruling: reuse installed .venv through a junction in isolated worktree; original source/installed package untouched during implementation — avoids redundant dependency downloads — wrong-path risk controlled by explicit workdir in every command.
