"""Validation for explicit M3 corrective and preventive service inputs."""


def _resource_errors(table, index, station, task, task_resources, capacity):
    errors = []
    for resource, quantity in task_resources.get(task, {}).items():
        if capacity.get((station, resource), 0) < quantity:
            errors.append(
                f'{table} 第 {index} 行.TASK {task}@{station}: '
                f'资源 {resource} 数量不足，无法执行。'
            )
    return errors


def _intersect(left, right):
    result = []
    for left_start, left_end in left:
        for right_start, right_end in right:
            start, end = max(left_start, right_start), min(left_end, right_end)
            if start < end:
                result.append((start, end))
    return result


def _shift_errors(table, index, station, task, task_resources, schedules, horizon):
    common = [(0, horizon)]
    for resource, quantity in task_resources.get(task, {}).items():
        if quantity:
            common = _intersect(common, schedules.get((station, resource), [(0, horizon)]))
    if not common:
        return [f'{table} 第 {index} 行.TASK {task}@{station}: 资源组合在仿真期内没有共同班次。']
    return []


def compile_service(tables, canonical, children, fleets, capacity, task_resources,
                    repairs, replacements, depot_processes, schedules, horizon):
    errors = []
    rules = canonical['SimLabMaintenanceRule']
    rule_by_id = {row['RULEID']: row for row in rules}
    context_seen = set()
    locations = {
        (row['IID'], row['FROM_STID']): row['REPAIR_STID']
        for row in canonical['SimLabRepairLocation']
    }

    for index, row in enumerate(rules, 1):
        context = row['MID'], row['IID'], row['STID'], row['KIND']
        if context in context_seen:
            errors.append(f'SimLabMaintenanceRule 第 {index} 行: 同一维修上下文重复。')
        context_seen.add(context)
        probability = row['REPLACE_P']
        if row['METHOD'] == 'MIXED':
            if probability == '':
                errors.append(f'SimLabMaintenanceRule 第 {index} 行.REPLACE_P: MIXED 必须填写换件概率。')
        elif probability != '':
            errors.append(f'SimLabMaintenanceRule 第 {index} 行.REPLACE_P: 仅 MIXED 方式允许填写。')

        # The item must be a direct child of MID; this rejects accidental slot ambiguity.
        direct = any(
            relation.get('MMID') == row['MID'] and relation.get('MID') == row['IID']
            for relation in tables.get('MaterielStructure', [])
        )
        if not direct:
            errors.append(f'SimLabMaintenanceRule 第 {index} 行: MID/IID 必须是直接母子项。')

    steps_by_rule = {}
    for index, row in enumerate(canonical['SimLabMaintenanceStep'], 1):
        rule = rule_by_id.get(row['RULEID'])
        if not rule:
            continue
        steps_by_rule.setdefault(row['RULEID'], set()).add(row['STEP'])
        allowed = {
            'IN_PLACE': {'DIAGNOSE', 'IN_PLACE', 'TEST'},
            'REPLACE': {'DIAGNOSE', 'REMOVE', 'INSTALL', 'TEST'},
            'MIXED': {'DIAGNOSE', 'IN_PLACE', 'REMOVE', 'INSTALL', 'TEST'},
        }[rule['METHOD']]
        if row['STEP'] not in allowed:
            errors.append(
                f'SimLabMaintenanceStep 第 {index} 行.STEP: {rule["METHOD"]} 不使用此工序。'
            )
        if row['TASK']:
            errors.extend(_resource_errors(
                'SimLabMaintenanceStep', index, rule['STID'], row['TASK'],
                task_resources, capacity))
            errors.extend(_shift_errors(
                'SimLabMaintenanceStep', index, rule['STID'], row['TASK'],
                task_resources, schedules, horizon))

    required_by_method = {
        'IN_PLACE': {'IN_PLACE', 'TEST'},
        'REPLACE': {'REMOVE', 'INSTALL', 'TEST'},
        'MIXED': {'IN_PLACE', 'REMOVE', 'INSTALL', 'TEST'},
    }
    for index, rule in enumerate(rules, 1):
        missing = required_by_method[rule['METHOD']] - steps_by_rule.get(rule['RULEID'], set())
        if missing:
            errors.append(
                f'SimLabMaintenanceRule 第 {index} 行 {rule["RULEID"]}: '
                f'缺少必需工序 {", ".join(sorted(missing))}。'
            )

    off_steps = {}
    for index, row in enumerate(canonical['SimLabOffItemService'], 1):
        if row['IID'] in children and row['STEP'] == 'SERVICE':
            errors.append(f'SimLabOffItemService 第 {index} 行: 父项不允许配置 SERVICE；其子件分别维修。')
        key = row['IID'], row['STID'], row['KIND']
        off_steps.setdefault(key, set()).add(row['STEP'])
        if row['TASK']:
            errors.extend(_resource_errors(
                'SimLabOffItemService', index, row['STID'], row['TASK'],
                task_resources, capacity))
            errors.extend(_shift_errors(
                'SimLabOffItemService', index, row['STID'], row['TASK'],
                task_resources, schedules, horizon))

    for index, rule in enumerate(rules, 1):
        if rule['METHOD'] not in ('REPLACE', 'MIXED'):
            continue
        repair = locations.get((rule['IID'], rule['STID']))
        if not repair:
            errors.append(
                f'SimLabMaintenanceRule 第 {index} 行 {rule["IID"]}@{rule["STID"]}: '
                '换件方式缺少显式维修地点映射。'
            )
            continue
        required = {'DIAGNOSE', 'TEST'} if rule['IID'] in children else {'DIAGNOSE', 'SERVICE', 'TEST'}
        configured = off_steps.get((rule['IID'], repair, rule['KIND']), set())
        if rule['IID'] in children and (repair, rule['IID']) in depot_processes:
            configured = configured | {'DIAGNOSE', 'TEST'}
        missing = required - configured
        if missing:
            errors.append(
                f'SimLabOffItemService {rule["IID"]}@{repair}/{rule["KIND"]}: '
                f'缺少拆下件工序 {", ".join(sorted(missing))}。'
            )

    preventive_by_iid = {}
    predictable_jobs = 0
    for index, row in enumerate(canonical['SimLabItemPreventive'], 1):
        iid = row['IID']
        if iid in preventive_by_iid:
            errors.append(f'SimLabItemPreventive 第 {index} 行.IID: 每类部件只能配置一项预防时钟。')
        preventive_by_iid[iid] = row
        if iid in children:
            errors.append(f'SimLabItemPreventive 第 {index} 行.IID: 预防性维修仅作用于叶子部件。')
        if float(row['INTERVAL_H']) < 1e-6:
            errors.append(f'SimLabItemPreventive 第 {index} 行.INTERVAL_H: 必须至少为 1e-6 小时。')
            continue
        interval, initial = float(row['INTERVAL_H']), float(row['INITIAL_H'])
        for fleet in fleets:
            quantity = 0
            for part in fleet['parts']:
                if part['iid'] == iid:
                    quantity += part['quantity']
                for child in children.get(part['iid'], []):
                    if child['iid'] == iid:
                        quantity += part['quantity'] * child['quantity']
            elapsed = horizon if row['CLOCK'] == 'CALENDAR' else horizon * fleet['util']
            predictable_jobs += fleet['quantity'] * quantity * int((initial + elapsed) // interval)
    if predictable_jobs > 200000:
        errors.append('SimLabItemPreventive: 可预测的部件预防维修每轮最多生成 200000 份服务工单。')

    deployed_contexts = set()
    for fleet in fleets:
        for part in fleet['parts']:
            if part['iid'] in children:
                for child in children[part['iid']]:
                    deployed_contexts.add((part['iid'], child['iid'], fleet['home']))
            else:
                deployed_contexts.add((fleet['sid'], part['iid'], fleet['home']))
    for mid, iid, station in deployed_contexts:
        if iid not in preventive_by_iid:
            continue
        if (mid, iid, station, 'PREVENTIVE') not in context_seen:
            errors.append(
                f'SimLabItemPreventive.{iid}: 缺少可到达作业地点 {mid}@{station} 的 PREVENTIVE 规则。'
            )

    # New and legacy rules may not silently compete for the same context.
    legacy_contexts = set(replacements)
    corrective_contexts = {
        (rule['MID'], rule['IID'], rule['STID'])
        for rule in rules if rule['KIND'] == 'CORRECTIVE'
    }
    for index, rule in enumerate(rules, 1):
        if rule['KIND'] == 'PREVENTIVE' and rule['IID'] not in preventive_by_iid:
            errors.append(
                f'SimLabMaintenanceRule 第 {index} 行 {rule["RULEID"]}: '
                'PREVENTIVE 规则缺少部件预防时钟。'
            )
        if rule['KIND'] == 'CORRECTIVE' and (rule['MID'], rule['IID'], rule['STID']) in legacy_contexts:
            errors.append(f'SimLabMaintenanceRule 第 {index} 行: 同一上下文存在新旧非等价维修规则。')

    new_off_contexts = {
        (row['STID'], row['IID'])
        for row in canonical['SimLabOffItemService'] if row['KIND'] == 'CORRECTIVE'
    }
    for station, iid in sorted(new_off_contexts & set(repairs)):
        errors.append(f'ItemRepair.{iid}@{station}: 同一拆下件上下文存在新旧非等价维修规则。')

    # Legacy corrective behavior may coexist with new preventive behavior, but
    # every unshadowed legacy replacement still needs an explicit destination.
    for mid, iid, station in replacements:
        if (mid, iid, station) in corrective_contexts:
            continue
        repair = locations.get((iid, station))
        if not repair:
            errors.append(f'SimLabRepairLocation: 缺少旧换件 {mid}/{iid}@{station} 的显式维修地点。')
        elif (repair, iid) not in repairs and (repair, iid) not in depot_processes:
            errors.append(f'ItemRepair: 维修地点 {repair} 缺少 {iid} 的旧修复规则。')

    return errors
