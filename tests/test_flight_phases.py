import pytest
import simpy
from simlab.flight import FlightManager
from simlab.compiler import compile_model, ModelError
from simlab.engine import simulate
from test_flight import flight_tables


def setup(out=1/6, back=1/6, count=4, extra=False):
    env=simpy.Environment()
    assets=[dict(id=str(i),sid='S',unit='U',home='H',state='available',mission=None,assignment_event=env.event()) for i in range(count)]
    tasks=[dict(id='T',type='FLIGHT',location='U',sid='S',quantity=2,start=9,end=12,flight_prep_hours=.5,
                out_fraction=out,return_fraction=back)]
    if extra:tasks.append(dict(tasks[0],id='T2',start=10,end=13))
    m=FlightManager(env,tasks,assets)
    return env,assets,m


def test_normal_phase_boundaries_and_actual_hours():
    env,a,m=setup()
    env.run(until=9.01);assert m.tasks[0]['phase']=='OUT'
    env.run(until=9.51);assert m.tasks[0]['phase']=='ON_STATION'
    env.run(until=11.51);assert m.tasks[0]['phase']=='BACK'
    env.run(until=12.01);assert m.tasks[0]['phase']=='LANDED'
    f=m.finish()['flight']
    assert f['out_aircraft_hours']==1
    assert f['on_station_aircraft_hours']==4
    assert f['return_aircraft_hours']==1
    assert f['abort_return_aircraft_hours']==0


@pytest.mark.parametrize('when,landing,phase',[(9.25,9.5,'OUT'),(9.5,10,'ON_STATION'),(10,10.5,'ON_STATION'),(11.5,12,'BACK'),(11.75,12,'BACK')])
def test_abort_return_duration_and_release_only_at_landing(when,landing,phase):
    env,a,m=setup()
    env.run(until=when)
    a[0]['state']='returning_failed';m.rebalance()
    t=m.tasks[0]
    assert t['abort_phase']==phase
    assert t['landing_due']==landing
    assert a[0]['mission']==a[1]['mission']=='T'
    assert a[2]['mission'] is None
    env.run(until=landing+.01)
    assert t['landed_at']==landing
    assert all(x['mission'] is None for x in a)
    assert a[0]['flight_phase']=='maintenance'
    assert a[1]['flight_phase']=='preparing'
    env.run(until=12.1);m.rebalance()
    r=m.finish()
    assert r['supplied_hours']==pytest.approx(2*(when-9))
    assert r['flight']['abort_return_aircraft_hours']==pytest.approx(2*(landing-when))
    assert sum(r['flight'][k] for k in ('out_aircraft_hours','on_station_aircraft_hours','return_aircraft_hours'))==pytest.approx(2*(landing-9))


def test_second_fault_does_not_reset_return_or_free_aircraft():
    env,a,m=setup(count=2,extra=True)
    env.run(until=9.75);a[0]['state']='returning_failed';m.rebalance()
    assert m.tasks[0]['landing_due']==10.25
    env.run(until=10.01)
    assert m.tasks[1]['flight_status']=='cancelled'
    a[1]['state']='returning_failed';m.rebalance()
    assert m.tasks[0]['landing_due']==10.25
    assert all(x['mission']=='T' for x in a)


def test_fault_at_planned_landing_does_not_abort_completed_flight():
    env,a,m=setup()
    env.run(until=12)
    a[0]['state']='returning_failed';m.rebalance()
    assert m.tasks[0]['flight_status']=='completed'
    assert m.tasks[0]['landed_at']==12
    assert m.tasks[0]['abort_phase'] is None
    assert a[0]['mission'] is None


@pytest.mark.parametrize('out,back,expected',[(0,0,(0,6,0)),(.5,.5,(3,0,3)),(0,1,(0,0,6)),(1,0,(6,0,0))])
def test_zero_length_phases(out,back,expected):
    env,a,m=setup(out,back)
    env.run(until=12.1);m.rebalance();f=m.finish()['flight']
    assert tuple(f[k] for k in ('out_aircraft_hours','on_station_aircraft_hours','return_aircraft_hours'))==expected


@pytest.mark.parametrize('out,back', [('0.6','0.5'),('-0.1','0'),('0','1.01')])
def test_invalid_ratios_rejected(out,back):
    t=flight_tables();t['MissionType'][0].update(TFOUT=out,TFRET=back)
    with pytest.raises(ModelError):compile_model(t)


def test_nonflight_ratios_rejected():
    t=flight_tables();t.pop('SimLabFlightRule');t['MissionType'][0]['TFOUT']='.2'
    with pytest.raises(ModelError):compile_model(t)


def test_all_components_may_fail_on_return_but_repair_waits_for_landing():
    t=flight_tables()
    t['Control'][0].update(SIMPE='6',ENLOG='Y')
    t['ResourceStationData']=[]
    for r in t['StationStructure']:r.update(TFRMS='0',TTOMS='0')
    t['OperationProfile']=[dict(PRID='P',SPRID='FLIGHT',STIM='1')]
    t['MissionType'][0].update(DURN='3',TFOUT='0',TFRET='.5')
    for r in t['Item']:r['FRT']='10000000'
    for r in t['ItemRepair']:r['DIRPT']='.2';r['DIRPD']=''
    for r in t['ItemReplacement']:r['SURPT']='0'
    r=simulate(t)
    task=r['replication_results'][0]['mission']['tasks'][0]
    assert task['flight_status']=='aborted'
    assert r['failures']>2  # more than the initial fault and its healthy wingmate
    assert r['downtime']['returning_failed']>0
    repairs=[e['time'] for e in r['events'] if e['event']=='部件修复返库']
    assert repairs and min(repairs)>=task['landed_at']
    # Exported event timestamps are rounded to five decimals; task times are exact.
    assert all(e['time']+1e-5>=task['landed_at'] for e in r['events'] if e['event']=='恢复可用')
    p=r['replication_results'][0]['parts'];assert p['initial']==p['final']


def test_three_day_no_fault_phase_totals():
    t=flight_tables();t['MissionType'][0].update(DURN='3',TFOUT=str(1/6),TFRET=str(1/6))
    r=simulate(t);f=r['mission']['flight']
    assert f['completed']==9 and f['aircraft_sorties']==18
    assert r['mission']['supplied_hours']==54
    assert (f['out_aircraft_hours'],f['on_station_aircraft_hours'],f['return_aircraft_hours'])==(9,36,9)
    assert f['preparation_aircraft_hours']==27
