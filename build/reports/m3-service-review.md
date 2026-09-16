# Independent M3 service review

Date: 2026-09-16. Reviewed commit `bcb97c258f42b2ebcc99eba6a48eae1efb13f580` against the approved M3 supply/maintenance design and `m3-service.md`. Scope: service/clock/engine code plus legacy integration diff. Read-only review and standalone probes; no implementation or test source modified.

## Verdict

Changes required: one reproduced P2 scheduling defect. No additional supported P1/P2 finding in the requested parent/child locking, method pick-once, preventive renewal, or legacy branch behavior. The known destination compatibility compiler gap is excluded because another owner is addressing it.

## P2: Batch simultaneous component-PM registrations before starting the first job

Locations: `simlab/m3_engine.py:72–73` and `simlab/service.py:107`; ordering contract at `simlab/service.py:110–112`.

`Exposure.due()` iterates clocks in physical insertion order, calling `service.preventive()` one at a time. Each call immediately invokes `advance()`, marking the first PM job `starting` and acquiring the parent-tree/aircraft lock before the remaining same-time jobs exist. Consequently the later priority sort cannot enforce the approved `(due time, type, rule ID)` ordering for simultaneously due leaves. The result depends on MaterielStructure/physical creation order despite identical due times and configured priorities.

Confirmed with a **compile_model-accepted** M3 model: one aircraft, installed POWER assembly, two healthy child leaves S1 then S2, no failure rate or stock, both CALENDAR interval2/initial0. S1's rule ID is Z_BASE_PREVENTIVE; S2's is A_BASE_PREVENTIVE. Both use IN_PLACE2h and TEST1h. Horizon7.

- Actual: Z_BASE_PREVENTIVE due2/start2/end5; A_BASE_PREVENTIVE due2/start5/unfinished.
- Required by spec §6.3: A_BASE_PREVENTIVE should start2 and finish5, followed by Z_BASE_PREVENTIVE. Both are component PM with equal due time, so rule ID must break the tie.
- The normal suite passes, confirming this is an uncovered simultaneous-registration boundary rather than an existing test failure.

Suggested fix: register all due component jobs and stock quarantines without launching work, then arbitrate once across the complete set; retain synchronous no-dispatch guarantees before flight launches. Add a reversed-structure-order regression and assert order by rule ID, without weakening corrective-first or planned/flight-inspection priority.

### Standalone reproduction (run from worktree)

```python
from simlab.m3_sample import m3_project
from simlab.compiler import compile_model
from simlab.engine import run_one

t = m3_project(1)['tables']
for key in ['MissionType', 'MissionSystem', 'Operations', 'OperationProfile', 'SimLabFlightRule']:
    t.pop(key, None)
t['Control'][0].update(SIMPE='7', RCINT='1')
t['SystemDeployment'][0]['QTYPS'] = '1'
t['Item'][0]['FRT'] = '0'
t['StockAllocation'] = []
t['SimLabMaintenanceRule'] = [r for r in t['SimLabMaintenanceRule'] if r['KIND'] == 'CORRECTIVE']
t['SimLabMaintenanceStep'] = [r for r in t['SimLabMaintenanceStep'] if r['RULEID'] == 'POWER_CORRECTIVE']
t['SimLabOffItemService'] = [r for r in t['SimLabOffItemService'] if r['KIND'] == 'CORRECTIVE' and r['STEP'] != 'SERVICE']
t['SimLabItemPreventive'] = []
for iid, prefix in [('S1', 'Z'), ('S2', 'A')]:
    t['Item'].append(dict(IID=iid, TYPE='SRU', FRT='0'))
    t['MaterielStructure'].append(dict(MID=iid, MMID='POWER', QTYPM='1'))
    t['SimLabItemPreventive'].append(dict(PMID=iid, IID=iid, CLOCK='CALENDAR', INTERVAL_H='2', INITIAL_H='0'))
    for station in ['BASE', 'REGION', 'CENTER']:
        for kind in ['CORRECTIVE', 'PREVENTIVE']:
            rid = f'{prefix}_{station}_{kind}'
            t['SimLabMaintenanceRule'].append(dict(RULEID=rid, MID='POWER', IID=iid, STID=station, KIND=kind, METHOD='IN_PLACE'))
            for step, hours in [('IN_PLACE', '2'), ('TEST', '1')]:
                t['SimLabMaintenanceStep'].append(dict(RULEID=rid, STEP=step, DURATION_H=hours, DISTRIBUTION='FIXED', TASK=''))
result = run_one(compile_model(t))
print([(j['rule'], j['due_at'], j['started_at'], j['ended_at']) for j in result['service']['jobs']])
```

## Verification and non-findings

Independently reran `.venv/Scripts/python.exe -m pytest tests/test_m3_service.py tests/test_aging.py tests/test_maintenance.py tests/test_flight.py -q`: **80 passed in 0.90s**.

Inspected leaf explicit renewal versus parent restore, child detach/attach and inherited locks, off-item asynchronous repair, method endpoints/single stored decision, calendar stock/transit/held quarantine, operating exposure through failure return, unfinished horizon state, and mode gating of legacy RNG/runtime. Existing regression evidence and implementation support these paths; no unsupported claim of exhaustive correctness is made. No packaging/install or cross-platform review in this bounded task.

## Finding resolution — 2026-09-16

The reproduced P2 is fixed. `Exposure.due()` registers the complete same-time leaf set inside `ServiceCoordinator.registration_batch()`. All calls to `advance()`, including synchronous `on_stock` callbacks, defer lock acquisition until the outermost registration completes. Quarantine and due flags remain synchronous; no simulator yield or dispatch gap is introduced. Existing queued jobs still compete using the same corrective/due/type/rule ordering, and already active tree locks remain non-preemptive.

Regression `test_simultaneous_leaf_preventive_jobs_arbitrate_by_rule_not_structure_order` covers both structure orders and both installed-only/installed-plus-stock-parent cases (four parameter combinations). RED: two Z-before-A structure cases reproduced Z start2, A start5. GREEN: all four cases give A due2/start2/end5 followed by Z due2/start5/unfinished-at7, independently within each physical parent tree.

Verification after the fix:

- `pytest tests/test_m3_service.py tests/test_aging.py tests/test_maintenance.py tests/test_flight.py tests/test_m3_supply.py -q`: **109 passed**.
- Whole-suite concurrent checkpoint: **312 passed,5 failed**. The five failures are newly added, in-progress configuration validation tests owned by the configuration agent (negative threshold, initial-clock bound, stock-calendar context, corrective coverage, relocated PM method compatibility). No service or legacy regression failed.

This resolves the review finding; final integration/release verification remains with the root task.
