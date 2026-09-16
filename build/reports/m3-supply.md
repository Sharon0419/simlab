# M3 supply implementation report

Date: 2026-09-16. Scope: Task2 only; source files `simlab/supply.py`, `simlab/supply_ledger.py`, tests `tests/test_m3_supply.py`.

## Delivered

- Single-writer physical inventory and Demand/Order/Shipment records, stable IDs and shared FIFO request sequence.
- Shortest currently available route, stable route-ID tie break, split batches, unlimited shipment capacity, explicit zero-hour receipt events.
- One sponsor for each unallocated quantity; alternate sources remove precisely the fulfilled sponsored quantity. Already committed upstream orders persist under D9.
- Threshold initialization, IP=A+O−B, periodic FIRST/INTERVAL, pending orders fulfilled between periods, no new policy order at horizon.
- Deferred SimPy priority-2 allocation phase: ordinary receipt/return and registration events settle first. Policy checks account for real allocations before propagating residual sponsorship. Existing local demand sequence takes precedence over input policy row order.
- Existing Store integration without reseeding; held physical tokens returned by requests; assemblies remain attached.
- Full internal quantity and physical-identity validation, order/shipment caps that raise runtime errors, JSON-safe independently truncated detail snapshots with full totals.

## Verification evidence

Initial red: `python -m pytest tests/test_m3_supply.py -q` → 17 explicit assertion failures because SupplyNetwork did not exist (not import collection errors).

Additional regression red→green:

- Earliest local request lost to policy row ordering; request-order sorting fixes it.
- Immediate candidate availability caused an unnecessary sponsored upstream order; actual allocation before next policy check fixes it.
- Replacing a physical ID without changing item counts escaped validation; start-time identity set now validates as well as counts.

Final focused command: `.venv/Scripts/python.exe -m pytest tests/test_m3_supply.py tests/test_maintenance.py -q` → **37 passed in 0.44s**, including **21 supply tests**. Supply tests cover S1–S10, zero-time convergence, finite-horizon unfinished transport, assembly IDs, supplied-store reuse, synchronous receipt quarantine, runtime caps, due-stock exclusion, route ties, FIFO, D9 candidate switch, full-total detail truncation and identity corruption.

## Runtime integration contract

`SupplyNetwork(env, components, config, stores=None, log=None)` uses canonical uppercase tables, coercing numeric strings locally and selecting SupplyPolicy through Control.APID. A minimal config without Control uses all supplied policies.

`start()` is idempotent and captures initial physical counts/IDs. Call it only after every installed and stocked part is created. `request_part(station,iid,owner='')` returns an Event whose value is a physical ID already moved to `held`. `return_part(station,part)` is synchronous insertion followed by deferred allocation. `withdraw(part)` removes stock to `held`, returning False when not stocked. `available(station,iid)` yields eligible physical IDs. Explicit `order(station,iid,quantity,reason='manual')` uses the same atomic ledger entry as policy replenishment; zero quantity creates nothing.

Hooks agreed with Task3: mutable `eligible(part)` callback; mutable `on_stock(station,part)` callback invoked after each physical receipt/return and before allocation. It may call withdraw to quarantine an arriving due part. Physical order receipt completes regardless of quarantine, allowing policies to replace unusable arrivals correctly.

Snapshot: lists `orders`, `shipments`, `stocks`, `demands`; full `totals`; `detail_counts` with total/retained/truncated per list; top-level `truncated`. Orders have quantity/unallocated/in_transit/received plus original sponsor. Sponsor quantity is the current `unallocated` value, not the original quantity. Completed orders remain auditable. Stock `reserved` is zero because this service immediately grants and moves tokens to held, never retaining reservations in a Store.

## Integration considerations

- Supplied Stores are read compatibility only; M3 service must use supply APIs for all writes.
- Ordinary `env.run(until=horizon)` excludes events exactly at horizon, following existing SimPy engine convention. Supply itself forbids new policy orders at or after the horizon. Task3 has been informed so final engine time semantics remain deliberate.
- Compile-time input validity and route DAG checks are Task1's responsibility; engine-level service/flight integration and release acceptance are not claimed by this report.

## Independent review P2 resolved

The review in `m3-supply-review.md` identified premature periodic eligibility clearing before newly created downstream sponsorship stabilized. Reproduced with b/c PERIODIC FIRST=0 INTERVAL=10, target1, a stock5, a→b→c. Added both policy row permutations at transit0 and transit1: pre-fix **2 failed, 23 passed**, with b-first incorrectly leaving b IP0 and a stock4.

Periodic eligibility now records each tick's timestamp and remains true for every allocation phase at that timestamp. This includes subsequent zero-time receipt phases. At later timestamps eligibility is false unless another tick occurs. New sponsor claims can therefore create an incremental commitment after the original b order, without changing or cancelling that original D9 order. Both row permutations now leave a stock3, b IP1, c IP1. The regression also consumes b stock at t3 and verifies no fresh periodic order before the t10 tick.

Post-fix command `.venv/Scripts/python.exe -m pytest tests/test_m3_supply.py tests/test_maintenance.py -q` → **41 passed in 0.65s**, including **25 supply cases**.
