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


def _draw_methods(rule):
    """Methods a rule can select when a job is first created."""
    if rule is None:
        return set()
    method = rule['METHOD']
    if method != 'MIXED':
        return {method}
    # Missing probability is reported separately; keep later coverage checks
    # conservative instead of raising before ModelError can aggregate it.
    if rule['REPLACE_P'] == '':
        return {'IN_PLACE', 'REPLACE'}
    probability = float(rule['REPLACE_P'])
    if probability == 0:
        return {'IN_PLACE'}
    if probability == 1:
        return {'REPLACE'}
    return {'IN_PLACE', 'REPLACE'}


def _executable_methods(rule):
    """Methods a destination rule has steps to execute after a previous draw."""
    if rule is None:
        return set()
    return ({'IN_PLACE', 'REPLACE'} if rule['METHOD'] == 'MIXED'
            else {rule['METHOD']})


def _stock_quantity(row):
    return int(float(row['ISTOH'] or row['STSIZ'] or 0))


def _reachable_stock_sites(iid, canonical, point, locations):
    """Sites where a loose physical item can be stocked or represented in transit."""
    sites = {
        row['STID'] for row in canonical.get('StockAllocation', [])
        if row['POINT'] == point and row['IID'] == iid and _stock_quantity(row) > 0
    }
    sites.update(
        destination for (item, _), destination in locations.items() if item == iid
    )
    routes = [row for row in canonical['SimLabSupplyRoute'] if row['IID'] == iid]
    sites.update(
        row['STID'] for row in canonical.get('SimLabPurchasePolicy', [])
        if row['POINT'] == point and row['IID'] == iid
    )
    changed = True
    while changed:
        changed = False
        for row in routes:
            if row['FROM_STID'] in sites and row['TO_STID'] not in sites:
                sites.add(row['TO_STID'])
                changed = True
    return sites


def compile_service(tables, canonical, children, fleets, capacity, task_resources,
                    repairs, replacements, depot_processes, schedules, horizon):
    errors = []
    rules = canonical['SimLabMaintenanceRule']
    retirement_items = {row['IID'] for row in canonical['SimLabItemRetirement']}
    bindings = tables.get('SimLabWorkflowBinding', [])
    def maintenance_bound(rule, method):
        return any(r.get('ACTIVITY') == 'MAINTENANCE' and r.get('RULEID') == rule['RULEID']
                   and r.get('METHOD') == method for r in bindings)

    def off_bound(iid, station, kind):
        return any(r.get('ACTIVITY') == 'OFF_ITEM' and r.get('IID') == iid
                   and r.get('STID') == station and r.get('KIND') == kind for r in bindings)

    path_steps = {'IN_PLACE': {'DIAGNOSE', 'IN_PLACE', 'TEST'},
                  'REPLACE': {'DIAGNOSE', 'REMOVE', 'INSTALL', 'TEST'},
                  'RETIREMENT': {'REMOVE', 'INSTALL', 'TEST'}}

    def legacy_methods(rule):
        methods = _executable_methods(rule)
        if rule['IID'] in retirement_items and rule['KIND'] == 'CORRECTIVE':
            methods.add('RETIREMENT')
        return {m for m in methods if not maintenance_bound(rule, m)}
    rule_by_id = {row['RULEID']: row for row in rules}
    rule_by_context = {
        (row['MID'], row['IID'], row['STID'], row['KIND']): row for row in rules
    }
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
            'IN_PLACE': ({'DIAGNOSE', 'IN_PLACE', 'REMOVE', 'INSTALL', 'TEST'}
                         if rule['IID'] in retirement_items and rule['KIND'] == 'CORRECTIVE'
                         else {'DIAGNOSE', 'IN_PLACE', 'TEST'}),
            'REPLACE': {'DIAGNOSE', 'REMOVE', 'INSTALL', 'TEST'},
            'MIXED': {'DIAGNOSE', 'IN_PLACE', 'REMOVE', 'INSTALL', 'TEST'},
        }[rule['METHOD']]
        if row['STEP'] not in allowed:
            errors.append(
                f'SimLabMaintenanceStep 第 {index} 行.STEP: {rule["METHOD"]} 不使用此工序。'
            )
        if row['TASK'] and any(row['STEP'] in path_steps[m] for m in legacy_methods(rule)):
            errors.extend(_resource_errors(
                'SimLabMaintenanceStep', index, rule['STID'], row['TASK'],
                task_resources, capacity))
            errors.extend(_shift_errors(
                'SimLabMaintenanceStep', index, rule['STID'], row['TASK'],
                task_resources, schedules, horizon))

    for index, rule in enumerate(rules, 1):
        required = set().union(*(path_steps[m] - {'DIAGNOSE'}
                                for m in legacy_methods(rule) if m != 'RETIREMENT'))
        missing = required - steps_by_rule.get(rule['RULEID'], set())
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
        if row['TASK'] and not off_bound(*key):
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
        if off_bound(rule['IID'], repair, rule['KIND']):
            configured = required
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
    point = canonical['Control'][0]['APID']
    stock_rows = [row for row in canonical.get('StockAllocation', []) if row['POINT'] == point]
    max_util = max((fleet['util'] for fleet in fleets), default=0)
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
            cycles = (1 + int(elapsed // interval) if initial >= interval
                      else int((initial + elapsed) // interval))
            predictable_jobs += fleet['quantity'] * quantity * cycles
        # Initial stock starts at zero PM-cycle age. Count each physical leaf once,
        # including leaves contained in stocked parent assemblies.
        stock_quantity = 0
        for stock in stock_rows:
            root_quantity = _stock_quantity(stock)
            if stock['IID'] == iid:
                stock_quantity += root_quantity
            for child in children.get(stock['IID'], []):
                if child['iid'] == iid:
                    stock_quantity += root_quantity * child['quantity']
        stock_elapsed = horizon if row['CLOCK'] == 'CALENDAR' else horizon * max_util
        predictable_jobs += stock_quantity * int(stock_elapsed // interval)
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

    # A loose CALENDAR-clocked spare can become due in stock or while represented
    # at a shipment destination. It needs the same explicit off-item path as a
    # removed part. A leaf attached inside a stocked assembly remains attached,
    # so it needs a parent/leaf rule at each reachable assembly site instead.
    for iid, clock in preventive_by_iid.items():
        if clock['CLOCK'] != 'CALENDAR':
            continue
        for station in sorted(_reachable_stock_sites(iid, canonical, point, locations)):
            repair = locations.get((iid, station))
            if repair is None:
                errors.append(
                    f'SimLabItemPreventive CALENDAR {iid}@{station}: '
                    '库存或在途实物缺少显式维修地点映射。'
                )
                continue
            missing = set() if off_bound(iid, repair, 'PREVENTIVE') else {'DIAGNOSE', 'SERVICE', 'TEST'} - off_steps.get(
                (iid, repair, 'PREVENTIVE'), set())
            if missing:
                errors.append(
                    f'SimLabOffItemService {iid}@{repair}/PREVENTIVE: '
                    f'缺少 CALENDAR 库存件工序 {", ".join(sorted(missing))}。'
                )
        for parent, parts in children.items():
            if not any(part['iid'] == iid for part in parts):
                continue
            for station in sorted(_reachable_stock_sites(parent, canonical, point, locations)):
                if (parent, iid, station, 'PREVENTIVE') not in rule_by_context:
                    errors.append(
                        f'SimLabItemPreventive CALENDAR {parent}/{iid}@{station}: '
                        '库存总成内叶子缺少 PREVENTIVE 规则。'
                    )

    def corrective_rule(mid, iid, station):
        explicit = rule_by_context.get((mid, iid, station, 'CORRECTIVE'))
        if explicit:
            return explicit
        if (mid, iid, station) in replacements:
            return {'METHOD': 'REPLACE', 'REPLACE_P': ''}
        return None

    # Validate every fault context reached by deployed physical structures. A
    # parent IN_PLACE path repairs children at home; a parent REPLACE path repairs
    # still-attached children at the explicit parent destination.
    for fleet in fleets:
        for part in fleet['parts']:
            parent_rule = corrective_rule(fleet['sid'], part['iid'], fleet['home'])
            if parent_rule is None:
                errors.append(
                    f'SimLabMaintenanceRule: {fleet["sid"]}/{part["iid"]}@{fleet["home"]} '
                    '缺少 CORRECTIVE 规则。'
                )
                continue
            if part['iid'] not in children:
                continue
            parent_methods = _draw_methods(parent_rule)
            child_sites = set()
            if 'IN_PLACE' in parent_methods:
                child_sites.add(fleet['home'])
            if 'REPLACE' in parent_methods:
                destination = locations.get((part['iid'], fleet['home']))
                if destination:
                    child_sites.add(destination)
            for child in children[part['iid']]:
                for station in child_sites:
                    if corrective_rule(part['iid'], child['iid'], station) is None:
                        errors.append(
                            f'SimLabMaintenanceRule: {part["iid"]}/{child["iid"]}@{station} '
                            '缺少 CORRECTIVE 规则。'
                        )

    # A lifetime limit can force replacement even when the normal corrective
    # method is in-place. Explicit rules therefore carry REMOVE/INSTALL/TEST;
    # legacy contexts reuse their ItemReplacement definition.
    for fleet in fleets:
        for part in fleet['parts']:
            contexts = [(fleet['sid'], part['iid'], fleet['home'])]
            parent_rule = corrective_rule(fleet['sid'], part['iid'], fleet['home'])
            child_sites = {fleet['home']}
            if 'IN_PLACE' in _draw_methods(parent_rule):
                child_sites.add(fleet['home'])
            if 'REPLACE' in _draw_methods(parent_rule):
                destination = locations.get((part['iid'], fleet['home']))
                if destination:
                    child_sites.add(destination)
            contexts.extend(
                (part['iid'], child['iid'], station)
                for child in children.get(part['iid'], [])
                for station in child_sites
            )
            for mid, iid, station in contexts:
                if iid not in retirement_items:
                    continue
                explicit = rule_by_context.get((mid, iid, station, 'CORRECTIVE'))
                if explicit is not None:
                    missing = set() if maintenance_bound(explicit, 'RETIREMENT') else {'REMOVE', 'INSTALL', 'TEST'} - steps_by_rule.get(explicit['RULEID'], set())
                    if missing:
                        errors.append(
                            f'SimLabMaintenanceRule {explicit["RULEID"]}: '
                            f'报废换件缺少工序 {", ".join(sorted(missing))}。')
                if explicit is None and (mid, iid, station) not in replacements:
                    errors.append(
                        f'SimLabItemRetirement.{iid}: 报废换件上下文 '
                        f'{mid}/{iid}@{station} 缺少 CORRECTIVE 或 ItemReplacement 定义。'
                    )

    # A queued PM can survive parent relocation in two ways: MINIMAL in-place
    # correction leaves the failed child attached, or a different leaf fails and
    # the healthy PM-bearing sibling moves with the parent. The destination must
    # execute every method that the source PM rule could already have selected.
    minimal_items = {
        row['IID'] for row in canonical.get('SimLabItemAging', []) if row['REPAIR'] == 'MINIMAL'
    }
    for fleet in fleets:
        source = fleet['home']
        for part in fleet['parts']:
            parent_rule = corrective_rule(fleet['sid'], part['iid'], source)
            if part['iid'] not in children or 'REPLACE' not in _draw_methods(parent_rule):
                continue
            destination = locations.get((part['iid'], source))
            if not destination or destination == source:
                continue
            total_leaf_quantity = sum(child['quantity'] for child in children[part['iid']])
            for child in children[part['iid']]:
                iid = child['iid']
                child_corrective = corrective_rule(part['iid'], iid, destination)
                failed_leaf_survives = (
                    iid in minimal_items and
                    'IN_PLACE' in _draw_methods(child_corrective)
                )
                healthy_sibling_can_move = total_leaf_quantity > 1
                if not failed_leaf_survives and not healthy_sibling_can_move:
                    continue
                source_pm = rule_by_context.get((part['iid'], iid, source, 'PREVENTIVE'))
                if source_pm is None:
                    continue
                destination_pm = rule_by_context.get(
                    (part['iid'], iid, destination, 'PREVENTIVE'))
                selected = _draw_methods(source_pm)
                executable = _executable_methods(destination_pm)
                missing = selected - executable
                if missing:
                    errors.append(
                        f'SimLabMaintenanceRule {source_pm["RULEID"]}: 父项换件到 {destination} 后，'
                        f'目的站 PREVENTIVE 规则不能执行已抽维修方式 {", ".join(sorted(missing))}。'
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
