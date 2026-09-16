# M3 legacy migration report

Date: 2026-09-16. Scope: `simlab/m3_migrate.py`, `tests/test_m3_migrate.py`; no UI edits.

API: `prepare_migration(project) -> (candidate, preview_text)`. It validates the legacy source, makes an independent `new_project` with copied tables and parent_revision provenance, drops run history from the new candidate only, generates explicit M3 rows, and compiles the candidate before returning. It does not save files or mutate the source. The caller can present the Chinese preview before accepting/saving the candidate.

Supported: valid legacy direct leaf items, two-level or same-site repair, fixed replacement (or exponential with only one nonzero split), fixed/exponential leaf repair, existing task/resource/shift/mission inputs. Replacements become CORRECTIVE/REPLACE plus REMOVE/INSTALL using Control.RMVFR and zero TEST. Repairs become OffItemService SERVICE with original distribution/task plus explicit zero DIAGNOSE/TEST. Directions preserve TFRMS for upper→lower supply and TTOMS for lower→upper service; old transport fields clear to zero. Converted ItemRepair/ItemReplacement clear to avoid overlapping explicit rules.

The Chinese preview lists source fields, generated row fields and values, preserved parameters, removal of old rows, new zero-time defaults, and new supply assumptions. Selected Control.APID determines initial stock; ISTOH falls back to STSIZ as the compiler does. Suggested target=max(initial stock,1); threshold=target−1. Zero-stock target1 is explicitly a new assumption. No preventive or mixed rules are added; no external procurement is created at the highest tier. Random streams and replenishment behavior differ from legacy and the preview explicitly disclaims per-sample equality.

Explicit refusal: already M3; partially populated M3 inputs that would otherwise be overwritten; assemblies/SimLabDepotProcess; exponential replacement with both remove and install positive. Valid legacy DepotProcess only applies to assemblies, so this bounded leaf migrator rejects it rather than flattening parent tests into leaf repair. A source exponential replacement draws once then splits, whereas M3 steps draw independently, so silently mapping both distributions would change correlation.

TDD: initial focused run produced 8 explicit missing-feature failures. Implemented conversion; one remaining preview-source qualification assertion failed and was fixed. Final `.venv/Scripts/python.exe -m pytest tests/test_m3_migrate.py tests/test_m3_config.py -q` → **39 passed in 0.66s** (8 migration +31 configuration cases).

Tests verify source deep immutability, distinct IDs/revisions, no copied history, provenance, compilation, removal of overlapping legacy rows, no unsolicited preventive behavior, .25 split of 2 hours into .5/1.5, preserved repair distribution/resources, asymmetric 3h/7h transport, ISTOH vs STSIZ and selected POINT, zero stock assumptions, mission/shift retention and the refusal paths.

UI acceptance/save integration remains the root task's responsibility. No runtime numerical equivalence or complex-model migration is claimed.
