"""Compile the supported two-level serial component structure."""
from .schema import value


def compile_structure(tables):
    items = {r['IID']: r for r in tables.get('Item', [])}
    systems = {r['SID'] for r in tables.get('System', [])}
    errors, children, structures = [], {}, {}
    if systems & items.keys():
        errors.append('System/Item: 系统与部件标识不能重名。')
    def num(t, r, f):
        return float(value(t, r, f, '0'))
    for r in tables.get('MaterielStructure', []):
        parent, child = r['MMID'], r['MID']
        if child not in items or parent not in systems | items.keys():
            errors.append('MaterielStructure: 需要有效的系统/LRU/SRU 组成。')
            continue
        kind = value('Item', items[child], 'TYPE')
        if parent in systems:
            target = structures
            valid = kind == 'LRU'
        else:
            target = children
            valid = value('Item', items[parent], 'TYPE') == 'LRU' and kind == 'SRU'
        if not valid:
            errors.append(f'MaterielStructure.{parent}/{child}: 仅支持 System→LRU→SRU，不支持更深层级。')
            continue
        qty, envf = int(num('MaterielStructure', r, 'QTYPM')), num('MaterielStructure', r, 'ENVF')
        if qty < 1:
            errors.append(f'MaterielStructure.{parent}/{child}: QTYPM 必须大于零。')
        rate = num('Item', items[child], 'FRT') * num('Item', items[child], 'AFFRT') * envf / 1_000_000
        target.setdefault(parent, []).append({'iid': child, 'quantity': qty, 'rate': rate, 'envf': envf})
    for parent, parts in children.items():
        if num('Item', items[parent], 'FRT') != 0 or num('Item', items[parent], 'AFFRT') != 1:
            errors.append(f'Item.{parent}: 带 SRU 的 LRU 必须 FRT=0、AFFRT=1，避免重复故障。')
    for parts in structures.values():
        for part in parts:
            if part['iid'] in children:
                part['rate'] = part['envf'] * sum(p['rate'] * p['quantity'] for p in children[part['iid']])
    return structures, children, errors
