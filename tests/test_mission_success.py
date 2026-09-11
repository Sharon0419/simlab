import copy
import csv
import json
import pytest
import simpy
from simlab.flight import FlightManager
from simlab.compiler import compile_model, ModelError
from simlab.engine import simulate, run_one
from simlab.project import new_project, save_project, load_project, export_package, import_package
from simlab.flight_results import export_tasks
from test_flight import flight_tables


def scene(fraction=5/6, count=2):
    env=simpy.Environment()
    assets=[dict(id=str(i),sid='S',unit='U',home='H',state='available',mission=None,assignment_event=env.event()) for i in range(count)]
    tasks=[dict(id='T',type='FLIGHT',location='U',sid='S',quantity=2,start=9,end=12,
                flight_prep_hours=.5,out_fraction=1/6,return_fraction=1/6,success_fraction=fraction)]
    events=[]
    manager=FlightManager(env,tasks,assets,lambda *args:events.append((env.now,*args)))
    return env,assets,manager,events


@pytest.mark.parametrize('when,success',[(11,False),(11.5,True),(11.75,True),(12,True)])
@pytest.mark.parametrize('timer_first',[False,True])
def test_fault_boundary_success_is_independent_of_queue_order(when,success,timer_first):
    env,assets,m,events=scene()
    def fault():
        yield env.timeout(when-env.now)
        assets[0]['state']='returning_failed'
        m.rebalance()
    if timer_first:
        env.run(until=9.1)
    env.process(fault())
    env.run(until=12.1);m.rebalance()
    task=m.tasks[0]
    assert task['successful']==success
    assert task['flight_status']==('completed' if when==12 else 'aborted')
    assert task['success_at']==(11.5 if success else None)
    assert task['successful_members']==(['0','1'] if success else [])
    recorded=[e for e in events if e[2]=='达到任务成功点']
    assert len(recorded)==int(success)
    if success:assert recorded[0][0]==11.5


@pytest.mark.parametrize('fraction',[0,5/6,1])
def test_zero_and_one_and_no_fault_nine_missions(fraction):
    t=flight_tables();t['MissionType'][0].update(DURN='3',TFOUT=str(1/6),TFRET=str(1/6),MSUCPT=str(fraction))
    r=simulate(t);f=r['mission']['flight']
    assert f['successful']==f['completed']==9
    assert f['successful_aircraft_sorties']==f['aircraft_sorties']==f['requested_aircraft_sorties']==18
    assert f['success_rate']==f['completion_rate']==1
    for task in r['replication_results'][0]['mission']['tasks']:
        assert task['success_at']==task['start']+3*fraction


def test_cancelled_zero_never_successful():
    env,assets,m,_=scene(0,count=1)
    env.run(until=12.1);m.rebalance();r=m.finish()
    assert r['flight']['requested']==r['flight']['cancelled']==1
    assert r['flight']['started']==r['flight']['successful']==0
    assert m.tasks[0]['success_at'] is None
    assert m.tasks[0]['success_reason']=='cancelled_unready'


def test_aborted_return_crossing_success_point_does_not_succeed():
    env,a,m,_=scene()
    env.run(until=11.4);a[0]['state']='returning_failed';m.rebalance()
    env.run(until=11.6)
    assert m.tasks[0]['landed_at'] is None
    assert not m.tasks[0]['successful']
    assert m.tasks[0]['success_reason']=='aborted_before_success_point'


def test_success_is_live_at_point_before_finish():
    env,a,m,events=scene(.7)
    env.run(until=11.11)
    assert m.tasks[0]['successful']
    assert m.tasks[0]['success_at']==pytest.approx(11.1)
    assert m.tasks[0]['flight_status']=='launched'


@pytest.mark.parametrize('fraction',['-0.01','1.01','nan','inf'])
def test_invalid_success_fraction(fraction):
    t=flight_tables();t['MissionType'][0]['MSUCPT']=fraction
    with pytest.raises(ModelError):compile_model(t)


def test_nonflight_nondefault_success_rejected():
    t=flight_tables();t.pop('SimLabFlightRule');t['MissionType'][0]['MSUCPT']='.5'
    with pytest.raises(ModelError,match='MSUCPT'):compile_model(t)


@pytest.mark.parametrize('rep',range(5))
def test_success_point_never_changes_physical_trajectory(rep):
    tables=flight_tables();tables['MissionType'][0].update(DURN='3',TFOUT=str(1/6),TFRET=str(1/6))
    tables['Control'][0]['ENLOG']='Y'
    for row in tables['Item']:row['FRT']='100000'
    results=[]
    for fraction in (0,.41,5/6,1):
        tables['MissionType'][0]['MSUCPT']=str(fraction)
        one=run_one(compile_model(tables),rep)
        one['events']=[e for e in one['events'] if e['event']!='达到任务成功点']
        for key in ('successful','successful_aircraft_sorties','success_rate','all_successful'):
            one['mission']['flight'].pop(key)
        for task in one['mission']['tasks']:
            for key in ('success_fraction','success_point','successful','success_at','success_phase','success_reason','successful_members'):
                task.pop(key)
        results.append(one)
    assert results[0]==results[1]==results[2]==results[3]


@pytest.mark.parametrize('version',[1,2,3,4,5])
def test_project_upgrade_preserves_historical_result(tmp_path,version):
    p=new_project();p['extensions_version']=version
    p['runs']=[dict(id='legacy',result={'engine':'0.6.0','mission':{'flight':{'completed':9}}})]
    old=copy.deepcopy(p['runs'])
    save_project(p,tmp_path/'saved.sqlite')
    from simlab.extensions import VERSION
    assert load_project(tmp_path/'saved.sqlite')['extensions_version']==VERSION
    assert p['runs']==old
    p['extensions_version']=version
    export_package(p,tmp_path/'export.simproj')
    loaded=import_package(tmp_path/'export.simproj')
    assert loaded['extensions_version']==VERSION and loaded['runs']==old


def test_native_csv_recomputes_success_and_preserves_members(tmp_path):
    t=flight_tables();t['Control'][0]['NREPS']='3'
    t['MissionType'][0]['MSUCPT']='.5'
    r=simulate(t);run=dict(id='csv',model_hash=r['model_hash'],result=r)
    export_tasks(run,tmp_path/'detail.csv',True)
    export_tasks(run,tmp_path/'summary.csv')
    with (tmp_path/'detail.csv').open(encoding='utf-8-sig',newline='') as file:rows=list(csv.DictReader(file))
    assert len(rows)==27 and sum(x['successful']=='True' for x in rows)==27
    assert sum(len(json.loads(x['successful_members'])) for x in rows)==54
    assert {x['replication'] for x in rows}=={'1','2','3'}
    with (tmp_path/'summary.csv').open(encoding='utf-8-sig',newline='') as file:rows=list(csv.DictReader(file))
    assert len(rows)==9 and all(float(x['success_rate'])==1 for x in rows)
    # Missing historical success is blank, never inferred from completed.
    r['mission']['tasks'][0].pop('success_rate')
    export_tasks(run,tmp_path/'legacy.csv')
    with (tmp_path/'legacy.csv').open(encoding='utf-8-sig',newline='') as file:
        assert next(csv.DictReader(file))['success_rate']==''
