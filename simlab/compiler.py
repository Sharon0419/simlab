"""Strict, documented execution subset of the full editable schema."""
import copy
import math
from .schema import TABLES, value, effective
from .validation import validate
from .operations import SUPPORTED_OPERATIONS, compile_operations
from .hierarchy import compile_structure
from .planned import compile_planned
from .aging import compile_aging
from .supply_config import M3_TABLES, compile_supply
from .service_config import compile_service

SUPPORTED = {
    'SimLabExecution': {'MODE'},
    'SimLabSupplyRoute': {'ROUTEID', 'IID', 'FROM_STID', 'TO_STID', 'TRANSIT_H'},
    'SimLabSupplyPolicy': {'POINT', 'STID', 'IID', 'TRIGGER', 'TARGET_QTY', 'REORDER_QTY', 'FIRST_H', 'INTERVAL_H'},
    'SimLabPurchasePolicy': {'POINT', 'STID', 'IID', 'TRIGGER', 'TARGET_QTY', 'REORDER_QTY', 'FIRST_H', 'INTERVAL_H', 'LEAD_H'},
    'SimLabItemRetirement': {'IID', 'LIMIT_H', 'LIMIT_REPAIRS'},
    'SimLabRepairLocation': {'IID', 'FROM_STID', 'REPAIR_STID'},
    'SimLabServiceRoute': {'ROUTEID', 'IID', 'FROM_STID', 'TO_STID', 'TRANSIT_H'},
    'SimLabMaintenanceRule': {'RULEID', 'MID', 'IID', 'STID', 'KIND', 'METHOD', 'REPLACE_P'},
    'SimLabMaintenanceStep': {'RULEID', 'STEP', 'DURATION_H', 'DISTRIBUTION', 'TASK'},
    'SimLabOffItemService': {'IID', 'STID', 'KIND', 'STEP', 'DURATION_H', 'DISTRIBUTION', 'TASK'},
    'SimLabItemPreventive': {'PMID', 'IID', 'CLOCK', 'INTERVAL_H', 'INITIAL_H'},
    'SimLabItemAging': {'IID', 'SHAPE', 'SCALE_H', 'INITIAL_H', 'REPAIR'},
    'SimLabFlightInspection': {'CHECKID', 'SID', 'USTID', 'INTERVAL_H', 'DURATION_H', 'TASK'},
    'SimLabInspectionInitial': {'CHECKID', 'ASSET_NO', 'INITIAL_H'},
    'SimLabPlannedMaintenance': {'PMID', 'SID', 'USTID', 'FIRST_H', 'INTERVAL_H', 'DURATION_H', 'TASK'},
    'SimLabDepotProcess': {'LRU', 'STATION', 'DIAG_H', 'DIAG_TASK', 'TEST_H', 'TEST_TASK'},
    'System': {'SID', 'FRT'},
    'Item': {'IID', 'FRT', 'OPID', 'TYPE', 'AFFRT', 'CRIT', 'TRACK'},
    'MaterielStructure': {'MID', 'MMID', 'QTYPM', 'ENVF'},
    'Station': {'STID', 'TYPE', 'XCOORD', 'YCOORD', 'LEVL', 'LINDX'},
    'StationStructure': {'STID', 'MSTID', 'TFRMS', 'TTOMS'},
    'Unit': {'UNID', 'STID'},
    'SystemDeployment': {'SID', 'USTID', 'QTYPS', 'UTIL'},
    'StockAllocation': {'POINT', 'IID', 'STID', 'STSIZ', 'ISTOH'},
    'ItemRepair': {'IID', 'STID', 'DIRPT', 'DIRPTID', 'DIRPD'},
    'ItemReplacement': {'MID', 'IID', 'STID', 'SURPT', 'SURPTID', 'SURPD'},
    'Resource': {'RID', 'TYPE'},
    'ResourceAllocation': {'POINT', 'RID', 'STID', 'RQTY'},
    'Tasks': {'TID'},
    'TaskResource': {'TID', 'RID', 'QTY'},
    'Control': {'NREPS', 'SIMPE', 'RSEED', 'APID', 'RCINT', 'RMVFR', 'ENLOG',
                'ENPM', 'ENLAT', 'ENALU', 'RELOP'},
}
DOCUMENTARY = {'DESCR', 'NOTE', 'UTXT1', 'UTXT2'}
SUPPORTED.update(SUPPORTED_OPERATIONS)

class ModelError(ValueError):
    def __init__(self, errors):
        self.errors = errors
        super().__init__('\n'.join(errors))

def equal(a, b):
    if str(a) == str(b):
        return True
    try:
        return float(a) == float(b)
    except (ValueError, TypeError):
        return False

def capability_errors(tables, m3=False):
    errors = []
    for name, rows in tables.items():
        if not rows:
            continue
        if name not in SUPPORTED:
            errors.append(f'{name}: 支持建模与交换，当前引擎尚不支持计算此表。')
            continue
        if name in M3_TABLES and name != 'SimLabExecution' and not m3:
            errors.append(f'{name}: 仅在 SimLabExecution.MODE=M3 时支持计算。')
            continue
        for i, row in enumerate(rows, 1):
            for field in TABLES[name]:
                column = field['id']
                val = row.get(column, '')
                if val not in ('', None) and column not in SUPPORTED[name] | DOCUMENTARY:
                    if not equal(val, field['default']):
                        # Zero direct system-independent values are harmless only here.
                        if name == 'ItemRepair' and column == 'SURPT' and equal(val, '0'):
                            continue
                        errors.append(f'{name} 第 {i} 行.{column}: 当前引擎不支持此非默认设置。')
    return errors

def compile_model(tables):
    execution = tables.get('SimLabExecution', []) if isinstance(tables, dict) else []
    m3 = len(execution) == 1 and isinstance(execution[0], dict) and execution[0].get('MODE') == 'M3'
    # The original dictionary makes these two legacy transport fields mandatory.
    # M3 replaces them with explicit routes, so omitted values canonically mean zero.
    candidate = copy.deepcopy(tables)
    if m3:
        for row in candidate.get('StationStructure', []):
            row.setdefault('TFRMS', '0')
            row.setdefault('TTOMS', '0')
    tables = candidate
    errors = validate(tables)
    if errors:
        raise ModelError(errors)
    errors = capability_errors(tables, m3)
    if errors:
        raise ModelError(errors)
    def rows(t): return tables.get(t, [])
    def val(t, row, col, fallback=''): return value(t, row, col, fallback)
    def num(t, row, col, fallback='0'): return float(val(t, row, col, fallback))
    if len(rows('Control')) != 1:
        raise ModelError(['Control: 需要且只能有一行仿真控制参数。'])
    c = rows('Control')[0]
    horizon, interval = num('Control', c, 'SIMPE'), num('Control', c, 'RCINT')
    reps = int(num('Control', c, 'NREPS'))
    try:
        seed = int(val('Control', c, 'RSEED'))
        if seed < 0 or seed > 2**128-1:
            raise ValueError()
    except ValueError:
        errors.append('Control.RSEED: 本引擎需要 0 至 2^128-1 的整数种子。')
        seed = 0
    if reps > 1000 or horizon > 876000 or math.ceil(horizon / interval) > 10000:
        errors.append('运行规模超限：重复次数≤1000，时长≤876000小时，采样点≤10000。')
    for flag in ('ENPM', 'ENLAT', 'ENALU'):
        if val('Control', c, flag) != 'N':
            errors.append(f'Control.{flag}: 本引擎暂不支持，请设为 N。')
    if val('Control', c, 'RELOP') != 'SERIAL':
        errors.append('Control.RELOP: 本引擎支持 SERIAL 串联系统。')
    systems = {r['SID']: r for r in rows('System')}
    items = {r['IID']: r for r in rows('Item')}
    stations = {r['STID']: r for r in rows('Station')}
    units = {r['UNID']: r['STID'] for r in rows('Unit')}
    resources = {r['RID']: r for r in rows('Resource')}
    for sid, row in systems.items():
        if num('System', row, 'FRT') != 0:
            errors.append(f'System.{sid}.FRT: 本版使用部件故障，请将系统独立故障率设为 0。')
    for iid, row in items.items():
        if val('Item', row, 'TYPE') not in ('LRU', 'SRU') or val('Item', row, 'OPID') != 'OPHOURS' or num('Item', row, 'CRIT') != 1:
            errors.append(f'Item.{iid}: 本版支持 TYPE=LRU/SRU、OPID=OPHOURS、CRIT=1。')
    for rid, row in resources.items():
        if val('Resource', row, 'TYPE') != 'SPECIAL':
            errors.append(f'Resource.{rid}: 本版支持固定数量 SPECIAL 资源。')
    point = val('Control', c, 'APID')
    canonical = None
    if m3:
        canonical, links, _, supply_errors = compile_supply(tables, point, horizon)
        errors.extend(supply_errors)
    else:
        links = {}
        for row in rows('StationStructure'):
            child, parent = row['STID'], row['MSTID']
            if child in links:
                errors.append(f'StationStructure.{child}: 本版仅支持一个上级站点。')
            links[child] = {'parent': parent, 'inward': num('StationStructure', row, 'TFRMS'),
                            'outward': num('StationStructure', row, 'TTOMS')}
        for child, link in links.items():
            if child == link['parent'] or link['parent'] in links:
                errors.append(f'StationStructure.{child}: 本版支持两级无环保障网络。')
    stock = {}
    for row in rows('StockAllocation'):
        if row['POINT'] == point:
            stock[(row['STID'], row['IID'])] = int(num('StockAllocation', row, 'ISTOH', val('StockAllocation', row, 'STSIZ')))
    capacity = {}
    for row in rows('ResourceAllocation'):
        if row['POINT'] == point:
            qty = num('ResourceAllocation', row, 'RQTY')
            if not qty.is_integer():
                errors.append('ResourceAllocation.RQTY: 本引擎需要整数资源数量。')
            capacity[(row['STID'], row['RID'])] = int(qty)
    tasks = {}
    for row in rows('TaskResource'):
        tasks.setdefault(row['TID'], {})[row['RID']] = int(num('TaskResource', row, 'QTY'))
    def requirements(tid, station):
        result = tasks.get(tid, {})
        for rid, qty in result.items():
            if capacity.get((station, rid), 0) < qty:
                errors.append(f'任务 {tid} @ {station}: 资源 {rid} 数量不足，无法执行。')
        return result
    def duration(t, row, field, distribution):
        dist = val(t, row, distribution)
        if dist not in ('', '<EXP>'):
            errors.append(f'{t}.{distribution}: 本版支持留空（固定时长）或 <EXP>（指数分布）。')
        return {'mean': num(t, row, field), 'random': dist == '<EXP>'}
    repairs = {}
    for row in rows('ItemRepair'):
        repairs[(row['STID'], row['IID'])] = {
            'time': duration('ItemRepair', row, 'DIRPT', 'DIRPD'),
            'resources': requirements(val('ItemRepair', row, 'DIRPTID'), row['STID'])}
    replacements = {}
    for row in rows('ItemReplacement'):
        replacements[(row['MID'], row['IID'], row['STID'])] = {
            'time': duration('ItemReplacement', row, 'SURPT', 'SURPD'),
            'resources': requirements(val('ItemReplacement', row, 'SURPTID'), row['STID'])}
    structures, children, structure_errors = compile_structure(tables)
    errors.extend(structure_errors)
    aging, aging_errors = compile_aging(tables, children, horizon)
    errors.extend(aging_errors)
    depot_processes = {}
    for row in rows('SimLabDepotProcess'):
        parent, station = row['LRU'], row['STATION']
        if parent not in children:
            errors.append(f'SimLabDepotProcess.{parent}: 仅用于带 SRU 子件的 LRU。')
        depot_processes[(station, parent)] = {
            'diagnosis': {'time': {'mean': float(row['DIAG_H']), 'random': False}, 'resources': requirements(row.get('DIAG_TASK', ''), station)},
            'test': {'time': {'mean': float(row['TEST_H']), 'random': False}, 'resources': requirements(row.get('TEST_TASK', ''), station)}}
    for station, iid in repairs:
        if iid in children:
            errors.append(f'ItemRepair.{iid}@{station}: 父 LRU 不能同时配置直接修复；请使用子件维修和 SimLabDepotProcess。')
    fleets = []
    for row in rows('SystemDeployment'):
        sid, location = row['SID'], row['USTID']
        home = units.get(location, location)
        if home not in stations:
            errors.append(f'SystemDeployment.{location}: 无法确定具体站点。')
            continue
        if not structures.get(sid):
            errors.append(f'SystemDeployment.{sid}: 缺少系统组成。')
        util = num('SystemDeployment', row, 'UTIL')
        if util > 1:
            errors.append('SystemDeployment.UTIL: OPHOURS 本版要求使用率在 0 至 1 之间。')
        root = links.get(home, {}).get('parent', home)
        if m3:
            seen = set()
            while root in links and root not in seen:
                seen.add(root)
                root = links[root]['parent']
        for part in structures.get(sid, []):
            iid = part['iid']
            if not m3:
                if iid in children:
                    if (root, iid) not in depot_processes:
                        errors.append(f'SimLabDepotProcess: 缺少 {iid}@{root} 的检测与测试工序。')
                    for child in children[iid]:
                        if (root, child['iid']) not in repairs or (iid, child['iid'], root) not in replacements:
                            errors.append(f'SRU {child["iid"]}@{root}: 缺少直接修复或父 LRU 内部更换规则。')
                elif (root, iid) not in repairs:
                    errors.append(f'ItemRepair: 缺少 {iid} 在 {root} 的直接修复规则。')
                if (sid, iid, home) not in replacements:
                    errors.append(f'ItemReplacement: 缺少 {sid}/{iid} 在 {home} 的更换规则。')
        fleets.append({'sid': sid, 'home': home, 'unit': location, 'root': root,
                       'quantity': int(num('SystemDeployment', row, 'QTYPS')), 'util': util,
                       'parts': structures.get(sid, [])})
    count = sum(f['quantity'] for f in fleets)
    if count == 0 or count > 2000:
        errors.append('SystemDeployment: 系统总数必须在 1 至 2000 之间。')
    def physical_size(iid):
        return 1 + sum(p['quantity'] for p in children.get(iid, []))
    installed_count = sum(f['quantity'] * sum(p['quantity'] * physical_size(p['iid']) for p in f['parts']) for f in fleets)
    if installed_count + sum(qty * physical_size(iid) for (_, iid), qty in stock.items()) > 200000:
        errors.append('模型规模超限：装机部件与初始库存合计不超过 200000 件。')
    estimated_failures = sum(f['quantity'] * f['util'] * sum(p['quantity']*p['rate'] for p in f['parts']) for f in fleets) * horizon
    # For nondecreasing Weibull hazard, end-age hazard bounds all repair paths.
    for fleet in fleets:
        for parent in fleet['parts']:
            for leaf in children.get(parent['iid'], [parent]):
                rule = aging.get(leaf['iid'])
                if not rule:
                    continue
                multiplier = rule['application'] * parent['envf']
                quantity = parent['quantity']
                if parent['iid'] in children:
                    multiplier *= leaf['envf']
                    quantity *= leaf['quantity']
                end_age = rule['initial'] + horizon * fleet['util']
                try:
                    hazard = multiplier * rule['shape'] / rule['scale'] * (end_age / rule['scale']) ** (rule['shape'] - 1)
                    estimated_failures += fleet['quantity'] * quantity * horizon * fleet['util'] * hazard
                except OverflowError:
                    estimated_failures = math.inf
    if not math.isfinite(estimated_failures) or estimated_failures > 5000000:
        errors.append('故障事件规模过大：请降低故障率、设备数量或仿真时长。')
    missions, schedules, operation_errors = compile_operations(
        tables, fleets, capacity, repairs, replacements, horizon, reps,
        [(station, rule) for (station, _), stages in depot_processes.items() for rule in stages.values()])
    errors.extend(operation_errors)
    if m3:
        errors.extend(compile_service(
            tables, canonical, children, fleets, capacity, tasks,
            repairs, replacements, depot_processes, schedules, horizon))
    planned, planned_errors = compile_planned(tables, fleets, missions, capacity, schedules, horizon, reps)
    errors.extend(planned_errors)
    if errors:
        raise ModelError(errors)
    config = {'horizon': horizon, 'interval': interval, 'replications': reps, 'seed': seed,
            'remove_fraction': num('Control', c, 'RMVFR'), 'log': val('Control', c, 'ENLOG') == 'Y',
            'point': point, 'fleets': fleets, 'count': count, 'links': links, 'stock': stock,
            'capacity': capacity, 'repairs': repairs, 'replacements': replacements,
            'missions': missions, 'schedules': schedules, 'children': children, 'depot_processes': depot_processes,
            'planned': planned, 'aging': aging}
    if m3:
        config['m3'] = {'tables': canonical}
    return config
