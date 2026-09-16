"""Physical running-age accounting for explicitly enabled aging models."""
import math

from .components import Components
from .aging import remaining_age, risk_increment


class AgingComponents(Components):
    def __init__(self, definitions, rules, env):
        super().__init__(definitions)
        self.rules, self.env = rules, env
        self.running = {}
        self.age_events = []
        self.age_event_count = 0

    def create(self, iid, location, site=''):
        part = super().create(iid, location, site)
        record = self.records[part]
        record.update(age=0., lifetime_hours=0.)
        if location == 'installed':
            for leaf in self.leaves(part):
                age = self.rules.get(leaf['iid'], {}).get('initial', 0.)
                leaf.update(age=age, lifetime_hours=age)
        return part

    def leaves(self, part):
        record = self.records[part]
        if not record['children']:
            yield record
        else:
            for child in record['children']:
                if child is not None:
                    yield from self.leaves(child)

    def age_event(self, record, event, before):
        self.age_event_count += 1
        if len(self.age_events) < 10000:
            self.age_events.append(dict(time=self.env.now, part=record['id'], iid=record['iid'],
                event=event, age_before=before, age_after=record['age'],
                lifetime_hours=record['lifetime_hours'],
                repair=self.rules.get(record['iid'], {}).get('repair', 'PERFECT')))

    def fail(self, parent, leaf):
        super().fail(parent, leaf)
        record = self.records[leaf]
        self.age_event(record, 'failure', record['age'])

    def restore(self, part):
        record = self.records[part]
        before = record['age']
        was_broken = record['broken']
        super().restore(part)
        if not record['children'] and was_broken:
            if self.rules.get(record['iid'], {}).get('repair', 'PERFECT') == 'PERFECT':
                record['age'] = 0.
            self.age_event(record, 'repair', before)

    def settle(self, key):
        active = self.running.pop(key, None)
        if active is None:
            return
        started, util, leaves = active
        elapsed = (self.env.now - started) * util
        for _, record, shape, scale, multiplier in leaves:
            used = risk_increment(record['age'], elapsed, shape, scale, multiplier)
            if record['budget'] is not None:
                record['budget'] = max(0., record['budget'] - used)
            record['age'] += elapsed
            record['lifetime_hours'] += elapsed

    def finish_ages(self):
        for key in list(self.running):
            self.settle(key)

    def age_snapshot(self):
        rows = []
        for part, record in self.records.items():
            if record['children']:
                continue
            if len(rows) >= 10000:
                break
            root = self.records[record['parent']] if record['parent'] else record
            rows.append(dict(part=part, iid=record['iid'], parent=record['parent'] or '',
                age=record['age'], lifetime_hours=record['lifetime_hours'], broken=record['broken'],
                location=self.locations[root['id']], site=root['site']))
        return dict(instances=rows, events=list(self.age_events),
                    instances_truncated=sum(not r['children'] for r in self.records.values()) > len(rows),
                    events_truncated=self.age_event_count > len(self.age_events))

    def failure(self, env, asset, fleet, rng, mission_mode, stop_on_landing=False):
        leaves = []
        for slot in asset['slots']:
            parent = self.records[slot['token']]
            specs = {p['iid']: p for p in self.definitions.get(parent['iid'], [])}
            for record in self.leaves(parent['id']):
                if record['broken']:
                    continue
                rule = self.rules.get(record['iid'])
                factor = slot['envf'] * (specs[record['iid']]['envf'] if specs else 1)
                if rule:
                    shape, scale, multiplier = rule['shape'], rule['scale'], rule['application'] * factor
                else:
                    # Existing per-operating-hour rate already contains AFFRT/ENVF.
                    rate = specs[record['iid']]['rate'] * slot['envf'] if specs else slot['rate']
                    shape, scale, multiplier = 1., 1., rate
                if multiplier and record['budget'] is None:
                    record['budget'] = float(rng.exponential(1.))
                leaves.append((slot, record, shape, scale, multiplier))
        while True:
            if stop_on_landing and asset['mission'] is None:
                return None
            if mission_mode and asset['mission'] is None:
                yield asset['assignment_event']
                continue
            best, delay = None, math.inf
            if fleet['util']:
                for entry in leaves:
                    _, record, shape, scale, multiplier = entry
                    wait = remaining_age(record['age'], shape, scale, record['budget'] or 0., multiplier) / fleet['util']
                    if wait < delay:
                        best, delay = entry, wait
            self.running[asset['id']] = (env.now, fleet['util'], leaves)
            deadline = env.timeout(delay)
            outcome = yield deadline | asset['assignment_event'] if mission_mode else deadline
            self.settle(asset['id'])
            if not mission_mode or deadline in outcome:
                if best is None:
                    continue
                slot, record, *_ = best
                record['budget'] = 0.
                return slot, record['id']
