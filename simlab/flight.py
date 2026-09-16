"""Prepared reserve pool and atomic fixed flights; no airborne replacement.

Phase fractions describe outbound travel, time on station, and return travel.
Preparation has no failure exposure; optional ground rules constrain resources. Availability is
separate from readiness, and effective mission supply excludes aborted return.
"""
from collections import Counter
from .missions import MissionManager
from .ground import PreparationManager
from .planned import PlannedMaintenance


class FlightManager(MissionManager):
    def __init__(self, env, tasks, assets, log=None, resource_pool=None, planned_rules=(), set_state=None):
        self.daily = {}
        self.pools = {}
        self.preparation_hours = 0.0
        self.ready_hours = 0.0
        for t in tasks:
            pool = (t['location'], t['sid'])
            day = int(t['start']//24)
            key = (pool, day)
            daily_ready=t.get('ground_rule',{}).get('daily_ready',False)
            self.daily[key] = min(self.daily.get(key, float('inf')), t['start'] if daily_ready else t['start']-t['flight_prep_hours'])
            self.pools[pool] = dict(prep=t['flight_prep_hours'], day=None,ground_rule=t.get('ground_rule'))
        for a in assets:
            a.update(flight_phase='idle', prep_deadline=None, sorties=0)
        super().__init__(env, tasks, assets, log)
        self.ground=PreparationManager(self,resource_pool) if any('ground_rule' in t for t in tasks) else None
        self.planned = PlannedMaintenance(self, resource_pool, planned_rules,
            set_state or (lambda a, s: a.update(state=s))) if planned_rules else None
        for t in self.tasks:
            duration=t['end']-t['start']
            t.update(flight_status='scheduled', members=[], launched_at=None, ended_at=None,
                     success_fraction=t.get('success_fraction',1),
                     success_point=t['start']+duration*t.get('success_fraction',1),
                     successful=False, success_at=None, success_phase=None,
                     success_reason='not_started', successful_members=[],
                     cancel_reason=None,launch_readiness=None,
                     landed_at=None, landing_due=t['end'], abort_phase=None, phase=None,
                     out_end=t['start']+duration*t.get('out_fraction',0),
                     return_start=t['end']-duration*t.get('return_fraction',0),
                     out_aircraft_hours=0.0, on_station_aircraft_hours=0.0,
                     return_aircraft_hours=0.0, abort_return_aircraft_hours=0.0)

    def record_success(self, task):
        """Observe only: never integrate, rebalance, draw RNG or signal an asset.

        Equality belongs to success, independently of same-time SimPy ordering.
        An earlier abort blocks success even if the aircraft is still returning.
        """
        point = task['success_point']
        if task['successful'] or task['launched_at'] is None or self.env.now < point:
            return
        if task['flight_status']=='aborted' and task['ended_at'] < point:
            return
        phase = ('LANDED' if point == task['end'] else
                 'OUT' if point < task['out_end'] else
                 'ON_STATION' if point < task['return_start'] else 'BACK')
        task.update(successful=True, success_at=point, success_phase=phase,
                    success_reason='success_point_reached', successful_members=list(task['members']))
        self.log(task['id'], '达到任务成功点', f'{point:g};{phase};'+','.join(task['members']))

    def observe_success(self, task):
        yield self.env.timeout(task['success_point']-self.env.now)
        self.record_success(task)

    def normal_phase(self, task):
        if self.env.now < task['out_end']:
            return 'OUT'
        if self.env.now < task['return_start']:
            return 'ON_STATION'
        return 'BACK'

    def return_duration(self, task):
        back=task['end']-task['return_start']
        phase=self.normal_phase(task)
        if phase=='OUT':
            return back*(self.env.now-task['start'])/(task['out_end']-task['start'])
        if phase=='ON_STATION':
            return back
        return max(0,task['end']-self.env.now)

    def returning(self, task):
        yield self.env.timeout(max(0,task['landing_due']-self.env.now))
        self.rebalance()

    def integrate(self):
        if getattr(self, 'm3_service', None):self.m3_service.runtime.integrate()
        if self.planned:self.planned.inspections.integrate()
        if self.ground:self.ground.integrate()
        elapsed = self.env.now-self.last
        self.preparation_hours += elapsed*sum(a['flight_phase']=='preparing' for a in self.assets)
        self.ready_hours += elapsed*sum(a['flight_phase']=='ready' for a in self.assets)
        fields={'OUT':'out_aircraft_hours','ON_STATION':'on_station_aircraft_hours','BACK':'return_aircraft_hours'}
        for t in self.tasks:
            if t.get('phase') in fields and t['landed_at'] is None:
                hours=elapsed*len(t['members'])
                t[fields[t['phase']]] += hours
                if t['flight_status']=='aborted':
                    t['abort_return_aircraft_hours'] += hours
        super().integrate()

    def pool_for(self, asset):
        return next((p for p in self.pools if p[1]==asset['sid'] and p[0] in (asset['unit'],asset['home'])), None)

    def prepare(self, asset, pool):
        if self.pools[pool]['ground_rule'] is not None:
            self.ground.request(asset,self.pools[pool]['ground_rule'],self.pools[pool]['prep'])
            return
        asset['flight_phase'] = 'preparing'
        deadline = self.env.now+self.pools[pool]['prep']
        asset['prep_deadline'] = deadline
        self.log(asset['id'], '开始出动保障', '')
        if deadline == self.env.now:
            asset['flight_phase'] = 'ready'
            asset['prep_deadline'] = None
            self.log(asset['id'], '保障完成待命', '')
        else:
            self.env.process(self.prepared(asset, deadline))

    def prepared(self, asset, deadline):
        yield self.env.timeout(deadline-self.env.now)
        if asset['prep_deadline'] == deadline:
            self.rebalance()

    def rebalance(self):
        self.integrate()
        if self.ground:self.ground.advance()
        before = {a['id']: a['mission'] for a in self.assets}
        # Complete flights before considering failures at their exact end boundary.
        for t in self.tasks:
            if t['flight_status'] not in ('launched','aborted') or t['landed_at'] is not None:
                continue
            members = [a for a in self.assets if a['mission']==t['id']]
            self.record_success(t)
            ended = self.env.now >= t['landing_due']
            failed = any(a['state']!='available' for a in members)
            if t['flight_status']=='launched' and not ended and failed:
                t['abort_phase']=self.normal_phase(t)
                t['landing_due']=self.env.now+self.return_duration(t)
                t['flight_status']='aborted'
                t['ended_at'] = self.env.now
                if not t['successful']:
                    t['success_reason']='aborted_before_success_point'
                self.log(t['id'], '编队故障中止', f'{t["abort_phase"]};落地={t["landing_due"]:g}')
                self.env.process(self.returning(t))
                ended=self.env.now>=t['landing_due']
            if ended:
                if t['flight_status']=='launched':
                    t['flight_status']='completed'
                    t['ended_at']=self.env.now
                t['landed_at']=self.env.now
                t['phase']='LANDED'
                self.log(t['id'], '编队任务完成' if t['flight_status']=='completed' else '中止编队落地', ','.join(t['members']))
                for a in members:
                    a['mission'] = None
                    a['flight_phase'] = 'idle'
            else:
                phase='BACK' if t['flight_status']=='aborted' else self.normal_phase(t)
                if phase!=t['phase']:
                    self.log(t['id'], '飞行阶段', phase)
                    t['phase']=phase
                for a in members:
                    a['flight_phase']=phase
        if getattr(self, 'm3_service', None):
            if self.planned:self.planned.register_due()
            self.m3_service.runtime.due()
        if self.planned:self.planned.advance()
        if getattr(self, 'm3_service', None):self.m3_service.advance()
        for (pool, day), start in sorted(self.daily.items(), key=lambda x:x[1]):
            if start <= self.env.now and (self.pools[pool]['day'] is None or self.pools[pool]['day'] < day):
                self.pools[pool]['day'] = day
                for a in self.assets:
                    if self.pool_for(a)==pool and a['mission'] is None:
                        if (getattr(self, 'm3_service', None) and (self.m3_service.blocked(a) or a.get('post_planned'))) or (self.planned and (self.planned.blocked(a) or a.get('post_planned'))):
                            continue
                        ground_rule=self.pools[pool]['ground_rule']
                        if ground_rule is not None:
                            if ground_rule['daily_ready'] and a['state']=='available':
                                self.ground.assume_ready(a)
                            elif a['id'] not in self.ground.active and a['state']=='available':
                                a['flight_phase']='idle'
                            continue
                        a['flight_phase'] = 'idle'
                        a['prep_deadline'] = None
        for a in self.assets:
            pool = self.pool_for(a)
            if pool is None or a['mission'] is not None:
                continue
            if (getattr(self, 'm3_service', None) and self.m3_service.blocked(a)) or (self.planned and self.planned.blocked(a)):
                continue
            if a['state'] != 'available':
                a['flight_phase'] = 'maintenance'
                a['prep_deadline'] = None
            elif a['flight_phase']=='preparing' and a['prep_deadline'] is not None and a['prep_deadline'] <= self.env.now:
                a['flight_phase'] = 'ready'
                a['prep_deadline'] = None
                self.log(a['id'], '保障完成待命', '')
            elif a['flight_phase'] in ('idle','maintenance') and (self.pools[pool]['day'] is not None or
                    (self.planned and self.planned.inspections.clocks and a.get('post_planned'))):
                self.prepare(a, pool)
            if a['flight_phase']=='ready':a.pop('post_planned',None)
        self.active = [t for t in self.tasks if t['start'] <= self.env.now < t['end']]
        for t in sorted(self.active, key=lambda x:(x['start'],x['id'])):
            if t['flight_status'] != 'scheduled':
                continue
            candidates = sorted([a for a in self.assets if self.eligible(t,a) and a['state']=='available'
                                 and a['mission'] is None and a['flight_phase']=='ready'
                                 and not (self.planned and self.planned.blocked(a))
                                 and not (getattr(self, 'm3_service', None) and self.m3_service.blocked(a))],
                                key=lambda a:(a['sorties'],a['id']))
            if self.env.now != t['start'] or len(candidates)<t['quantity']:
                t['flight_status'] = 'cancelled'
                t['ended_at'] = self.env.now
                t['success_reason']='cancelled_unready'
                eligible=[a for a in self.assets if self.eligible(t,a)]
                snapshot=Counter('planned_maintenance' if self.planned and self.planned.blocked(a) and a['mission'] is None
                                 else 'maintenance' if a['state']!='available' else 'airborne' if a['mission'] is not None else a['flight_phase'] for a in eligible)
                t['launch_readiness']=dict(snapshot)
                t['cancel_reason']=('fleet_shortage' if len(eligible)<t['quantity'] else
                    'planned_maintenance' if snapshot['planned_maintenance'] else
                    'maintenance' if sum(a['state']=='available' for a in eligible)<t['quantity'] else
                    'airborne' if sum(a['state']=='available' and a['mission'] is None for a in eligible)<t['quantity'] else
                    'preparation_wait' if snapshot['waiting_preparation'] else 'preparing')
                self.log(t['id'], '准备就绪飞机不足取消', '')
                continue
            chosen = candidates[:t['quantity']]
            t['flight_status'] = 'launched'
            t['launched_at'] = self.env.now
            t['members'] = [a['id'] for a in chosen]
            t['success_reason']='awaiting_success_point'
            t['phase']=self.normal_phase(t)
            for a in chosen:
                a['mission'] = t['id']
                a['flight_phase'] = t['phase']
                a['sorties'] += 1
            self.log(t['id'], '编队统一起飞', ','.join(t['members']))
            self.log(t['id'], '飞行阶段', t['phase'])
            if t['success_point']==self.env.now:
                self.record_success(t)
            else:
                self.env.process(self.observe_success(t))
        for a in self.assets:
            if before[a['id']] != a['mission']:
                signal = a['assignment_event']
                a['assignment_event'] = self.env.event()
                if not signal.triggered:
                    signal.succeed()
                self.log(a['id'], '任务分配' if a['mission'] else '退出任务', a['mission'] or '')
        if self.planned:self.planned.inspections.arm()
        if getattr(self, 'm3_service', None):self.m3_service.runtime.changed()
        self.supply, self.reasons = {}, {}
        for t in self.active:
            n = t['quantity'] if t['flight_status']=='launched' else 0
            self.supply[t['id']] = n
            reason = 'flight_aborted' if t['flight_status']=='aborted' else 'flight_unready'
            self.reasons[t['id']] = Counter({reason:t['quantity']-n})

    def calendar(self):
        times = {t[k] for t in self.tasks for k in ('start','out_end','return_start','end')} | set(self.daily.values())
        if self.planned:times.update(x[0] for x in self.planned.schedule)
        if self.planned and self.planned.inspections.clocks:times.add(0)
        for time in sorted(times):
            yield self.env.timeout(time-self.env.now)
            self.rebalance()

    def finish(self):
        result = super().finish()
        counts = Counter(t['flight_status'] for t in self.tasks)
        result['flight'] = dict(requested=len(self.tasks), started=sum(t['launched_at'] is not None for t in self.tasks),
            completed=counts['completed'], aborted=counts['aborted'], cancelled=counts['cancelled'],
            aircraft_sorties=sum(len(t['members']) for t in self.tasks),
            completed_aircraft_sorties=sum(len(t['members']) for t in self.tasks if t['flight_status']=='completed'),
            preparation_aircraft_hours=self.preparation_hours, ready_aircraft_hours=self.ready_hours,
            all_completed=int(counts['completed']==len(self.tasks)))
        for key in ('out_aircraft_hours','on_station_aircraft_hours','return_aircraft_hours','abort_return_aircraft_hours'):
            result['flight'][key]=sum(t[key] for t in self.tasks)
        f=result['flight']
        f.update(successful=sum(t['successful'] for t in self.tasks),
                 requested_aircraft_sorties=sum(t['quantity'] for t in self.tasks),
                 successful_aircraft_sorties=sum(len(t['successful_members']) for t in self.tasks))
        f.update(started_rate=f['started']/f['requested'], success_rate=f['successful']/f['requested'],
                 completion_rate=f['completed']/f['requested'],
                 all_successful=int(f['successful']==f['requested']))
        if self.ground:result['ground']=self.ground.snapshot()
        if self.planned:result['planned']=self.planned.snapshot()
        return result
