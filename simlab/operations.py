"""Explicit fixed demand windows and non-preemptive maintenance start calendars.

This is a documented execution subset, not an implementation of all SIMLOX
mission semantics. All times are absolute hours from simulation start.
"""
from .schema import value


SUPPORTED_OPERATIONS = {
    'SimLabFlightRule': {'MTID', 'PREP_H'},
    'SimLabDutyRule': {'MTID', 'MIN_QTY', 'PRIORITY', 'RELIEF_H', 'TOLERANCE_H'},
    'MissionType': {'MTID', 'NOS', 'MNOS', 'MNOSA', 'DURN', 'TFOUT', 'TFRET'},
    'MissionSystem': {'MTID', 'SID', 'NOS', 'MNOS', 'MNOSA'},
    'Operations': {'USTID', 'PRID'},
    'OperationProfile': {'PRID', 'SPRID', 'STIM'},
    'Shift': {'SHID'},
    'ShiftProfile': {'SHPID', 'SSHPID', 'STIM', 'ETIM'},
    'ResourceStationData': {'RID', 'STID', 'SHPID'},
}


def intersect(left, right):
    result = []
    i = j = 0
    while i < len(left) and j < len(right):
        start = max(left[i][0], right[j][0])
        end = min(left[i][1], right[j][1])
        if start < end:
            result.append((start, end))
        if left[i][1] < right[j][1]:
            i += 1
        else:
            j += 1
    return result


def compile_operations(tables, fleets, capacity, repairs, replacements, horizon, reps, extra_rules=()):
    errors, missions, schedules = [], [], {}
    def val(table, row, col):
        return value(table, row, col)
    profiles = {}
    for row in tables.get('OperationProfile', []):
        profiles.setdefault(row['PRID'], []).append(row)
    types = {r['MTID']: r for r in tables.get('MissionType', [])}
    duty = {}
    for row in tables.get('SimLabDutyRule', []):
        tid = row['MTID']
        minimum = int(float(val('SimLabDutyRule', row, 'MIN_QTY')))
        priority = int(float(val('SimLabDutyRule', row, 'PRIORITY')))
        if not 1 <= minimum <= int(val('MissionType', types[tid], 'NOS')) or priority < 1:
            errors.append(f'SimLabDutyRule.{tid}: 最低数量须为1至目标数量，优先级须为正整数。')
        duty[tid] = {'minimum': minimum, 'priority': priority,
                     'relief_hours': float(val('SimLabDutyRule', row, 'RELIEF_H')),
                     'tolerance_hours': float(val('SimLabDutyRule', row, 'TOLERANCE_H'))}
    systems = {}
    for row in tables.get('MissionSystem', []):
        systems.setdefault(row['MTID'], []).append(row)
    operations = tables.get('Operations', [])
    if not operations and any(tables.get(t) for t in ('MissionType', 'MissionSystem', 'OperationProfile')):
        errors.append('Operations: 已填写任务定义，但没有关联运行计划。')
    if operations and any(f['util'] != 1 for f in fleets):
        errors.append('SystemDeployment.UTIL: 任务模式要求 UTIL=1；仅被分配的设备累计运行故障，待命不累计。')
    for operation in operations:
        location, profile = operation['USTID'], operation['PRID']
        for index, entry in enumerate(profiles.get(profile, [])):
            tid = entry['SPRID']
            if tid not in types:
                errors.append(f'OperationProfile.{profile}: 仅支持直接引用 MissionType，不支持递归剖面。')
                continue
            spec = types[tid]
            choices = systems.get(tid, [])
            if len(choices) != 1:
                errors.append(f'MissionSystem.{tid}: 固定需求窗口必须且只能指定一种系统。')
                continue
            choice = choices[0]
            sid = choice['SID']
            quantity = int(val('MissionType', spec, 'NOS'))
            for field in ('MNOS', 'MNOSA'):
                v = val('MissionType', spec, field)
                if v and int(v) != quantity:
                    errors.append(f'MissionType.{tid}.{field}: 本版要求与 NOS 一致，不执行部分任务或任务中止阈值。')
            for field in ('NOS', 'MNOS', 'MNOSA'):
                v = val('MissionSystem', choice, field)
                if v and int(v) != quantity:
                    errors.append(f'MissionSystem.{tid}.{field}: 请留空或与 MissionType.NOS 一致。')
            start = float(entry['STIM'])
            end = start + float(val('MissionType', spec, 'DURN'))
            if not (0 <= start < end <= horizon) or quantity > 2000:
                errors.append(f'OperationProfile.{profile}@{start:g}: 要求 0≤开始<结束≤SIMPE，需求数量≤2000。')
            if not any(f['sid'] == sid and location in (f['unit'], f['home']) for f in fleets):
                errors.append(f'Operations.{location}: 没有部署任务所需系统 {sid}。')
            missions.append({'id': f'{location}/{profile}/{tid}/{index+1}', 'type': tid,
                             'location': location, 'sid': sid, 'quantity': quantity,
                             'start': start, 'end': end,
                             **duty.get(tid, {'minimum': quantity, 'priority': 1, 'relief_hours': 0.0, 'tolerance_hours': 0.0})})
    if len(missions) > 2000 or len(missions) * reps > 200000:
        errors.append('Operations: 任务窗口≤2000，任务窗口数×重复次数≤200000。')
    missions.sort(key=lambda m: (m['start'], m['id']))
    flight_rules = {r['MTID']: float(r['PREP_H']) for r in tables.get('SimLabFlightRule', [])}
    for tid, spec in types.items():
        out, back = float(val('MissionType',spec,'TFOUT')), float(val('MissionType',spec,'TFRET'))
        if out+back > 1:
            errors.append(f'MissionType.{tid}: TFOUT+TFRET不能超过1。')
        if (out or back) and tid not in flight_rules:
            errors.append(f'MissionType.{tid}: 非零阶段比例需要SimLabFlightRule飞行模式。')
    if flight_rules:
        pools = {}
        for task in missions:
            if task['type'] not in flight_rules:
                errors.append('SimLabFlightRule: 飞行模式不能与固定值守混合；所有任务类型都需配置飞行规则。')
                continue
            if task['type'] in duty:
                errors.append('SimLabFlightRule: 同一任务不能同时配置 SimLabDutyRule。')
            task['flight_prep_hours'] = flight_rules[task['type']]
            spec = types[task['type']]
            task['out_fraction'] = float(val('MissionType',spec,'TFOUT'))
            task['return_fraction'] = float(val('MissionType',spec,'TFRET'))
            day = int(task['start']//24)
            if task['end'] > (day+1)*24 or task['start']-day*24 < task['flight_prep_hours']:
                errors.append('SimLabFlightRule: 保障开始不得早于当天00:00，飞行不得跨日。')
            pool = (task['location'], task['sid'])
            pools.setdefault(pool, set()).add(task['flight_prep_hours'])
        if not missions:
            errors.append('SimLabFlightRule: 必须配置飞行任务计划。')
        if any(len(v)>1 for v in pools.values()):
            errors.append('SimLabFlightRule: 同一选机池的保障时长须一致。')
        for fleet in fleets:
            matching = [pool for pool in pools if pool[1] == fleet['sid'] and pool[0] in (fleet['unit'], fleet['home'])]
            if len(matching)>1:
                errors.append('SimLabFlightRule: 同一装备不能同时属于站点与单位两个重叠选机池。')
    shifts = {r['SHID'] for r in tables.get('Shift', [])}
    windows = {}
    for row in tables.get('ShiftProfile', []):
        start, end = float(row['STIM']), float(val('ShiftProfile', row, 'ETIM'))
        if row['SSHPID'] not in shifts or end <= start:
            errors.append(f'ShiftProfile.{row["SHPID"]}: 仅支持直接 Shift 引用且 ETIM>STIM 的显式班次。')
            continue
        windows.setdefault(row['SHPID'], []).append((start, end))
    for name, spans in windows.items():
        merged = []
        for start, end in sorted(spans):
            if merged and start <= merged[-1][1]:
                merged[-1] = (merged[-1][0], max(end, merged[-1][1]))
            else:
                merged.append((start, end))
        windows[name] = merged
    if sum(len(v) for v in windows.values()) > 10000:
        errors.append('ShiftProfile: 班次窗口数量超过 10000。')
    for row in tables.get('ResourceStationData', []):
        key = (row['STID'], row['RID'])
        name = val('ResourceStationData', row, 'SHPID')
        if key not in capacity or not name or name not in windows:
            errors.append(f'ResourceStationData.{key}: 需要已配置资源和有效 SHPID。')
        else:
            schedules[key] = windows[name]
    for (station, _), rule in repairs.items():
        _check_common(station, rule, schedules, horizon, errors)
    for (_, _, station), rule in replacements.items():
        _check_common(station, rule, schedules, horizon, errors)
    for station, rule in extra_rules:
        _check_common(station, rule, schedules, horizon, errors)
    return missions, schedules, errors


def _check_common(station, rule, schedules, horizon, errors):
    common = [(0, horizon)]
    for rid, quantity in rule['resources'].items():
        if quantity:
            common = intersect(common, schedules.get((station, rid), [(0, horizon)]))
    if not common:
        errors.append(f'资源组合 @ {station}: 仿真期内没有共同班次，作业无法开始。')
