# Procurement supply independent review

Date: 2026-09-16. Scope: current `C:/Users/sharo/Documents/ChatGPT/Simlox` working diff versus HEAD in `simlab/supply.py` and `tests/test_procurement_supply.py`, against `procurement-task-2-brief.md` and `procurement-supply.md`. Read-only implementation review; only this report was written. No edits to source/tests and no commits.

## Verdict at final inspection

Two P2 defects were reproduced and reported, including a zero-time boundary of mixed-order conversion. The owner fixed all reported cases during review; independent reruns confirm the corrections. No outstanding supported P1/P2 finding remains in this bounded scope.

## Closed during review — P2 creation-time allowance blocked same-time periodic re-evaluation

Location: `simlab/supply.py`, `_fulfil`, initial_purchase selection near line270 and fixed `base_ip`/allocated quota near line295.

The intermediate correction still retained the exhausted creation-time purchase allowance after a zero-lead receipt and newly registered local demand, because `row.created == env.now` stayed true. The PERIODIC tick remained eligible but the old unsourced transfer remainder was not converted until the next period. This was the same mixed-order re-evaluation issue at a zero-time receipt boundary.

Reproduction using the existing test helpers (no production monkeypatch):

```python
import sys
sys.path.insert(0, 'tests')
from test_procurement_supply import setup, policy, route

env, parts, supply = setup(
    [policy(target=1, first=0, lead=0)],
    [route(1)], [policy(target=5)])
demands = []
def received(station, part):
    if not demands:
        demands.append(supply.request_part(station, 'X'))
supply.on_stock = received
supply.start()
env.run(until=.1)
print([(p['created'], p['quantity']) for p in supply.purchases])
print(len(supply.available('c', 'X')))
print([(o.quantity, o.unallocated, o.received) for o in supply.orders])
supply.validate()
```

Before correction: purchases `[(0,1)]`, available0, order `(5,4,1)`, local demand fulfilled. With the stated same-time periodic eligibility and old-unallocated conversion semantics, the same order should convert one additional unit at t0 after that demand, yielding available1 without a duplicate order. Owner correction now also requires `row.quantity == row.unallocated` for initial-mode selection. Independently rerunning the same probe gives purchases `[(0,1),(0,1)]`, available1, and one order `(5,3,2)`; validation passes. The new regression `test_same_tick_zero_lead_mixed_purchase_rechecks_after_immediate_consumption` passes. Subsequent same-time stabilization uses dynamic eligibility without duplicating the order.

## Closed during review — P2 threshold evaluated after excluding its own promise

Original `_fulfil` dynamic conversion tested procurement eligibility on `IP - row.unallocated`. Repro: C stock1; transfer target5/reorder1; A empty with A->C; purchase target1/reorder0. t0 creates transferU4. t1 consumes the local1. Full shared IP is4, above procurement threshold0, yet the original branch purchased1 by testing adjustedIP0.

Owner correction now tests the trigger on full shared IP and subtracts unallocated only for conversion quantity. Regression `test_purchase_threshold_uses_shared_ip_including_unallocated_transfer` passes.

## Closed later-tick portion — P2 mixed orders permanently excluded from conversion

Original `not(options and options.purchase)` gate excluded an order forever if procurement had participated at creation. Repro: transfer target5, purchase PERIODIC first0/interval3/target1/lead0, upstream empty. t0 purchase1 leavesU4; consume1 at t1. At t3 the old code did not purchase despite an eligible tick. A transfer-only order with identical current available0/U4 did convert, so behavior depended on historical mode participation rather than current inventory.

Owner correction permits dynamic conversion at later timestamps. Regression `test_later_periodic_tick_can_convert_remainder_of_mixed_order` passes. The same-time subcase above is also now fixed and independently verified.

## Verification and reviewed non-findings

- Focused suite after owner fixes: `pytest tests/test_procurement_supply.py tests/test_m3_supply.py -q` => **40 passed**.
- Independently replayed30 no-purchase scenarios against an in-memory class loaded from `git show HEAD:simlab/supply.py`. Complete snapshots, physical records and locations matched exactly for all30. Cases cover threshold/periodic hierarchy, zero/nonzero routes and varied fixed demand times.
- Inspected unequal targets, transfer/purchase tie ordering, partial split, sponsor removal on conversion, stable demand sequence, finite-horizon outstanding orders, arrival-only identity creation, and order/physical validation. No additional reproducible discrepancy found in those paths.
- Owner added `max_physical=200000` with a whole-subtree preflight before receipt/creation. The scale regression passes; the guard prevents partial materialization of an oversized batch.
- Initial/final counts include every purchased root and attached child; no IDs are created for unreceived external purchases. No source/test or retirement-engine edits were made by this review.
