# M3 supply independent review

Date: 2026-09-16. Reviewed range: `8c26d95..d18377c`, limited to `simlab/supply.py`, `simlab/supply_ledger.py`, `tests/test_m3_supply.py`. Sources: approved design sections 3, 5, 8, 9; implementation plan Task 2; implementation report. No implementation files changed. Existing 21 passed tests were not rerun.

## Verdict

**Spec: changes required (one P2). Quality: otherwise acceptable within the bounded supply scope.**

Shortest available route selection, stable route tie break, split shipments, single sponsorship derived from each order's remaining U, atomic U→T→R accounting, persistent D9 upstream commitments, physical token allocation, and full internal validation independent of truncated display are implemented coherently. Existing tests exercise the principal S1–S10 scenarios. Maintenance integration and incomplete files outside Task 2 were not reviewed.

## P2 — Keep a due periodic policy active until same-timestamp demand propagation settles

Location: `simlab/supply.py:209` (context lines 187–211).

`_periodic_due.clear()` runs after the first policy sweep even when that sweep created downstream orders and therefore new sponsor demand at an intermediate site already evaluated earlier in the sweep. The next stability iteration cannot top up that intermediate site's periodic order. The outcome consequently depends on the input policy row order and can leave its inventory position below target for a complete cycle.

Concrete standalone probe (executed successfully against the reviewed code):

- Routes a→b = 1 hour, b→c = 1 hour; initial a stock = 5.
- Both b and c use PERIODIC, TARGET_QTY=1, FIRST_H=0, INTERVAL_H=10.
- Start at t=0 and run to t=3.
- With policy rows `[b,c]`, orders are b:1 and c:1; after delivery b has available/IP=0, c has available/IP=1.
- With rows `[c,b]`, orders are c:1 and b:2; after delivery b and c both have available/IP=1.
- Both executions pass `validate()`, so this is a trigger/phase error rather than a quantity-conservation failure.

The approved design D2 requires a periodic replenishment to target; section 5.2 requires the single downstream sponsorship to reduce intermediate IP; section 5.3 requires same-timestamp phases to execute to stability. Clearing the tick eligibility while newly created sponsorship is still propagating violates their combination.

Suggested correction: retain periodic eligibility through the timestamp's necessary stabilization, or stage propagation before final periodic target evaluation. Ensure the fix does not create repeated orders for quantities already committed in O and does not allow unrelated arrivals between periods to initiate a new periodic replenishment. Add a deterministic regression for both policy permutations, including quantity and final intermediate IP assertions. If stabilization emits incremental committed orders, preserve each order identity and D9 semantics.

## Validation scope and limitations

The existing implementation report records 37 focused passes, including 21 supply tests; that evidence was inspected, not independently rerun. This review independently ran only the concrete two-permutation probe above. No additional actionable defect was established in the requested shortest-route, sponsorship uniqueness, D9, physical identity, or display-truncation areas. Final complete-engine service/time conservation remains an integration acceptance obligation.

## Scoped re-review — 4aa5877 (2026-09-16)

**Verdict: PASS for the reported P2 fix; finding closed.** Read-only review of implementation and tests; only this report was appended.

The fix records each periodic tick timestamp and retains eligibility only while `env.now` equals that timestamp. This allows subsequent stabilization sweeps and zero-hour receipt phases to include newly propagated sponsorship, while naturally expiring eligibility between periods. Previously committed orders still contribute U+T to O and are never edited/cancelled: when b is evaluated first, the original quantity-1 order remains and a second quantity-1 order adds the missing amount; the opposite row order produces one quantity-2 order. Both preserve D9 and finish with b/c inventory position 1.

Independent focused verification: `.venv/Scripts/python.exe -m pytest tests/test_m3_supply.py -q -k 'same_tick_periodic_sponsorship or s10_sponsored or s6_pending'` → **6 passed, 19 deselected in 0.24s**. This includes both policy permutations with zero/nonzero transit, no new periodic order after an off-tick withdrawal, fulfillment between ticks, and preservation of upstream commitments after alternate-source fulfillment. No new actionable finding within the fix scope. This does not replace complete-engine/release acceptance.
