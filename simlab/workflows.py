"""Deterministic finish-to-start DAG execution on the shared resource pool."""
import inspect


def off_shift_hours(pool, station, needs, start, end):
    """Measure union of off-shift intervals; overlapping resource shifts count once."""
    boundaries = {start, end}
    schedules = [pool.schedules[(station, rid)] for rid, qty in needs.items()
                 if qty and (station, rid) in pool.schedules]
    for spans in schedules:
        for a, b in spans:
            boundaries.update(t for t in (a, b) if start < t < end)
    points = sorted(boundaries)
    return sum(b-a for a, b in zip(points, points[1:])
               if any(not any(x <= a < y for x, y in spans) for spans in schedules))


class WorkflowExecutor:
    """One runner per replication. advance() settles same-time work before dispatch."""
    def __init__(self, env, pool, plans, rng):
        self.env, self.pool, self.plans, self.rng = env, pool, plans, rng
        self.jobs = []
        self._advancing = False
        self._rows = 0

    def start(self, plan, context, before=None, after=None, on_change=None):
        nodes = self.plans[plan]
        self._rows += len(nodes)
        if self._rows > 200000:
            raise RuntimeError('工序记录超过每轮200000条，仿真停止。')
        job = dict(id=f'W{len(self.jobs)+1:06d}', plan=plan, context=dict(context),
                   created_at=self.env.now, ended_at=None, status='running', event=self.env.event(),
                   before=before, after=after, on_change=on_change, nodes=[])
        for spec in nodes:
            job['nodes'].append(dict(spec=spec, step=spec['id'], name=spec['name'], action=spec['action'],
                status='pending', ready_at=None, requested_at=None, started_at=None, ended_at=None,
                resources=dict(spec['resources']), duration=None, _request=None, attempt=1,
                attempt_created_at=self.env.now, history=[]))
        self.jobs.append(job)
        self.advance()
        return job

    def _wake(self, event):
        yield event
        self.advance()

    def _hook(self, job, node, which, next_status):
        callback = job[which]
        value = callback(node['action'], node) if callback else None
        if inspect.isgenerator(value):
            self.env.process(self._await_hook(job, node, value, next_status))
        elif hasattr(value, 'callbacks'):
            self.env.process(self._await_event(job, node, value, next_status))
        else:
            self._hook_done(node, next_status, value)

    def _hook_done(self, node, status, result=None):
        if result == 'retry':
            self._rows += 1
            if self._rows > 200000:
                raise RuntimeError('工序记录超过每轮200000条，仿真停止。')
            previous = {k:v for k,v in node.items() if k != 'history'}
            previous.update(status='retry', ended_at=self.env.now)
            node['history'].append(previous)
            node.update(status='pending', ready_at=None, requested_at=None, started_at=None,
                        ended_at=None, duration=None, _request=None, attempt=node['attempt']+1,
                        attempt_created_at=self.env.now)
            node.pop('work_ended_at', None)
            return
        node['status'] = status
        if status == 'completed':
            node['ended_at'] = self.env.now

    def _await_hook(self, job, node, generator, status):
        result = yield from generator
        if job['status'] == 'running':
            self._hook_done(node, status, result)
            self.advance()

    def _await_event(self, job, node, event, status):
        result = yield event
        if job['status'] == 'running':
            self._hook_done(node, status, result)
            self.advance()

    def advance(self):
        if self._advancing:
            return
        self._advancing = True
        changed_jobs = {}
        try:
            changed = True
            while changed:
                changed = False
                for job in self.jobs:
                    if job['status'] != 'running':
                        continue
                    completed = {n['step'] for n in job['nodes'] if n['status'] == 'completed'}
                    for node in job['nodes']:
                        previous = node['status']
                        spec = node['spec']
                        if previous == 'pending' and set(spec['predecessors']) <= completed:
                            node.update(status='prerequisite', ready_at=self.env.now)
                            self._hook(job, node, 'before', 'ready')
                        if node['status'] == 'ready':
                            node.update(status='waiting', requested_at=self.env.now)
                            node['_request'] = self.pool.request(job['context']['station'], node['resources'])
                            if not node['_request'].triggered:
                                self.env.process(self._wake(node['_request']))
                        if node['status'] == 'waiting' and node['_request'].triggered:
                            duration = spec['duration']
                            if spec['random'] and duration:
                                duration = float(self.rng.exponential(duration))
                            node.update(status='working', started_at=self.env.now, duration=duration)
                            if duration:
                                self.env.process(self._wake(self.env.timeout(duration)))
                        if node['status'] == 'working' and node['started_at']+node['duration'] <= self.env.now:
                            self.pool.release(job['context']['station'], node['resources'])
                            node.update(status='finalizing', work_ended_at=self.env.now)
                            self._hook(job, node, 'after', 'completed')
                        if previous != node['status']:
                            changed = True
                            changed_jobs[job['id']] = job
                    if all(n['status'] == 'completed' for n in job['nodes']):
                        job.update(status='completed', ended_at=self.env.now)
                        job['event'].succeed(job)
                        changed_jobs[job['id']] = job
                        changed = True
        finally:
            self._advancing = False
        for job in changed_jobs.values():
            if job['on_change']:
                job['on_change'](job)

    def cancel(self, job):
        if job['status'] != 'running':
            return
        job.update(status='cancelled', ended_at=self.env.now)
        for node in job['nodes']:
            status = node['status']
            if status == 'completed':
                continue
            node.update(status='cancelled', ended_at=self.env.now)
            if status == 'working' or (status == 'waiting' and node['_request'].triggered):
                self.pool.release(job['context']['station'], node['resources'])
            elif status == 'waiting':
                self.pool.cancel(node['_request'])
        job['event'].succeed(job)

    def snapshot(self):
        self.advance()
        rows, activities = [], []
        for job in self.jobs:
            end = job['ended_at'] if job['ended_at'] is not None else self.env.now
            activities.append(dict(id=job['id'], plan=job['plan'], **job['context'],
                started_at=job['created_at'], ended_at=job['ended_at'], status=job['status'],
                elapsed_hours=end-job['created_at']))
            for n in [attempt for node in job['nodes'] for attempt in node['history'] + [node]]:
                node_end = n['ended_at'] if n['ended_at'] is not None else end
                ready = n['ready_at'] if n['ready_at'] is not None else node_end
                requested = n['requested_at'] if n['requested_at'] is not None else node_end
                start = n['started_at'] if n['started_at'] is not None else node_end
                shift = off_shift_hours(self.pool, job['context']['station'], n['resources'], requested, start)
                work_end = n.get('work_ended_at', n['ended_at'] if n['ended_at'] is not None else end)
                rows.append(dict(workflow=job['id'], plan=job['plan'], **job['context'],
                    **{k:n[k] for k in ('step','name','action','status','ready_at','requested_at','started_at','ended_at','resources','duration','attempt')},
                    predecessors=list(n['spec']['predecessors']),
                    successors=[s['step'] for s in job['nodes'] if n['step'] in s['spec']['predecessors']],
                    wait_dependency_hours=ready-n['attempt_created_at'],
                    wait_prerequisite_hours=requested-ready,
                    wait_shift_hours=shift, wait_resource_hours=max(0., start-requested-shift),
                    work_hours=max(0., work_end-start) if n['started_at'] is not None else 0.))
        return dict(activities=activities, steps=rows)
