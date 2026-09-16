"""Per-aircraft inspection clocks, independent of component failure clocks."""
import math
from .schema import value
from .operations import _check_common
from .workflow_activity import configured_plan


def compile_inspections(tables, fleets, missions, capacity, schedules, horizon):
    rules, errors, bound = [], [], 0
    name = 'SimLabFlightInspection'
    for row in tables.get(name, []):
        cid = row['CHECKID']
        targets = [f for f in fleets if f['sid']==row['SID'] and f['unit']==row['USTID']]
        matching = [m for m in missions if m['sid']==row['SID'] and any(m['location'] in (f['unit'],f['home']) for f in targets)]
        if len(targets)!=1 or not matching or any('flight_prep_hours' not in m for m in matching):
            errors.append(f'{name}.{cid}: 必须唯一匹配部署位置及固定飞行选机池。')
            continue
        f = targets[0]
        interval = float(value(name,row,'INTERVAL_H'))
        duration = float(value(name,row,'DURATION_H'))
        plan = configured_plan(tables, 'INSPECTION', cid)
        if interval < 1e-6 or (not plan and duration < 1e-6):
            errors.append(f'{name}.{cid}: 检查间隔及作业时长须至少0.000001小时。')
            continue
        tid = value(name,row,'TASK')
        if plan:
            tid = ''
        needs = {r['RID']:int(float(r['QTY'])) for r in tables.get('TaskResource', [])
                 if r['TID']==tid and int(float(r['QTY']))>0}
        if tid and not needs:errors.append(f'{name}.{cid}: 资源作业须有正数量资源需求。')
        for rid, qty in needs.items():
            if capacity.get((f['home'],rid),0)<qty:errors.append(f'{name}.{cid}: 资源{rid}容量不足。')
        _check_common(f['home'],{'resources':needs},schedules,horizon,errors)
        initial = {}
        for entry in tables.get('SimLabInspectionInitial', []):
            if entry['CHECKID'] != cid:continue
            number = int(float(entry['ASSET_NO']))
            if not 1 <= number <= f['quantity']:
                errors.append(f'SimLabInspectionInitial.{cid}: 飞机序号超出部署数量。')
            initial[number] = float(value('SimLabInspectionInitial',entry,'INITIAL_H'))
        rules.append(dict(id=cid,sid=f['sid'],unit=f['unit'],task=tid,resources=needs,
                          duration=duration,due_times=[],quantity=f['quantity'],
                          flight_interval=interval,initial=initial))
        # At most one new inspection per sortie, plus initially due aircraft.
        bound += sum(m['quantity'] for m in matching)+f['quantity']
    return rules, errors, bound


class InspectionClocks:
    def __init__(self, planned, rules):
        self.planned, self.env = planned, planned.env
        self.last = 0.0
        self.clocks = []
        for r in rules:
            if 'flight_interval' not in r:continue
            assets = [a for a in planned.manager.assets if a['sid']==r['sid'] and a['unit']==r['unit']]
            for number, a in enumerate(assets,1):
                initial = r['initial'].get(number,0.0)
                self.clocks.append(dict(asset=a,rule=r,initial=initial,hours=initial,flown=0.0,
                    completed=0,job=None,alarm_mission=None))

    def integrate(self):
        elapsed = self.env.now-self.last
        for c in self.clocks:
            if c['asset']['mission'] is not None:
                c['hours'] += elapsed
                c['flown'] += elapsed
        self.last = self.env.now

    def due(self):
        for c in self.clocks:
            threshold = c['rule']['flight_interval']
            if c['job'] is None and (c['hours']>=threshold or math.isclose(c['hours'],threshold,rel_tol=1e-12,abs_tol=1e-12)):
                j = self.planned.enqueue(self.env.now,c['rule'],c['asset'])
                j.update(trigger='flight_hours',interval_hours=threshold,_clock=c)
                c['job'] = j

    def arm(self):
        for c in self.clocks:
            mission = c['asset']['mission']
            if mission is None:
                c['alarm_mission'] = None
            elif c['job'] is None and c['alarm_mission'] != mission:
                c['alarm_mission'] = mission
                self.env.process(self.wake(c,mission,max(0,c['rule']['flight_interval']-c['hours'])))

    def wake(self, c, mission, delay):
        yield self.env.timeout(delay)
        if c['asset']['mission']==mission and c['job'] is None:
            self.planned.manager.rebalance()

    def complete(self, job):
        c = job.get('_clock')
        if c is None:return
        job.update(cycle_hours=c['hours'],overrun_hours=max(0,c['hours']-c['rule']['flight_interval']))
        c.update(hours=0.0,job=None,completed=c['completed']+1,alarm_mission=None)

    def snapshot(self):
        return [dict(asset=c['asset']['id'],rule=c['rule']['id'],initial_hours=c['initial'],
                     flown_hours=c['flown'],hours_since_check=c['hours'],interval_hours=c['rule']['flight_interval'],
                     completed_checks=c['completed'],due=c['job'] is not None,
                     overrun_hours=max(0,c['hours']-c['rule']['flight_interval'])) for c in self.clocks]
