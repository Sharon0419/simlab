# M3 configuration independent review

Date: 2026-09-16. Reviewed commit `41d77973070502e9d8174680e039497d35717af4`, its report, approved M3 design, and configuration callers. Implementation remained unchanged. Existing test suite was not rerun; concrete standalone compile/runtime probes below were executed.

## Verdict

**Changes required: four P2 findings.** Explicit no-M3 gating, preserved legacy compiler branch, three-level ancestry/direction checks, directed repair-path checks, probability/finite-number validation, required configured steps, and resource capacity/common-shift checks look consistent. No separate regression in the legacy branch was established. The important missing area is validation of every reachable service context, plus an incorrect preventive job-cap estimate.

All reproduction recipes below begin with `tables = runpy.run_path('tests/test_m3_config.py')['one_leaf_new_service_tables']()` and use `compile_model(tables)`. Runtime probes call `simlab.engine.run_one(config)` after successful compilation.

## P2 — Validate CALENDAR inventory service contexts, not only installed contexts

Location: `simlab/service_config.py:163–176`.

Only fleet-home installed parent/item contexts are enumerated. CALENDAR clocks also apply to initial stock, stock created by repairs, and items received through supply routes. Their repair-location mappings and PREVENTIVE off-item steps are never required unless a configured replacement rule happens to cover them. This lets a model pass compilation then fail during ordinary calendar expiry.

Executed repro: retain the fixture's CALENDAR interval100; set `Item[0].FRT='0'` and `Control[0]` to `SIMPE='101', RCINT='1'`. Compilation succeeds. At inventory expiry, `run_one` raises `ValueError: M3 缺少维修地点映射: POWER/DEPOT`. The fixture has POWER inventory at DEPOT but only BASE→DEPOT repair mapping and CORRECTIVE off-item service. Even where mapping exists, missing PREVENTIVE service steps are not rejected.

Design sections 4.2, 6.3, and 7 require all reachable service contexts and the explicit quarantine/service flow for CALENDAR stock/in-transit expiry. Enumerate reachable physical stock/assembly contexts, require applicable location/path/steps, and report a Chinese compile error before running. A valid regression must add the corresponding explicit services and demonstrate actual service rather than skipping missing steps.

## P2 — Restore mandatory corrective coverage after bypassing the legacy checks

Locations: `simlab/compiler.py:222–237` and `simlab/service_config.py:179–210`.

M3 bypasses all existing required-repair/replacement checks. The new validator checks rules that exist and conflicts between rules, but does not require either new or compatible legacy corrective behavior for every deployed/recursive repair context. Entire corrective rules can be deleted and compilation still succeeds.

Executed repro: remove the fixture's `POWER-CM` MaintenanceRule and its MaintenanceStep rows; leave the valid PREVENTIVE rule. Set `Item[0].FRT='1000000'`, `Control[0].SIMPE='2'`, `RCINT='1'`. Compilation succeeds, then `run_one` raises `ValueError: M3 缺少修复规则: VEHICLE/POWER/BASE`. The same gap applies to leaf service rules required after a parent LRU is moved to a repair site.

Require coverage of reachable corrective contexts by an explicit new rule or a complete permitted legacy chain. Preserve legitimate zero-failure/no-corrective-use cases if that is the chosen documented rule; do not silently accept failure-enabled equipment with no executable corrective path.

## P2 — Do not count already-overdue INITIAL_H as repeated future service jobs

Location: `simlab/service_config.py:159`.

`int((initial + elapsed) // interval)` counts historical overdue periods as future work. The design explicitly registers one due event at t=0 when INITIAL_H exceeds the interval, permits only one unfinished job, and resets the period to zero after service. A large valid initial overrun therefore causes a false 200000-job rejection.

Executed repro: use fixture `CLOCK='OPERATING', INTERVAL_H='100', INITIAL_H='10000000'`; set `FRT='0'`, `SIMPE='2', RCINT='1'`. Compilation rejects with the 200000-service-job error. There are 20 installed items; they can generate only 20 initial due jobs and cannot reach a new 100-hour interval in the two-hour horizon. Stock OPERATING clocks do not advance. Count one initial due event plus future fresh intervals, retaining the documented overrun rather than treating it as a queue of past cycles.

## P2 — Enforce nonnegative REORDER_QTY

Locations: `simlab/extensions.py:89` (REORDER_QTY field) and `simlab/supply_config.py:108–115`.

The new Integer field has no nonnegative constraint; policy validation only compares target and threshold. The fixture with `SimLabSupplyPolicy[0].REORDER_QTY='-1'` compiles successfully. This violates the approved nonnegative quantity contract and can disable replenishment at empty inventory unexpectedly. Add explicit numeric range validation or the proper schema constraint, with a negative-value regression. TARGET_QTY already has a separate positive check.

## Evidence limits

The reviewed implementation report records 297 full-suite passes. This review does not dispute those executions; the above are additional uncovered cases. No files other than this review report were changed. A scoped review of the fixes should verify the probes above and distinguish valid zero-failure scenarios from reachable missing service paths.


## Scoped re-review — 19ce0e1 (2026-09-16)

**The four original config findings are closed.** Independent targeted command `pytest tests/test_m3_config.py -q -k 'threshold_cannot or large_preventive_initial or calendar_pm_stock or every_deployed or pending_minimal'` passed **5 tests, 31 deselected in 0.08s**. The negative threshold is rejected, one initially overdue period no longer becomes historical jobs, CALENDAR inventory mappings/PM off-item steps are required, and deployed/recursive corrective coverage is checked.

**Cross-site method compatibility remains incomplete (P2).** At `simlab/service_config.py` in the block gated by `minimal_items` and `child_corrective` (around lines322–341), only MINIMAL-repaired leaf scenarios require preservation of previously selected PM methods. A healthy sibling's queued PM is also moved with its replaced parent, and is not covered by another sibling's PERFECT corrective service. The configuration must validate that case as well.

Executed reproduction: start with `nested_pending_pm_tables()`, change BOARD aging REPAIR to PERFECT and BOARD MaterielStructure QTYPM to2. Compilation succeeds despite source `CHILD-PM-S=REPLACE` and destination `CHILD-PM-D=IN_PLACE`. Construct ServiceCoordinator from that compiled config, install a POWER with two BOARD leaves, and under an existing aircraft lock register due REPLACE PM for the healthy leaf and parent corrective REPLACE for failure of the other leaf. Release the lock and run. The parent and still-attached healthy leaf move to DEPOT; the faulty leaf completes PERFECT corrective work. The healthy leaf's pending PM then raises `ValueError: M3 已选维修方式 REPLACE 在新地点 DEPOT 缺少兼容规则`. This proves a compiler-accepted reachable failure, not a hypothetical malformed-runtime-state check. Root and config owner were informed. Validate possible surviving PM for all moved attached leaves, including healthy siblings; preserve already selected method without re-drawing.

## Final compatibility closure — 4cc935c (2026-09-16)

**PASS; the remaining healthy-sibling P2 is closed.** Independently reviewed the exact working-tree diff subsequently committed as `4cc935c`. Relocation coverage now checks both the original failed-leaf MINIMAL/in-place path and healthy siblings when the parent contains multiple physical leaves. The destination must implement every source method that could already have been selected. A single PERFECT-repaired leaf remains accepted because its pending PM is covered, avoiding a blanket false rejection.

Independent focused verification: `pytest tests/test_m3_config.py -q -k 'healthy_sibling or pending_minimal'` → **2 passed, 35 deselected in 0.05s**. The regression includes single-leaf PERFECT acceptance and two-leaf PERFECT rejection for the exact source-REPLACE/destination-IN_PLACE mismatch from the review probe. The earlier four findings remain closed. No outstanding actionable config finding from this review.
