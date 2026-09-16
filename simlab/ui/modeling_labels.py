"""Chinese presentation only; dictionary values remain the exchange format."""
from ..schema import TABLES, table_label, field_label
from ..validation import choices

VALUE_LABELS = {
    'PERFECT': '修复如新', 'MINIMAL': '最小修复',
    'Y': '是', 'N': '否', '<EXP>': '指数分布', '<POISSON>': '泊松分布',
    'ENABLER': '使能资源', 'SPECIAL': '专用资源', 'STANDARD': '标准资源',
    'EQUIDIST': '等间隔', 'RANDOM': '随机', 'FAST': '快速', 'SLOW': '慢速',
    'FIXED': '固定时长', 'CONTINUOUS': '连续', 'EXTENDABLE': '可延长',
    'LRU': '外场可更换部件', 'SRU': '车间可更换部件', 'PRU': '部分可修复部件',
    'SPRU': '部分可修复子件', 'DU': '不可修复部件', 'DP': '不可修复零件', 'ASSY': '组件',
    'OPERATION': '运行时间', 'CALENDAR': '日历时间', 'OPHOURS': '运行小时',
    'SCHEDULED': '按计划', 'REGENERATIVE': '再生式', 'SERIAL': '串联',
    'REDUNDANCY': '冗余', 'RBD': '可靠性框图', 'WS': '维修车间', 'DEPOT': '修理中心',
    'STORE': '仓库', 'OP': '使用站点', 'AUTOM': '自动站点',
}
TYPE_LABELS = {'Text': '文本', 'Integer': '整数', 'Floating point': '小数',
               'Index': '标识字段', 'Mandatory': '必填字段', 'Regular': '普通字段', 'Comment': '说明字段'}
UNIT_LABELS = {'': '无量纲或文本', 'Hours': '小时', '1/Hour': '每小时',
               '1/MOPIDs': '每百万运行参数单位'}
CONSTRAINT_LABELS = {
    '': '无额外约束', '0.0 <= number <= 1.0': '数值为零到一（含端点）',
    'Non-negative integer': '非负整数', 'Non-negative number': '非负数值',
    'Number greater than or equal to 1.0': '数值大于或等于一',
    'Positive integer': '正整数', 'Positive number': '正数',
    'Positive number <= 1.0': '数值大于零且不超过一',
}


def display_value(field, value):
    value = '' if value is None else str(value)
    return VALUE_LABELS.get(value, value) if value in choices(field) else value


def raw_value(field, text):
    for value in choices(field):
        if display_value(field, value) == text:
            return value
    return text


def constraint_label(field):
    options = choices(field)
    if options:
        result = '可选：' + '、'.join(display_value(field, value) for value in options)
        if 'or element in related table' in field['constraints']:
            result += '，或选择关联表中的记录'
        return result
    return CONSTRAINT_LABELS.get(field['constraints'], field['constraints'])


def references_label(field):
    labels = []
    for ref in field['references'].split(','):
        pair = ref.strip().split()
        if len(pair) == 2:
            table, column = pair
            related = next(f for f in TABLES[table] if f['id'] == column)
            labels.append(table_label(table) + ' · ' + field_label(related))
    return '；'.join(labels) or '无'
