# M3 final integration review

Date: 2026-09-16. Scope: `ada3f00..4cc935c`, focusing on module interfaces and approved required features rather than repeating every prior module review. The requested release verification script was also inspected. No implementation files were changed by this reviewer.

## Verdict

**PASS for source review: all supported P1/P2 findings from these reviews are closed.** No further confirmed P1/P2 or clearly unimplemented approved mandatory feature was established in this integration pass. This does not certify an executable that has not completed release acceptance.

Scoped closure records are appended to `m3-supply-review.md`, `m3-desktop-review.md`, `m3-service-review.md`, and `m3-config-review.md`. In the final pass, the healthy-sibling relocation case exposed an incomplete destination-method check in 19ce0e1; fix 4cc935c now covers that case while preserving valid single-leaf PERFECT behavior. Its independent regression passed. The final build must include 4cc935c.

## Verified interfaces

- Supply snapshots and result/CSV metadata now agree on nested per-dataset total/retained/truncated values. The original real-snapshot probe passes for both a truncated order dataset and an intact stock dataset.
- Same-instant component PM registration is batched before tree-lock arbitration. Four combinations of structure ordering and stocked parents pass.
- A new standalone combined-queue integration probe has calendar maintenance, flight-hour inspection and component PM all due at 3. After landing 4, calendar runs 4–5, inspection 5–6, component PM 6–9, with one preparation after the queue clears. This checks the existing inspection interface in addition to the earlier calendar/component tests.
- Explicit MODE gating, canonical tables, single stock writer, order/shipment identities, pending-demand sponsorship, D9 commitments, independent RNG labels, leaf-clock renewal, migration copies, retained all-replication datasets, and compatibility version 10 are present. Existing service tests cover continuous, fixed mission and fixed flight runtime contexts; no mode was silently dropped.
- Whole-state supply/physical/time validation is invoked before a replication result returns; display retention is applied to snapshots afterward. Dynamic order/service/shipment caps raise failures rather than returning successful partial physical simulations.
- Configuration checks now cover CALENDAR stock/assembly service contexts, required deployed/recursive corrective chains, nonnegative thresholds and valid initially overdue clock bounds. Previously chosen PM methods must remain executable when an attached leaf survives parent relocation, whether it is the MINIMAL-repaired faulty leaf or a healthy sibling.

## Independent verification in this pass

- Result metadata and simultaneous-PM subset: **6 passed, 24 deselected in 0.82s**.
- Original configuration fix subset: **5 passed, 31 deselected in 0.08s**.
- Final healthy-sibling/MINIMAL compatibility subset: **2 passed, 35 deselected in 0.05s**.
- Original real SupplyNetwork snapshot and both dataset CSV probes: passed.
- Combined calendar/flight-inspection/component queue probe: passed.

Root subsequently reported the final post-4cc935c full suite: **319 passed**. This reviewer did not independently rerun that entire suite. Root also reported first-build EXE 63 checks plus four-case source/saved/EXE comparison and old-v9 rejection passing; the final rebuild including 4cc935c is underway, so those first-build checks are not represented as final-install verification.

## Release verification script inspection

`tools/verify_m3_release.py` compares a fresh compiled source first replication with the saved result, then the EXE first replication; separately compares first-replication events/components/samples. NREPS is set to 1 without changing the seed, preserving replication 0 RNG labels. It deletes any previous worker result before dispatch, checks process success, and asserts result equality. Loading the old `ada3f00` project reader with extension constant 9 and asserting its version rejection is a reasonable targeted old-reader check. No unsupported assertion or obvious false-positive success path was found in this script. The script was inspected, not run by this reviewer.

## Remaining release acceptance

Complete final source/package/install smoke, source/saved/EXE first-replication comparisons, deterministic/1000-replication case audits, release documentation and user-data-preserving installation using the final reviewed source. These are tracked acceptance steps, not outstanding source-review findings.
