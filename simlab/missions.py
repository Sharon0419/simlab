"""FCFS demand windows; integrate demand and supply at every state transition."""
from collections import Counter

GAP_LABELS = {'fleet_shortage': '部署设备不足', 'busy': '其他任务占用',
              'relief': '补位准备与交接',
              'waiting_spare': '等待备件及运输', 'waiting_resource': '等待维修资源或班次',
              'replacement': '拆装作业'}


class MissionManager:
    def __init__(self, env, tasks, assets, log=None):
        self.env, self.assets = env, assets
        self.log = log or (lambda *args: None)
        self.tasks = [dict(t, supplied_hours=0.0, gap_hours=0.0,
                           minimum=t.get('minimum', t['quantity']), priority=t.get('priority', 1),
                           relief_hours=t.get('relief_hours', 0.0), tolerance_hours=t.get('tolerance_hours', 0.0),
                           below_hours=0.0, longest_below_hours=0.0, below_start=None,
                           demand_hours=(t['end']-t['start'])*t['quantity'],
                           gap_reasons=Counter()) for t in tasks]
        self.last = 0
        self.active = []
        self.supply = {}
        self.reasons = {}
        self.pending = {}
        self.intervals = []
        self.last_interval = {}
        self.intervals_truncated = False
        env.process(self.calendar())

    def eligible(self, task, asset):
        return asset['sid'] == task['sid'] and task['location'] in (asset['unit'], asset['home'])

    def integrate(self):
        elapsed = self.env.now - self.last
        for task in self.active:
            n = self.supply.get(task['id'], 0)
            task['supplied_hours'] += elapsed * n
            task['gap_hours'] += elapsed * (task['quantity'] - n)
            if elapsed > 0:
                if n < task['minimum']:
                    task['below_hours'] += elapsed
                    if task['below_start'] is None:
                        task['below_start'] = self.last
                    task['longest_below_hours'] = max(task['longest_below_hours'], self.env.now-task['below_start'])
                    reasons = {k: v for k, v in self.reasons.get(task['id'], {}).items() if v}
                    previous = self.last_interval.get(task['id'])
                    if previous and previous['end'] == self.last and previous['supplied'] == n and previous['reasons'] == reasons:
                        previous['end'] = self.env.now
                    elif len(self.intervals) < 5000:
                        record = {'task': task['id'], 'start': self.last, 'end': self.env.now,
                                  'supplied': n, 'minimum': task['minimum'], 'reasons': reasons}
                        self.intervals.append(record)
                        self.last_interval[task['id']] = record
                    else:
                        self.intervals_truncated = True
                else:
                    task['below_start'] = None
            for reason, count in self.reasons.get(task['id'], {}).items():
                task['gap_reasons'][reason] += elapsed * count
        self.last = self.env.now

    def rebalance(self):
        self.integrate()
        self.active = [t for t in self.tasks if t['start'] <= self.env.now < t['end']]
        active_ids = {t['id'] for t in self.active}
        before = {a['id']: a['mission'] for a in self.assets}
        for asset in self.assets:
            if asset['state'] != 'available' or asset['mission'] not in active_ids:
                asset['mission'] = None
            reservation = self.pending.get(asset['id'])
            if reservation:
                if asset['state'] != 'available' or reservation['task'] not in active_ids:
                    del self.pending[asset['id']]
                    self.log(asset['id'], '取消补位', reservation['task'])
                elif self.env.now >= reservation['ready']:
                    asset['mission'] = reservation['task']
                    del self.pending[asset['id']]
        for task in sorted(self.active, key=lambda t: (t['priority'], t['start'], t['id'])):
            assigned = [a for a in self.assets if a['mission'] == task['id']]
            reserved = sum(r['task'] == task['id'] for r in self.pending.values())
            for asset in self.assets:
                if len(assigned) + reserved >= task['quantity']:
                    break
                if asset['state'] == 'available' and asset['mission'] is None and asset['id'] not in self.pending and self.eligible(task, asset):
                    if self.env.now > task['start'] and task['relief_hours'] > 0:
                        reservation = {'task': task['id'], 'ready': self.env.now + task['relief_hours']}
                        self.pending[asset['id']] = reservation
                        reserved += 1
                        self.log(asset['id'], '准备补位', task['id'])
                        self.env.process(self.relief_ready(asset['id'], reservation, task['end']))
                    else:
                        asset['mission'] = task['id']
                        assigned.append(asset)
        for asset in self.assets:
            if before[asset['id']] != asset['mission']:
                signal = asset['assignment_event']
                asset['assignment_event'] = self.env.event()
                if not signal.triggered:
                    signal.succeed()
                self.log(asset['id'], '任务分配' if asset['mission'] else '退出任务', asset['mission'] or '')
        self.supply, self.reasons = {}, {}
        for task in self.active:
            eligible = [a for a in self.assets if self.eligible(task, a)]
            supplied = sum(a['mission'] == task['id'] for a in eligible)
            self.supply[task['id']] = supplied
            missing = task['quantity'] - supplied
            reasons = Counter()
            reasons['fleet_shortage'] = min(missing, max(0, task['quantity']-len(eligible)))
            remaining = missing - reasons['fleet_shortage']
            relief_count = min(remaining, sum(r['task'] == task['id'] for r in self.pending.values()))
            reasons['relief'] = relief_count
            remaining -= relief_count
            # Mutually exclusive accounting for each task. Stable asset order is
            # a descriptive attribution, not a causal counterfactual ranking.
            for asset in eligible:
                if remaining <= 0:
                    break
                if asset['mission'] != task['id']:
                    reservation = self.pending.get(asset['id'])
                    if reservation and reservation['task'] == task['id']:
                        continue
                    reason = asset['state'] if asset['state'] != 'available' else 'busy'
                    reasons[reason] += 1
                    remaining -= 1
            assert remaining == 0
            self.reasons[task['id']] = reasons

    def relief_ready(self, asset_id, reservation, end):
        yield self.env.timeout(min(reservation['ready'], end) - self.env.now)
        if self.pending.get(asset_id) is reservation:
            self.rebalance()

    def calendar(self):
        for time in sorted({t[k] for t in self.tasks for k in ('start', 'end')}):
            yield self.env.timeout(time - self.env.now)
            self.rebalance()

    def sample(self):
        return {'demand': sum(t['quantity'] for t in self.active), 'minimum': sum(t['minimum'] for t in self.active),
                'supplied': sum(self.supply.values())}

    def finish(self):
        self.integrate()
        demand = sum(t['demand_hours'] for t in self.tasks)
        supplied = sum(t['supplied_hours'] for t in self.tasks)
        reasons = Counter()
        for task in self.tasks:
            reasons.update(task['gap_reasons'])
            assert abs(task['supplied_hours'] + task['gap_hours'] - task['demand_hours']) < 1e-6
            task['minimum_rate'] = 1 - task['below_hours'] / (task['end'] - task['start'])
            task['qualified'] = task['longest_below_hours'] <= task['tolerance_hours'] + 1e-9
        window_hours = sum(t['end']-t['start'] for t in self.tasks)
        return {'demand_hours': demand, 'supplied_hours': supplied,
                'minimum_rate': 1-sum(t['below_hours'] for t in self.tasks)/window_hours if window_hours else None,
                'qualified_rate': sum(t['qualified'] for t in self.tasks)/len(self.tasks) if self.tasks else None,
                'below_hours': sum(t['below_hours'] for t in self.tasks),
                'intervals': self.intervals, 'intervals_truncated': self.intervals_truncated,
                'gap_hours': demand - supplied, 'fulfillment': supplied / demand if demand else None,
                'full_window_rate': sum(t['gap_hours'] < 1e-9 for t in self.tasks) / len(self.tasks) if self.tasks else None,
                'gap_reasons': {key: reasons[key] for key in GAP_LABELS},
                'tasks': [{**{k: v for k, v in t.items() if k != 'below_start'}, 'gap_reasons': dict(t['gap_reasons'])} for t in self.tasks]}
