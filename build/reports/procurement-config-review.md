# Procurement / retirement config review

Date: 2026-09-16

Scope: read-only review of the Task 1 diff against `HEAD`, with the binding business rules in `procurement-task-1-brief.md` as authority. Focused tests currently pass (`52 passed`).

## Findings

### P1 — Child retirement at the installed home site is not validated when the parent corrective method is `REPLACE`

`compile_service()` derives retirement contexts for children from the parent's ordinary corrective method. For a `REPLACE` parent it adds only the parent's repair destination. That is a fault-repair context, but it is not the only retirement context: an installed child accumulates lifetime operating hours while its parent remains installed, and on reaching its limit after a flight it must be removed/replaced at the equipment home site before the next mission. The retirement runtime review confirms that this path replaces the child directly at home. A stocked/repaired parent can likewise carry a child with retained lifetime state; installing that parent does not change the required home replacement context.

The compiler therefore accepts a model with a child lifetime limit, a parent `REPLACE` rule, and a retirement-capable child rule only at the depot, even though runtime can require `POWER/BOARD@BASE` and has no definition for it.

Reproduction (using existing test fixtures):

```python
from tests.test_m3_config import nested_pending_pm_tables
from simlab.compiler import compile_model

t = nested_pending_pm_tables()
t["SimLabItemPreventive"] = []
t["SimLabMaintenanceRule"] = [r for r in t["SimLabMaintenanceRule"] if r["KIND"] == "CORRECTIVE"]
t["SimLabMaintenanceStep"] = [
    r for r in t["SimLabMaintenanceStep"]
    if r["RULEID"] in {"PARENT-CM", "CHILD-CM-D"}
]
t["SimLabItemRetirement"] = [{"IID": "BOARD", "LIMIT_H": "5", "LIMIT_REPAIRS": ""}]
for step in ("REMOVE", "INSTALL"):
    t["SimLabMaintenanceStep"].append({
        "RULEID": "CHILD-CM-D", "STEP": step,
        "DURATION_H": "1", "TASK": "SERVICE",
    })

compile_model(t)  # accepted, despite no POWER/BOARD@BASE replacement context
```

Expected: reject with a missing retirement replacement context for `POWER/BOARD@BASE`. The depot context may still be required for repair-count retirement reached by actual corrective work there, but it cannot replace the installed-home context.

### P2 — All explicit corrective rules for a retirement IID are forced to carry replacement steps, including unreachable contexts

The first retirement loop checks every explicit `CORRECTIVE` rule whose IID has a lifetime limit and requires `REMOVE`, `INSTALL`, and `TEST`. This runs before and independently of the later actual-context traversal. An otherwise valid, unused rule at a station no deployed or stocked physical item can reach is rejected solely because retirement is enabled for that IID.

This conflicts with the task's context-based requirement and can break compatibility when an existing project contains documentary/future-site maintenance rules that are not executable in the current deployment. Only actual retirement contexts should require a replacement definition and its required steps.

Reproduction:

```python
from tests.test_m3_config import one_leaf_new_service_tables
from simlab.compiler import compile_model

t = one_leaf_new_service_tables()
t["SimLabItemRetirement"] = [{"IID": "POWER", "LIMIT_H": "100", "LIMIT_REPAIRS": ""}]
t["ResourceAllocation"].append({
    "POINT": "BASELINE", "RID": "TECH", "STID": "REGIONAL", "RQTY": "1",
})
t["SimLabMaintenanceRule"].append({
    "RULEID": "UNUSED", "MID": "VEHICLE", "IID": "POWER",
    "STID": "REGIONAL", "KIND": "CORRECTIVE", "METHOD": "IN_PLACE",
})
t["SimLabMaintenanceStep"].extend([
    {"RULEID": "UNUSED", "STEP": "IN_PLACE", "DURATION_H": "1", "TASK": "SERVICE"},
    {"RULEID": "UNUSED", "STEP": "TEST", "DURATION_H": "1", "TASK": "TEST"},
])

compile_model(t)  # rejected: UNUSED is said to lack INSTALL and REMOVE
```

Expected: accept unless `VEHICLE/POWER@REGIONAL` is an actual retirement context. If it is actual, validate the selected explicit rule's retirement steps at that point.

## Checks with no defect found

- Invalid and non-finite numeric values are rejected by generic schema validation before `int(float(...))` conversions; negative `FIRST_H` and `LEAD_H` are also rejected through the effective schema constraints.
- Procurement threshold/periodic unused fields, target ordering, minimum interval, and the 200,000 scheduled-order cap are covered and passed focused tests.
- Persistence upgrades old extension versions through 11 and rejects version 12; the new canonical tables are empty for old projects. No direct old-model execution behavior is changed by these config files when the tables are absent.
- Procurement correctly has no inbound-route requirement and its configured stock sites participate in calendar preventive-service reachability.

## Verification

```text
.venv\Scripts\python.exe -m pytest tests/test_procurement_config.py tests/test_m3_config.py -q
52 passed in 0.47s
```

`git diff --check` reported no whitespace errors (only the repository's existing line-ending warnings).

## Fix re-review

Date: 2026-09-16

Both findings above are closed in the current `service_config.py` diff.

- Child retirement contexts now always include the deployed home site, while still including the parent's repair destination when ordinary parent correction can move the attached child there. The new regression rejects the formerly accepted `POWER/BOARD@BASE` omission.
- Required retirement steps are now checked only after an actual retirement context selects its explicit corrective rule. An unreachable extra rule no longer causes a model error; the new compatibility regression passes.

### Stocked parent assemblies

No additional arbitrary stock-site replacement context is required under the current physical-state contract:

- Initial stock and externally purchased parent assemblies create their children with zero lifetime hours and zero corrective repairs.
- Stocked trees do not accumulate operating hours.
- A child reaching its hour limit does so while installed, so replacement occurs at the deployed home site now covered by validation.
- A child reaching its repair-count limit does so synchronously at corrective repair completion, before the repaired tree is returned to stock, so the actual service site is already the applicable context.
- `eligible()` rejects any tree containing a reached or pending retirement limit, preventing that tree from being issued or transferred as usable stock.

Consequently `_reachable_stock_sites(parent, ...)` should not be added wholesale to retirement replacement validation. Doing so would recreate the closed compatibility problem by demanding executable replacement rules at stations where no lifetime-limit transition can occur. If a future feature permits non-new initial stock lifetime/count state or accrues lifetime while in stock, this conclusion must be revisited.

### Re-verification

```text
.venv\Scripts\python.exe -m pytest tests/test_procurement_config.py tests/test_m3_config.py tests/test_procurement_supply.py -q
67 passed in 0.56s
```

This independently exercises the two config regressions plus procurement supply tests. The root integration checkpoint reports 92 focused combined tests passing after its additional retirement-runtime set. No actionable configuration defect remains in the reviewed fix scope.
