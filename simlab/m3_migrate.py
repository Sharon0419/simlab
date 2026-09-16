"""Reviewable, non-mutating migration of supported legacy leaf-item models."""
import copy
from decimal import Decimal

from .compiler import compile_model
from .project import new_project
from .schema import value
from .supply_config import M3_TABLES


def _text(number):
    return format(Decimal(str(number)).normalize(), 'f')


def prepare_migration(project):
    """Return a compiled independent candidate and a Chinese change preview.

    This function never saves files or alters the supplied project. The caller
    presents the preview before accepting/saving the candidate. Assembly service
    and correlated random replacement splits require a separate migration design.
    """
    source = project['tables']
    if source.get('SimLabExecution'):
        raise ValueError('项目已有 M3 执行模式，无需再次迁移。')
    existing = sorted(name for name in M3_TABLES if source.get(name))
    if existing:
        raise ValueError('项目已有显式 M3 数据，不能覆盖：' + '、'.join(existing))
    legacy = compile_model(source)
    if legacy.get('children') or source.get('SimLabDepotProcess'):
        raise ValueError('当前迁移仅支持叶件；带子件总成及 SimLabDepotProcess 的检测/测试不能可靠自动迁移。')

    control = source['Control'][0]
    point = value('Control', control, 'APID')
    fraction = Decimal(value('Control', control, 'RMVFR'))
    for row in source.get('ItemReplacement', []):
        if (value('ItemReplacement', row, 'SURPD') == '<EXP>'
                and Decimal(value('ItemReplacement', row, 'SURPT')) > 0 and 0 < fraction < 1):
            raise ValueError(
                f'ItemReplacement {row["MID"]}/{row["IID"]}@{row["STID"]}: '
                '旧指数更换共用一次抽样，拆卸/安装相关；M3 独立工序无法可靠保留该相关性，需人工配置。')

    candidate = new_project(project.get('name', '未命名项目') + ' · M3迁移副本')
    candidate['parent_revision'] = project.get('revision')
    tables = candidate['tables'] = copy.deepcopy(source)
    for name in M3_TABLES:
        tables[name] = []
    tables['SimLabExecution'] = [{'MODE': 'M3'}]
    preview = [
        '旧模型 → M3 显式规则迁移预览',
        f'来源项目：{project.get("name", "未命名项目")}；来源版本：{project.get("revision", "未记录")}',
        '生成独立新项目；原项目及历史运行记录保持不变，新副本不复制历史结果。',
        '执行模式：旧隐式两级补给 → SimLabExecution.MODE=M3。',
        '范围：保留直接叶件修复性换件；不新增预防性时钟、原位或混合维修。',
        '差异：M3 采用订单、库存位置和公共返库；新模式随机流及资源申请顺序不同，不保证与旧模型逐样本数值相同。',
        '新增假设：补货用 THRESHOLD，目标取当前选中方案的初始在库量，临界值=目标−1；库存为 0 时建议目标 1。',
        '新增假设：旧叶件未单列的 DIAGNOSE / TEST 工序显式设为 0 小时、无资源；请在保存副本前评审。',
    ]

    def append(table, row, origin, note=''):
        tables[table].append(row)
        fields = '，'.join(f'{key}={val if val != "" else "（空）"}' for key, val in row.items())
        preview.append(f'{origin} → {table}: {fields}。' + (f' {note}' if note else ''))

    repairs = {(row['STID'], row['IID']): row for row in source.get('ItemRepair', [])}
    locations = {}
    route_keys = set()
    for index, row in enumerate(source.get('ItemReplacement', []), 1):
        mid, iid, station = row['MID'], row['IID'], row['STID']
        destination = legacy['links'].get(station, {}).get('parent', station)
        if (destination, iid) not in repairs:
            raise ValueError(f'ItemReplacement {mid}/{iid}@{station}: 上级维修站 {destination} 缺少叶件修复规则，不能可靠迁移。')
        locations[(iid, station)] = destination
        if station != destination:
            route_keys.add((station, iid))
        rule = f'MIG_CM_{index:04d}'
        append('SimLabMaintenanceRule', dict(RULEID=rule, MID=mid, IID=iid, STID=station,
               KIND='CORRECTIVE', METHOD='REPLACE'), f'ItemReplacement 第 {index} 行上下文及旧固定换件行为')
        total = Decimal(value('ItemReplacement', row, 'SURPT'))
        distribution = 'EXPONENTIAL' if value('ItemReplacement', row, 'SURPD') == '<EXP>' else 'FIXED'
        task = value('ItemReplacement', row, 'SURPTID')
        for step, duration, formula in [('REMOVE', total*fraction, 'SURPT × RMVFR'),
                                         ('INSTALL', total*(1-fraction), 'SURPT × (1−RMVFR)')]:
            append('SimLabMaintenanceStep', dict(RULEID=rule, STEP=step, DURATION_H=_text(duration),
                   DISTRIBUTION=distribution, TASK=task),
                   f'ItemReplacement.SURPT={total}、SURPD={value("ItemReplacement", row, "SURPD") or "固定"}、'
                   f'SURPTID={task or "空"}；Control.RMVFR={fraction}（{formula}）')
        append('SimLabMaintenanceStep', dict(RULEID=rule, STEP='TEST', DURATION_H='0',
               DISTRIBUTION='FIXED', TASK=''), '旧叶件无独立装后测试字段', '新增默认：显式零时长，不增加资源需求。')

    for index, row in enumerate(source.get('ItemRepair', []), 1):
        iid, station = row['IID'], row['STID']
        locations.setdefault((iid, station), station)
        for step in ('DIAGNOSE', 'SERVICE', 'TEST'):
            service = step == 'SERVICE'
            append('SimLabOffItemService', dict(IID=iid, STID=station, KIND='CORRECTIVE', STEP=step,
                   DURATION_H=_text(value('ItemRepair', row, 'DIRPT')) if service else '0',
                   DISTRIBUTION=('EXPONENTIAL' if value('ItemRepair', row, 'DIRPD') == '<EXP>' else 'FIXED') if service else 'FIXED',
                   TASK=value('ItemRepair', row, 'DIRPTID') if service else ''),
                   f'ItemRepair 第 {index} 行：ItemRepair.DIRPT / ItemRepair.DIRPD / ItemRepair.DIRPTID' if service else '旧叶件无独立检测/修后测试字段',
                   '保留修复时长分布与资源任务。' if service else '新增默认：显式零时长，不增加资源需求。')

    for (station, iid) in legacy['stock']:
        if station in legacy['links']:
            route_keys.add((station, iid))
    for (iid, station), destination in sorted(locations.items()):
        append('SimLabRepairLocation', dict(IID=iid, FROM_STID=station, REPAIR_STID=destination),
               '旧 StationStructure 直接上级 / 本站 ItemRepair', '显式固定修理目的地。')

    stock_rows = {(r['STID'], r['IID']): r for r in source.get('StockAllocation', []) if r['POINT'] == point}
    for index, (station, iid) in enumerate(sorted(route_keys), 1):
        link = legacy['links'][station]
        parent = link['parent']
        append('SimLabSupplyRoute', dict(ROUTEID=f'MIG_SUP_{index:04d}', IID=iid,
               FROM_STID=parent, TO_STID=station, TRANSIT_H=_text(link['inward'])),
               f'StationStructure.TFRMS（{station}）', '原上级→本站补给运输时长，按部件显式化。')
        if locations.get((iid, station)) == parent:
            append('SimLabServiceRoute', dict(ROUTEID=f'MIG_SVC_{index:04d}', IID=iid,
                   FROM_STID=station, TO_STID=parent, TRANSIT_H=_text(link['outward'])),
                   f'StationStructure.TTOMS（{station}）', '原本站→上级送修运输时长；独立于补给路线。')
        quantity = legacy['stock'].get((station, iid), 0)
        target = max(1, quantity)
        row = stock_rows.get((station, iid), {})
        field = 'ISTOH' if str(row.get('ISTOH', '')).strip() else 'STSIZ'
        append('SimLabSupplyPolicy', dict(POINT=point, STID=station, IID=iid, TRIGGER='THRESHOLD',
               TARGET_QTY=str(target), REORDER_QTY=str(target-1)),
               f'StockAllocation.{field}（POINT={point}，{iid}@{station}，初始实物={quantity}）',
               '新增假设：库存为 0，建议目标 1；临界值=目标−1。' if quantity == 0
               else '新增假设：库存数仅作为订货目标建议，不是原有补货字段；临界值=目标−1。')

    for row in tables.get('StationStructure', []):
        row['TFRMS'] = row['TTOMS'] = '0'
    tables['ItemReplacement'] = []
    tables['ItemRepair'] = []
    preview.extend([
        'StationStructure.TFRMS / TTOMS → 0：运输参数已复制至独立路线，避免隐式/显式重复计时。',
        'ItemReplacement / ItemRepair → 清空旧执行规则：字段已转入上述显式表，消除同上下文新旧重叠。',
        '最高层不新增外部补货，不隐式采购；其他输入表及初始实物、任务、资源和班次均深拷贝保留。',
    ])
    compile_model(tables)
    preview.append('校验结果：候选项目已通过 M3 编译；尚未保存或替换原项目。')
    return candidate, '\n'.join(preview)
