# Task 3 — lifetime retirement runtime

Date: 2026-09-16. Implemented, not committed. Owned changes: `simlab/retirement.py`, `simlab/m3_engine.py`, `simlab/service.py`, `simlab/aging_components.py`, `simlab/preventive.py`, `tests/test_retirement.py`.

## Behavior

- Exact operating-hour deadlines are part of the existing event-driven exposure loop. All installed physical levels accrue lifetime hours once; leaf hazard/effective-age behavior stays unchanged. Assemblies do not inherit child repair counts.
- Flight deadlines register pending retirement while allowing the current flight to finish. Pending work blocks dispatch; actual removal begins after landing. Continuous/nonflight operation stops at the threshold. Pending parent retirement suppresses descendant deadline wakeups, including simultaneous parent/child expiry.
- Retirement uses the existing corrective REMOVE/INSTALL/TEST steps or legacy replacement definition, always forcing REPLACE without drawing a repair method. No off-item repair is created for retired items.
- Actual leaf corrective completion increases lifetime repair count once, independently of perfect/minimal effective-age reset. Preventive work, parent repair rollup, removal/install/test-only replacement, and transport do not increase it. An off-item leaf reaching its repair limit is retired before any return-to-stock.
- Retirement removes unstarted obsolete work and PM clocks. Retired roots have location `retired`; their children remain attached to that retired root with explicit retired flags, preserving physical identities and conservation without salvage.
- Expired stock is excluded from allocation and withdrawn. A detached parent whose child needs retirement is quarantined; the parent returns to its local stock only after that child's replacement completes. This fixes a reproduced initial implementation deadlock where the retiring detached child no longer identified its original quarantined parent.
- Procurement arrivals dynamically register fresh PM clocks after integrating existing clocks to the arrival instant. New root and child lifetime hours/counts/effective ages are zero. Engine conservation uses initial counts plus SupplyNetwork.created_counts.
- Additive `service.retirements` and `service.lifetimes`, totals and truncation indicators appear when retirement or procurement is enabled. Retirement reasons are LIMIT_H, LIMIT_REPAIRS, and PARENT_RETIREMENT. Jobs use kind RETIREMENT, distinct from corrective repair completions.

## Time/report interpretation

- `job.due_at`: threshold time, including expiry during flight.
- `job.started_at`: replacement work start, after landing/resource queue eligibility.
- `retirements.time`: physical withdrawal after REMOVE completes; lifetime stops with operating exposure, so removal time does not add operating hours. A flight expiring at 2, landing at 3, then taking 1 hour to remove has due_at=2, started_at=3, retirement time=4, lifetime_hours=3.
- Descendant disposal rows use PARENT_RETIREMENT and preserve their own lifetime/corrective count values.

## Evidence

- Red: seven initial retirement tests all failed on missing retirement datasets/counters before implementation.
- Final focused run: `.venv/Scripts/python.exe -m pytest tests/test_retirement.py tests/test_m3_service.py tests/test_procurement_supply.py -q` — **53 passed in 1.70s**. Includes 15 retirement tests covering continuous/flight/parent/child hours, simultaneous parent-child flight expiry, actual Nth repair, perfect repair preservation, PM exclusion, off-item disposal, parent quarantine release, same-time PM/fault/expiry, stale stock rejection, legacy replacement fallback, and fresh purchased-tree clocks.
- Full suite during initial integration: **358 passed in 10.14s**. Further edge tests and the quarantined-parent fix were added afterward; root is responsible for final integrated full-suite/package verification.
- Recompiled and ran all four tables captured in `build/reports/pre-v011-trajectories.json`; normalized complete result equality was **True for all four**: M3 threshold, M3 periodic, legacy aging PERFECT, legacy aging MINIMAL.
- `git diff --check` on modified existing owned files passed; only existing LF-to-CRLF warnings.

## Integration concerns

- Root fixed configuration validation to require an installed child's home replacement context for retirement even if the parent's ordinary corrective mode is REPLACE. This differs from ordinary off-item child repair reachability and is necessary for independent child hour expiry.
- No known unresolved runtime blocker. No commit, packaging, installation, or full final acceptance claim is made by this subtask. Root should perform the consolidated final validation and Obsidian update to avoid concurrent edits of the shared project memory.
