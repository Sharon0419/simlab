"""Compile and validate user-defined support DAGs and activity bindings."""
import math
import re
from .operations import _check_common
from .schema import value

ACTIVITIES = ('MAINTENANCE', 'OFF_ITEM', 'PREPARATION', 'CALENDAR', 'INSPECTION')
ACTIONS = ('CUSTOM', 'DIAGNOSE', 'REMOVE', 'INSTALL', 'IN_PLACE', 'SERVICE', 'TEST')


def compile_graph(plan, nodes):
    errors, lookup = [], {n['id']: n for n in nodes}
    if not nodes:
        return [f'工序方案 {plan}: 至少需要一道工序。']
    if len(lookup) != len(nodes):
        errors.append(f'工序方案 {plan}: 工序标识重复。')
    for n in nodes:
        if n['id'] in n['predecessors']:
            errors.append(f'工序方案 {plan}/{n["id"]}: 不能依赖自身。')
        for p in n['predecessors']:
            if p not in lookup:
                errors.append(f'工序方案 {plan}/{n["id"]}: 紧前工序 {p} 不存在。')
    settled = set()
    while True:
        ready = {n['id'] for n in nodes if set(n['predecessors']) <= settled}
        if ready <= settled:
            break
        settled |= ready
    if len(settled) < len(lookup):
        errors.append(f'工序方案 {plan}: 存在循环依赖或无法满足的紧前关系。')
    return errors


def ancestors(nodes, target):
    lookup = {n['id']: n for n in nodes}
    result, pending = set(), list(lookup[target]['predecessors'])
    while pending:
        name = pending.pop()
        if name in result or name not in lookup:
            continue
        result.add(name)
        pending.extend(lookup[name]['predecessors'])
    return result


def compile_workflows(tables, config):
    plans, bindings, errors = {}, {}, []
    names = {r['WFID'] for r in tables.get('SimLabWorkflow', [])}
    for name in names:
        plans[name] = []
    tasks = {r['TID'] for r in tables.get('Tasks', [])}
    for row in tables.get('SimLabWorkflowStep', []):
        name, step = row['WFID'], row['STEPID']
        if name not in names:
            errors.append(f'SimLabWorkflowStep.{name}/{step}: 方案不存在。')
            continue
        duration = float(row.get('DURATION_H', 0) or 0)
        if not math.isfinite(duration) or duration < 0:
            errors.append(f'SimLabWorkflowStep.{name}/{step}: 工序时长必须为有限非负数。')
        task = row.get('TASK', '')
        if task and task not in tasks:
            errors.append(f'SimLabWorkflowStep.{name}/{step}: 资源任务不存在。')
        resources = {r['RID']: int(float(value('TaskResource', r, 'QTY'))) for r in tables.get('TaskResource', [])
                     if task and r['TID'] == task and float(value('TaskResource', r, 'QTY')) > 0}
        if task and not resources:
            errors.append(f'SimLabWorkflowStep.{name}/{step}: 资源任务需要正数量需求。')
        action = row.get('ACTION', '') or 'CUSTOM'
        if action not in ACTIONS:
            errors.append(f'SimLabWorkflowStep.{name}/{step}: 不支持的业务动作。')
        distribution = row.get('DISTRIBUTION', '') or 'FIXED'
        if distribution not in ('FIXED', 'EXPONENTIAL'):
            errors.append(f'SimLabWorkflowStep.{name}/{step}: 不支持的时长分布。')
        plans[name].append(dict(id=step, name=row.get('NAME', '') or step, action=action,
            duration=duration, random=distribution == 'EXPONENTIAL', resources=resources,
            predecessors=[s for s in re.split(r'[,，;；\s]+', row.get('PREDECESSORS', '')) if s]))
    for name, nodes in plans.items():
        errors.extend(compile_graph(name, nodes))
    for row in tables.get('SimLabWorkflowBinding', []):
        activity, rule, method = row['ACTIVITY'], row.get('RULEID', ''), row.get('METHOD', '')
        iid, station, kind = row.get('IID', ''), row.get('STID', ''), row.get('KIND', '')
        name = row['WFID']
        prefix = f'SimLabWorkflowBinding.{activity}/{rule or iid}/{method or kind}'
        key = (activity, rule, method, iid, station, kind)
        if key in bindings:
            errors.append(f'{prefix}: 活动绑定重复。')
        bindings[key] = name
        if name not in plans:
            errors.append(f'{prefix}: 方案不存在。')
            continue
        stations, required, order = [], set(), []
        if activity == 'MAINTENANCE':
            match = next((r for r in tables.get('SimLabMaintenanceRule', []) if r['RULEID'] == rule), None)
            if not match or method not in ('IN_PLACE', 'REPLACE', 'RETIREMENT') or iid or station or kind:
                errors.append(f'{prefix}: 必须填写有效维修规则与具体维修路径，IID/STID/KIND应留空。')
                continue
            if not config.get('m3'):
                errors.append(f'{prefix}: 维修工序方案须启用M3执行模式。')
            allowed = ('IN_PLACE', 'REPLACE') if match['METHOD'] == 'MIXED' else (match['METHOD'],)
            if method not in allowed and method != 'RETIREMENT':
                errors.append(f'{prefix}: 路径与维修规则方式不匹配。')
            if method == 'RETIREMENT' and (match['KIND'] != 'CORRECTIVE' or not any(
                    r['IID'] == match['IID'] for r in tables.get('SimLabItemRetirement', []))):
                errors.append(f'{prefix}: 报废路径须绑定已配置报废限值的修复性维修规则。')
            stations = [match['STID']]
            order = ['IN_PLACE', 'TEST'] if method == 'IN_PLACE' else ['REMOVE', 'INSTALL', 'TEST']
            required = set(order)
        elif activity == 'OFF_ITEM':
            if rule or method or not iid or not station or kind not in ('CORRECTIVE', 'PREVENTIVE'):
                errors.append(f'{prefix}: 拆下件须填写IID/STID/KIND，RULEID/METHOD应留空。')
                continue
            if not config.get('m3'):
                errors.append(f'{prefix}: 拆下件工序方案须启用M3执行模式。')
            reachable = any(r['IID'] == iid and r['REPAIR_STID'] == station
                            for r in tables.get('SimLabRepairLocation', []))
            if not reachable:
                errors.append(f'{prefix}: 必须绑定该部件已配置的维修目的地。')
            stations = [station]
            order = ['DIAGNOSE', 'SERVICE', 'TEST']
            required = set(order)
        elif activity in ('PREPARATION', 'CALENDAR', 'INSPECTION'):
            if method or iid or station or kind:
                errors.append(f'{prefix}: 仅填写活动类型、规则标识与方案。')
            table, id_field = {'PREPARATION': ('SimLabFlightRule', 'MTID'),
                'CALENDAR': ('SimLabPlannedMaintenance', 'PMID'),
                'INSPECTION': ('SimLabFlightInspection', 'CHECKID')}[activity]
            match = next((r for r in tables.get(table, []) if r[id_field] == rule), None)
            if not match:
                errors.append(f'{prefix}: 活动规则不存在。')
                continue
            if activity == 'PREPARATION':
                missions = [m for m in config['missions'] if m['type'] == rule]
                stations = sorted({f['home'] for f in config['fleets'] for m in missions
                    if f['sid'] == m['sid'] and m['location'] in (f['unit'], f['home'])})
            else:
                stations = [f['home'] for f in config['fleets'] if f['sid'] == match['SID'] and f['unit'] == match['USTID']]
        else:
            errors.append(f'{prefix}: 不支持的活动类型。')
            continue
        nodes = plans[name]
        actions = {}
        for n in nodes:
            if n['action'] != 'CUSTOM':
                if n['action'] in actions:
                    errors.append(f'{prefix}: 业务动作{n["action"]}只能出现一次。')
                actions[n['action']] = n['id']
        if not required <= actions.keys():
            errors.append(f'{prefix}: 缺少必要动作 {", ".join(sorted(required-actions.keys()))}。')
        allowed = required | ({'DIAGNOSE'} if activity == 'MAINTENANCE' and method != 'RETIREMENT' else set())
        if actions.keys()-allowed:
            errors.append(f'{prefix}: 包含此活动不使用的业务动作。')
        full_order = (['DIAGNOSE'] if 'DIAGNOSE' in actions and activity == 'MAINTENANCE' else []) + order
        for a, b in zip(full_order, full_order[1:]):
            if a in actions and b in actions and actions[a] not in ancestors(nodes, actions[b]):
                errors.append(f'{prefix}: {b}必须在{a}完成后执行。')
        for stid in stations:
            for n in nodes:
                for rid, qty in n['resources'].items():
                    if qty > config['capacity'].get((stid, rid), 0):
                        errors.append(f'{prefix}/{n["id"]}: {stid}资源{rid}容量不足。')
                _check_common(stid, n, config.get('schedules', {}), config['horizon'], errors)
    return dict(plans=plans, bindings=bindings), errors


def bound_plan(config, activity, rule='', method='', iid='', station='', kind=''):
    return config.get('workflows', {}).get('bindings', {}).get((activity, rule, method, iid, station, kind))


def bind_flight_activities(config):
    """Attach selected plans to existing preparation/check rule instances."""
    errors, pools = [], {}
    for mission in config['missions']:
        plan = bound_plan(config, 'PREPARATION', mission['type'])
        pool = mission['location'], mission['sid']
        pools.setdefault(pool, set()).add(plan)
        if plan:
            mission['ground_rule'] = dict(mission.get('ground_rule') or
                dict(task='', resources={}, daily_ready=False), workflow_plan=plan)
    for pool, plans in pools.items():
        if len(plans) > 1:
            errors.append(f'SimLabWorkflowBinding.{pool}: 同一选机池须使用相同出动准备工序方案。')
    for rule in config.get('planned', []):
        activity = 'INSPECTION' if 'flight_interval' in rule else 'CALENDAR'
        plan = bound_plan(config, activity, rule['id'])
        if plan:
            rule['workflow_plan'] = plan
    return errors
