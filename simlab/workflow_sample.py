"""Synthetic two-level redundancy and fork/join support demonstration."""
from .m3_sample import m3_project


def workflow_project(replications=5):
    project = m3_project(replications)
    project['name'] = '示例 · 两层冗余与保障多工序'
    t = project['tables']
    t['Item'][0]['FRT'] = '0'
    t['Item'].append(dict(IID='BOARD', DESCR='冗余控制模块', TYPE='SRU', FRT='80000'))
    t['MaterielStructure'][0]['QTYPM'] = '3'
    t['MaterielStructure'].append(dict(MMID='POWER', MID='BOARD', QTYPM='2'))
    t['SimLabRedundancy'] = [dict(PARENT='AIRCRAFT', IID='POWER', K='2'), dict(PARENT='POWER', IID='BOARD', K='1')]
    t['SimLabItemPreventive'] = [dict(PMID='BOARD_PM', IID='BOARD', CLOCK='OPERATING', INTERVAL_H='4', INITIAL_H='1')]
    t['SimLabMaintenanceRule'] = [r for r in t['SimLabMaintenanceRule'] if r['KIND'] == 'CORRECTIVE']
    t['SimLabMaintenanceStep'] = [r for r in t['SimLabMaintenanceStep'] if r['RULEID'] == 'POWER_CORRECTIVE']
    t['SimLabOffItemService'] = [r for r in t['SimLabOffItemService'] if r['KIND'] == 'CORRECTIVE' and r['STEP'] != 'SERVICE']
    for station in ('BASE', 'CENTER'):
        for kind in ('CORRECTIVE', 'PREVENTIVE'):
            rid = f'BOARD_{station}_{kind}'
            t['SimLabMaintenanceRule'].append(dict(RULEID=rid, MID='POWER', IID='BOARD', STID=station,
                KIND=kind, METHOD='IN_PLACE'))
            for step, duration in [('DIAGNOSE','.05'), ('IN_PLACE','.2'), ('TEST','.05')]:
                t['SimLabMaintenanceStep'].append(dict(RULEID=rid, STEP=step, DURATION_H=duration, TASK='CHANGE'))
    t['SimLabRepairLocation'] += [dict(IID='BOARD', FROM_STID=s, REPAIR_STID='CENTER') for s in ('BASE','CENTER')]
    t['SimLabServiceRoute'].append(dict(ROUTEID='BOARD_RETURN', IID='BOARD', FROM_STID='BASE', TO_STID='CENTER', TRANSIT_H='1'))
    t['SimLabOffItemService'] += [dict(IID='BOARD', STID='CENTER', KIND=kind, STEP=step,
        DURATION_H='.1', TASK='CHANGE') for kind in ('CORRECTIVE','PREVENTIVE') for step in ('DIAGNOSE','SERVICE','TEST')]
    t['SimLabPlannedMaintenance'] = [dict(PMID='CAL_CHECK', SID='AIRCRAFT', USTID='FLEET', FIRST_H='20',
        INTERVAL_H='24', DURATION_H='.4', TASK='CHANGE')]
    t['SimLabFlightInspection'] = [dict(CHECKID='HOUR_CHECK', SID='AIRCRAFT', USTID='FLEET',
        INTERVAL_H='5', DURATION_H='.4', TASK='CHANGE')]
    t['SimLabWorkflow'], t['SimLabWorkflowStep'], t['SimLabWorkflowBinding'] = [], [], []

    def plan(name, actions):
        t['SimLabWorkflow'].append(dict(WFID=name, NAME=name))
        previous = ''
        for index, action in enumerate(actions):
            ident = f'S{index+1}'
            t['SimLabWorkflowStep'].append(dict(WFID=name, STEPID=ident, NAME={'DIAGNOSE':'检测','REMOVE':'拆卸',
                'INSTALL':'安装','TEST':'测试','IN_PLACE':'原位修复','SERVICE':'实际维修'}.get(action,'作业'),
                ACTION=action, DURATION_H='.15', TASK='CHANGE', PREDECESSORS=previous))
            previous = ident
            if index == 0:
                for label, suffix in [('机械检查','M'), ('电气检查','E')]:
                    t['SimLabWorkflowStep'].append(dict(WFID=name, STEPID=suffix, NAME=label, ACTION='CUSTOM',
                        DURATION_H='.1', TASK='CHANGE', PREDECESSORS=ident))
                previous = 'M,E'
        return name

    inplace = plan('原位维修方案', ['DIAGNOSE','IN_PLACE','TEST'])
    replace = plan('换件维修方案', ['DIAGNOSE','REMOVE','INSTALL','TEST'])
    off = plan('拆下件方案', ['DIAGNOSE','SERVICE','TEST'])
    prepare = plan('出动准备方案', ['CUSTOM','CUSTOM'])
    check = plan('定期检查方案', ['CUSTOM','CUSTOM'])
    def bind(wfid, activity, **fields):
        t['SimLabWorkflowBinding'].append(dict(BINDID=f'B{len(t["SimLabWorkflowBinding"])+1}',
            WFID=wfid, ACTIVITY=activity, **fields))
    for rule in t['SimLabMaintenanceRule']:
        for method in (['IN_PLACE','REPLACE'] if rule['METHOD'] == 'MIXED' else [rule['METHOD']]):
            bind(inplace if method == 'IN_PLACE' else replace, 'MAINTENANCE', RULEID=rule['RULEID'], METHOD=method)
    bind(off, 'OFF_ITEM', IID='POWER', STID='CENTER', KIND='CORRECTIVE')
    for kind in ('CORRECTIVE','PREVENTIVE'):
        bind(off, 'OFF_ITEM', IID='BOARD', STID='CENTER', KIND=kind)
    bind(prepare, 'PREPARATION', RULEID='FLIGHT')
    bind(check, 'CALENDAR', RULEID='CAL_CHECK')
    bind(check, 'INSPECTION', RULEID='HOUR_CHECK')
    return project
