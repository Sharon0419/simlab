# Procurement and lifetime retirement Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use subagent-driven-development to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** Deliver the approved M3 procurement and retirement increment as v0.11.0, retaining existing project compatibility and concise UI.
**Architecture:** Keep SupplyNetwork the sole inventory writer. Add external procurement candidates to replenishment allocation and lifetime retirement to physical service/exposure; keep legacy execution unchanged. New extension tables are canonical strings in config.m3.tables.
**Tech Stack:** Python, SimPy, PySide6, SQLite, pytest, Windows PyInstaller.

## Binding business rules
- Any item level: optional lifetime operating-hour and corrective-repair-count limits; either reached retires. No reset with perfect repair. Only actual corrective repair completion counts, never preventive, parent rollup, removal/install or transport.
- Flight hour expiry: complete current flight, then remove/replace before next mission. Ground expiry handled immediately. Parent retirement removes its subtree from service; no salvage/recovery workflow.
- Retirement replacements reuse existing removal/install/test and resources, without rerolling repair method. Missing replacement definition must produce model validation error rather than silently instantaneous replacement.
- Procurement per point/station/item: THRESHOLD or PERIODIC, order up to target IP. All tiers may purchase only where configured. Fixed lead time, unlimited quantity, new physical identities and zero lifetime/effective age/repair count including children at arrival.
- Shared IP = eligible on-hand + committed unreceived replenishment - unmet demand; external orders counted once. Simultaneously eligible supply modes compete by earliest arrival; transfer wins ties, route ID stable. Faster transfer stock can partially supply then remaining quantity purchased. No automatic cancellation of already dispatched orders or old upstream replenishment (D9).
- Procurement and transfer triggers remain independent. Stable same-time planning must avoid duplicate orders. No external purchase when its own trigger is ineligible.
- Existing no-new-feature models retain trajectories and compatibility; old readers must reject new format.

## Task 1 — Input contracts and validation
Ownership: extensions.py, schema.py, compiler.py, supply_config.py, service_config.py, tests/test_m3_config.py, new tests/test_procurement_config.py.
- [x] Add failing schema/compiler/roundtrip tests, run focused pytest, then implement.
- [x] SimLabPurchasePolicy fields POINT/STID/IID/TRIGGER/TARGET_QTY/REORDER_QTY/FIRST_H/INTERVAL_H (same meanings as supply policy), LEAD_H nonnegative fixed hours. No inbound route requirement. Add to M3_TABLES and SUPPORTED fields, Chinese groups/names.
- [x] SimLabItemRetirement fields IID index Item IID, LIMIT_H optional positive float, LIMIT_REPAIRS optional positive integer, at least one required. Add to M3_TABLES. No restriction to leaves.
- [x] Advance extension format to 11, accept old 1..10. Validate procurement periodic workload/thresholds/unused fields and references; include procurement sites in PM/service reachable-stock validation.
- [x] Validate retirement replacement contexts: reuse CORRECTIVE rule REMOVE/INSTALL/TEST when present, otherwise legacy replacements. Existing IN_PLACE rule may carry these steps when retirement enabled; fail if missing. Parent children serviced only at actual work sites.
- [x] Report tests and integration concerns to build/reports/procurement-config.md. Do not commit while other local edits exist.

## Task 2 — Procurement runtime
Ownership: supply.py, supply_ledger.py, new tests/test_procurement_supply.py.
- [x] Add failing runtime tests: purchase-only threshold/periodic; pending orders deducted; fast transfer partial 2+purchase3; faster purchase; equal-time transfer; differing triggers; hierarchy sponsor interaction; zero lead; whole new subtree at arrival; conservation.
- [x] Implement shared order planning using contracts Task1. No physical purchasing inventory created before arrival; created IDs tracked for quantity conservation.
- [x] Expose supply.purchases list in snapshot with id/order/station/iid/quantity/created/arrival/received/parts; include purchase totals and correct detail_counts. Keep existing orders/shipments and stable old behavior.
- [x] New component identities must start age/lifetime/count zero at receipt. Invoke on_stock for PM registration; include created counts in assert_invariants; retirement locations remain accounted physical IDs.
- [x] Report focused test evidence to build/reports/procurement-supply.md.

## Task 3 — Retirement runtime
Ownership: m3_engine.py, service.py, aging_components.py (M3-only behavior), new retirement.py if useful, tests/test_retirement.py.
- [x] Add failing tests for hour expiry continuous/flight/parent, count threshold after Nth actual repair, perfect vs lifetime, PM excluded, off-item scrap not returned, parent children disposal, simultaneous PM/failure retirement, queued stock never installs expired parts, no repeat loop.
- [x] Track operating lifetime of all physical levels without doubling existing leaf accumulation. Hour trigger exact, hold aircraft until landing then reuse removal/install/test regardless selected repair method. At count limit after repair retire immediately; installed parts require replacement, detached retired never stocked.
- [x] Procurement-created parts fresh; remove stale PM jobs/clocks for retired trees; preserve identities/count conservation and unrelated legacy behavior.
- [x] Expose service.retirements rows (part/iid/time/reason/lifetime_hours/corrective_repairs/site/asset) and service.lifetimes for all levels. Add totals and truncation metadata; distinguish retirement jobs from corrective repair counts.
- [x] Report tests and edge decisions to build/reports/procurement-retirement.md.

## Task 4 — Presentation, example, integration, review
Ownership root: m3_results.py, ui, sample/desktop smoke, docs, version/build.
- [x] Add concise Chinese purchase/retirement datasets, all-rep export; sample should demonstrate procurement triggered by retirement. No persistent explanatory clutter.
- [x] Run focused tests and full pytest; source desktop smoke. Independent review of full change and fix evidenced issues.
- [x] Update README/version/docs and verify legacy sample reproducibility + new model roundtrip. Build with tools/build_windows.ps1, package and run installed smoke. Install side-by-side and update launcher; preserve project library and old data.
- [x] Commit verified changes on the authorized branch. Final remote revision and Obsidian synchronization are recorded in the delivery note.

## Execution ledger
- Base 07c2fd8f315fedb068571d1fe96f74ea9ca966cf, existing codex/m3-supply-maintenance branch clean.
- Ruling: remain in existing dedicated feature checkout, avoid changing user project/library paths.
- Ruling: equal arrival times prefer transfer; retirement ends subtree availability without salvage; both avoid inventing post-retirement work.
- Ruling: use task-scoped subagent implementation sequentially per skill, root handles independent presentation and acceptance work.

- Config review: missing installed-child home context and unreachable-context overvalidation fixed, regressions passed.
- Supply review: threshold trigger now uses full shared IP; mixed pending orders re-evaluate later and same-time periodic ticks; red/green tests passed.
- Retirement review: detached parent returns only after child replacement; 15 targeted tests and whole-runtime review closed.
- Consolidated pytest: 371 passed. Source desktop: 72 checks passed (offscreen fixed scale for reproducible screenshots). Packaging/install/push still in progress.

- Final release acceptance: source/package/installed each 72 desktop checks; 371 pytest; both 100-rep lifecycle cases conserved (702/676 purchased arrivals; each217 retired). Six source/EXE first-rep comparisons and old format10 rejection passed. Installed executable SHA256 BFF71FCE5CF3E1E6B819CB3E741895CA0C7E81A0B9B2F34C491E3C44B81E87AC. Original project library still2 and readable.

- Delivery artifacts complete: 399 installed files match staging hashes; ZIP66.7MiB integrity passed. Source/runtime unchanged after final test run; final documentation synchronized into installation.
