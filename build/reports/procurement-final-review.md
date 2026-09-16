# Procurement / retirement final runtime review

Date: 2026-09-16

Scope: read-only review of the retirement runtime and its procurement/service interfaces against `HEAD`, using `docs/superpowers/plans/2026-09-16-procurement-retirement.md` as the binding business contract. Reviewed `retirement.py`, `service.py`, `m3_engine.py`, `preventive.py`, `aging_components.py`, relevant supply callbacks, validation contracts, and adversarial retirement tests.

## Result

No remaining correctness blocker was reproduced in the reviewed scope.

## Lifecycle conclusions

- Operating lifetime is accumulated once for every installed physical level. Leaf records already visited by hazard aging are excluded from the second tree walk, while parent assemblies and non-aging children receive the same utilization-weighted exposure.
- Flight expiry preserves the active flight. At a flight boundary, exposure is integrated and retirement is registered before mission ownership is cleared; service readiness blocks the retirement job while airborne, then removal starts after landing. Pending retirement also blocks selection for the next flight.
- Continuous and ordinary nonflight mission operation stops at the threshold. These tasks do not have the flight-only completion exception; changing asset state for retirement immediately causes the normal mission manager to release the assignment.
- Only `finish_leaf(..., CORRECTIVE)` increments `corrective_repairs`. Preventive completion, parent traversal, replacement steps, testing, and transport do not increment it. A detached leaf reaching its limit is disposed before `return_part()`.
- Parent retirement disposes the attached subtree without salvage. Parent-first creation order and the ancestor-pending guard prevent simultaneous parent/child expiry from producing duplicate retirement jobs.
- Retirement jobs force `REPLACE` while retaining the already configured corrective rule and its REMOVE/INSTALL/TEST resources. They do not draw the ordinary repair method and do not create an off-item repair for the retired identity.
- Queued work on the retiring subtree is cancelled, PM clocks are removed, and repeated `due()` calls are idempotent. The retirement priority and per-asset/tree locks serialize same-time failure, PM, and retirement work.
- Stock allocation calls `eligible()`, which rejects reached or pending limits anywhere in a physical tree. `on_stock()` withdraws and quarantines invalid trees; a detached parent is released only after its retiring child has been replaced. Purchased roots and descendants start with zero effective age, lifetime hours, and corrective counts.
- If replacement stock is unavailable, the retirement job remains in `waiting_spare`, the asset remains unavailable, and the removed identity remains accounted at `retired`; it cannot silently return to service.

## Verification

Independent combined focused run:

```text
.venv\Scripts\python.exe -m pytest tests/test_retirement.py tests/test_m3_service.py tests/test_procurement_supply.py tests/test_procurement_config.py tests/test_m3_config.py -q
107 passed in 0.97s
```

The 15 retirement tests exercise continuous and flight expiry, parent and child limits, actual Nth repair counting, perfect repair persistence, preventive exclusion, off-item disposal, parent quarantine release, simultaneous expiry/failure/PM ordering, expired-spare rejection, legacy replacement execution, and fresh purchased trees.

The implementer report records an earlier complete-suite checkpoint of 358 passes and normalized equality for four no-new-feature trajectories. Those results were inspected but not independently repeated in this review; root owns the final full-suite and packaged-runtime acceptance.

## Residual boundaries

- Runtime correctness relies on the compiler requiring every actual retirement context to provide corrective REMOVE/INSTALL/TEST steps or a legacy replacement definition. The separate config fix review verified that contract, including installed child home contexts.
- Initial loose and purchased stock is always new. If a future input format permits nonzero lifetime or repair counts for initial stock, stock-site retirement-context validation and initialization behavior must be revisited.
- Retirement rows are capped for display while totals retain the full count; this is reporting truncation, not physical deletion.

No code changes were made during this review.
