"""Explicit SimLab-owned inputs; never modify the original SIMLOX dictionary."""
VERSION = 10


def field(name, kind, description, type='Text', default='', references='', unit=''):
    return {'id': name, 'kind': kind, 'description': description, 'type': type,
            'default': default, 'references': references, 'unit': unit,
            'constraints': 'Non-negative number' if type == 'Floating point' else ''}


TABLES = {'SimLabDepotProcess': [
    field('LRU', 'Index', 'LRU 标识（SimLab 扩展）', references='Item IID'),
    field('STATION', 'Index', '维修站标识', references='Station STID'),
    field('DIAG_H', 'Mandatory', '故障检测时间 / 小时', 'Floating point', unit='Hours'),
    field('DIAG_TASK', 'Regular', '检测任务与资源', references='Tasks TID'),
    field('TEST_H', 'Mandatory', '修后测试时间 / 小时', 'Floating point', unit='Hours'),
    field('TEST_TASK', 'Regular', '测试任务与资源', references='Tasks TID'),
]}

TABLES['SimLabDutyRule'] = [
    field('MTID', 'Index', '值守任务类型（SimLab 扩展）', references='MissionType MTID'),
    field('MIN_QTY', 'Mandatory', '最低保障数量', 'Integer'),
    field('PRIORITY', 'Regular', '分配优先级（越小越优先，不抢占）', 'Integer', '1'),
    field('RELIEF_H', 'Regular', '窗口开始后补位准备时间', 'Floating point', '0', unit='Hours'),
    field('TOLERANCE_H', 'Regular', '允许连续不达标时间', 'Floating point', '0', unit='Hours'),
]

TABLES['SimLabFlightRule'] = [
    field('MTID', 'Index', '固定飞行任务类型（SimLab 扩展）', references='MissionType MTID'),
    field('PREP_H', 'Mandatory', '一次完整再次出动准备时长；首波假设除外', 'Floating point', unit='Hours'),
    field('PREP_TASK', 'Regular', '再次出动准备所需资源任务（留空无资源约束）', references='Tasks TID'),
    field('DAILY_READY', 'Regular', '每天首波健康地面飞机假定已提前准备好：Y或N', default='N'),
]
TABLES['SimLabFlightRule'][-1]['constraints']='Multiple choice: Y, N'

TABLES['SimLabPlannedMaintenance'] = [
    field('PMID', 'Index', '计划维修标识'),
    field('SID', 'Mandatory', '适用系统', references='System SID'),
    field('USTID', 'Mandatory', '部署单位或站点', references='Unit UNID, Station STID'),
    field('FIRST_H', 'Mandatory', '首次到期时刻', 'Floating point', unit='Hours'),
    field('INTERVAL_H', 'Regular', '重复间隔；零为仅一次', 'Floating point', '0', unit='Hours'),
    field('DURATION_H', 'Mandatory', '每次固定维修时长', 'Floating point', unit='Hours'),
    field('TASK', 'Regular', '维修资源作业；留空无资源约束', references='Tasks TID'),
]

TABLES['SimLabFlightInspection'] = [
    field('CHECKID', 'Index', '飞行小时检查标识'),
    field('SID', 'Mandatory', '适用系统', references='System SID'),
    field('USTID', 'Mandatory', '部署单位或站点', references='Unit UNID, Station STID'),
    field('INTERVAL_H', 'Mandatory', '每次检查之间的累计在空小时', 'Floating point', unit='Hours'),
    field('DURATION_H', 'Mandatory', '固定检查作业时长', 'Floating point', unit='Hours'),
    field('TASK', 'Regular', '检查资源作业；留空无资源约束', references='Tasks TID'),
]
TABLES['SimLabInspectionInitial'] = [
    field('CHECKID', 'Index', '飞行小时检查标识', references='SimLabFlightInspection CHECKID'),
    field('ASSET_NO', 'Index', '该部署内飞机序号，从一开始', 'Integer'),
    field('INITIAL_H', 'Regular', '距本项上次检查已飞小时', 'Floating point', '0', unit='Hours'),
]
TABLES['SimLabInspectionInitial'][1]['constraints'] = 'Positive integer'

TABLES['SimLabItemAging'] = [
    field('IID', 'Index', '适用叶子部件', references='Item IID'),
    field('SHAPE', 'Regular', '寿命形状参数，一至十；一为恒定故障风险', 'Floating point', '1'),
    field('SCALE_H', 'Mandatory', '寿命尺度小时，不等于平均寿命', 'Floating point', unit='Hours'),
    field('INITIAL_H', 'Regular', '初始装机有效运行年龄；初始库存为新件', 'Floating point', '0', unit='Hours'),
    field('REPAIR', 'Regular', '故障维修后的年龄处理方式', default='PERFECT'),
]
TABLES['SimLabItemAging'][-1]['constraints'] = 'Multiple choice: PERFECT, MINIMAL'

TABLES['SimLabExecution'] = [
    field('MODE', 'Index', '执行模式'),
]
TABLES['SimLabExecution'][0]['constraints'] = 'Multiple choice: M3'

TABLES['SimLabSupplyRoute'] = [
    field('ROUTEID', 'Index', '补给路线标识'),
    field('IID', 'Mandatory', '部件标识', references='Item IID'),
    field('FROM_STID', 'Mandatory', '供货站点', references='Station STID'),
    field('TO_STID', 'Mandatory', '收货站点', references='Station STID'),
    field('TRANSIT_H', 'Mandatory', '固定运输时长', 'Floating point', unit='Hours'),
]

TABLES['SimLabSupplyPolicy'] = [
    field('POINT', 'Index', '配置方案'),
    field('STID', 'Index', '库存站点', references='Station STID'),
    field('IID', 'Index', '部件标识', references='Item IID'),
    field('TRIGGER', 'Mandatory', '补货触发方式'),
    field('TARGET_QTY', 'Mandatory', '目标库存位置', 'Integer'),
    field('REORDER_QTY', 'Regular', '临界库存位置', 'Integer'),
    field('FIRST_H', 'Regular', '首次周期触发时刻', 'Floating point', '0', unit='Hours'),
    field('INTERVAL_H', 'Regular', '周期触发间隔', 'Floating point', unit='Hours'),
]
TABLES['SimLabSupplyPolicy'][3]['constraints'] = 'Multiple choice: THRESHOLD, PERIODIC'

TABLES['SimLabRepairLocation'] = [
    field('IID', 'Index', '部件标识', references='Item IID'),
    field('FROM_STID', 'Index', '实际拆卸站点', references='Station STID'),
    field('REPAIR_STID', 'Mandatory', '指定维修站点', references='Station STID'),
]

TABLES['SimLabServiceRoute'] = [
    field('ROUTEID', 'Index', '送修路线标识'),
    field('IID', 'Mandatory', '部件标识', references='Item IID'),
    field('FROM_STID', 'Mandatory', '送出站点', references='Station STID'),
    field('TO_STID', 'Mandatory', '接收维修站点', references='Station STID'),
    field('TRANSIT_H', 'Mandatory', '固定送修时长', 'Floating point', unit='Hours'),
]

TABLES['SimLabMaintenanceRule'] = [
    field('RULEID', 'Index', '维修规则标识'),
    field('MID', 'Mandatory', '直接母项标识', references='System SID, Item IID'),
    field('IID', 'Mandatory', '叶子部件标识', references='Item IID'),
    field('STID', 'Mandatory', '实际作业站点', references='Station STID'),
    field('KIND', 'Mandatory', '维修类别'),
    field('METHOD', 'Mandatory', '维修方式'),
    field('REPLACE_P', 'Regular', '选择换件方式的概率', 'Floating point'),
]
TABLES['SimLabMaintenanceRule'][4]['constraints'] = 'Multiple choice: CORRECTIVE, PREVENTIVE'
TABLES['SimLabMaintenanceRule'][5]['constraints'] = 'Multiple choice: IN_PLACE, REPLACE, MIXED'
TABLES['SimLabMaintenanceRule'][6]['constraints'] = '0.0 <= number <= 1.0'

TABLES['SimLabMaintenanceStep'] = [
    field('RULEID', 'Index', '维修规则标识', references='SimLabMaintenanceRule RULEID'),
    field('STEP', 'Index', '维修工序'),
    field('DURATION_H', 'Mandatory', '工序时长', 'Floating point', unit='Hours'),
    field('DISTRIBUTION', 'Regular', '时长分布', default='FIXED'),
    field('TASK', 'Regular', '资源作业', references='Tasks TID'),
]
TABLES['SimLabMaintenanceStep'][1]['constraints'] = 'Multiple choice: DIAGNOSE, IN_PLACE, REMOVE, INSTALL, TEST'
TABLES['SimLabMaintenanceStep'][3]['constraints'] = 'Multiple choice: FIXED, EXPONENTIAL'

TABLES['SimLabOffItemService'] = [
    field('IID', 'Index', '叶子部件标识', references='Item IID'),
    field('STID', 'Index', '维修站点', references='Station STID'),
    field('KIND', 'Index', '维修类别'),
    field('STEP', 'Index', '拆下件作业工序'),
    field('DURATION_H', 'Mandatory', '工序时长', 'Floating point', unit='Hours'),
    field('DISTRIBUTION', 'Regular', '时长分布', default='FIXED'),
    field('TASK', 'Regular', '资源作业', references='Tasks TID'),
]
TABLES['SimLabOffItemService'][2]['constraints'] = 'Multiple choice: CORRECTIVE, PREVENTIVE'
TABLES['SimLabOffItemService'][3]['constraints'] = 'Multiple choice: DIAGNOSE, SERVICE, TEST'
TABLES['SimLabOffItemService'][5]['constraints'] = 'Multiple choice: FIXED, EXPONENTIAL'

TABLES['SimLabItemPreventive'] = [
    field('PMID', 'Index', '部件预防维修标识'),
    field('IID', 'Mandatory', '叶子部件标识', references='Item IID'),
    field('CLOCK', 'Mandatory', '预防维修计时方式'),
    field('INTERVAL_H', 'Mandatory', '预防维修周期', 'Floating point', unit='Hours'),
    field('INITIAL_H', 'Regular', '初始周期已用时长', 'Floating point', '0', unit='Hours'),
]
TABLES['SimLabItemPreventive'][2]['constraints'] = 'Multiple choice: CALENDAR, OPERATING'
