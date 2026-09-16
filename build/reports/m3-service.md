# M3 service runtime implementation evidence

Date: 2026-09-16. Scope: Task 3 approved M3 execution design; source worktree only.

## Implemented

- Explicit config.m3 engine dispatch preserves legacy run_one behavior and old RNG initialization. M3 tracks effective/lifetime hours on every physical leaf, including exponential or zero-risk leaves.
- Event-driven continuous, fixed-mission, and fixed-flight execution. Flight PM expiry does not abort; healthy leaves continue accruing actual operating exposure during fault return. All ground work precedes a unified preparation.
- Corrective/preventive method selected once at registration; mixed endpoints consume no draw. Explicit independent step durations/resources and directed shortest service paths. Leaf off-item repair is asynchronous to equipment recovery.
- Parent/tree locks, nested inherited jobs, SRU detach/attach, healthy sibling preservation, independent detached-tree work. Pending leaf PM moves with its removed parent and no longer blocks the repaired aircraft.
- Calendar/operating leaf preventive clocks, stock/transit/held-token quarantine, no overdue spare installation, initial expiry at zero, explicit healthy preventive service completion, PERFECT coverage versus MINIMAL continuation.
- Shared calendar/flight-inspection/component-PM queue ordering, exact-time due registration, existing preparation non-preemption, shift-start and cross-shift work, finite-horizon unfinished work retained.
- Per-replication service/supply snapshots, full-count totals, 10000-row display caps, 200000-job runtime stop. Existing physical/order validation and equipment state-time conservation run on complete internal state.

## Red-green evidence

1. Initial six behavioral tests: six red (missing service/supply runtime, explicit healthy completion, M3 dispatch). After coordinator/runtime implementation: six green.
2. M6-M10 plus mission/flight/shared-queue tests expanded to fourteen. Flight oracle: due2, land/start3, finish6, overrun1; no PM flight abort. Clock transit oracle: due2, receipt/start4, finish14; order received is still1.
3. Held-spare concurrency regression red: an OFF_ITEM service began on a token while installation held it. Reservation ownership fix green; subsequent assertion confirms overdue token is not installed.
4. Same-time calendar and component PM regression red: calendar incorrectly started5 instead of2. Register all due clocks before arbitration; calendar2 and componentPM3 now green.
5. Parent explicit IN_PLACE step regression red: parent completed4 instead of6; now executes parent work overhead after nested child service without resetting sibling ages.
6. Removed-parent pending-PM regression red: aircraft remained in replacement state despite replacement completion3. Pending leaf jobs transfer to detached tree; aircraft available3, destination PM completes independently.
7. Aggregate assumptions regression red: M3 reported legacy two-level semantics. M3 assumptions and per-replication retention now green.
8. Preventive event metadata regression red: actual PERFECT renewal was labeled MINIMAL from corrective configuration. Explicit completion now records the actual renewal type.

Latest focused verification: `.venv/Scripts/python.exe -m pytest tests/test_m3_service.py tests/test_aging.py tests/test_maintenance.py tests/test_flight.py -q` => **80 passed** (20 M3 service and60 existing regressions).

Latest broader checkpoint at execution time: **300 passed,8 failed**, all failures were another owner's active migration RED tests because simlab.m3_migrate did not yet exist. Earlier all M3 config/demo/supply/service focused checkpoint:66 passed before later regressions were added. No claim here about final release/package/install verification.

## Interfaces

ServiceCoordinator(env,config,components,supply,pool,method_rng,work_rng,set_state,log).
Supply hooks: eligible(part), on_stock(station,part), withdraw(part), request_part returns held physical ID, return_part only supply writes stock. Supply.start occurs after all initial physical instances exist.

service.jobs fields: id,kind,rule,part,iid,parent,asset,station,method,status,due_at,started_at,ended_at,age_before,age_after,lifetime_hours,overrun_hours. Status: queued,starting,waiting_resource,working,waiting_spare,transport,completed,covered_by_corrective. OFF_ITEM rows are separately identifiable from method selection rows.

service.clocks fields: part,iid,rule,clock,interval_hours,hours,due_at,paused,completed_services,overrun_hours.
Snapshot counts: jobs_total,clocks_total,jobs_truncated,clocks_truncated; totals.status, totals.selected, totals.completed; random_streams maps failure0,repair1,replace2,method3,preventive4. Top-level detailed snapshots show first replication, replication_results preserves every replica.

## Review attention

Cross-site pending PM compatibility: a leaf SRU has PM already selected at base, then its parent LRU is replaced and sent to depot, where MINIMAL corrective does not cover the PM. The pending PM keeps its selected method but uses the rule/steps/resources at its actual destination. Runtime rejects a destination rule that cannot support that selected method. Compiler should conservatively reject this possible incompatible reachable-context combination before execution (root/config owner notified); no reroll or implicit conversion is performed.

Concrete supported regression: parentL atC, childS MINIMAL; parent REPLACE toA; S preventive IN_PLACE atC andA. Aircraft recovers3, old parent child corrective and PM execute serially atA. Incompatible variant: source S PM REPLACE/MIXED but destination only IN_PLACE; preserve pick-once requires destination to support REPLACE as well. An attached child remains attached and uses the parent/SRU maintenance rule; it must not be silently converted into a detached leaf OFF_ITEM service. A physically detached standalone leaf legitimately uses OFF_ITEM and no second method draw.
