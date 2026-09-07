from .project import new_project

def demo_project():
    project = new_project('示例 · 车辆装备保障分析')
    project['tables'] = {
        'System': [{'SID': 'VEHICLE', 'DESCR': '通用保障车辆', 'FRT': '0'}],
        'Item': [
            {'IID': 'POWER', 'DESCR': '动力模块', 'TYPE': 'LRU', 'FRT': '1250'},
            {'IID': 'CONTROL', 'DESCR': '控制模块', 'TYPE': 'LRU', 'FRT': '800'},
            {'IID': 'PUMP', 'DESCR': '液压泵', 'TYPE': 'LRU', 'FRT': '1600'},
        ],
        'MaterielStructure': [
            {'MID': 'POWER', 'MMID': 'VEHICLE', 'QTYPM': '1'},
            {'MID': 'CONTROL', 'MMID': 'VEHICLE', 'QTYPM': '1'},
            {'MID': 'PUMP', 'MMID': 'VEHICLE', 'QTYPM': '2'},
        ],
        'Station': [
            {'STID': 'BASE', 'DESCR': '使用基地', 'TYPE': 'OP'},
            {'STID': 'DEPOT', 'DESCR': '修理中心', 'TYPE': 'DEPOT'},
        ],
        'StationStructure': [{'STID': 'BASE', 'MSTID': 'DEPOT', 'TFRMS': '12', 'TTOMS': '12'}],
        'Unit': [{'UNID': 'FLEET', 'DESCR': '车辆分队', 'STID': 'BASE'}],
        'SystemDeployment': [{'SID': 'VEHICLE', 'USTID': 'FLEET', 'QTYPS': '20', 'UTIL': '0.5'}],
        'StockAllocation': [
            {'POINT': 'BASELINE', 'IID': iid, 'STID': station, 'STSIZ': str(qty)}
            for iid, qty in [('POWER', 2), ('CONTROL', 2), ('PUMP', 3)]
            for station in ('BASE', 'DEPOT')
        ],
        'ItemRepair': [
            {'IID': iid, 'STID': 'DEPOT', 'DIRPT': str(hours), 'SURPT': '0', 'DIRPTID': 'REPAIR', 'DIRPD': '<EXP>'}
            for iid, hours in [('POWER', 48), ('CONTROL', 24), ('PUMP', 36)]
        ],
        'ItemReplacement': [
            {'MID': 'VEHICLE', 'IID': iid, 'STID': 'BASE', 'SURPT': '2', 'SURPTID': 'REPLACE'}
            for iid in ('POWER', 'CONTROL', 'PUMP')
        ],
        'Resource': [{'RID': 'TECH', 'DESCR': '维修人员', 'TYPE': 'SPECIAL'},
                     {'RID': 'BAY', 'DESCR': '维修工位', 'TYPE': 'SPECIAL'}],
        'ResourceAllocation': [
            {'POINT': 'BASELINE', 'RID': 'TECH', 'STID': 'BASE', 'RQTY': '3'},
            {'POINT': 'BASELINE', 'RID': 'TECH', 'STID': 'DEPOT', 'RQTY': '2'},
            {'POINT': 'BASELINE', 'RID': 'BAY', 'STID': 'DEPOT', 'RQTY': '2'},
        ],
        'Tasks': [{'TID': 'REPLACE', 'DESCR': '部件拆装'}, {'TID': 'REPAIR', 'DESCR': '部件修复'}],
        'TaskResource': [{'TID': 'REPLACE', 'RID': 'TECH'}, {'TID': 'REPAIR', 'RID': 'TECH'},
                         {'TID': 'REPAIR', 'RID': 'BAY'}],
        'Control': [{'NREPS': '20', 'SIMPE': '2160', 'RSEED': '20260904', 'APID': 'BASELINE',
                     'RCINT': '24', 'ENPM': 'N', 'ENLAT': 'N', 'ENALU': 'N', 'RELOP': 'SERIAL', 'ENLOG': 'Y'}],
    }
    return project


def mission_project():
    """20 vehicles, 15 required daily 08:00–16:00, maintenance starts 08:00–17:00."""
    project = demo_project()
    project['name'] = '示例 · 任务日历与维修班次'
    t = project['tables']
    t['SystemDeployment'][0]['UTIL'] = '1'
    t['Control'][0].update(SIMPE='720', RCINT='1', NREPS='10')
    t['MissionType'] = [{'MTID': 'DUTY', 'DESCR': '日间保障任务', 'NOS': '15', 'MNOS': '15', 'DURN': '8'}]
    t['MissionSystem'] = [{'MTID': 'DUTY', 'SID': 'VEHICLE'}]
    t['Operations'] = [{'USTID': 'FLEET', 'PRID': 'DAILY'}]
    t['OperationProfile'] = [{'PRID': 'DAILY', 'SPRID': 'DUTY', 'STIM': str(day * 24 + 8)} for day in range(30)]
    t['Shift'] = [{'SHID': 'WORK', 'DESCR': '维修白班'}]
    t['ShiftProfile'] = [{'SHPID': 'DAY', 'SSHPID': 'WORK', 'STIM': str(day * 24 + 8),
                          'ETIM': str(day * 24 + 17)} for day in range(30)]
    t['ResourceStationData'] = [{'RID': 'TECH', 'STID': station, 'SHPID': 'DAY'} for station in ('BASE', 'DEPOT')]
    return project
