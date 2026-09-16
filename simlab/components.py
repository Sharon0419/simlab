"""Physical identities, assembly slots and persistent leaf failure budgets."""
from collections import Counter
from .redundancy import capable


class Components:
    def __init__(self, definitions):
        self.definitions = definitions
        self.records = {}
        self.locations = {}
        self.redundancy = {}

    def create(self, iid, location, site=''):
        name = f'{iid}#{len(self.records)+1}'
        record = {'id': name, 'iid': iid, 'parent': None, 'children': [], 'expected': [],
                  'broken': False, 'budget': None, 'site': site}
        self.records[name] = record
        self.locations[name] = location
        for spec in self.definitions.get(iid, []):
            for _ in range(spec['quantity']):
                child = self.create(spec['iid'], 'attached', site)
                self.records[child]['parent'] = name
                record['children'].append(child)
                record['expected'].append(spec['iid'])
        return name

    def move(self, part, location, site):
        assert self.records[part]['parent'] is None, 'Attached subitem cannot move independently'
        self.locations[part] = location
        self.records[part]['site'] = site

    def detach(self, parent, child):
        p, c = self.records[parent], self.records[child]
        assert c['parent'] == parent
        index = p['children'].index(child)
        p['children'][index] = None
        c['parent'] = None
        c['site'] = p['site']
        self.locations[child] = 'held'
        return index

    def attach(self, parent, index, child):
        p, c = self.records[parent], self.records[child]
        assert p['children'][index] is None and c['parent'] is None
        assert p['expected'][index] == c['iid'] and not c['broken']
        assert self.locations[child] == 'held'
        p['children'][index] = child
        c['parent'] = parent
        self.locations[child] = 'attached'

    def fail(self, parent, leaf):
        assert leaf == parent or self.records[leaf]['parent'] == parent
        self.records[leaf]['broken'] = True
        self.records[leaf]['own_broken'] = True
        self.records[parent]['broken'] = True

    def restore(self, part):
        r = self.records[part]
        assert all(c is not None and not self.records[c]['broken'] for c in r['children'])
        r['broken'] = False
        r['own_broken'] = False
        if not r['children']:
            r['budget'] = None

    def validate(self, installed, stocked):
        assert len(installed) == len(set(installed))
        assert len(stocked) == len(set(stocked))
        assert not set(installed) & set(stocked)
        assert set(installed) == {k for k, v in self.locations.items() if v == 'installed'}
        assert set(stocked) == {k for k, v in self.locations.items() if v == 'stock'}
        attached = []
        for parent, r in self.records.items():
            for index, child in enumerate(r['children']):
                if child is not None:
                    attached.append(child)
                    assert self.records[child]['parent'] == parent
                    assert self.records[child]['iid'] == r['expected'][index]
            if self.locations[parent] == 'stock':
                assert not r['broken'] and all(r['children'])
        assert len(attached) == len(set(attached))
        assert set(attached) == {k for k, r in self.records.items() if r['parent'] is not None}
        assert set(attached) == {k for k, loc in self.locations.items() if loc == 'attached'}

    def snapshot(self):
        rows = []
        counts = Counter(r['iid'] for r in self.records.values())
        for name, r in list(self.records.items())[:1000]:
            root = self.records[r['parent']] if r['parent'] else r
            rows.append({'id': name, 'iid': r['iid'], 'parent': r['parent'] or '',
                         'location': self.locations[name], 'physical_location': self.locations[root['id']],
                         'site': root['site'], 'broken': r['broken']})
        return {'by_item': dict(counts), 'instances': rows, 'truncated': len(self.records) > len(rows)}

    def failure(self, env, asset, fleet, rng, mission_mode, stop_on_landing=False):
        leaves = []
        for slot in asset['slots']:
            if slot['token'] is None or (self.redundancy and not capable(self, slot['token'], self.redundancy)):
                continue
            parent = self.records[slot['token']]
            if parent['children']:
                specs = {p['iid']: p for p in self.definitions[parent['iid']]}
                for name in parent['children']:
                    r = self.records[name]
                    leaves.append((slot, r, specs[r['iid']]['rate'] * slot['envf'] * fleet['util']))
            else:
                leaves.append((slot, parent, slot['rate'] * fleet['util']))
        leaves = [(s, r, rate) for s, r, rate in leaves if rate > 0 and not r['broken']]
        for _, r, _ in leaves:
            if r['budget'] is None:
                r['budget'] = float(rng.exponential(1.0))
        while True:
            if stop_on_landing and asset['mission'] is None:
                return None
            if not leaves:
                yield asset['assignment_event']
                continue
            if mission_mode and asset['mission'] is None:
                yield asset['assignment_event']
                continue
            slot, record, rate = min(leaves, key=lambda x: x[1]['budget']/x[2])
            delay = record['budget']/rate
            started = env.now
            deadline = env.timeout(delay)
            outcome = yield deadline | asset['assignment_event'] if mission_mode else deadline
            for _, r, hazard in leaves:
                r['budget'] = max(0.0, r['budget'] - hazard*(env.now-started))
            if not mission_mode or deadline in outcome:
                record['budget'] = 0.0
                return slot, record['id']
