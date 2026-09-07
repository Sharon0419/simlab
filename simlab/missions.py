"""FCFS demand windows; integrate demand and supply at every state transition."""
from collections import Counter

GAP_LABELS = {'fleet_shortage': '部署设备不足', 'busy': '其他任务占用',
              'waiting_spare': '等待备件及运输', 'waiting_resource': '等待维修资源或班次',
              'replacement': '拆装作业'}


class MissionManager:
    def __init__(self, env, tasks, assets, log=None):
        self.env, self.assets = env, assets
        self.log = log or (lambda *args: None)
        self.tasks = [dict(t, supplied_hours=0.0, gap_hours=0.0,
                           demand_hours=(t['end']-t['start'])*t['quantity'],
                           gap_reasons=Counter()) for t in tasks]
        self.last = 0
        self.active = []
        self.supply = {}
        self.reasons = {}
        env.process(self.calendar())

    def eligible(self, task, asset):
        return asset['sid'] == task['sid'] and task['location'] in (asset['unit'], asset['home'])

    def integrate(self):
        elapsed = self.env.now - self.last
        for task in self.active:
            n = self.supply.get(task['id'], 0)
            task['supplied_hours'] += elapsed * n
            task['gap_hours'] += elapsed * (task['quantity'] - n)
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
        for task in self.active:
            assigned = [a for a in self.assets if a['mission'] == task['id']]
            for asset in self.assets:
                if len(assigned) >= task['quantity']:
                    break
                if asset['state'] == 'available' and asset['mission'] is None and self.eligible(task, asset):
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
            # Mutually exclusive accounting for each task. Stable asset order is
            # a descriptive attribution, not a causal counterfactual ranking.
            for asset in eligible:
                if remaining <= 0:
                    break
                if asset['mission'] != task['id']:
                    reason = asset['state'] if asset['state'] != 'available' else 'busy'
                    reasons[reason] += 1
                    remaining -= 1
            assert remaining == 0
            self.reasons[task['id']] = reasons

    def calendar(self):
        for time in sorted({t[k] for t in self.tasks for k in ('start', 'end')}):
            yield self.env.timeout(time - self.env.now)
            self.rebalance()

    def sample(self):
        return {'demand': sum(t['quantity'] for t in self.active), 'supplied': sum(self.supply.values())}

    def finish(self):
        self.integrate()
        demand = sum(t['demand_hours'] for t in self.tasks)
        supplied = sum(t['supplied_hours'] for t in self.tasks)
        reasons = Counter()
        for task in self.tasks:
            reasons.update(task['gap_reasons'])
            assert abs(task['supplied_hours'] + task['gap_hours'] - task['demand_hours']) < 1e-6
        return {'demand_hours': demand, 'supplied_hours': supplied,
                'gap_hours': demand - supplied, 'fulfillment': supplied / demand if demand else None,
                'full_window_rate': sum(t['gap_hours'] < 1e-9 for t in self.tasks) / len(self.tasks) if self.tasks else None,
                'gap_reasons': {key: reasons[key] for key in GAP_LABELS},
                'tasks': [{**t, 'gap_reasons': dict(t['gap_reasons'])} for t in self.tasks]}
