"""SIMLOX dictionary metadata. Field IDs and units are never renamed."""
import json
from pathlib import Path
from .extensions import TABLES as EXTENSION_TABLES

SCHEMA = json.loads((Path(__file__).parent / 'data' / 'schema.json').read_text(encoding='utf-8'))
TABLES = {**SCHEMA['tables'], **EXTENSION_TABLES}
TABLE_LABELS = {
    'SimLabDepotProcess': '检测与测试（SimLab 扩展）',
    'System': '系统定义', 'Item': '备件 / 部件', 'MaterielStructure': '装备组成',
    'MaterielPosition': '安装位置', 'SystemStructure': '系统组成', 'ItemStructure': '部件组成',
    'Station': '保障站点', 'StationStructure': '保障网络', 'Unit': '使用单位',
    'SystemDeployment': '系统部署', 'StockAllocation': '备件配置',
    'SystemRepair': '系统维修', 'ItemRepair': '部件修复', 'ItemReplacement': '部件更换',
    'ItemReorder': '采购补充', 'FailureMode': '故障模式', 'ItemFailureRate': '部件故障率',
    'Control': '仿真控制', 'Resource': '维修资源', 'ResourceAllocation': '资源配置',
    'Tasks': '维修任务', 'TaskResource': '任务资源需求', 'TaskBreakDown': '任务分解',
    'ResourceStationData': '站点资源参数', 'TimeDistributions': '时间分布',
    'MissionType': '任务类型', 'MissionSystem': '任务系统需求', 'Operations': '运行计划',
    'OperationProfile': '运行剖面', 'OperationParameter': '运行参数',
    'CMLocation': '纠正性维修位置', 'CMReplacement': '故障件更换',
    'MaterielPM': '预防性维修', 'PMLocation': '预防性维修位置',
    'PMActivation': '预防性维修激活', 'ProblemDescription': '项目描述',
    'Shift': '班次', 'ShiftProfile': '班次剖面', 'Redundancy': '冗余配置',
    'Prelife': '初始寿命', 'PrelifeData': '初始寿命数据',
    'SystemTransfer': '系统调动', 'ItemTransfer': '部件调拨',
    'LateralSupport': '横向支援', 'OperationalModes': '运行模式',
}
FIELD_LABELS = {
    'NOS': '需求设备数', 'MNOS': '最小设备数', 'MNOSA': '中止阈值',
    'DURN': '任务时长 / 小时', 'STIM': '开始 / 小时', 'ETIM': '结束 / 小时',
    'SPRID': '任务类型 / 子剖面', 'SHID': '班次标识', 'SHPID': '班次剖面',
    'SSHPID': '子班次', 'IQTY': '启动数量', 'IINT': '启动间隔',
    'SID': '系统标识', 'IID': '部件标识', 'DESCR': '名称 / 描述', 'NOTE': '备注',
    'FRT': '故障率', 'OPID': '运行参数', 'TYPE': '类型', 'GIID': '部件组',
    'GSID': '系统组', 'STID': '站点标识', 'MSTID': '上级站点', 'USTID': '单位 / 站点',
    'UNID': '单位标识', 'MID': '装备 / 子件标识', 'MMID': '母件标识',
    'QTYPM': '每母件数量', 'QTYPS': '每单位 / 站点数量', 'UTIL': '使用率',
    'ENVF': '环境系数', 'AFFRT': '应用系数', 'CRIT': '关键度', 'CRITF': '关键度系数',
    'STSIZ': '库存配置量', 'ISTOH': '初始在库量', 'AINST': '额外初始库存',
    'ROSIZ': '订货批量', 'POINT': '配置方案', 'APID': '选用配置方案',
    'DIRPT': '直接修复时间', 'SURPT': '子件更换时间', 'DIRPF': '直接修复比例',
    'SURPF': '子件更换比例', 'DIRPTID': '直接修复任务', 'SURPTID': '更换任务',
    'DIRPD': '直接修复时间分布', 'SURPD': '更换时间分布',
    'NREPS': '重复次数', 'SIMPE': '仿真时长', 'RSEED': '随机种子',
    'RCINT': '结果采样间隔', 'RCSTA': '统计开始', 'RCEND': '统计结束',
    'RID': '资源标识', 'TID': '任务标识', 'RQTY': '资源数量', 'QTY': '数量',
    'TFRMS': '上级到本站时间', 'TTOMS': '本站到上级时间', 'DFRAC': '需求比例',
    'OPOL': '订货策略', 'RPROB': '资源需求概率', 'FMID': '故障模式', 'FRQ': '故障频率',
    'MTID': '任务类型标识', 'PRID': '剖面标识', 'DISTID': '分布标识',
    'BASED': '基础分布', 'PARAM1': '参数 1', 'PARAM2': '参数 2', 'PARAM3': '参数 3',
    'ENPM': '启用预防性维修', 'ENLAT': '启用横向支援', 'ENROB': '启用拆借',
    'TRACK': '收集部件结果', 'RELOP': '可靠性逻辑', 'LEADT': '采购提前期',
    'GSTID': '站点组', 'LINDX': '保障层级序号', 'LEVL': '保障层级',
}
CORE_TABLES = ['System', 'Item', 'MaterielStructure', 'Station', 'StationStructure',
               'Unit', 'SystemDeployment', 'StockAllocation', 'ItemRepair',
               'ItemReplacement', 'Resource', 'ResourceAllocation', 'Tasks', 'TaskResource', 'Control']

def field_label(field):
    return FIELD_LABELS.get(field['id'], field['description'])

def table_label(name):
    return TABLE_LABELS.get(name, name)

def defaults(name):
    return {f['id']: f['default'] for f in TABLES[name] if f['default'] != ''}

def effective(row, field):
    value = row.get(field['id'], '')
    return str(value).strip() if value is not None and str(value).strip() else field['default']

def value(table, row, column, fallback=''):
    field = next(f for f in TABLES[table] if f['id'] == column)
    result = effective(row, field)
    return result if result != '' else fallback

def category(name):
    if name in CORE_TABLES:
        return '01  核心建模'
    if name.startswith(('Changes', 'Prelife')):
        return '06  时变参数与初始寿命'
    if name.startswith(('RBD', 'Redundancy', 'Failure', 'MaterielOperational')):
        return '03  可靠性与能力'
    if name.startswith(('Mission', 'Operation', 'Formation', 'SystemTransfer', 'Unit')):
        return '04  任务与运行'
    if name.startswith(('PM', 'CM', 'MaterielPM', 'Task', 'SubTask', 'Resource', 'Shift', 'Maintenance')):
        return '05  维修与资源'
    if name.startswith(('Station', 'Stock', 'Item', 'Transport', 'Lateral')):
        return '02  保障与供应'
    return '07  其他与结果控制'
