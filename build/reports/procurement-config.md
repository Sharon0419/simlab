# Procurement and retirement input contracts

Date: 2026-09-16

## Status

Implemented Task 1 in the assigned schema/compiler/config/test files. No commit was created.

- Extension format is now `11`; project persistence consequently accepts and upgrades versions `1..11`, while version `12+` is rejected.
- Added canonical `SimLabPurchasePolicy` with fields `POINT/STID/IID/TRIGGER/TARGET_QTY/REORDER_QTY/FIRST_H/INTERVAL_H/LEAD_H`.
- Added canonical `SimLabItemRetirement` with fields `IID/LIMIT_H/LIMIT_REPAIRS`.
- Added both tables to M3 canonicalization, supported compiler fields, Chinese table/field labels, and modeling groups.
- Procurement validates references, nonnegative fixed `LEAD_H`, positive target, threshold target ordering, unused trigger fields, periodic interval, and the 200,000 predictable-order cap. It deliberately has no inbound-route requirement.
- Retirement accepts any item level. Each row requires at least one limit; configured hour and repair limits must be positive, and repair limits must be integers.
- Procurement sites participate in CALENDAR preventive-service reachable-stock validation.
- Retirement replacement contexts reuse an explicit `CORRECTIVE` rule when present; that rule must expose `REMOVE`, `INSTALL`, and `TEST`, including when its ordinary method is `IN_PLACE`. Without an explicit rule, a legacy `ItemReplacement` context is accepted. Missing replacement context is a model error.
- Child contexts are checked only at actual work sites derived from the parent corrective method: home for `IN_PLACE`, repair destination for `REPLACE`, and both for `MIXED`.

## Tests

Red phase: focused run initially produced 17 expected failures because the two tables and version 11 did not yet exist.

Green focused run:

`\.venv\Scripts\python.exe -m pytest tests/test_procurement_config.py tests/test_m3_config.py -q`

Result: `52 passed in 0.65s`.

Full-suite integration run during concurrent Task 2 work:

`\.venv\Scripts\python.exe -m pytest -q`

Result: `338 passed, 9 failed in 9.22s`. All nine failures are in concurrently added procurement runtime/example tests (`tests/test_procurement_supply.py` and `tests/test_m3_demo.py`) because purchase execution/snapshot support was not yet implemented at that instant. No schema/config or pre-existing regression failed.

`git diff --check` reported no whitespace errors; only the repository's existing LF-to-CRLF warnings were emitted.

## Runtime integration contract and concerns

- Runtime consumers should read canonical strings from `config['m3']['tables']['SimLabPurchasePolicy']` and `config['m3']['tables']['SimLabItemRetirement']`; numeric parsing remains a runtime responsibility, matching existing M3 table contracts.
- `LEAD_H` is fixed and may be zero. Purchase has unlimited quantity and does not require any `SimLabSupplyRoute` row.
- Do not infer retirement work location from deployment home for child items. Use the same parent method/destination resolution described above.
- Explicit retirement-enabled `IN_PLACE` corrective rules can now legally include `REMOVE` and `INSTALL`; service runtime must select those only for retirement replacement, not for ordinary in-place corrective execution.
- The compiler currently requires retirement replacement steps on every configured explicit corrective context for a retirement IID. This is intentionally conservative and ensures any reachable explicit context can execute retirement.
- Root/runtime work was concurrent. Re-run the full suite after Task 2 and retirement runtime land; the nine recorded failures are expected to be resolved there.
