"""Explicit SimLab-owned inputs; never modify the original SIMLOX dictionary."""
VERSION = 9


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
