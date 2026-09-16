"""Pure compilation and validation for the explicit M3 supply network."""
import math

from .schema import TABLES, effective


M3_TABLES = {
    'SimLabExecution', 'SimLabSupplyRoute', 'SimLabSupplyPolicy',
    'SimLabRepairLocation', 'SimLabServiceRoute', 'SimLabMaintenanceRule',
    'SimLabMaintenanceStep', 'SimLabOffItemService', 'SimLabItemPreventive',
}


def canonicalize_tables(tables):
    """Return input rows with every schema default materialized as text."""
    result = {}
    for name in set(tables) | M3_TABLES:
        if name not in TABLES:
            continue
        result[name] = [
            {field['id']: effective(row, field) for field in TABLES[name]}
            for row in tables.get(name, [])
        ]
    return result


def _num(row, column):
    try:
        return float(row.get(column, '') or 0)
    except (TypeError, ValueError):
        return math.nan


def _tree(tables):
    errors, parents = [], {}
    for index, row in enumerate(tables.get('StationStructure', []), 1):
        child, parent = row.get('STID', ''), row.get('MSTID', '')
        if child in parents:
            errors.append(f'StationStructure 第 {index} 行.{child}: M3 每个站点只能有一个直接上级。')
        parents[child] = parent
        for field in ('TFRMS', 'TTOMS'):
            if _num(row, field) != 0:
                errors.append(f'StationStructure 第 {index} 行.{field}: M3 使用显式路线，此字段必须为零。')
    depths = {}
    for station in {r.get('STID', '') for r in tables.get('Station', [])}:
        chain, node = [], station
        while node in parents:
            if node in chain:
                errors.append(f'StationStructure.{station}: 保障层级存在循环。')
                break
            chain.append(node)
            node = parents[node]
        depths[station] = len(chain) + 1
        if depths[station] > 3:
            errors.append(f'StationStructure.{station}: M3 保障层级深度不能超过三级。')
    return parents, depths, errors


def _is_ancestor(ancestor, descendant, parents):
    seen, node = set(), descendant
    while node in parents and node not in seen:
        seen.add(node)
        node = parents[node]
        if node == ancestor:
            return True
    return False


def _has_path(routes, iid, start, destination):
    frontier, visited = [start], {start}
    while frontier:
        node = frontier.pop()
        for row in routes:
            if row.get('IID') != iid or row.get('FROM_STID') != node:
                continue
            target = row.get('TO_STID')
            if target == destination:
                return True
            if target not in visited:
                visited.add(target)
                frontier.append(target)
    return False


def compile_supply(tables, point, horizon):
    """Compile tree metadata and validate routes, policies and repair destinations."""
    canonical = canonicalize_tables(tables)
    errors = []
    parents, depths, tree_errors = _tree(canonical)
    errors.extend(tree_errors)

    route_specs = (
        ('SimLabSupplyRoute', '补给路线', lambda source, target: _is_ancestor(source, target, parents)),
        ('SimLabServiceRoute', '送修路线', lambda source, target: _is_ancestor(target, source, parents)),
    )
    for table, label, direction_ok in route_specs:
        seen = set()
        for index, row in enumerate(canonical[table], 1):
            source, target = row['FROM_STID'], row['TO_STID']
            key = row['IID'], source, target
            if key in seen:
                errors.append(f'{table} 第 {index} 行: {label}的部件、起点和终点重复。')
            seen.add(key)
            if source == target or not direction_ok(source, target):
                errors.append(f'{table} 第 {index} 行: {label}必须沿保障层级的正确方向连接祖先与后代。')

    inbound = {(row['IID'], row['TO_STID']) for row in canonical['SimLabSupplyRoute']}
    periodic_orders = 0
    for index, row in enumerate(canonical['SimLabSupplyPolicy'], 1):
        target = int(float(row['TARGET_QTY'])) if row['TARGET_QTY'] else 0
        threshold = int(float(row['REORDER_QTY'])) if row['REORDER_QTY'] else 0
        trigger = row['TRIGGER']
        if (row['IID'], row['STID']) not in inbound:
            errors.append(f'SimLabSupplyPolicy 第 {index} 行 {row["IID"]}@{row["STID"]}: 外部补货策略缺少匹配入向补给路线。')
        if target <= 0:
            errors.append(f'SimLabSupplyPolicy 第 {index} 行.TARGET_QTY: 必须为正整数。')
        if trigger == 'THRESHOLD':
            if target <= threshold:
                errors.append(f'SimLabSupplyPolicy 第 {index} 行.TARGET_QTY: 必须大于 REORDER_QTY。')
            if row['INTERVAL_H'] not in ('', None):
                errors.append(f'SimLabSupplyPolicy 第 {index} 行.INTERVAL_H: 临界模式不使用此字段，必须留空。')
            # FIRST_H has schema default zero; explicit non-zero is still invalid.
            if _num(row, 'FIRST_H') != 0:
                errors.append(f'SimLabSupplyPolicy 第 {index} 行.FIRST_H: 临界模式不使用此字段。')
        elif trigger == 'PERIODIC':
            interval, first = _num(row, 'INTERVAL_H'), _num(row, 'FIRST_H')
            if interval < 1e-6:
                errors.append(f'SimLabSupplyPolicy 第 {index} 行.INTERVAL_H: 周期间隔必须至少为 1e-6 小时。')
            if row['REORDER_QTY'] not in ('', None):
                errors.append(f'SimLabSupplyPolicy 第 {index} 行.REORDER_QTY: 周期模式不使用此字段，必须留空。')
            if interval >= 1e-6 and first <= horizon:
                periodic_orders += math.floor((horizon - first) / interval) + 1
    if periodic_orders > 200000:
        errors.append('SimLabSupplyPolicy: 周期触发每轮最多生成 200000 份订单。')

    locations = canonical['SimLabRepairLocation']
    for index, row in enumerate(locations, 1):
        source, repair = row['FROM_STID'], row['REPAIR_STID']
        if source != repair and not _is_ancestor(repair, source, parents):
            errors.append(f'SimLabRepairLocation 第 {index} 行: 维修地点必须为本站或其祖先站点。')
        if source != repair and not _has_path(canonical['SimLabServiceRoute'], row['IID'], source, repair):
            errors.append(f'SimLabRepairLocation 第 {index} 行 {row["IID"]}@{source}: 缺少到 {repair} 的显式送修路线。')

    links = {
        child: {'parent': parent, 'inward': 0.0, 'outward': 0.0}
        for child, parent in parents.items()
    }
    return canonical, links, depths, errors
