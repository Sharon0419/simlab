"""Atomic duty-plan editing and capacity-conflict preview."""
import copy
import math
from .compiler import compile_model


def set_rule(tables, tid, target, minimum, priority, relief, tolerance):
    candidate = copy.deepcopy(tables)
    spec = next(r for r in candidate['MissionType'] if r['MTID'] == tid)
    spec.update(NOS=str(target), MNOS=str(target))
    if spec.get('MNOSA'):
        spec['MNOSA'] = str(target)
    for row in candidate.get('MissionSystem', []):
        if row['MTID'] == tid:
            for key in ('NOS', 'MNOS', 'MNOSA'):
                if row.get(key):
                    row[key] = str(target)
    rules = candidate.setdefault('SimLabDutyRule', [])
    rules[:] = [r for r in rules if r['MTID'] != tid]
    rules.append(dict(MTID=tid, MIN_QTY=str(minimum), PRIORITY=str(priority),
                      RELIEF_H=str(relief), TOLERANCE_H=str(tolerance)))
    return candidate


def daily_plan(tables, name, sid, location, first_day, days, start_hour, end_hour,
               target, minimum, priority, relief, tolerance):
    name = name.strip()
    if not name or any(r['MTID'] == name for r in tables.get('MissionType', [])) or any(
            r['PRID'] == name for r in tables.get('OperationProfile', []) + tables.get('Operations', [])):
        raise ValueError('计划名称须非空，且不能与已有任务或剖面标识重复。')
    if not all(math.isfinite(v) for v in (first_day, days, start_hour, end_hour)) or not (
            first_day >= 1 and first_day == int(first_day) and 1 <= days <= 2000 and days == int(days)
            and 0 <= start_hour < end_hour <= 24):
        raise ValueError('首日从第1天开始；天数1–2000；要求0≤开始时刻<结束时刻≤24。')
    candidate = copy.deepcopy(tables)
    candidate.setdefault('MissionType', []).append(dict(MTID=name, DESCR=name, NOS=str(target),
                                                        MNOS=str(target), DURN=str(end_hour-start_hour)))
    candidate.setdefault('MissionSystem', []).append(dict(MTID=name, SID=sid))
    operations = candidate.setdefault('Operations', [])
    existing = next((r for r in operations if r['USTID'] == location), None)
    profile = name
    if existing:
        profile = existing['PRID']
        if sum(r['PRID'] == profile for r in operations) > 1:
            # A shared profile must be branched before changing one location.
            candidate.setdefault('OperationProfile', []).extend(
                [dict(row, PRID=name) for row in candidate.get('OperationProfile', []) if row['PRID'] == profile])
            existing['PRID'] = profile = name
    else:
        operations.append(dict(USTID=location, PRID=profile))
    candidate.setdefault('OperationProfile', []).extend(
        dict(PRID=profile, SPRID=name, STIM=str((first_day-1+day)*24+start_hour)) for day in range(days))
    candidate = set_rule(candidate, name, target, minimum, priority, relief, tolerance)
    config = compile_model(candidate)
    new = [t for t in config['missions'] if t['type'] == name]
    # Pairwise competition is advisory: overlaps may deliberately share a fleet.
    eligible = {t['id']: {i for i, f in enumerate(config['fleets'])
                         if f['sid'] == t['sid'] and t['location'] in (f['unit'], f['home'])}
                for t in config['missions']}
    overlaps = sum(1 for a in new for b in config['missions'] if b['type'] != name
                   and a['start'] < b['end'] and b['start'] < a['end']
                   and eligible[a['id']] & eligible[b['id']])
    return candidate, new, overlaps
