"""Conditional Weibull lifetime in operating hours.

Risk multipliers scale cumulative hazard, not physical operating age.
Use log1p/expm1 to preserve small increments at large ages.
"""
import math


def compile_aging(tables, children, horizon):
    from .schema import value
    items = {row['IID']: row for row in tables.get('Item', [])}
    rules, errors = {}, []
    for row in tables.get('SimLabItemAging', []):
        iid = row['IID']
        shape = float(value('SimLabItemAging', row, 'SHAPE'))
        scale = float(value('SimLabItemAging', row, 'SCALE_H'))
        initial = float(value('SimLabItemAging', row, 'INITIAL_H'))
        repair = value('SimLabItemAging', row, 'REPAIR')
        if iid in children:
            errors.append(f'SimLabItemAging.{iid}: 仅允许叶子部件，不能配置带子件的总成。')
        if float(value('Item', items[iid], 'FRT')) != 0:
            errors.append(f'SimLabItemAging.{iid}: 配置寿命模型时 Item.FRT 必须为零。')
        if not 1 <= shape <= 10 or not 1e-6 <= scale or not 0 <= initial or not all(map(math.isfinite, (shape, scale, initial))):
            errors.append(f'SimLabItemAging.{iid}: 形状须为一至十，尺度至少百万分之一小时，年龄须非负且数值有限。')
            continue
        # Bound ratios for reliable double-precision hazard integration.
        if (initial + horizon) / scale > 1e12 or initial > 1e12:
            errors.append(f'SimLabItemAging.{iid}: 年龄与寿命尺度比值过大，请调整模型范围。')
        rules[iid] = dict(shape=shape, scale=scale, initial=initial, repair=repair,
                          application=float(value('Item', items[iid], 'AFFRT')))
    return rules, errors


def remaining_age(age, shape, scale, budget, multiplier):
    if multiplier == 0:
        return math.inf
    if budget <= 0:
        return 0.0
    risk = budget / multiplier
    if age == 0:
        return scale * risk ** (1 / shape)
    base = (age / scale) ** shape
    if base == 0 or risk >= base:
        return scale * (base + risk) ** (1 / shape) - age
    return age * math.expm1(math.log1p(risk / base) / shape)


def risk_increment(age, elapsed, shape, scale, multiplier):
    if multiplier == 0 or elapsed == 0:
        return 0.0
    if age == 0:
        return multiplier * (elapsed / scale) ** shape
    if elapsed >= age:
        return multiplier * (((age + elapsed) / scale) ** shape - (age / scale) ** shape)
    return multiplier * (age / scale) ** shape * math.expm1(shape * math.log1p(elapsed / age))
