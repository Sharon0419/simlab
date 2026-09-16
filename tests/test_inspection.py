import copy
import csv
import simpy
import pytest
from simlab.flight import FlightManager
from simlab.engine import ResourcePool,simulate
from simlab.compiler import compile_model,ModelError
from simlab.flight_results import export_planned,export_inspection_clocks
from simlab.project import new_project,save_project,load_project,export_package,import_package
from test_planned import planned_tables


def scene(initial=0,interval=2,starts=(9,15),flight=3,check=1,calendar=None):
    env=simpy.Environment();pool=ResourcePool(env,{('H','C'):2})
    assets=[dict(id=str(i),sid='S',unit='U',home='H',state='available',mission=None,assignment_event=env.event()) for i in range(2)]
    tasks=[dict(id=f'T{i}',type='F',location='U',sid='S',quantity=2,start=t,end=t+flight,
                out_fraction=1/6,return_fraction=1/6,flight_prep_hours=.5,
                ground_rule=dict(task='PREP',resources={'C':1},daily_ready=True)) for i,t in enumerate(starts)]
    rules=[dict(id='HOURS',sid='S',unit='U',duration=check,task='CHECK',resources={'C':1},due_times=[],
                flight_interval=interval,initial={1:initial})]
    if calendar is not None:rules.insert(0,dict(id='CAL',sid='S',unit='U',duration=1,task='CAL',resources={'C':1},due_times=[calendar]))
    m=FlightManager(env,tasks,assets,resource_pool=pool,planned_rules=rules)
    return env,assets,m,pool


def test_midflight_due_overrun_and_reset():
    env,a,m,p=scene()
    env.run(until=11.01)
    assert len(m.planned.jobs)==2 and all(j['due_at']==11 for j in m.planned.jobs)
    assert m.tasks[0]['flight_status']=='launched'
    env.run(until=13.1)
    jobs=m.planned.snapshot()['jobs']
    assert all((j['started_at'],j['ended_at'],j['cycle_hours'],j['overrun_hours'])==(12,13,3,1) for j in jobs)
    assert all(c['hours']==0 for c in m.planned.inspections.clocks)
    env.run(until=18.1)
    assert [j['due_at'] for j in m.planned.jobs]==[11,11,17,17]


def test_simultaneous_calendar_inspection_then_one_preparation():
    env,a,m,p=scene(check=2,calendar=11,starts=(9,))
    env.run(until=16);m.rebalance()
    for asset in a:
        jobs=[j for j in m.planned.jobs if j['asset']==asset['id']]
        assert [(j['rule'],j['started_at'],j['ended_at']) for j in jobs]==[('CAL',12,13),('HOURS',13,15)]
    assert m.ground.snapshot()['completed_jobs']==2
    assert all(j['started_at']==15 and j['ended_at']==15.5 for j in m.ground.jobs)
    assert p.free==p.capacity


def test_individual_initial_and_initial_due():
    env,a,m,p=scene(initial=2,interval=2)
    env.run(until=.01)
    assert len(m.planned.jobs)==1 and m.planned.jobs[0]['asset']=='0' and m.planned.jobs[0]['due_at']==0
    env.run(until=9.1)
    assert m.tasks[0]['flight_status']=='launched'
    assert m.planned.inspections.clocks[0]['completed']==1


def test_different_initial_progress_and_standby_pause():
    env,a,m,p=scene(initial=1,interval=4,starts=(9,15))
    env.run(until=12.01)
    assert [j['asset'] for j in m.planned.jobs]==['0']
    assert m.planned.jobs[0]['due_at']==12
    env.run(until=14)
    assert m.planned.inspections.clocks[1]['hours']==3
    env.run(until=16.01)
    assert [j['due_at'] for j in m.planned.jobs]==[12,16]


def test_abort_return_counts_and_fault_not_healed():
    env,a,m,p=scene(interval=1.25,starts=(9,))
    env.run(until=10)
    a[0]['state']='returning_failed';m.rebalance()
    env.run(until=10.51)
    assert m.tasks[0]['landed_at']==10.5
    assert all(j['due_at']==10.25 for j in m.planned.jobs)
    assert a[0]['state']=='returning_failed' and m.planned.jobs[0]['started_at'] is None
    assert all(c['hours']==1.5 for c in m.planned.inspections.clocks)
    a[0]['state']='available';m.rebalance()
    assert m.planned.jobs[0]['started_at']==10.51


def test_horizon_due_unfinished_has_one_job_and_clock_conservation():
    env,a,m,p=scene(interval=.5,check=5,starts=(9,))
    env.run(until=12.5);m.rebalance()
    pm=m.planned.snapshot()
    assert pm['due_jobs']==2 and pm['working_jobs']==2
    assert all(c['flown_hours']==3 and c['hours_since_check']==3 for c in pm['clocks'])
    assert all(j['overrun_hours']==2.5 and j['work_hours']==.5 for j in pm['jobs'])


def inspection_tables():
    t=planned_tables();t['SimLabPlannedMaintenance']=[]
    t['SimLabFlightInspection']=[dict(CHECKID='H',SID=t['System'][0]['SID'],
        USTID=t['SystemDeployment'][0]['USTID'],INTERVAL_H='3',DURATION_H='1',TASK='PREP')]
    t['SimLabInspectionInitial']=[dict(CHECKID='H',ASSET_NO='1',INITIAL_H='1')]
    return t


@pytest.mark.parametrize('table,field,value',[('SimLabFlightInspection','INTERVAL_H','0'),
    ('SimLabFlightInspection','DURATION_H','1e-320'),('SimLabFlightInspection','TASK','X'),
    ('SimLabInspectionInitial','ASSET_NO','3'),('SimLabInspectionInitial','INITIAL_H','-1'),
    ('SimLabInspectionInitial','CHECKID','X')])
def test_invalid(table,field,value):
    t=inspection_tables();t[table][0][field]=value
    with pytest.raises(ModelError):compile_model(t)


def test_csv_serialization_conservation_and_format7(tmp_path):
    t=inspection_tables();t['Control'][0]['NREPS']='3'
    r=simulate(t);run=dict(id='hours',model_hash=r['model_hash'],result=r,snapshot=t)
    for rep in r['replication_results']:
        pm=rep['mission']['planned']
        for c in pm['clocks']:
            completed=[j for j in pm['jobs'] if j['asset']==c['asset'] and j['status']=='completed']
            assert c['initial_hours']+c['flown_hours']==pytest.approx(c['hours_since_check']+sum(j['cycle_hours'] for j in completed))
    export_planned(run,tmp_path/'jobs.csv');export_inspection_clocks(run,tmp_path/'clocks.csv')
    with (tmp_path/'clocks.csv').open(encoding='utf-8-sig',newline='') as f:assert len(list(csv.DictReader(f)))==6
    p=new_project();p['tables']=t;p['runs']=[run]
    save_project(p,tmp_path/'p.sqlite');export_package(p,tmp_path/'p.simproj')
    assert import_package(tmp_path/'p.simproj')['runs']==[run]
    p['extensions_version']=7;p['tables']=planned_tables();save_project(p,tmp_path/'old.sqlite')
    from simlab.extensions import VERSION
    assert load_project(tmp_path/'old.sqlite')['extensions_version']==VERSION


def test_empty_extension_preserves_calendar_results():
    t=planned_tables();before=simulate(t)
    t['SimLabFlightInspection']=[];t['SimLabInspectionInitial']=[]
    after=simulate(t)
    for k in ('mission','events','replication_results','availability','resources','downtime'):
        assert before[k]==after[k]


def test_independent_inspection_clocks_do_not_reset_each_other():
    env,a,m,p=scene(starts=(9,))
    first=m.planned.inspections.clocks[0]
    second=dict(first,rule=dict(first['rule'],id='SECOND',flight_interval=5))
    m.planned.inspections.clocks.append(second)
    env.run(until=14)
    assert first['completed']==1 and first['hours']==0
    assert second['completed']==0 and second['hours']==3


def test_nonbinding_clock_does_not_change_random_physics():
    t=inspection_tables();t['SimLabFlightInspection'][0]['INTERVAL_H']='10000'
    for row in t['Item']:row['FRT']='2500'
    base=copy.deepcopy(t);base['SimLabFlightInspection']=[];base['SimLabInspectionInitial']=[]
    before=simulate(base);after=simulate(t)
    for key in ('availability','resources','events','samples','failures'):
        assert before[key]==after[key]
    for task in before['mission']['tasks']:
        task['cancel_rates']['planned_maintenance']=0.0
    assert before['mission']['tasks']==after['mission']['tasks']


def test_version7_reader_configuration_rejects_new_format(monkeypatch):
    import simlab.project as project
    p=project.new_project();p['tables']=inspection_tables()
    monkeypatch.setattr(project,'EXTENSIONS_VERSION',7)
    with pytest.raises(ValueError,match='扩展格式版本'):
        project.check_structure(p)
