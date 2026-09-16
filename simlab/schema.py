"""SIMLOX dictionary metadata. Field IDs and units are never renamed."""
import json
from pathlib import Path
from .extensions import TABLES as EXTENSION_TABLES

SCHEMA = json.loads((Path(__file__).parent / 'data' / 'schema.json').read_text(encoding='utf-8'))
TABLES = {**SCHEMA['tables'], **EXTENSION_TABLES}
TABLE_LABELS = {
    'SimLabExecution': '执行模式',
    'SimLabSupplyRoute': '补给路线', 'SimLabSupplyPolicy': '库存补货策略',
    'SimLabRepairLocation': '维修地点映射', 'SimLabServiceRoute': '送修路线',
    'SimLabMaintenanceRule': '维修方式规则', 'SimLabMaintenanceStep': '在位维修工序',
    'SimLabOffItemService': '拆下件维修工序', 'SimLabItemPreventive': '部件预防维修时钟',
    'SimLabItemAging': '部件老化与修复',
    'SimLabFlightInspection': '飞行小时检查', 'SimLabInspectionInitial': '逐架初始检查小时',
    'SimLabPlannedMaintenance': '日历计划维修',
    'SimLabFlightRule': '飞行与备用机规则',
    'SimLabDutyRule': '固定值守规则',
    'SimLabDepotProcess': '检测与测试',
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
    'TransportPolicyProfile': '运输策略剖面', 'MaxPMProfile': '预防维修数量上限剖面',
    'TaskCategory': '作业类别', 'TaskLevel': '作业层级', 'StationVariant': '站点变体',
    'IntegerDistributions': '整数分布', 'UnitGroup': '使用单位组', 'MaintenanceAllocation': '维修配置',
}
FIELD_LABELS = {
    'MODE': '执行模式', 'ROUTEID': '路线标识', 'FROM_STID': '起点站点',
    'TO_STID': '终点站点', 'TRANSIT_H': '运输时长', 'TRIGGER': '触发方式',
    'TARGET_QTY': '目标库存位置', 'REORDER_QTY': '临界库存位置',
    'REPAIR_STID': '维修站点', 'RULEID': '维修规则标识', 'KIND': '维修类别',
    'METHOD': '维修方式', 'REPLACE_P': '换件概率', 'STEP': '工序',
    'DISTRIBUTION': '时长分布', 'CLOCK': '计时方式',
    'SHAPE': '寿命形状参数', 'SCALE_H': '寿命尺度小时', 'REPAIR': '修复年龄方式',
    'CHECKID': '飞行小时检查标识', 'ASSET_NO': '飞机序号', 'INITIAL_H': '初始已飞小时',
    'PMID': '计划维修标识', 'FIRST_H': '首次到期时刻', 'INTERVAL_H': '重复间隔',
    'DURATION_H': '固定维修时长', 'TASK': '维修资源作业',
    'TFOUT': '出航时间比例（0～1）', 'TFRET': '返航时间比例（0～1）',
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
    'CBSID': '配置基准系统', 'MAXNC': '最大非关键故障数', 'BSID': '基准系统',
    'NSIMI': '相似部件数量', 'SGID': '相似部件组', 'WTLIM': '等待时间容限',
    'NCFTL': '非关键故障时间容限', 'NCFTT': '非关键故障计时类型',
    'UTXT1': '自定义文本一', 'UTXT2': '自定义文本二', 'LGID': '横向支援站点组',
    'BOPRI': '欠件优先级', 'XCOORD': '地图横坐标', 'YCOORD': '地图纵坐标',
    'PFRMS': '上级到本站运输剖面', 'PTOMS': '本站到上级运输剖面',
    'MAXPM': '同时预防维修的系统上限', 'MAXPMP': '预防维修数量上限剖面',
    'PLID': '初始寿命标识', 'MUTILF': '最大利用率', 'TCID': '作业类别',
    'TLID': '作业层级', 'ARID': '替代资源', 'ARTF': '替代资源时间系数',
    'ENRMS': '启用远程支援', 'ENALU': '启用替代使用单位', 'TCLEV': '目标置信水平',
    'ENLOG': '记录仿真日志', 'RMVFR': '更换时间中的拆卸比例',
    'RRFIM': '隐式拆卸率系数', 'ENBOP': '启用欠件优先级',
    'DRAOS': '部署资源在班外可用', 'PRMVF': '预防维修拆卸时间比例',
    'PRPLF': '预防维修更换时间比例', 'PERCL': '百分位水平',
    'MAXPL': '预防维修初始寿命上限', 'ENPNM': '允许暂停非关键维修',
    'DURND': '任务时长分布', 'MSUCPT': '任务成功点比例（0～1）',
    'MPAT': '任务模式', 'PRI': '优先级', 'NOPER': '提前通知时间',
    'MFF': '任务故障率系数', 'SYACF': '关键故障时中止任务',
    'SYACP': '关键预防维修时中止任务', 'ITYPE': '启动方式',
    'IQTYD': '启动数量分布', 'IPER': '启动周期', 'IDISP': '启动分布方式',
    'DTIM': '允许延迟时间', 'RMTBF': '资源平均故障间隔', 'RFTT': '资源故障计时类型',
    'RMDT': '资源平均停机时间', 'RMDTD': '资源停机时间分布',
    'LRU': '外场可更换部件', 'STATION': '维修站点', 'DIAG_H': '故障检测时间',
    'DIAG_TASK': '故障检测作业', 'TEST_H': '修后测试时间', 'TEST_TASK': '修后测试作业',
    'MIN_QTY': '最低保障数量', 'PRIORITY': '分配优先级', 'RELIEF_H': '补位准备时间',
    'TOLERANCE_H': '允许连续不达标时间', 'PREP_H': '再次出动准备时长',
    'PREP_TASK': '再次出动准备作业', 'DAILY_READY': '每天首波假定已准备',
    'MPID': '安装位置标识', 'TPRID': '运输剖面标识', 'STVID': '站点变体标识',
    'UGID': '使用单位组标识',
}
def field_label(field):
    if field['id'] == 'INITIAL_H' and '有效运行年龄' in field['description']:
        return '初始有效运行年龄'
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

# Workflow order applies to navigation only; the original dictionary is unchanged.
MODELING_GROUPS = {
    '01  装备组成': ('System', 'Item', 'MaterielStructure', 'SimLabItemAging', 'SimLabItemPreventive'),
    '02  站点与部署': ('Station', 'StationStructure', 'Unit', 'SystemDeployment'),
    '03  资源与班次': ('Resource', 'Shift', 'ShiftProfile', 'ResourceStationData', 'ResourceAllocation'),
    '04  维修与保障作业': ('Tasks', 'TaskResource', 'ItemRepair', 'ItemReplacement', 'SimLabDepotProcess', 'SimLabMaintenanceRule', 'SimLabMaintenanceStep', 'SimLabOffItemService', 'SimLabRepairLocation', 'SimLabServiceRoute', 'SimLabPlannedMaintenance', 'SimLabFlightInspection', 'SimLabInspectionInitial'),
    '05  备件与供应': ('StockAllocation', 'SimLabSupplyRoute', 'SimLabSupplyPolicy'),
    '06  任务与运行': ('MissionType', 'MissionSystem', 'OperationProfile', 'Operations', 'SimLabDutyRule', 'SimLabFlightRule'),
    '07  仿真控制': ('Control', 'SimLabExecution'),
}
