"""Synthetic three-level aircraft case; parameters are demonstration assumptions."""
from .project import new_project


def m3_project(replications=5):
    project = new_project('示例 · 三级供应与飞机维修方式')
    tables = {
        'SimLabExecution': [{'MODE': 'M3'}],
        'System': [{'SID': 'AIRCRAFT', 'DESCR': '三级保障演示飞机', 'FRT': '0'}],
        'Item': [{'IID': 'POWER', 'DESCR': '动力模块', 'TYPE': 'LRU', 'FRT': '20000'}],
        'MaterielStructure': [{'MID': 'POWER', 'MMID': 'AIRCRAFT', 'QTYPM': '1'}],
        'Station': [dict(STID=s, DESCR=name, TYPE=kind) for s, name, kind in (
            ('CENTER', '中心修理仓', 'DEPOT'), ('REGION', '区域仓', 'STORE'), ('BASE', '飞行基地', 'OP'))],
        'StationStructure': [{'STID': 'BASE', 'MSTID': 'REGION', 'TFRMS': '0', 'TTOMS': '0'},
                             {'STID': 'REGION', 'MSTID': 'CENTER', 'TFRMS': '0', 'TTOMS': '0'}],
        'Unit': [{'UNID': 'FLEET', 'STID': 'BASE', 'DESCR': '演示飞行分队'}],
        'SystemDeployment': [{'SID': 'AIRCRAFT', 'USTID': 'FLEET', 'QTYPS': '4', 'UTIL': '1'}],
        'StockAllocation': [dict(POINT='BASELINE', IID='POWER', STID=s, STSIZ=str(q))
                            for s, q in [('BASE', 0), ('REGION', 1), ('CENTER', 6)]],
        'Resource': [{'RID': 'TECH', 'TYPE': 'SPECIAL', 'DESCR': '保障人员'},
                     {'RID': 'BAY', 'TYPE': 'SPECIAL', 'DESCR': '维修工位'}],
        'ResourceAllocation': [dict(POINT='BASELINE', STID=s, RID=r, RQTY=str(q))
            for s in ('BASE', 'REGION', 'CENTER') for r, q in [('TECH', 2), ('BAY', 1)]],
        'Tasks': [{'TID': 'FIX', 'DESCR': '维修与检测'}, {'TID': 'CHANGE', 'DESCR': '拆装与准备'}],
        'TaskResource': [{'TID': 'FIX', 'RID': 'TECH', 'QTY': '1'},
                         {'TID': 'FIX', 'RID': 'BAY', 'QTY': '1'},
                         {'TID': 'CHANGE', 'RID': 'TECH', 'QTY': '1'}],
        'Control': [dict(NREPS=str(replications), SIMPE='72', RCINT='1', RSEED='20260916',
                         APID='BASELINE', ENPM='N', ENLAT='N', ENALU='N', RELOP='SERIAL', ENLOG='Y')],
        'MissionType': [dict(MTID='FLIGHT', DESCR='双机飞行', NOS='2', MNOS='2', DURN='2.5',
                             TFOUT='.2', TFRET='.2', MSUCPT='.8')],
        'MissionSystem': [{'MTID': 'FLIGHT', 'SID': 'AIRCRAFT'}],
        'Operations': [{'USTID': 'FLEET', 'PRID': 'DAILY'}],
        'OperationProfile': [dict(PRID='DAILY', SPRID='FLIGHT', STIM=str(day*24+hour))
                             for day in range(3) for hour in (6, 10, 14)],
        'SimLabFlightRule': [dict(MTID='FLIGHT', PREP_H='.25', PREP_TASK='CHANGE', DAILY_READY='Y')],
        'SimLabSupplyRoute': [dict(ROUTEID=rid, IID='POWER', FROM_STID=src, TO_STID=dst, TRANSIT_H=hours)
            for rid, src, dst, hours in [('REGION_BASE', 'REGION', 'BASE', '.5'),
                                         ('CENTER_BASE', 'CENTER', 'BASE', '1.5'),
                                         ('CENTER_REGION', 'CENTER', 'REGION', '1')]],
        'SimLabSupplyPolicy': [dict(POINT='BASELINE', STID=s, IID='POWER', TRIGGER='THRESHOLD',
                                    TARGET_QTY='2', REORDER_QTY='1') for s in ('BASE', 'REGION')],
        'SimLabRepairLocation': [dict(IID='POWER', FROM_STID=s, REPAIR_STID='CENTER')
                                for s in ('BASE', 'REGION', 'CENTER')],
        'SimLabServiceRoute': [dict(ROUTEID='RETURN_'+s, IID='POWER', FROM_STID=s,
                                    TO_STID='CENTER', TRANSIT_H='1') for s in ('BASE', 'REGION')],
        'SimLabMaintenanceRule': [], 'SimLabMaintenanceStep': [], 'SimLabOffItemService': [],
        'SimLabItemPreventive': [dict(PMID='POWER_SERVICE', IID='POWER', CLOCK='OPERATING',
                                      INTERVAL_H='3', INITIAL_H='0')],
    }
    for kind, ratio, service_time in [('CORRECTIVE', '.5', '1.5'), ('PREVENTIVE', '.6', '.5')]:
        rid = 'POWER_' + kind
        tables['SimLabMaintenanceRule'].append(dict(RULEID=rid, MID='AIRCRAFT', IID='POWER',
            STID='BASE', KIND=kind, METHOD='MIXED', REPLACE_P=ratio))
        for step, duration, task in [('DIAGNOSE', '.1', 'FIX'), ('IN_PLACE', service_time, 'FIX'),
            ('REMOVE', '.1', 'CHANGE'), ('INSTALL', '.15', 'CHANGE'), ('TEST', '.1', 'FIX')]:
            tables['SimLabMaintenanceStep'].append(dict(RULEID=rid, STEP=step,
                DURATION_H=duration, DISTRIBUTION='FIXED', TASK=task))
        for step, duration in [('DIAGNOSE', '.1'), ('SERVICE', service_time), ('TEST', '.1')]:
            tables['SimLabOffItemService'].append(dict(IID='POWER', STID='CENTER', KIND=kind,
                STEP=step, DURATION_H=duration, DISTRIBUTION='FIXED', TASK='FIX'))
    project['tables'] = tables
    return project
