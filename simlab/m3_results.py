"""Read-only M3 result presentation and traceable all-replication exports."""
import csv
import json


DATASETS = {
    'supply': {'orders': '补货申请', 'shipments': '运输批次', 'stocks': '期末库存', 'demands': '取件需求'},
    'service': {'jobs': '维修工单', 'clocks': '部件预防计时'},
}
LABELS = {
    'id': '编号', 'sequence': '先后序号', 'station': '站点', 'iid': '部件', 'created': '申请时刻/h',
    'quantity': '数量', 'unallocated': '待分配', 'in_transit': '在途', 'received': '已收货',
    'sponsor': '缺口记账来源', 'reason': '触发原因', 'order': '申请编号', 'route': '调运策略',
    'source': '来源', 'destination': '目的地', 'parts': '实物清单', 'departure': '发运时刻/h',
    'arrival': '到货时刻/h', 'available': '可用库存', 'reserved': '已预留',
    'unreceived': '已申请未到货', 'unmet': '未满足需求', 'inventory_position': '库存位置',
    'target': '目标库存', 'owner': '需求对象', 'fulfilled': '已满足', 'completed': '已完成',
    'kind': '维修类型', 'rule': '规则', 'part': '实物号', 'parent': '母件', 'asset': '装备',
    'method': '维修方式', 'status': '状态', 'due_at': '到期时刻/h', 'started_at': '开始时刻/h',
    'ended_at': '结束时刻/h', 'age_before': '作业前年龄/h', 'age_after': '作业后年龄/h',
    'lifetime_hours': '终身运行/h', 'overrun_hours': '超限/h', 'clock': '计时类型',
    'interval_hours': '周期/h', 'hours': '本周期累计/h', 'paused': '已暂停',
    'completed_services': '完成次数', 'order_count': '申请数', 'shipment_count': '批次数',
    'demand_count': '需求数', 'requested': '申请件数', 'shipped': '发运件数',
    'selected': '选中次数', 'in_place': '原位维修', 'replace': '换件维修',
    'selected_in_place': '选中原位', 'selected_replace': '选中换件',
    'completed_in_place': '完成原位', 'completed_replace': '完成换件',
    'job_count': '工单数', 'completed_jobs': '完成工单', 'pending_jobs': '未完工单',
    'corrective': '修复性维修', 'preventive': '预防性维修',
}
VALUES = {
    'CORRECTIVE': '修复性维修', 'PREVENTIVE': '预防性维修',
    'IN_PLACE': '原位维修', 'REPLACE': '换件维修', 'MIXED': '按比例选择', 'OFF_ITEM': '拆下件维修',
    'OPERATING': '有效运行小时', 'CALENDAR': '日历小时',
    'THRESHOLD': '临界库存', 'PERIODIC': '周期调运',
    'queued': '已排队', 'waiting_resource': '等待资源', 'working': '作业中',
    'waiting_spare': '等待备件', 'transport': '送修运输', 'completed': '已完成',
    'covered_by_corrective': '已由修复性维修覆盖', 'pending': '待满足',
    'threshold': '临界库存', 'periodic': '周期调运', 'initial': '初始检查',
}


def display(value):
    if value is None:
        return '—'
    if isinstance(value, bool):
        return '是' if value else '否'
    if isinstance(value, float):
        return f'{value:.6g}'
    if isinstance(value, dict):
        return '、'.join(f'{VALUES.get(key, LABELS.get(key, key))} {display(item)}' for key, item in value.items())
    if isinstance(value, list):
        return json.dumps(value, ensure_ascii=False)
    return VALUES.get(value, str(value))


def snapshot(result, section, replication=0):
    repetitions = result.get('replication_results') or []
    if repetitions:
        return repetitions[replication].get(section) or {}
    return result.get(section) or {}


def truncated(data, dataset):
    flags = data.get('truncated', False)
    if isinstance(flags, dict):
        flags = flags.get(dataset, False)
    return bool(flags or data.get(dataset + '_truncated', False))


def detail_total(data, dataset):
    return (data.get('detail_counts') or {}).get(dataset,
        data.get(dataset + '_total', len(data.get(dataset) or [])))


def export_m3(run, path, section, dataset):
    if dataset not in DATASETS.get(section, {}):
        raise ValueError('未知的 M3 导出内容。')
    result = run['result']
    repetitions = result.get('replication_results') or [result]
    if not any(section in rep and rep[section] is not None for rep in repetitions):
        raise ValueError('本实验没有 M3 供应或维修方式结果，请用新版模型重新运行。')
    columns = []
    for rep in repetitions:
        for row in (rep.get(section) or {}).get(dataset, []):
            for key in row:
                if not key.startswith('_') and key not in columns:
                    columns.append(key)
    metadata = ['run_id', 'model_hash', 'seed', 'engine', 'replication', 'section', 'dataset',
                'details_truncated', 'detail_total', 'detail_retained']
    with open(path, 'w', encoding='utf-8-sig', newline='') as handle:
        writer = csv.writer(handle)
        writer.writerow(metadata + columns)
        for number, rep in enumerate(repetitions, 1):
            data = rep.get(section) or {}
            rows = data.get(dataset) or []
            provenance = [run['id'], run.get('model_hash', result.get('model_hash', '')),
                          result.get('seed', ''), result.get('engine', ''), number, section, dataset,
                          truncated(data, dataset), detail_total(data, dataset), len(rows)]
            for row in rows:
                values = [row.get(key, '') for key in columns]
                writer.writerow(provenance + [json.dumps(value, ensure_ascii=False)
                    if isinstance(value, (dict, list)) else value for value in values])
