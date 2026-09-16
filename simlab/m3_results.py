"""Read-only M3 result presentation and traceable all-replication exports."""
import csv
import json


DATASETS = {
    'workflows': {'activities': '保障活动', 'steps': '工序执行明细'},
    'supply': {'orders': '补货申请', 'shipments': '调运批次', 'purchases': '外部采购',
               'stocks': '期末库存', 'demands': '取件需求'},
    'service': {'jobs': '维修工单', 'clocks': '部件预防计时',
                'retirements': '报废记录', 'lifetimes': '实物寿命台账'},
}
LABELS = {
    'attempt': '尝试次数',
    'workflow': '流程实例', 'plan': '工序方案', 'activity': '活动类型', 'step': '工序',
    'name': '名称', 'action': '业务动作', 'ready_at': '紧前完成时刻/h',
    'requested_at': '申请资源时刻/h', 'resources': '资源需求', 'duration': '抽取作业时长/h',
    'predecessors': '紧前工序', 'successors': '紧后工序', 'elapsed_hours': '活动历时/h',
    'wait_dependency_hours': '等待紧前/h', 'wait_prerequisite_hours': '等待业务条件/h',
    'wait_shift_hours': '等待班次/h', 'wait_resource_hours': '等待资源/h', 'work_hours': '实际作业/h',
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
    'corrective_repairs': '累计修复次数', 'retired': '已报废', 'retirement_due': '待报废',
    'limit_hours': '运行小时限值/h', 'limit_repairs': '维修次数限值',
    'purchase_count': '采购批次数', 'purchased': '采购件数', 'purchase_received': '采购到货件数',
    'retirement_count': '报废件数', 'time': '时刻/h', 'site': '地点', 'location': '位置',
    'age': '有效年龄/h',
}
VALUES = {
    'retry': '备件到限后重试',
    'MAINTENANCE': '在位维修', 'PREPARATION': '出动准备', 'INSPECTION': '飞行小时检查',
    'CUSTOM': '自定义作业', 'DIAGNOSE': '检测', 'REMOVE': '拆卸', 'INSTALL': '安装',
    'SERVICE': '实际维修', 'TEST': '测试', 'running': '进行中', 'waiting': '等待资源或班次',
    'prerequisite': '等待业务条件', 'finalizing': '业务处理中', 'cancelled': '已取消', 'ready': '已就绪',
    'CORRECTIVE': '修复性维修', 'PREVENTIVE': '预防性维修',
    'IN_PLACE': '原位维修', 'REPLACE': '换件维修', 'MIXED': '按比例选择', 'OFF_ITEM': '拆下件维修',
    'OPERATING': '有效运行小时', 'CALENDAR': '日历小时',
    'THRESHOLD': '临界库存', 'PERIODIC': '指定周期',
    'RETIREMENT': '到限换件', 'LIFETIME_HOURS': '运行小时到限',
    'REPAIR_COUNT': '维修次数到限', 'PARENT_RETIRED': '随整件退出',
    'retired': '已报废', 'retired_with_parent': '随整件退出',
    'LIMIT_H': '运行小时到限', 'LIMIT_REPAIRS': '维修次数到限',
    'PARENT_RETIREMENT': '随整件退出', 'cancelled_retirement': '已因报废取消',
    'installed': '装机', 'attached': '附属部件', 'stock': '库存',
    'held': '已取件', 'service': '维修中', 'service_transport': '送修在途',
    'queued': '已排队', 'starting': '准备开始', 'waiting_resource': '等待资源', 'working': '作业中',
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
    details = (data.get('detail_counts') or {}).get(dataset)
    if isinstance(details, dict):
        return bool(details.get('truncated', False))
    flags = data.get('truncated', False)
    if isinstance(flags, dict):
        flags = flags.get(dataset, False)
    return bool(flags or data.get(dataset + '_truncated', False))


def detail_total(data, dataset):
    details = (data.get('detail_counts') or {}).get(dataset)
    if isinstance(details, dict):
        return details['total']
    return details if details is not None else data.get(dataset + '_total', len(data.get(dataset) or []))


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
