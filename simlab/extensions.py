"""Explicit SimLab-owned inputs; never modify the original SIMLOX dictionary."""
VERSION = 1


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
