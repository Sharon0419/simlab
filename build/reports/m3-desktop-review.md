# M3 desktop, results, migration and case review

Date: 2026-09-16. Scope: commits `83d1859` (desktop/results/example/packaging preparation) and `ef3f5ce` (migration), against approved design sections 4.2, 7–9 and implementation plan Tasks 4–5. Current result-label-only edits were excluded. Configuration/service fixes in progress were not reviewed. Implementation files were not changed.

## Verdict

**Changes required: one P2 result-contract mismatch.** No additional actionable migration, all-replication row iteration, example audit, or packaging preparation defect was established within this scope.

## P2 — Read per-dataset supply detail metadata using its actual nested structure

Location: `simlab/m3_results.py:64–73`; user-visible consumers at `simlab/ui/m3_results.py:65` and `simlab/m3_results.py:99`.

`SupplyNetwork.snapshot()` emits `detail_counts[dataset] = {'total': N, 'retained': K, 'truncated': bool}` and a section-wide `truncated` boolean. The presentation helper instead returns the entire dictionary as `detail_total` and treats the section-wide flag as the truncation state of every dataset. Thus CSV count metadata is a Python dictionary string rather than a number, and an intact dataset is falsely marked incomplete merely because a different dataset was truncated. The result-page notice also prints the dictionary as the total.

Independently executed reproduction using the real SupplyNetwork snapshot:

1. Configure a→c transit1, source stock3, `detail_limit=2`.
2. Create three quantity1 manual orders and run to t=2.
3. Snapshot correctly reports orders `{total:3, retained:2, truncated:True}` and stocks `{total:2, retained:2, truncated:False}`.
4. `detail_total(data, 'orders')` returns the whole dict.
5. `truncated(data, 'stocks')` incorrectly returns `True`.
6. Exported order CSV `detail_total` is `{'total': 3, 'retained': 2, 'truncated': True}` instead of `3`.

This violates design section 8 and the new metric documentation, which require independent total/retained/truncation metadata per detail type. Read nested per-dataset metadata first; preserve the numeric/flat legacy fallbacks used by service snapshots. Use the global flag only when dataset-specific evidence is unavailable. Add a regression built from a real supply snapshot; current result tests use integer `detail_counts` fixtures and therefore do not represent the producer contract.

## Areas reviewed without additional findings

- Migration deep-copies source tables into a fresh project ID/revision, preserves parent revision, and starts with no copied historical runs. It blocks existing M3 data, assemblies, and unsupported correlated exponential replacement splits instead of overwriting or silently approximating them. Preview identifies source fields and new stock/zero-step assumptions; UI acceptance precedes adopting the candidate. Existing normal editor autosave behavior remains separate from the migration transformation.
- Migration explicitly copies supply/service directions and durations, preserves resource tasks, and removes transformed legacy execution rows only from the candidate. The new candidate is compiled before presentation. No claim of old/new sample-by-sample equivalence is made.
- CSV iterates all stored replication snapshots and preserves original record values and physical ID arrays, with model hash, seed, engine and replication metadata. It exports retained details with explicit truncation metadata; the identified metadata bug is the required correction.
- The acceptance script rejects truncated supply/service details, checks order quantity and shipment consistency, checks stock-position arithmetic, confirms physical counts, and checks package roundtrip. Runtime final validation supplements these exported-result checks. The source/EXE worker comparison uses the first replication with the same seed and inputs except repetition count.
- The supplied demonstrator explicitly models three levels, direct/indirect routes, both corrective and preventive MIXED rules, resources and aircraft windows. Packaging changes include the M3 examples and documentation without replacing the independent runtime acceptance steps.

## Evidence limits

Only the concrete supply-snapshot/CSV probe above was independently executed during this review. Existing desktop, migration, demo, and full-suite passes were not rerun simply to repeat prior evidence. This review does not certify a built or installed executable; source/package/install smoke, 1000-replication case audits and exact source/EXE replay remain required acceptance evidence before final release claims.

## Independent scoped closure — 9294bd0 (2026-09-16)

**PASS; the desktop P2 is closed.** Nested supply per-dataset total/truncation metadata now takes precedence, while flat service totals and older integer count fallbacks remain supported. Targeted pytest across result and simultaneous-PM regressions: **6 passed, 24 deselected in 0.82s**. Independently reran the original real SupplyNetwork probe with three orders and detail_limit2: orders export numeric total3/truncatedTrue, while stocks export numeric total2/truncatedFalse. Both UI helpers and CSV evidence match the producer. No additional fix-scope finding.
