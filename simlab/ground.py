"""Single non-preemptive preparation operation using the shared resource pool."""


class PreparationManager:
    def __init__(self,manager,resources):
        self.manager=manager
        self.env=manager.env
        self.resources=resources
        self.jobs=[]
        self.active={}
        self.assumed_ready=0
        self.last=0.0
        self.wait_resource_hours=0.0
        self.wait_shift_hours=0.0
        self.env.process(self.shift_boundaries())

    def shift_boundaries(self):
        for time in sorted({x for spans in self.resources.schedules.values() for span in spans for x in span}):
            yield self.env.timeout(max(0,time-self.env.now))
            self.manager.rebalance()

    def integrate(self):
        elapsed=self.env.now-self.last
        for job in self.active.values():
            if job['status']!='waiting':continue
            off_shift=any(not any(start<=self.last<end for start,end in self.resources.schedules.get((job['station'],rid),[(0,float('inf'))]))
                          for rid in job['resources'])
            if off_shift:self.wait_shift_hours+=elapsed
            else:self.wait_resource_hours+=elapsed
        self.last=self.env.now

    def request(self,asset,rule,duration):
        assert asset['id'] not in self.active
        event=self.resources.request(asset['home'],rule['resources'])
        job=dict(id=len(self.jobs)+1,asset=asset['id'],station=asset['home'],task=rule['task'],
                 resources=dict(rule['resources']),duration=duration,requested_at=self.env.now,
                 started_at=None,ended_at=None,status='waiting',_asset=asset,_event=event)
        self.jobs.append(job);self.active[asset['id']]=job
        asset['flight_phase']='waiting_preparation'
        self.manager.log(asset['id'],'排队等待再次出动准备',rule['task'])
        self.env.process(self.granted(job))
        self.advance()

    def granted(self,job):
        yield job['_event']
        if job['status']=='waiting':self.manager.rebalance()

    def wake(self,job):
        yield self.env.timeout(max(0,job['started_at']+job['duration']-self.env.now))
        if job['status']=='working':self.manager.rebalance()

    def advance(self):
        # Settle every due completion/grant synchronously before launch decisions.
        # This makes zero-duration and same-time completion independent of queue order.
        changed=True
        while changed:
            changed=False
            for job in list(self.active.values()):
                if job['status']=='working' and job['started_at']+job['duration']<=self.env.now:
                    self.finish(job,'completed');changed=True
                elif job['status']=='waiting' and job['_event'].triggered:
                    job['status']='working';job['started_at']=self.env.now
                    job['_asset']['flight_phase']='preparing'
                    self.manager.log(job['asset'],'开始再次出动准备',job['task'])
                    if job['duration']>0:self.env.process(self.wake(job))
                    changed=True

    def finish(self,job,status):
        previous=job['status']
        job['status']=status;job['ended_at']=self.env.now
        del self.active[job['asset']]
        if previous=='working' or job['_event'].triggered:
            self.resources.release(job['station'],job['resources'])
        else:
            assert self.resources.cancel(job['_event'])
        job['_asset']['flight_phase']='ready'
        self.manager.log(job['asset'],'再次出动准备完成' if status=='completed' else '首波假设接续未完准备',job['task'])

    def assume_ready(self,asset):
        if asset['id'] in self.active:self.finish(self.active[asset['id']],'assumed_ready')
        asset['flight_phase']='ready';asset['prep_deadline']=None
        self.assumed_ready+=1
        self.manager.log(asset['id'],'每日首波假定已保障','不计本模型资源作业')

    def snapshot(self):
        self.integrate()
        jobs=[]
        for job in self.jobs:
            end=job['ended_at'] if job['ended_at'] is not None else self.env.now
            start=job['started_at']
            jobs.append({**{k:v for k,v in job.items() if not k.startswith('_')},
                         'wait_hours':(start if start is not None else end)-job['requested_at'],
                         'work_hours':end-start if start is not None else 0})
        return dict(jobs=jobs,requested_jobs=len(jobs),completed_jobs=sum(j['status']=='completed' for j in jobs),
                    assumed_jobs=sum(j['status']=='assumed_ready' for j in jobs),
                    waiting_jobs=sum(j['status']=='waiting' for j in jobs),working_jobs=sum(j['status']=='working' for j in jobs),
                    wait_aircraft_hours=sum(j['wait_hours'] for j in jobs),work_aircraft_hours=sum(j['work_hours'] for j in jobs),
                    wait_resource_aircraft_hours=self.wait_resource_hours,wait_shift_aircraft_hours=self.wait_shift_hours,
                    daily_assumed_ready_aircraft=self.assumed_ready)
