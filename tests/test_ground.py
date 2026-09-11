import copy
import pytest
import simpy
from simlab.flight import FlightManager
from simlab.engine import ResourcePool,simulate
from simlab.compiler import compile_model,ModelError
from test_flight import flight_tables
from simlab.flight_results import export_ground
import csv


def scene(groups=1,starts=(9,12),duration=2.5,prep=.5,count=2,daily_ready=True,shifts=None,extra_resources=None):
    env=simpy.Environment()
    capacities={('H','CREW'):groups,**(extra_resources or {})}
    pool=ResourcePool(env,capacities,shifts)
    assets=[dict(id=str(i),sid='S',unit='U',home='H',state='available',mission=None,assignment_event=env.event()) for i in range(count)]
    tasks=[dict(id=f'T{i}',type='F',location='U',sid='S',quantity=2,start=t,end=t+duration,flight_prep_hours=prep,
                ground_rule=dict(task='PREP',resources={'CREW':1},daily_ready=daily_ready)) for i,t in enumerate(starts)]
    manager=FlightManager(env,tasks,assets,resource_pool=pool)
    return env,assets,manager,pool


@pytest.mark.parametrize('groups,cancelled',[(1,1),(2,0)])
def test_capacity_and_same_time_completion_before_takeoff(groups,cancelled):
    env,a,m,pool=scene(groups)
    env.run(until=12.01)
    assert m.tasks[1]['flight_status']==('cancelled' if cancelled else 'launched')
    if cancelled:
        assert m.tasks[1]['cancel_reason']=='preparing'
        assert m.tasks[1]['launch_readiness']=={'ready':1,'preparing':1}
    env.run(until=16);m.rebalance();g=m.finish()['ground']
    assert g['requested_jobs']==g['completed_jobs']
    assert g['work_aircraft_hours']==g['completed_jobs']*.5
    assert g['wait_aircraft_hours']==g['wait_resource_aircraft_hours']+g['wait_shift_aircraft_hours']
    assert pool.free==pool.capacity


def test_daily_assumption_releases_running_and_queued_resources_without_healing():
    env,a,m,pool=scene(starts=(9,33),prep=30,count=3)
    env.run(until=32.9)
    assert len(m.ground.active)==2 and pool.free[('H','CREW')]==0
    a[2]['state']='waiting_spare'
    env.run(until=33.01)
    assert m.tasks[1]['flight_status']=='launched'
    assert a[2]['state']=='waiting_spare' and a[2]['flight_phase']=='maintenance'
    g=m.ground.snapshot()
    assert g['assumed_jobs']==2 and g['completed_jobs']==0
    assert g['daily_assumed_ready_aircraft']==5
    assert pool.free==pool.capacity and pool.queue==[]


def test_shift_wait_and_cross_shift_continuation():
    env,a,m,pool=scene(starts=(9,),shifts={('H','CREW'):[(12,12.1),(14,15)]})
    env.run(until=12.6)
    assert a[0]['flight_phase']=='ready' # started12, completed12.5 despite end12.1
    assert a[1]['flight_phase']=='waiting_preparation'
    env.run(until=15.1);m.rebalance();g=m.finish()['ground']
    assert g['completed_jobs']==2
    assert g['wait_aircraft_hours']==pytest.approx(3)
    assert g['wait_shift_aircraft_hours']==pytest.approx(2.9)
    assert g['wait_resource_aircraft_hours']==pytest.approx(.1)
    assert pool.free==pool.capacity


def test_horizon_pending_time_accounting():
    env,a,m,pool=scene(starts=(9,))
    env.run(until=11.75);m.rebalance();g=m.ground.snapshot()
    assert g['waiting_jobs']==g['working_jobs']==1
    assert g['wait_aircraft_hours']==g['work_aircraft_hours']==.25
    assert g['completed_jobs']==0


def test_zero_duration_and_no_daily_assumption():
    env,a,m,pool=scene(starts=(9,),prep=0,daily_ready=False)
    env.run(until=9.01)
    assert m.tasks[0]['flight_status']=='launched'
    assert pool.free==pool.capacity


def ground_tables():
    t=flight_tables()
    home=t['Unit'][0]['STID']
    point=t['Control'][0]['APID']
    t.setdefault('Resource',[]).append(dict(RID='CREW'))
    t.setdefault('Tasks',[]).append(dict(TID='PREP'))
    t.setdefault('TaskResource',[]).append(dict(TID='PREP',RID='CREW',QTY='1'))
    t.setdefault('ResourceAllocation',[]).append(dict(POINT=point,RID='CREW',STID=home,RQTY='2'))
    t['SimLabFlightRule'][0].update(PREP_TASK='PREP',DAILY_READY='Y')
    return t


@pytest.mark.parametrize('invalid',['capacity','missing_task','ready_value','conflicting_rule'])
def test_invalid_input(invalid):
    t=ground_tables()
    if invalid=='capacity':t['ResourceAllocation'][-1]['RQTY']='0'
    if invalid=='missing_task':t['SimLabFlightRule'][0]['PREP_TASK']='UNKNOWN'
    if invalid=='ready_value':t['SimLabFlightRule'][0]['DAILY_READY']='X'
    if invalid=='conflicting_rule':
        t['MissionType'].append(dict(MTID='OTHER',NOS='2',DURN='2'))
        t['MissionSystem'].append(dict(MTID='OTHER',SID=t['System'][0]['SID']))
        t['OperationProfile'].append(dict(PRID='P',SPRID='OTHER',STIM='18'))
        t['SimLabFlightRule'].append(dict(MTID='OTHER',PREP_H='.5'))
    with pytest.raises(ModelError):compile_model(t)


def test_resource_combination_and_maintenance_share_pool():
    env,a,m,pool=scene(starts=(9,),extra_resources={('H','TOOL'):1})
    m.pools[('U','S')]['ground_rule']['resources']['TOOL']=1
    held=pool.request('H',{'TOOL':1})
    env.run(until=11.6)
    assert pool.free[('H','CREW')]==1 # no partial reservation of crew
    assert all(x['flight_phase']=='waiting_preparation' for x in a)
    pool.release('H',{'TOOL':1})
    env.run(until=12.7);m.rebalance()
    assert m.ground.snapshot()['completed_jobs']==2
    assert pool.free==pool.capacity


def test_engine_aggregation_and_csv(tmp_path):
    t=ground_tables();t['Control'][0]['NREPS']='3'
    result=simulate(t);g=result['mission']['ground']
    assert g['completed_jobs']==18 and g['daily_assumed_ready_aircraft']==36
    assert g['work_aircraft_hours']==9
    assert result['mission']['flight']['completed']==9
    run=dict(id='test',model_hash=result['model_hash'],result=result)
    export_ground(run,tmp_path/'ground.csv')
    with (tmp_path/'ground.csv').open(encoding='utf-8-sig',newline='') as file:rows=list(csv.DictReader(file))
    assert len(rows)==54
    assert sum(float(r['work_hours']) for r in rows)==27
