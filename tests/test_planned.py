import copy
import csv
import pytest
import simpy
from simlab.flight import FlightManager
from simlab.engine import ResourcePool, simulate
from simlab.compiler import compile_model, ModelError
from simlab.flight_results import export_planned
from simlab.project import new_project, save_project, load_project, export_package, import_package
from simlab.extensions import VERSION
from test_ground import ground_tables


def scene(due=(9,), duration=1, groups=2, starts=(9,12), prep=.5, ground=True):
    env = simpy.Environment()
    pool = ResourcePool(env, {('H','CREW'):groups})
    assets = [dict(id=str(i),sid='S',unit='U',home='H',state='available',mission=None,
                   assignment_event=env.event()) for i in range(2)]
    tasks = [dict(id=f'T{i}',type='F',location='U',sid='S',quantity=2,start=t,end=t+2,
                  flight_prep_hours=prep) for i,t in enumerate(starts)]
    if ground:
        for t in tasks:t['ground_rule']=dict(task='PREP',resources={'CREW':1},daily_ready=True)
    rules = [dict(id='PM',sid='S',unit='U',task='CHECK',resources={'CREW':1},duration=duration,due_times=due)]
    manager = FlightManager(env,tasks,assets,resource_pool=pool,planned_rules=rules)
    return env, assets, manager, pool


def test_due_at_launch_blocks_daily_assumption_and_prepares_after_repair():
    env,a,m,p = scene()
    env.run(until=9.01)
    assert m.tasks[0]['flight_status']=='cancelled'
    assert m.tasks[0]['cancel_reason']=='planned_maintenance'
    assert all(x['state']=='planned_maintenance' for x in a)
    assert m.ground.assumed_ready==0
    env.run(until=10.1)
    assert all(x['flight_phase']=='preparing' for x in a)
    env.run(until=12.01)
    assert m.tasks[1]['flight_status']=='launched'
    jobs=m.planned.snapshot()['jobs']
    assert [(j['started_at'],j['ended_at']) for j in jobs]==[(9,10),(9,10)]


def test_airborne_due_defers_without_aborting_then_holds_resource():
    env,a,m,p=scene(due=(10,),groups=1)
    env.run(until=10.1)
    assert m.tasks[0]['flight_status']=='launched'
    assert all(j['status']=='deferred' for j in m.planned.jobs)
    env.run(until=11.1)
    assert m.tasks[0]['flight_status']=='completed'
    assert [j['requested_at'] for j in m.planned.jobs]==[11,11]
    assert [j['status'] for j in m.planned.jobs]==['working','waiting']
    env.run(until=14);m.rebalance()
    jobs=m.planned.snapshot()['jobs']
    assert [j['started_at'] for j in jobs]==[11,12]
    assert sum(j['work_hours'] for j in jobs)==2
    assert sum(j['wait_hours'] for j in jobs)==1
    assert p.free==p.capacity


@pytest.mark.parametrize('ground',[True,False])
def test_existing_preparation_finishes_before_due_job(ground):
    env,a,m,p=scene(due=(11.25,),ground=ground)
    env.run(until=11.3)
    assert all(j['status']=='deferred' for j in m.planned.jobs)
    env.run(until=11.6)
    assert [j['started_at'] for j in m.planned.jobs]==[11.5,11.5]


def test_repeated_due_jobs_are_serial_and_horizon_accounting():
    env,a,m,p=scene(due=(9,9.5,10),duration=2)
    env.run(until=10.5);m.rebalance()
    pm=m.planned.snapshot()
    assert pm['due_jobs']==6 and pm['working_jobs']==2 and pm['deferred_jobs']==4
    assert pm['work_aircraft_hours']==3 and pm['completed_jobs']==0
    env.run(until=16);m.rebalance()
    assert m.planned.snapshot()['completed_jobs']==6
    for aid in ('0','1'):
        assert [j['started_at'] for j in m.planned.jobs if j['asset']==aid]==[9,11,13]
    assert p.free==p.capacity


def test_fault_is_not_healed_and_repair_recovery_wakes_planned():
    env,a,m,p=scene(due=(9,))
    a[0]['state']='waiting_spare'
    env.run(until=9.1)
    assert a[0]['state']=='waiting_spare' and m.planned.jobs[0]['status']=='deferred'
    env.run(until=10.5)
    a[0]['state']='available';m.rebalance()
    assert m.planned.jobs[0]['started_at']==10.5
    assert a[0]['state']=='planned_maintenance'


def test_completion_at_launch_requires_real_preparation():
    env,a,m,p=scene(due=(8,),duration=1,prep=.5)
    env.run(until=9.01)
    assert m.tasks[0]['flight_status']=='cancelled'
    assert m.ground.assumed_ready==0
    assert all(x['flight_phase']=='preparing' for x in a)


def test_zero_prep_allows_exact_completion_launch():
    env,a,m,p=scene(due=(8,),duration=1,prep=0)
    env.run(until=9.01)
    assert m.tasks[0]['flight_status']=='launched'


def test_planned_shift_wait_cross_shift_and_pending_resource_accounting():
    env,a,m,p=scene(due=(9,),groups=1)
    p.schedules={('H','CREW'):[(10,10.1),(12,13)]}
    env.process(p.openings())
    env.run(until=10.5);m.rebalance()
    pm=m.planned.snapshot()
    assert pm['waiting_jobs']==pm['working_jobs']==1
    assert pm['wait_aircraft_hours']==2.5 and pm['work_aircraft_hours']==.5
    env.run(until=13.1);m.rebalance()
    assert [j['started_at'] for j in m.planned.jobs]==[10,12]
    assert [j['ended_at'] for j in m.planned.jobs]==[11,13]


@pytest.mark.parametrize('due',[11,11.5])
def test_due_on_landing_or_preparation_completion(due):
    env,a,m,p=scene(due=(due,))
    env.run(until=due+.01)
    assert all(j['started_at']==due for j in m.planned.jobs)
    assert m.tasks[0]['flight_status']=='completed'


def planned_tables():
    t=ground_tables()
    t['SystemDeployment'][0]['QTYPS']='2'
    t['SimLabPlannedMaintenance']=[dict(PMID='CHECK',SID=t['System'][0]['SID'],
        USTID=t['SystemDeployment'][0]['USTID'],FIRST_H='9',INTERVAL_H='24',DURATION_H='1',TASK='PREP')]
    return t


@pytest.mark.parametrize('field,value',[('FIRST_H','72'),('DURATION_H','0'),('INTERVAL_H','-1'),
    ('FIRST_H','nan'),('TASK','MISSING'),('USTID','MISSING'),('INTERVAL_H','.000001'),('INTERVAL_H','1e-320')])
def test_invalid_planned_inputs(field,value):
    t=planned_tables();t['SimLabPlannedMaintenance'][0][field]=value
    with pytest.raises(ModelError):compile_model(t)


def test_planned_rejects_nonflight_and_insufficient_capacity():
    t=planned_tables();t['SimLabFlightRule']=[]
    with pytest.raises(ModelError):compile_model(t)


def test_blank_optional_fields_use_dictionary_defaults():
    t=planned_tables()
    t['SimLabPlannedMaintenance'][0].update(INTERVAL_H=' ',TASK=' ')
    rule=compile_model(t)['planned'][0]
    assert rule['due_times']==[9] and rule['resources']=={}
    t=planned_tables();t['ResourceAllocation'][-1]['RQTY']='0'
    with pytest.raises(ModelError):compile_model(t)


def test_engine_metrics_csv_and_legacy_project_roundtrip(tmp_path):
    t=planned_tables();t['Control'][0]['NREPS']='3'
    result=simulate(t)
    pm=result['mission']['planned']
    assert pm['due_jobs']==pm['completed_jobs']==6
    assert pm['work_aircraft_hours']==6
    assert result['availability']==pytest.approx(1-6/(2*72))
    assert result['downtime']['planned_maintenance']==3
    assert result['mission']['flight']['cancelled']==3
    run=dict(id='pm',model_hash=result['model_hash'],result=result)
    export_planned(run,tmp_path/'pm.csv')
    with (tmp_path/'pm.csv').open(encoding='utf-8-sig',newline='') as f:rows=list(csv.DictReader(f))
    assert len(rows)==18 and sum(float(r['work_hours']) for r in rows)==18
    p=new_project();p['tables']=t;p['runs']=[run]
    save_project(p,tmp_path/'pm.sqlite')
    assert load_project(tmp_path/'pm.sqlite')['runs']==p['runs']
    export_package(p,tmp_path/'pm.simproj')
    assert import_package(tmp_path/'pm.simproj')['runs']==p['runs']
    legacy=new_project();legacy['extensions_version']=6;legacy['tables']=ground_tables();legacy['runs']=[run]
    save_project(legacy,tmp_path/'legacy.sqlite')
    loaded=load_project(tmp_path/'legacy.sqlite')
    assert loaded['extensions_version']==VERSION and loaded['runs']==[run]


def test_empty_table_does_not_change_existing_trajectories():
    t=ground_tables()
    for row in t['Item']:row['FRT']='2500'
    baseline=simulate(t)
    t['SimLabPlannedMaintenance']=[]
    after=simulate(t)
    for key in ('events','replication_results','samples','availability','mission','resources','downtime'):
        assert baseline[key]==after[key]
