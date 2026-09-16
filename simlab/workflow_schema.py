"""SimLab-owned support workflow input fields."""
def workflow_tables(field):
    tables = {
        'SimLabWorkflow': [field('WFID', 'Index', '工序方案标识'), field('NAME', 'Regular', '方案名称')],
        'SimLabWorkflowStep': [
            field('WFID', 'Index', '所属方案', references='SimLabWorkflow WFID'),
            field('STEPID', 'Index', '方案内唯一工序标识'), field('NAME', 'Regular', '工序名称'),
            field('ACTION', 'Regular', '业务动作', default='CUSTOM'),
            field('DURATION_H', 'Mandatory', '工序时长', 'Floating point', unit='Hours'),
            field('DISTRIBUTION', 'Regular', '时长分布', default='FIXED'),
            field('TASK', 'Regular', '工序资源需求', references='Tasks TID'),
            field('PREDECESSORS', 'Regular', '全部紧前工序标识，多个用逗号分隔')],
        'SimLabWorkflowBinding': [
            field('BINDID', 'Index', '活动绑定标识'),
            field('WFID', 'Mandatory', '采用的工序方案', references='SimLabWorkflow WFID'),
            field('ACTIVITY', 'Mandatory', '适用保障活动'),
            field('RULEID', 'Regular', '维修/飞行/检查规则标识'),
            field('METHOD', 'Regular', '在位维修路径或报废换件'),
            field('IID', 'Regular', '拆下件型号，其他活动留空', references='Item IID'),
            field('STID', 'Regular', '拆下件维修站点，其他活动留空', references='Station STID'),
            field('KIND', 'Regular', '拆下件维修类别，其他活动留空')],
    }
    tables['SimLabWorkflowStep'][3]['constraints'] = 'Multiple choice: CUSTOM, DIAGNOSE, REMOVE, INSTALL, IN_PLACE, SERVICE, TEST'
    tables['SimLabWorkflowStep'][5]['constraints'] = 'Multiple choice: FIXED, EXPONENTIAL'
    tables['SimLabWorkflowBinding'][2]['constraints'] = 'Multiple choice: MAINTENANCE, OFF_ITEM, PREPARATION, CALENDAR, INSPECTION'
    tables['SimLabWorkflowBinding'][4]['constraints'] = 'Multiple choice: IN_PLACE, REPLACE, RETIREMENT'
    tables['SimLabWorkflowBinding'][7]['constraints'] = 'Multiple choice: CORRECTIVE, PREVENTIVE'
    return tables
