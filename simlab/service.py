"""M3 service jobs, single-draw method selection and physical-tree ownership."""
from collections import Counter
from contextlib import contextmanager
import heapq
from .retirement import Retirement


class ServiceCoordinator:
    def __init__(self, env, config, components, supply, pool, method_rng, work_rng, set_state, log):
        self.env, self.config, self.parts, self.supply = env, config, components, supply
        self.pool, self.method_rng, self.work_rng = pool, method_rng, work_rng
        self.corrective_rng = self.replace_rng = work_rng
        self.set_state, self.log = set_state, log
        self.tables = config['m3']['tables']
        self.rules = {(r['MID'], r['IID'], r['STID'], r['KIND']): r
                      for r in self.tables.get('SimLabMaintenanceRule', [])}
        self.steps = {(r['RULEID'], r['STEP']): r for r in self.tables.get('SimLabMaintenanceStep', [])}
        self.offsteps = {(r['IID'], r['STID'], r['KIND'], r['STEP']): r
                         for r in self.tables.get('SimLabOffItemService', [])}
        self.destinations = {(r['IID'], r['FROM_STID']): r['REPAIR_STID']
                             for r in self.tables.get('SimLabRepairLocation', [])}
        self.assets, self.jobs, self.locks = [], [], {}
        self.manager = self.clocks = self.runtime = None
        self.quarantined = set()
        self.reservations = {}
        self._registration_depth = 0
        self.retirement = Retirement(self)
        supply.eligible = self.eligible
        supply.on_stock = self.on_stock

    def root(self, part):
        while self.parts.records[part]['parent']:
            part = self.parts.records[part]['parent']
        return part

    def eligible(self, part):
        return not any(r.get('retired') or r.get('retirement_due') or self.retirement.reason(r)
                       for r in self.retirement.tree(part)) and not self.parts.records[part]['broken'] and all(
            not r['broken'] and not r.get('preventive_due') for r in self.parts.leaves(part))

    def locate(self, part):
        root = self.root(part)
        for asset in self.assets:
            for slot in asset['slots']:
                if slot['token'] == root:
                    return asset, slot
        return None, None

    def select_method(self, rule):
        method = rule['METHOD']
        if method != 'MIXED':
            return method
        p = float(rule['REPLACE_P'])
        return 'REPLACE' if p == 1 or (p != 0 and self.method_rng.random() < p) else 'IN_PLACE'

    def rule(self, mid, iid, station, kind):
        rule = self.rules.get((mid, iid, station, kind))
        if rule is not None:
            return rule
        if kind != 'CORRECTIVE':
            raise ValueError(f'M3 缺少维修规则: {mid}/{iid}/{station}/{kind}')
        old = self.config.get('replacements', {}).get((mid, iid, station))
        if old is None:
            raise ValueError(f'M3 缺少修复规则: {mid}/{iid}/{station}')
        return dict(RULEID=f'legacy:{mid}:{iid}:{station}', METHOD='REPLACE', _legacy=old)

    def create_job(self, part, kind, mid, station, asset=None, slot=None, off=False, due=None):
        if len(self.jobs) >= 200000:
            raise RuntimeError('M3 服务工单规模超过200000，仿真停止。')
        record = self.parts.records[part]
        rule = None if off else self.rule(mid, record['iid'], station, 'CORRECTIVE' if kind == 'RETIREMENT' else kind)
        job = dict(id=f'J{len(self.jobs)+1:06d}', kind=kind, rule=rule['RULEID'] if rule else 'OFF_ITEM',
            part=part, iid=record['iid'], parent=mid, asset=asset['id'] if asset else '', station=station,
            method='REPLACE' if kind == 'RETIREMENT' else self.select_method(rule) if rule else 'OFF_ITEM', status='queued',
            due_at=self.env.now if due is None else due, started_at=None, ended_at=None,
            age_before=record.get('age'), age_after=None, lifetime_hours=record.get('lifetime_hours'),
            overrun_hours=0., _rule=rule, _asset=asset, _slot=slot, _off=off)
        self.jobs.append(job)
        self.log(job['asset'] or part, '维修工单登记', f"{job['id']}:{kind}:{job['method']}")
        return job

    def corrective(self, asset, slot):
        part = slot['token']
        if self.parts.records[part].get('retirement_due'):
            return
        old = next((j for j in self.jobs if j['part'] == part and j['kind'] == 'CORRECTIVE'
                    and j['ended_at'] is None and not j['_off']), None)
        if old:
            return old
        job = self.create_job(part, 'CORRECTIVE', asset['sid'], asset['home'], asset, slot)
        if self.config.get('redundancy'):
            asset['repair_pending'] = True
        self.advance()
        return job

    def preventive(self, part):
        if self.parts.records[part].get('retired') or self.parts.records[part].get('retirement_due'):
            return
        if any(j['part'] == part and j['kind'] == 'PREVENTIVE' and j['ended_at'] is None for j in self.jobs):
            return
        record = self.parts.records[part]
        asset, slot = self.locate(part)
        reservation = self.reservations.get(self.root(part))
        if reservation:
            asset, slot = reservation['_asset'], reservation['_slot']
        station = asset['home'] if asset else self.parts.records[self.root(part)]['site']
        mid = self.parts.records[record['parent']]['iid'] if record['parent'] else reservation['parent'] if reservation else asset['sid'] if asset else ''
        off = (asset is None or reservation is not None) and record['parent'] is None
        if off and reservation:
            asset, slot = None, None
        job = self.create_job(part, 'PREVENTIVE', mid, station, asset, slot, off)
        if self.clocks:
            job['due_at'] = self.clocks.clocks[part]['due_at']
        root = self.root(part)
        if self.parts.locations[root] == 'stock':
            self.supply.withdraw(root)
            self.quarantined.add(root)
        self.advance()
        return job

    @staticmethod
    def priority(job):
        return (-1 if job['kind'] == 'RETIREMENT' else 0 if job['kind'] == 'CORRECTIVE' else 1, job['due_at'], 2, job['rule'], job['id'])

    @contextmanager
    def registration_batch(self):
        """Register one instant's work/quarantines before acquiring tree locks.

        Stock callbacks may call advance synchronously during registration; the
        same guard covers them and nested registrations. No SimPy yield occurs.
        """
        self._registration_depth += 1
        try:
            yield
        finally:
            self._registration_depth -= 1
        if not self._registration_depth:
            self.advance()

    def blocked(self, asset):
        return any(j['_asset'] is asset and j['ended_at'] is None and not j['_off'] for j in self.jobs)

    def planned_can_start(self, asset, planned_job):
        if asset['id'] in self.locks:
            return False
        pending = [j for j in self.jobs if j['_asset'] is asset and j['status'] == 'queued' and not j['_off']]
        key = (1, planned_job['due_at'], 1 if '_clock' in planned_job else 0, planned_job['rule'], '')
        return not pending or min(map(self.priority, pending)) >= key

    def ready(self, job):
        if self.root(job['part']) in self.reservations:
            return False
        asset = job['_asset']
        if asset:
            if asset['mission'] is not None and self.manager and (hasattr(self.manager, 'ground') or self.config.get('redundancy')):
                return False
            if asset['state'] in ('planned_wait', 'planned_maintenance'):
                return False
            if self.manager and hasattr(self.manager, 'ground'):
                ground = self.manager.ground
                if ground and asset['id'] in ground.active:
                    return False
                if asset.get('prep_deadline') is not None and asset['prep_deadline'] > self.env.now:
                    return False
                planned = self.manager.planned
                if planned:
                    queue = planned.pending.get(asset['id'], [])
                    if queue and self.planned_can_start(asset, queue[0]):
                        return False
        elif self.parts.locations[self.root(job['part'])] in ('transport', 'shipment', 'service_transport'):
            return False
        return True

    def advance(self):
        if self._registration_depth:
            return
        for job in sorted(self.jobs, key=self.priority):
            if job['status'] != 'queued' or not self.ready(job):
                continue
            key = job['_asset']['id'] if job['_asset'] else self.root(job['part'])
            if key in self.locks:
                continue
            self.locks[key] = job['id']
            job['status'] = 'starting'
            if job['_asset']:
                self.set_state(job['_asset'], 'waiting_resource')
            self.env.process(self.run(job, key))

    def on_stock(self, station, part):
        if self.runtime:
            self.runtime.integrate()
        if self.clocks:
            self.clocks.register((r['id'] for r in self.retirement.tree(part)), fresh=True)
        if self.runtime:
            self.runtime.changed()
        self.retirement.due()
        if self.parts.records[part].get('retired'):
            self.supply.withdraw(part)
            self.parts.move(part, 'retired', station)
            return
        if not self.eligible(part):
            self.supply.withdraw(part)
            self.quarantined.add(part)
            for job in self.jobs:
                if job['ended_at'] is None and self.root(job['part']) == part:
                    job['station'] = station
            self.advance()

    def needs(self, step):
        task = step.get('TASK', '')
        return {r['RID']: int(float(r['QTY'])) for r in self.tables.get('TaskResource', [])
                if task and r['TID'] == task and float(r['QTY']) > 0}

    def step(self, job, name, off=False):
        rng = self.work_rng if job['kind'] == 'PREVENTIVE' else self.replace_rng if name in ('REMOVE', 'INSTALL') else self.corrective_rng
        if off:
            spec = self.offsteps.get((job['iid'], job['station'], job['kind'], name))
        else:
            spec = self.steps.get((job['rule'], name))
        old = (job.get('_rule') or {}).get('_legacy')
        if old and name in ('REMOVE', 'INSTALL'):
            if '_legacy_duration' not in job:
                mean = old['time']['mean']
                job['_legacy_duration'] = float(rng.exponential(mean)) if old['time']['random'] and mean else mean
            frac = self.config['remove_fraction'] if name == 'REMOVE' else 1-self.config['remove_fraction']
            duration, needs = job['_legacy_duration']*frac, old['resources']
        elif spec:
            duration = float(spec['DURATION_H'])
            if spec.get('DISTRIBUTION', 'FIXED') == 'EXPONENTIAL' and duration:
                duration = float(rng.exponential(duration))
            needs = self.needs(spec)
        elif off and job['kind'] == 'CORRECTIVE' and (name == 'SERVICE' or
                (self.parts.records[job['part']]['children'] and name in ('DIAGNOSE', 'TEST'))):
            if name == 'SERVICE':
                old = self.config.get('repairs', {}).get((job['station'], job['iid']))
            else:
                old = self.config.get('depot_processes', {}).get((job['station'], job['iid']), {}).get(
                    'diagnosis' if name == 'DIAGNOSE' else 'test')
            if old is None:
                raise ValueError(f"M3 缺少拆下件服务: {job['iid']}/{job['station']}/{job['kind']}")
            mean = old['time']['mean']
            duration = float(rng.exponential(mean)) if old['time']['random'] and mean else mean
            needs = old['resources']
        else:
            return
        job['status'] = 'waiting_resource'
        if job['_asset']:
            self.set_state(job['_asset'], 'waiting_resource')
        yield self.pool.request(job['station'], needs)
        job['status'] = 'working'
        if job['_asset']:
            self.set_state(job['_asset'], 'replacement')
        yield self.env.timeout(duration)
        self.pool.release(job['station'], needs)

    def path(self, iid, source, destination):
        queue = [(0., (), source, ())]
        seen = set()
        while queue:
            delay, ids, node, path = heapq.heappop(queue)
            if node == destination:
                return path
            if node in seen:
                continue
            seen.add(node)
            for r in self.tables.get('SimLabServiceRoute', []):
                if r['IID'] == iid and r['FROM_STID'] == node:
                    heapq.heappush(queue, (delay+float(r['TRANSIT_H']), ids+(r['ROUTEID'],),
                                          r['TO_STID'], path+(r,)))
        raise ValueError(f'M3 缺少有向送修路径: {iid}/{source}->{destination}')

    def finish_leaf(self, job):
        part = job['part']
        if self.runtime:
            self.runtime.integrate()
        perfect = self.parts.service_complete(part, job['kind'])
        if self.clocks and (job['kind'] == 'PREVENTIVE' or perfect):
            clock = self.clocks.clocks.get(part)
            if clock:
                job['overrun_hours'] = max(0., clock['hours']-clock['interval_hours'])
            self.clocks.complete(part, actual=job['kind'] == 'PREVENTIVE')
        elif self.clocks and part in self.clocks.clocks:
            self.clocks.clocks[part]['paused'] = False
        if job['kind'] == 'CORRECTIVE' and perfect:
            for other in self.jobs:
                if other['part'] == part and other['kind'] == 'PREVENTIVE' and other['status'] == 'queued':
                    other.update(status='covered_by_corrective', ended_at=self.env.now,
                                 age_after=self.parts.records[part]['age'])
        record = self.parts.records[part]
        if job['kind'] == 'CORRECTIVE' and self.retirement.enabled:
            record['corrective_repairs'] += 1
            reason = self.retirement.reason(record)
            if reason:
                self.retirement.request(part, reason)
        job.update(age_after=record['age'], lifetime_hours=record['lifetime_hours'])

    def children(self, job):
        parent = self.parts.records[job['part']]
        for child in list(parent['children']):
            if child is not None and self.parts.records[child]['broken']:
                nested = self.create_job(child, 'CORRECTIVE', parent['iid'], job['station'], job['_asset'])
                nested['status'] = 'starting'
                yield from self.execute(nested)
        self.parts.restore(job['part'])

    def execute(self, job):
        job['started_at'] = self.env.now
        part, kind = job['part'], job['kind']
        record = self.parts.records[part]
        if not job['_off'] and (job['_rule'] or {}).get('STID', job['station']) != job['station']:
            rule = self.rule(job['parent'], job['iid'], job['station'], 'CORRECTIVE' if kind == 'RETIREMENT' else kind)
            if kind != 'RETIREMENT' and rule['METHOD'] not in ('MIXED', job['method']):
                raise ValueError(f"M3 已选维修方式 {job['method']} 在新地点 {job['station']} 缺少兼容规则")
            job.update(rule=rule['RULEID'], _rule=rule)
        if self.runtime:
            self.runtime.integrate()
        job['age_before'] = record.get('age')
        if self.clocks:
            self.clocks.pause(part)
        if job['_off']:
            source = job['station']
            destination = self.destinations.get((job['iid'], source))
            if destination is None:
                raise ValueError(f"M3 缺少维修地点映射: {job['iid']}/{source}")
            job['status'] = 'transport'
            for route in self.path(job['iid'], source, destination):
                self.parts.move(part, 'service_transport', route['TO_STID'])
                yield self.env.timeout(float(route['TRANSIT_H']))
            job['station'] = destination
            self.parts.move(part, 'service', destination)
            for pending in self.jobs:
                if pending['status'] == 'queued' and self.root(pending['part']) == part:
                    pending['station'] = destination
            yield from self.step(job, 'DIAGNOSE', off=True)
            if record['children']:
                yield from self.children(job)
            else:
                yield from self.step(job, 'SERVICE', off=True)
            yield from self.step(job, 'TEST', off=True)
            if not record['children']:
                self.finish_leaf(job)
            if not record.get('retired'):
                self.supply.return_part(destination, part)
        else:
            if kind != 'RETIREMENT':
                yield from self.step(job, 'DIAGNOSE')
            if job['method'] == 'IN_PLACE':
                if record['children']:
                    yield from self.children(job)
                yield from self.step(job, 'IN_PLACE')
                yield from self.step(job, 'TEST')
                if not record['children']:
                    self.finish_leaf(job)
            else:
                yield from self.step(job, 'REMOVE')
                parent = record['parent']
                if parent:
                    if kind == 'RETIREMENT':
                        job['_assembly'] = parent
                    index = self.parts.detach(parent, part)
                else:
                    job['_slot']['token'] = None
                    self.parts.move(part, 'held', job['station'])
                if kind == 'RETIREMENT':
                    self.retirement.dispose(part, asset=job['asset'])
                else:
                    off = self.create_job(part, kind, job['parent'], job['station'], off=True)
                    off['status'] = 'starting'
                # Detached parts leave the installed tree lock, but retain their
                # own lock while off-item repair and any pending PM are serialized.
                for pending in self.jobs:
                    if pending is not job and self.root(pending['part']) == part and pending['status'] == 'queued':
                        pending.update(_asset=None, _slot=None, asset='')
                        if pending['part'] == part:
                            pending.update(_off=True, method='OFF_ITEM')
                if kind != 'RETIREMENT':
                    self.locks[part] = off['id']
                    self.env.process(self.run(off, part))
                job['status'] = 'waiting_spare'
                if job['_asset']:
                    self.set_state(job['_asset'], 'waiting_spare')
                while True:
                    job['status'] = 'waiting_spare'
                    if job['_asset']:
                        self.set_state(job['_asset'], 'waiting_spare')
                    spare = yield self.supply.request_part(job['station'], job['iid'], owner=job['id'])
                    self.reservations[spare] = job
                    yield from self.step(job, 'INSTALL')
                    if self.runtime:
                        self.runtime.due()
                    self.reservations.pop(spare, None)
                    if self.eligible(spare):
                        break
                    # A calendar expiration while waiting/working cannot make an
                    # overdue spare installable. Finish the non-preempted step,
                    # quarantine its physical token, then request another spare.
                    self.quarantined.add(spare)
                    for pending in self.jobs:
                        if pending['status'] == 'queued' and self.root(pending['part']) == spare:
                            pending.update(_asset=None, _slot=None, asset='')
                    self.advance()
                if parent:
                    self.parts.attach(parent, index, spare)
                    if kind == 'RETIREMENT' and all(c and not self.parts.records[c]['broken'] for c in self.parts.records[parent]['children']):
                        self.parts.restore(parent)
                else:
                    job['_slot']['token'] = spare
                    self.parts.move(spare, 'installed', job['station'])
                yield from self.step(job, 'TEST')
        job.update(status='completed', ended_at=self.env.now)
        self.log(job['asset'] or part, '维修工单完成', job['id'])

    def run(self, job, key):
        yield from self.execute(job)
        if key is not None:
            self.locks.pop(key, None)
        asset = job['_asset']
        if asset:
            # No dispatch or preparation between consecutive ground work items.
            if not self.blocked(asset):
                asset.pop('repair_pending', None)
                asset.update(flight_phase='idle', prep_deadline=None, post_planned=True)
                self.set_state(asset, 'available')
        roots = {self.root(job['part'])}
        if job.get('_assembly'):
            roots.add(self.root(job['_assembly']))
        for root in sorted(roots):
            if root in self.quarantined and self.eligible(root) and root not in self.locks:
                self.quarantined.remove(root)
                if self.parts.locations[root] != 'stock':
                    self.supply.return_part(self.parts.records[root]['site'], root)
        self.advance()
        if self.runtime:
            self.runtime.changed()

    def snapshot(self):
        rows = [{k:v for k,v in j.items() if not k.startswith('_')} for j in self.jobs[:10000]]
        counts = Counter(j['status'] for j in self.jobs)
        selected = Counter(j['method'] for j in self.jobs if not j['_off'])
        completed = Counter(j['method'] for j in self.jobs if not j['_off'] and j['status'] == 'completed')
        return dict(jobs=rows, clocks=self.clocks.snapshot() if self.clocks else [],
            jobs_total=len(self.jobs), clocks_total=len(self.clocks.clocks) if self.clocks else 0,
            jobs_truncated=len(self.jobs)>len(rows), clocks_truncated=bool(self.clocks and len(self.clocks.clocks)>10000),
            totals=dict(status=dict(counts), selected=dict(selected), completed=dict(completed)),
            random_streams=dict(failure=0, repair=1, replace=2, method=3, preventive=4),
            **self.retirement.snapshot())
