"""Explicit calendar maintenance for fixed flights; no component renewal."""
import math
from .operations import _check_common
from .schema import value
from .inspection import compile_inspections, InspectionClocks
from .workflow_activity import configured_plan, aircraft_timing


def compile_planned(tables, fleets, missions, capacity, schedules, horizon, reps):
    rules, errors = [], []
    for row in tables.get('SimLabPlannedMaintenance', []):
        name = row['PMID']
        targets = [f for f in fleets if f['sid'] == row['SID'] and f['unit'] == row['USTID']]
        if not targets or any(not any('flight_prep_hours' in m and m['sid'] == f['sid']
                    and m['location'] in (f['unit'], f['home']) for m in missions) for f in targets):
            errors.append(f'SimLabPlannedMaintenance.{name}: 必须匹配部署位置及固定飞行选机池；暂不支持连续运行或值守。')
        first = float(value('SimLabPlannedMaintenance', row, 'FIRST_H'))
        interval = float(value('SimLabPlannedMaintenance', row, 'INTERVAL_H'))
        duration = float(value('SimLabPlannedMaintenance', row, 'DURATION_H'))
        plan = configured_plan(tables, 'CALENDAR', name)
        if first >= horizon or (not plan and duration <= 0):
            errors.append(f'SimLabPlannedMaintenance.{name}: 首次到期须小于仿真时长，维修时长须大于零。')
            continue
        span_count = (horizon-first)/interval if interval else 1
        if not math.isfinite(span_count) or span_count > 10000:
            errors.append(f'SimLabPlannedMaintenance.{name}: 到期次数超过10000。')
            continue
        count = max(0, math.ceil(span_count))
        tid = value('SimLabPlannedMaintenance', row, 'TASK')
        if plan:
            tid = ''
        needs = {r['RID']: int(float(r['QTY'])) for r in tables.get('TaskResource', [])
                 if r['TID'] == tid and int(float(r['QTY'])) > 0}
        if tid and not needs:
            errors.append(f'SimLabPlannedMaintenance.{name}: 维修资源作业须配置正数量资源需求。')
        for fleet in targets:
            for rid, qty in needs.items():
                if capacity.get((fleet['home'], rid), 0) < qty:
                    errors.append(f'SimLabPlannedMaintenance.{name}: 资源{rid}容量不足。')
            _check_common(fleet['home'], {'resources': needs}, schedules, horizon, errors)
            rules.append(dict(id=name, sid=fleet['sid'], unit=fleet['unit'], task=tid,
                              duration=duration, resources=needs,
                              due_times=[first+i*interval for i in range(count) if first+i*interval < horizon],
                              quantity=fleet['quantity']))
    inspections, inspection_errors, bound = compile_inspections(tables,fleets,missions,capacity,schedules,horizon)
    errors.extend(inspection_errors)
    if (sum(len(r['due_times'])*r['quantity'] for r in rules)+bound)*reps > 200000:
        errors.append('SimLabPlannedMaintenance: 计划维修作业数×重复次数不能超过200000。')
    rules.extend(inspections)
    return rules, errors


class PlannedMaintenance:
    def __init__(self, manager, resources, rules, set_state):
        self.manager, self.env, self.resources = manager, manager.env, resources
        self.set_state = set_state
        self.jobs = []
        self.active = {}
        self.pending = {}
        self.schedule = sorted([(time, r['id'], a['id'], r, a)
            for r in rules for time in r['due_times'] for a in manager.assets
            if a['sid'] == r['sid'] and a['unit'] == r['unit']], key=lambda x: x[:3])
        self.cursor = 0
        self.inspections = InspectionClocks(self,rules)

    def enqueue(self, due, rule, asset):
        job = dict(id=len(self.jobs)+1, rule=rule['id'], asset=asset['id'], station=asset['home'],
                   task=rule['task'], resources=dict(rule['resources']), duration=rule['duration'],
                   due_at=due, requested_at=None, started_at=None, ended_at=None,
                   status='deferred', _asset=asset)
        self.jobs.append(job)
        if rule.get('workflow_plan'):
            job['_workflow_plan'] = rule['workflow_plan']
        self.pending.setdefault(asset['id'], []).append(job)
        self.manager.log(asset['id'], '计划维修到期', rule['id'])
        return job

    def blocked(self, asset):
        return bool(self.pending.get(asset['id']))

    def wake(self, event):
        yield event
        self.manager.rebalance()

    def register_due(self):
        """Register all clocks before M3 arbitrates the shared ground queue."""
        while self.cursor < len(self.schedule) and self.schedule[self.cursor][0] <= self.env.now:
            due, name, aid, rule, asset = self.schedule[self.cursor]
            self.cursor += 1
            self.enqueue(due,rule,asset)
        self.inspections.due()

    def advance(self):
        # Register due work synchronously before any launch, irrespective of event order.
        self.register_due()
        changed = True
        while changed:
            changed = False
            for aid, queue in list(self.pending.items()):
                if not queue:
                    continue
                if getattr(self.manager, 'm3_service', None):
                    queue.sort(key=lambda j: (j['status']=='deferred', j['due_at'], 1 if '_clock' in j else 0, j['rule']))
                job, asset = queue[0], queue[0]['_asset']
                workflow = job.get('_workflow')
                if workflow:
                    self.manager.workflow_runner.advance()
                    starts = [n['started_at'] for n in workflow['nodes'] if n['started_at'] is not None]
                    if starts and job['started_at'] is None:
                        job['started_at'] = min(starts)
                    working = any(n['status'] == 'working' for n in workflow['nodes'])
                    job['status'] = 'working' if working else 'waiting'
                    phase = 'planned_maintenance' if working else 'planned_wait'
                    # M3 state changes wake the exposure clock and dispatcher.
                    # Re-reporting the same phase creates a zero-time wake loop.
                    if asset['state'] != phase:
                        self.set_state(asset, phase)
                    asset['flight_phase'] = phase
                finished = workflow['status'] == 'completed' if workflow else (
                    job['status'] == 'working' and job['started_at']+job['duration'] <= self.env.now)
                if finished:
                    job.update(status='completed', ended_at=self.env.now)
                    self.inspections.complete(job)
                    queue.pop(0)
                    self.active.pop(aid)
                    if workflow:
                        job['duration'] = aircraft_timing(workflow, self.resources, self.env.now)['work_hours']
                    else:
                        self.resources.release(job['station'], job['resources'])
                    self.set_state(asset, 'available')
                    asset.update(flight_phase='idle', prep_deadline=None, post_planned=True)
                    self.manager.log(aid, '计划维修完成', job['rule'])
                    changed = True
                    continue
                if job['status'] == 'deferred':
                    service = getattr(self.manager, 'm3_service', None)
                    if service and not service.planned_can_start(asset, job):
                        continue
                    if asset['mission'] is not None or asset['state'] != 'available' or (asset.get('repair_pending') and not service):
                        continue
                    ground = self.manager.ground
                    if ground and aid in ground.active:
                        continue  # Do not preempt an already queued or working preparation.
                    if asset['prep_deadline'] is not None and asset['prep_deadline'] > self.env.now:
                        continue
                    asset.update(flight_phase='planned_wait', prep_deadline=None)
                    self.set_state(asset, 'planned_wait')
                    job.update(status='waiting', requested_at=self.env.now)
                    self.active[aid] = job
                    if job.get('_workflow_plan'):
                        job['_workflow'] = self.manager.workflow_runner.start(job['_workflow_plan'],
                            dict(activity='INSPECTION' if '_clock' in job else 'CALENDAR',
                                 owner=str(job['id']), rule=job['rule'], station=job['station'], asset=aid),
                            on_change=lambda _: self.manager.queue_dispatch())
                        changed = True
                        continue
                    job['_event'] = self.resources.request(job['station'], job['resources'])
                    self.env.process(self.wake(job['_event']))
                    self.manager.log(aid, '计划维修等待资源', job['rule'])
                    changed = True
                if job['status'] == 'waiting' and '_workflow' not in job and job['_event'].triggered:
                    job.update(status='working', started_at=self.env.now)
                    self.set_state(asset, 'planned_maintenance')
                    asset['flight_phase'] = 'planned_maintenance'
                    self.env.process(self.wake(self.env.timeout(job['duration'])))
                    self.manager.log(aid, '开始计划维修', job['rule'])
                    changed = True

    def snapshot(self):
        jobs = []
        for j in self.jobs:
            end = j['ended_at'] if j['ended_at'] is not None else self.env.now
            requested = j['requested_at'] if j['requested_at'] is not None else end
            started = j['started_at'] if j['started_at'] is not None else end
            extra = {}
            if '_clock' in j:
                hours = j.get('cycle_hours',j['_clock']['hours'])
                extra = dict(cycle_hours=hours,overrun_hours=max(0,hours-j['interval_hours']))
            timing = dict(wait_hours=started-requested, work_hours=end-started)
            if '_workflow' in j:
                timing = aircraft_timing(j['_workflow'], self.resources, self.env.now)
            jobs.append({**{k:v for k,v in j.items() if not k.startswith('_')},**extra,
                         'deferred_hours': requested-j['due_at'],
                         **timing})
        result = dict(jobs=jobs, due_jobs=len(jobs),
                    completed_jobs=sum(j['status']=='completed' for j in jobs),
                    deferred_jobs=sum(j['status']=='deferred' for j in jobs),
                    waiting_jobs=sum(j['status']=='waiting' for j in jobs),
                    working_jobs=sum(j['status']=='working' for j in jobs),
                    deferred_aircraft_hours=sum(j['deferred_hours'] for j in jobs),
                    wait_aircraft_hours=sum(j['wait_hours'] for j in jobs),
                    work_aircraft_hours=sum(j['work_hours'] for j in jobs))
        if self.inspections.clocks:result['clocks']=self.inspections.snapshot()
        return result
