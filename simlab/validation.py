"""Generic dictionary checks, separate from engine capability validation."""
import math
import re
from .schema import TABLES, effective

def choices(field):
    constraint = field['constraints']
    if not constraint.startswith('Multiple choice:'):
        return []
    text = constraint.split(':', 1)[1].strip()
    text = re.sub(r',?\s*or element in related table.*', '', text)
    return [x.strip() for x in re.split(r',|\s+or\s+', text) if x.strip()]

def validate(tables):
    errors = []
    for name, rows in tables.items():
        if name not in TABLES:
            errors.append(f'{name}: 未知数据表')
            continue
        fields = TABLES[name]
        known = {f['id'] for f in fields}
        keys = [f for f in fields if f['kind'] == 'Index']
        seen = set()
        if not isinstance(rows, list):
            errors.append(f'{name}: 数据应为记录列表')
            continue
        for index, row in enumerate(rows, 1):
            prefix = f'{name} 第 {index} 行'
            if not isinstance(row, dict):
                errors.append(f'{prefix}: 记录应为字段对象')
                continue
            for unknown in set(row) - known:
                errors.append(f'{prefix}.{unknown}: 字典中不存在的字段')
            if keys:
                key = tuple(effective(row, f) for f in keys)
                if key in seen:
                    errors.append(f'{prefix}: 组合键重复 {key}')
                seen.add(key)
            for field in fields:
                val = effective(row, field)
                location = f"{prefix}.{field['id']}"
                if not val:
                    if field['kind'] in ('Mandatory', 'Index'):
                        errors.append(f'{location}: 必填')
                    continue
                if field['type'] in ('Integer', 'Floating point'):
                    try:
                        number = float(val)
                        if not math.isfinite(number):
                            raise ValueError()
                        if field['type'] == 'Integer' and not number.is_integer():
                            raise ValueError()
                    except (ValueError, OverflowError):
                        errors.append(f'{location}: 需要有限的' + ('整数' if field['type'] == 'Integer' else '数值'))
                        continue
                    rule = field['constraints']
                    if ('Non-negative' in rule and number < 0 or
                        'Positive' in rule and number <= 0 or
                        '0.0 <= number <= 1.0' in rule and not 0 <= number <= 1 or
                        'number <= 1.0' in rule and number > 1 or
                        'greater than or equal to 1.0' in rule and number < 1):
                        errors.append(f'{location}: 不满足 {rule}')
                allowed = choices(field)
                refs = field['references']
                if refs and val not in allowed:
                    found = False
                    for ref in refs.split(','):
                        pair = ref.strip().split()
                        if len(pair) != 2:
                            continue
                        target, column = pair
                        found |= any(str(r.get(column, '')).strip() == val for r in tables.get(target, []) if isinstance(r, dict))
                    if not found:
                        errors.append(f'{location}: 引用 {val} 不存在；关联 {refs}')
                elif allowed and not refs and val not in allowed:
                    errors.append(f"{location}: 允许值 {', '.join(allowed)}")
    # Detect materiel cycles even before the engine compiler is called.
    edges = {}
    for row in tables.get('MaterielStructure', []):
        if isinstance(row, dict):
            edges.setdefault(row.get('MMID'), []).append(row.get('MID'))
    done, active = set(), set()
    def visit(node):
        if node in active:
            return True
        if node in done:
            return False
        active.add(node)
        for child in edges.get(node, []):
            if visit(child):
                return True
        active.remove(node)
        done.add(node)
        return False
    if any(visit(node) for node in list(edges)):
        errors.append('MaterielStructure: 装备组成存在循环引用')
    return errors
