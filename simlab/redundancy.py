"""Same-type k-of-n capability, independent of queued maintenance work."""
from collections import defaultdict
import math
from .aging import remaining_age, risk_increment


def compile_redundancy(tables, structures, children):
    counts = {(parent, p['iid']): p['quantity']
              for source in (structures, children) for parent, group in source.items() for p in group}
    rules, errors = {}, []
    for row in tables.get('SimLabRedundancy', []):
        key = row['PARENT'], row['IID']
        label = f'SimLabRedundancy.{key[0]}/{key[1]}'
        if key in rules:
            errors.append(f'{label}: 不允许重复配置。')
        try:
            k = float(row['K'])
            if not k.is_integer() or not 1 <= k <= counts.get(key, 0):
                raise ValueError()
        except (ValueError, TypeError, OverflowError):
            errors.append(f'{label}.K: 必须为现有直接父子组的整数，1≤K≤n。')
            continue
        rules[key] = int(k)
    return rules, errors


def groups(parts, parent, children, rules):
    """Summaries use installed slots (including empty ones), never global counts."""
    grouped = defaultdict(list)
    for iid, token in children:
        grouped[iid].append(token)
    return [dict(parent=parent, iid=iid, n=len(tokens), k=rules.get((parent, iid), len(tokens)),
                 available=sum(capable(parts, token, rules) for token in tokens))
            for iid, tokens in grouped.items()]


def capable(parts, token, rules):
    if token is None:
        return False
    record = parts.records[token]
    if record.get('own_broken') or record.get('retired'):
        return False
    if not record['children']:
        return not record['broken']
    return all(g['available'] >= g['k'] for g in groups(parts, record['iid'],
        zip(record['expected'], record['children']), rules))


def asset_groups(parts, asset, rules):
    return groups(parts, asset['sid'], ((s['iid'], s['token']) for s in asset['slots']), rules)


def asset_capable(parts, asset, rules):
    return all(g['available'] >= g['k'] for g in asset_groups(parts, asset, rules))


def fault_summary(parts, asset, rules):
    result = asset_groups(parts, asset, rules)
    for slot in asset['slots']:
        token = slot['token']
        if token and parts.records[token]['children']:
            record = parts.records[token]
            result.extend(dict(g, physical_parent=token) for g in groups(parts, record['iid'],
                zip(record['expected'], record['children']), rules))
    return result


class RedundantExposure:
    """Legacy maintenance adapter's physical clock; dispatch settles faults first.

    The old serial path retains its historical random draws. Explicit redundancy
    uses persistent leaf budgets, including models without an aging input table.
    """
    def __init__(self, env, config, parts, assets, rng, failed):
        self.env, self.config, self.parts, self.assets = env, config, parts, assets
        self.rng, self.failed = rng, failed
        self.last, self.event, self.settling = env.now, env.event(), False

    def changed(self):
        if not self.event.triggered:
            self.event.succeed()

    def entries(self, installed=False):
        for asset in self.assets:
            active = asset['mission'] is not None if self.config['missions'] else asset['state'] == 'available'
            if not active and not installed:
                continue
            for slot in asset['slots']:
                token = slot['token']
                if token is None or not capable(self.parts, token, self.config['redundancy']):
                    continue
                root = self.parts.records[token]
                specs = {p['iid']: p for p in self.parts.definitions.get(root['iid'], [])}
                for leaf in self.parts.leaves(token):
                    if leaf['broken']:
                        continue
                    rule = self.parts.rules.get(leaf['iid'])
                    factor = slot['envf'] * (specs[leaf['iid']]['envf'] if specs else 1.)
                    if rule:
                        shape, scale, multiplier = rule['shape'], rule['scale'], rule['application'] * factor
                    else:
                        shape, scale = 1., 1.
                        multiplier = specs[leaf['iid']]['rate'] * slot['envf'] if specs else slot['rate']
                    yield asset, slot, leaf, asset['_fleet']['util'], shape, scale, multiplier

    def integrate(self):
        elapsed = self.env.now - self.last
        if elapsed <= 0:
            return
        for _, _, leaf, util, shape, scale, multiplier in self.entries():
            hours = elapsed * util
            if leaf['budget'] is not None:
                leaf['budget'] = max(0., leaf['budget'] - risk_increment(leaf['age'], hours, shape, scale, multiplier))
            leaf['age'] += hours
            leaf['lifetime_hours'] += hours
        self.last = self.env.now

    def settle_faults(self):
        if self.settling:
            return
        self.integrate()
        self.settling = True
        try:
            # Snapshot before applying any fault: simultaneous physical failures
            # remain real even if the first one disables their parent branch.
            due = [(a, s, r['id']) for a, s, r, _, _, _, m in self.entries(installed=True)
                   if m and r['budget'] is not None and r['budget'] <= 1e-12]
            for asset, slot, leaf in due:
                self.failed(asset, slot, leaf)
        finally:
            self.settling = False

    def run(self):
        while True:
            self.settle_faults()
            delay = math.inf
            for _, _, leaf, util, shape, scale, multiplier in self.entries():
                if multiplier and leaf['budget'] is None:
                    leaf['budget'] = float(self.rng.exponential(1.))
                if multiplier and util:
                    delay = min(delay, remaining_age(leaf['age'], shape, scale, leaf['budget'], multiplier) / util)
            event, self.event = self.event, self.env.event()
            if event.triggered:
                yield self.env.timeout(0)
            elif math.isfinite(delay):
                yield self.env.timeout(max(0., delay)) | self.event
            else:
                yield self.event
