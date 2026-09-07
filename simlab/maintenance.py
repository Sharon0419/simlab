"""Depot repair flows; parent turnaround is independent of system recovery."""
from collections import Counter

PHASES = {'transport': '送修运输', 'wait_resource': '等待资源或班次', 'diagnosis': '故障检测',
          'remove': '内部拆卸', 'wait_sru': '等待 SRU', 'install': '内部安装',
          'test': '修后测试', 'repair': '直接修复'}


class Workshop:
    def __init__(self, env, config, components, pool, store, rng, log):
        self.env, self.config, self.parts = env, config, components
        self.pool, self.store, self.rng, self.log = pool, store, rng, log
        self.active, self.history = {}, []
        self.count = 0
        self.totals = {}

    def begin(self, part, kind, station, parent=''):
        self.count += 1
        job = {'id': self.count, 'part': part, 'kind': kind, 'parent': parent, 'station': station,
               'start': self.env.now, 'end': None, 'phase': '', 'phase_start': self.env.now,
               'phase_hours': Counter()}
        self.active[self.count] = job
        self.totals.setdefault(kind, {'started': 0, 'completed': 0, 'tat_sum': 0.0, 'phase_hours': Counter()})['started'] += 1
        return job

    def phase(self, job, name):
        if job['phase']:
            job['phase_hours'][job['phase']] += self.env.now-job['phase_start']
        job['phase'], job['phase_start'] = name, self.env.now
        if name:
            self.parts.move(job['part'], name, job['station'])
            self.log(job['part'], PHASES[name], job['parent'])

    def complete(self, job):
        self.phase(job, '')
        job['end'] = self.env.now
        total = self.totals[job['kind']]
        total['completed'] += 1
        total['tat_sum'] += job['end']-job['start']
        total['phase_hours'].update(job['phase_hours'])
        self.active.pop(job['id'])
        if len(self.history) < 1000:
            self.history.append(job)

    def work(self, job, phase, rule, fraction=1):
        self.phase(job, 'wait_resource')
        yield self.pool.request(job['station'], rule['resources'])
        self.phase(job, phase)
        mean = rule['time']['mean']
        time = float(self.rng.exponential(mean)) if mean and rule['time']['random'] else mean
        yield self.env.timeout(time*fraction)
        self.pool.release(job['station'], rule['resources'])

    def repair_sru(self, station, part, parent):
        iid = self.parts.records[part]['iid']
        job = self.begin(part, 'SRU', station, parent)
        yield from self.work(job, 'repair', self.config['repairs'][(station, iid)])
        self.parts.restore(part)
        self.complete(job)
        self.parts.move(part, 'stock', station)
        yield self.store(station, iid).put(part)
        self.log(part, 'SRU 修复返库', parent)

    def repair(self, fleet, iid, part):
        station = fleet['root']
        job = self.begin(part, 'LRU', station)
        self.phase(job, 'transport')
        if station != fleet['home']:
            yield self.env.timeout(self.config['links'][fleet['home']]['outward'])
        if iid in self.config['children']:
            process = self.config['depot_processes'][(station, iid)]
            yield from self.work(job, 'diagnosis', process['diagnosis'])
            broken = [c for c in self.parts.records[part]['children'] if self.parts.records[c]['broken']]
            assert len(broken) == 1, 'Expected one failed SRU in serial model'
            child = broken[0]
            child_iid = self.parts.records[child]['iid']
            rule = self.config['replacements'][(iid, child_iid, station)]
            # Sample total replacement once, then split consistently with base replacement.
            mean = rule['time']['mean']
            total = float(self.rng.exponential(mean)) if mean and rule['time']['random'] else mean
            fixed = {'time': {'mean': total, 'random': False}, 'resources': rule['resources']}
            yield from self.work(job, 'remove', fixed, self.config['remove_fraction'])
            index = self.parts.detach(part, child)
            self.env.process(self.repair_sru(station, child, part))
            self.phase(job, 'wait_sru')
            replacement = yield self.store(station, child_iid).get()
            self.parts.move(replacement, 'held', station)
            yield from self.work(job, 'install', fixed, 1-self.config['remove_fraction'])
            self.parts.attach(part, index, replacement)
            yield from self.work(job, 'test', process['test'])
        else:
            yield from self.work(job, 'repair', self.config['repairs'][(station, iid)])
        self.parts.restore(part)
        self.complete(job)
        self.parts.move(part, 'stock', station)
        yield self.store(station, iid).put(part)
        self.log(part, 'LRU 修复返库', iid)

    def snapshot(self):
        totals = {kind: {**v, 'phase_hours': Counter(v['phase_hours'])} for kind, v in self.totals.items()}
        active = []
        for job in self.active.values():
            hours = Counter(job['phase_hours'])
            if job['phase']:
                hours[job['phase']] += self.env.now-job['phase_start']
            totals[job['kind']]['phase_hours'].update(hours)
            active.append({**job, 'phase_hours': dict(hours)})
        for kind, total in totals.items():
            total['in_progress'] = total['started']-total['completed']
            total['mean_tat'] = total['tat_sum']/total['completed'] if total['completed'] else None
            total['phase_hours'] = dict(total['phase_hours'])
        jobs = sorted(self.history + active, key=lambda j: j['id'])[:1000]
        return {'by_kind': totals, 'jobs': jobs, 'truncated': self.count > len(jobs)}


def aggregate(results):
    kinds = sorted({kind for r in results for kind in r['maintenance']['by_kind']})
    output = {}
    for kind in kinds:
        values = [r['maintenance']['by_kind'].get(kind, {}) for r in results]
        totals = {key: sum(v.get(key, 0) for v in values) for key in ('started', 'completed', 'tat_sum', 'in_progress')}
        output[kind] = {key: val/len(results) for key, val in totals.items()}
        output[kind]['mean_tat'] = totals['tat_sum']/totals['completed'] if totals['completed'] else None
        output[kind]['phase_hours'] = {key: sum(v.get('phase_hours', {}).get(key, 0) for v in values)/len(results) for key in PHASES}
    return {'by_kind': output, 'jobs': results[0]['maintenance']['jobs'],
            'truncated': results[0]['maintenance']['truncated']}
