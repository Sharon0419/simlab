import pytest
import simpy
from simlab.flight import FlightManager
from simlab.engine import simulate
from simlab.compiler import compile_model, ModelError
from simlab.project import new_project, save_project, load_project


def setup(count=4, starts=(9,12), prep=.5):
    env = simpy.Environment()
    assets = [dict(id=str(i), sid='S', unit='U', home='H', state='available',
                   mission=None, assignment_event=env.event()) for i in range(count)]
    tasks = [dict(id=f'T{i}',type='FLIGHT',location='U',sid='S',quantity=2,
                  start=start,end=start+2,flight_prep_hours=prep) for i,start in enumerate(starts)]
    log=[]
    manager=FlightManager(env,tasks,assets,lambda *args: log.append((env.now,*args)))
    return env,assets,manager,log


def test_all_prepared_at_boundary_and_two_launch_atomically():
    env,assets,m,log=setup()
    env.run(until=8.75)
    assert all(a['flight_phase']=='preparing' and a['mission'] is None for a in assets)
    env.run(until=9.01)
    assert sum(a['mission']=='T0' for a in assets)==2
    assert sum(a['flight_phase']=='ready' for a in assets)==2
    assert all(a['prep_deadline'] is None for a in assets)
    assert m.tasks[0]['launched_at']==9


def test_failed_candidate_uses_prepared_reserve():
    env,assets,m,log=setup()
    env.run(until=8.9)
    assets[0]['state']='waiting_spare'; m.rebalance()
    env.run(until=9.01)
    assert m.tasks[0]['members']==['1','2']
    assert assets[3]['flight_phase']=='ready'


def test_insufficient_prepared_cancels_and_never_starts_late():
    env,assets,m,log=setup(count=2)
    env.run(until=8.9)
    assets[0]['state']='waiting_spare'; m.rebalance()
    env.run(until=9.1)
    assert m.tasks[0]['flight_status']=='cancelled'
    assert all(a['mission'] is None for a in assets)
    assets[0]['state']='available'; m.rebalance()
    env.run(until=10)
    assert assets[0]['flight_phase']=='ready'
    assert all(a['mission'] is None for a in assets)


def test_airborne_failure_aborts_whole_pair_no_replacement_or_resume():
    env,assets,m,log=setup()
    env.run(until=10)
    assets[0]['state']='waiting_spare'; m.rebalance()
    assert m.tasks[0]['flight_status']=='aborted'
    assert all(a['mission'] is None for a in assets)
    env.run(until=10.2)
    assets[0]['state']='available'; m.rebalance()
    assert assets[0]['flight_phase']=='preparing'
    env.run(until=11.5)
    assert m.tasks[0]['supplied_hours']==2
    assert m.tasks[0]['gap_hours']==2
    assert all(a['mission'] is None for a in assets)
    env.run(until=12.01)
    assert m.tasks[1]['members']==['2','3']
    env.run(until=14.6); m.rebalance()
    result=m.finish()
    assert result['flight']['started']==2
    assert result['flight']['completed']==result['flight']['aborted']==1
    assert result['supplied_hours']==6


def test_daily_preparation_resets_ready_pool_and_postflight_prep():
    env,assets,m,log=setup(starts=(9,33))
    env.run(until=11.25)
    assert sum(a['flight_phase']=='preparing' for a in assets)==2
    env.run(until=32.75)
    assert all(a['flight_phase']=='preparing' for a in assets)
    env.run(until=33.01)
    assert m.tasks[1]['members']==['2','3']


def test_overlapping_flights_cannot_double_book_and_zero_prep():
    env,assets,m,log=setup(count=2, starts=(9,10),prep=0)
    env.run(until=10.01)
    assert m.tasks[0]['flight_status']=='launched'
    assert m.tasks[1]['flight_status']=='cancelled'
    assert sum(a['mission']=='T0' for a in assets)==2


def flight_tables():
    from simlab.sample import mission_project
    t=mission_project()['tables']
    sid=t['System'][0]['SID']; location=t['SystemDeployment'][0]['USTID']
    t['SystemDeployment']=[dict(SID=sid,USTID=location,QTYPS='12',UTIL='1')]
    for r in t['Item']: r['FRT']='0'
    t['MissionType']=[dict(MTID='FLIGHT',NOS='2',MNOS='2',DURN='2')]
    t['MissionSystem']=[dict(MTID='FLIGHT',SID=sid)]
    t['Operations']=[dict(USTID=location,PRID='P')]
    t['OperationProfile']=[dict(PRID='P',SPRID='FLIGHT',STIM=str(d*24+h)) for d in range(3) for h in (9,12,15)]
    t['SimLabFlightRule']=[dict(MTID='FLIGHT',PREP_H='.5')]
    t['Control'][0].update(SIMPE='72',NREPS='1')
    return t


def test_engine_no_fault_flight_hours_and_preparation_separate():
    result=simulate(flight_tables())
    f=result['mission']['flight']
    assert f['completed']==f['requested']==9
    assert f['aircraft_sorties']==18
    assert f['preparation_aircraft_hours']==27
    assert result['mission']['supplied_hours']==36
    assert result['mission']['gap_hours']==0
    assert result['availability']==1
    assert result['replication_results'][0]['mission']['tasks'][0]['members']


@pytest.mark.parametrize('change', ['mixed','duty','negative','cross_day','prep_before_day'])
def test_invalid_flight_inputs_rejected(change):
    t=flight_tables()
    if change=='mixed':
        t['MissionType'].append(dict(MTID='OTHER',NOS='2',DURN='1'))
        t['MissionSystem'].append(dict(MTID='OTHER',SID=t['System'][0]['SID']))
        t['OperationProfile'].append(dict(PRID='P',SPRID='OTHER',STIM='5'))
    elif change=='duty': t['SimLabDutyRule']=[dict(MTID='FLIGHT',MIN_QTY='2')]
    elif change=='negative': t['SimLabFlightRule'][0]['PREP_H']='-1'
    elif change=='cross_day': t['OperationProfile'][0]['STIM']='23'
    else: t['SimLabFlightRule'][0]['PREP_H']='10'
    with pytest.raises(ModelError): compile_model(t)


def test_extension_v2_project_remains_readable(tmp_path):
    p=new_project(); p['extensions_version']=2
    save_project(p,tmp_path/'legacy.sqlite')
    from simlab.extensions import VERSION
    assert load_project(tmp_path/'legacy.sqlite')['extensions_version']==VERSION
