"""Per-physical-leaf preventive clocks; independent of failure age and slots."""


class PreventiveClocks:
    def __init__(self, env, components, tables):
        self.env, self.parts = env, components
        self.rules = {r['IID']: r for r in tables.get('SimLabItemPreventive', [])}
        self.clocks = {}
        self.register(components.records)

    def register(self, parts, fresh=False):
        """New procurement identities start now, never at the last integration time."""
        components = self.parts
        for part in parts:
            record = components.records[part]
            if part in self.clocks or record.get('retired') or record.get('retirement_due') or record['children'] or record['iid'] not in self.rules:
                continue
            rule = self.rules[record['iid']]
            root = record
            while root['parent']:
                root = components.records[root['parent']]
            initial = float(rule.get('INITIAL_H') or 0) if not fresh and components.locations[root['id']] == 'installed' else 0.
            self.clocks[part] = dict(part=part, iid=record['iid'], rule=rule['PMID'],
                clock=rule['CLOCK'], interval_hours=float(rule['INTERVAL_H']), hours=initial,
                due_at=None, paused=False, completed_services=0)

    def integrate(self, elapsed, operating):
        for part, c in self.clocks.items():
            if not c['paused']:
                c['hours'] += elapsed if c['clock'] == 'CALENDAR' else operating.get(part, 0.)

    def due(self):
        found = []
        for part, c in self.clocks.items():
            if c['due_at'] is None and not c['paused'] and c['hours'] >= c['interval_hours'] - 1e-10:
                c['due_at'] = self.env.now
                self.parts.records[part]['preventive_due'] = True
                found.append(part)
        return found

    def remaining(self, part, operating_rate):
        c = self.clocks[part]
        if c['paused'] or c['due_at'] is not None:
            return float('inf')
        rate = 1. if c['clock'] == 'CALENDAR' else operating_rate
        return max(0., c['interval_hours'] - c['hours']) / rate if rate else float('inf')

    def pause(self, part):
        if part in self.clocks:
            self.clocks[part]['paused'] = True

    def complete(self, part, actual=True):
        if part in self.clocks:
            c = self.clocks[part]
            c.update(hours=0., due_at=None, paused=False,
                     completed_services=c['completed_services'] + int(actual))
            self.parts.records[part]['preventive_due'] = False

    def snapshot(self):
        return [{**c, 'overrun_hours': max(0., c['hours'] - c['interval_hours'])}
                for c in list(self.clocks.values())[:10000]]
