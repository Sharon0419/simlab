"""Explicit SimLab-owned inputs; never modify the original SIMLOX dictionary."""
VERSION = 4


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
    field('PREP_H', 'Mandatory', '每天首波、回收及修复后的保障时长', 'Floating point', unit='Hours'),
]
