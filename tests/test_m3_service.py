from collections import Counter
import pytest
import simpy
import numpy as np
from simlab.aging_components import AgingComponents
from simlab.engine import ResourcePool, run_one


def config(method='IN_PLACE', preventive=False, children=False):
    tables = {'SimLabMaintenanceRule': [], 'SimLabMaintenanceStep': [],
              'SimLabOffItemService': [], 'SimLabRepairLocation': [],
              'SimLabServiceRoute': [], 'SimLabItemPreventive': [],
              'SimLabSupplyRoute': [], 'SimLabSupplyPolicy': [], 'TaskResource': []}
    cfg = dict(seed=7, horizon=16, interval=1, replications=1, count=1, point='P', log=True,
               stock={}, children={}, aging={}, capacity={}, schedules={}, missions=[], planned=[],
               repairs={}, replacements={}, depot_processes={}, remove_fraction=.5, links={},
               m3={'tables':tables}, fleets=[dict(sid='SYS',unit='U',home='C',root='A',quantity=1,util=1,
                   parts=[dict(iid='L',quantity=1,rate=0,envf=1)])])
    add_rule(cfg,'R','SYS','L','C','CORRECTIVE',method)
    tables['SimLabRepairLocation']=[dict(IID='L',FROM_STID='C',REPAIR_STID='A')]
    tables['SimLabServiceRoute']=[dict(ROUTEID='CA',IID='L',FROM_STID='C',TO_STID='A',TRANSIT_H=0)]
    for kind in ('CORRECTIVE','PREVENTIVE'):
        for step,h in [('DIAGNOSE',0),('SERVICE',10),('TEST',0)]:
            tables['SimLabOffItemService'].append(dict(IID='L',STID='A',KIND=kind,STEP=step,DURATION_H=h,DISTRIBUTION='FIXED',TASK=''))
    if preventive:
        add_rule(cfg,'PM','SYS','L','C','PREVENTIVE',method)
        tables['SimLabItemPreventive']=[dict(PMID='P',IID='L',CLOCK='OPERATING',INTERVAL_H=2,INITIAL_H=0)]
    return cfg


def add_rule(cfg,rid,mid,iid,station,kind,method,p=.3):
    t=cfg['m3']['tables']
    t['SimLabMaintenanceRule'].append(dict(RULEID=rid,MID=mid,IID=iid,STID=station,KIND=kind,METHOD=method,REPLACE_P=p))
    steps=[('DIAGNOSE',0),('TEST',1)]
    if method in ('IN_PLACE','MIXED'):steps.append(('IN_PLACE',2))
    if method in ('REPLACE','MIXED'):steps.extend([('REMOVE',1),('INSTALL',1)])
    for step,h in steps:t['SimLabMaintenanceStep'].append(dict(RULEID=rid,STEP=step,DURATION_H=h,DISTRIBUTION='FIXED',TASK=''))


def rig(cfg):
    from simlab.supply import SupplyNetwork
    from simlab.service import ServiceCoordinator
    env=simpy.Environment(); parts=AgingComponents(cfg['children'],cfg['aging'],env)
    part=parts.create('L','installed','C')
    asset=dict(id='A',sid='SYS',unit='U',home='C',slots=[dict(iid='L',token=part,rate=0,envf=1)],
               mission=None,state='available',times=Counter(),last=0,assignment_event=env.event())
    net=SupplyNetwork(env,parts,cfg)
    def state(a,s):a.update(state=s)
    service=ServiceCoordinator(env,cfg,parts,net,ResourcePool(env,cfg['capacity'],cfg.get('schedules')),
        np.random.default_rng(1),np.random.default_rng(2),state,lambda *a:None)
    service.assets=[asset]; net.start()
    return env,parts,part,asset,net,service


def test_m1_in_place_finishes_after_test_without_stock_change():
    env,parts,p,a,net,s=rig(config()); parts.fail(p,p)
    job=s.corrective(a,a['slots'][0]); env.run(until=3.01)
    assert job['ended_at']==3 and a['slots'][0]['token']==p
    assert not parts.records[p]['broken'] and not net.snapshot()['orders']


def test_m2_replacement_recovers_before_removed_item_service():
    cfg=config('REPLACE'); cfg['stock']={('C','L'):1}
    env,parts,p,a,net,s=rig(cfg); parts.fail(p,p)
    job=s.corrective(a,a['slots'][0]); env.run(until=3.01)
    assert job['ended_at']==3 and a['slots'][0]['token']!=p
    assert parts.records[p]['broken']
    env.run(until=11.01)
    assert not parts.records[p]['broken'] and p in net.available('A','L')


def test_m3_pick_once_endpoints_and_wait_does_not_reroll():
    class Draws:
        def __init__(self):self.calls=0
        def random(self):self.calls+=1; return .2
    cfg=config('MIXED'); env,parts,p,a,net,s=rig(cfg); rng=Draws(); s.method_rng=rng
    parts.fail(p,p); job=s.corrective(a,a['slots'][0]); env.run(until=8)
    assert job['method']=='REPLACE' and rng.calls==1 and job['status']=='waiting_spare'
    assert s.select_method(dict(METHOD='MIXED',REPLACE_P=0))=='IN_PLACE'
    assert s.select_method(dict(METHOD='MIXED',REPLACE_P=1))=='REPLACE' and rng.calls==1
    assert s.select_method(dict(METHOD='MIXED',REPLACE_P=.1))=='IN_PLACE'


def test_m4_healthy_preventive_completion_resets_age_preserves_lifetime():
    env=simpy.Environment(); parts=AgingComponents({}, {'L':{'repair':'MINIMAL'}},env)
    p=parts.create('L','stock','C'); parts.records[p].update(age=40,lifetime_hours=100,budget=.7)
    assert hasattr(parts,'service_complete'), 'explicit healthy service completion is missing'
    parts.service_complete(p,'PREVENTIVE')
    assert parts.records[p]['age']==0 and parts.records[p]['lifetime_hours']==100
    assert parts.records[p]['broken'] is False and parts.records[p]['budget'] is None
    assert parts.age_events[-1]['event']=='preventive'
    assert parts.age_events[-1]['repair']=='PERFECT'


def test_m5_replacement_keeps_spare_age_and_unfinished_old_age():
    cfg=config('REPLACE'); cfg['stock']={('C','L'):1}
    env,parts,p,a,net,s=rig(cfg); spare=net.available('C','L')[0]
    parts.records[p].update(age=40,lifetime_hours=40); parts.records[spare].update(age=12,lifetime_hours=12)
    parts.fail(p,p); s.corrective(a,a['slots'][0]); env.run(until=3.01)
    assert parts.records[spare]['age']==12 and parts.records[p]['age']==40


def test_no_fault_continuous_preventive_runs_and_counts_all_leaf_hours():
    r=run_one(config(preventive=True))
    assert 'service' in r, 'M3 service runtime is not connected'
    jobs=[j for j in r['service']['jobs'] if j['kind']=='PREVENTIVE']
    assert [(j['due_at'],j['ended_at']) for j in jobs]==[(2,5),(7,10),(12,15)]
    assert r['failures']==0 and r['availability']==pytest.approx(7/16)
    assert r['aging']['instances'][0]['lifetime_hours']==7

def flight(start=0,end=3,prep=0,id='F'):
    return dict(id=id,type='FLIGHT',location='U',sid='SYS',quantity=1,start=start,end=end,flight_prep_hours=prep)


def test_m6_parent_in_place_preserves_healthy_sibling_identity_age_budget():
    cfg=config(); cfg['children']={'L':[dict(iid='S',quantity=2,rate=0,envf=1)]}
    add_rule(cfg,'CHILD','L','S','C','CORRECTIVE','IN_PLACE')
    env,parts,p,a,net,s=rig(cfg); bad,good=parts.records[p]['children']
    parts.records[good].update(age=42,lifetime_hours=100,budget=.765)
    parts.fail(p,bad); parent_job=s.corrective(a,a['slots'][0]); env.run(until=6.01)
    assert parent_job['ended_at']==6
    assert parts.records[p]['children']==[bad,good]
    assert parts.records[good]['age']==42 and parts.records[good]['budget']==.765
    assert not parts.records[p]['broken']
    assert len(s.jobs)==2 and all(j['status']=='completed' for j in s.jobs)


def test_m7_operating_due_in_air_does_not_abort_and_records_overrun():
    cfg=config(preventive=True); cfg['missions']=[flight(),flight(3,4,id='F2')]
    cfg['horizon']=8
    r=run_one(cfg)
    pm=next(j for j in r['service']['jobs'] if j['kind']=='PREVENTIVE')
    assert (pm['due_at'],pm['started_at'],pm['ended_at'],pm['overrun_hours'])==(2,3,6,1)
    assert r['mission']['tasks'][0]['flight_status']=='completed'
    assert r['mission']['tasks'][1]['flight_status']=='cancelled'
    assert r['aging']['instances'][0]['lifetime_hours']==3


def test_m8_calendar_in_transit_quarantines_receipt_until_service():
    cfg=config(preventive=True); t=cfg['m3']['tables']; cfg['stock']={('A','L'):1}; cfg['horizon']=15
    t['SimLabItemPreventive'][0]['CLOCK']='CALENDAR'
    t['SimLabSupplyRoute']=[dict(ROUTEID='AC',IID='L',FROM_STID='A',TO_STID='C',TRANSIT_H=4)]
    t['SimLabSupplyPolicy']=[dict(POINT='P',STID='C',IID='L',TRIGGER='THRESHOLD',TARGET_QTY=1,REORDER_QTY=0)]
    t['SimLabRepairLocation'].append(dict(IID='L',FROM_STID='A',REPAIR_STID='A'))
    r=run_one(cfg)
    job=next(j for j in r['service']['jobs'] if j['part']=='L#1')
    assert job['due_at']==2 and job['started_at']==4 and job['ended_at']==14
    assert r['supply']['orders'][0]['received']==1
    assert next(x for x in r['aging']['instances'] if x['part']=='L#1')['age']==0


@pytest.mark.parametrize('mode,covered', [('PERFECT',True),('MINIMAL',False)])
def test_m9_corrective_covers_only_unstarted_perfect_preventive(mode,covered):
    from simlab.preventive import PreventiveClocks
    cfg=config(preventive=True); cfg['aging']={'L':dict(initial=40,repair=mode)}
    env,parts,p,a,net,s=rig(cfg); s.clocks=PreventiveClocks(env,parts,cfg['m3']['tables'])
    s.clocks.clocks[p]['hours']=2; s.clocks.due(); s.locks['A']='existing_work'
    pm=s.preventive(p); parts.fail(p,p); s.corrective(a,a['slots'][0]); s.locks.clear(); s.advance()
    env.run(until=6.01)
    assert pm['status']==('covered_by_corrective' if covered else 'completed')
    assert len([e for e in parts.age_events if e['event']=='preventive'])==int(not covered)


def test_m10_resources_cross_shift_and_unfinished_age_is_not_reset():
    cfg=config(preventive=True); cfg['horizon']=4
    cfg['m3']['tables']['SimLabItemPreventive'][0]['INITIAL_H']=2
    cfg['aging']={'L':dict(initial=40,repair='MINIMAL',shape=1,scale=100,application=0)}
    cfg['capacity']={('C','R'):1}; cfg['schedules']={('C','R'):[(2,3)]}
    cfg['m3']['tables']['TaskResource']=[dict(TID='T',RID='R',QTY=1)]
    for row in cfg['m3']['tables']['SimLabMaintenanceStep']:
        if row['STEP']=='IN_PLACE':row['TASK']='T'
    r=run_one(cfg); job=r['service']['jobs'][0]
    assert job['ended_at'] is None and r['aging']['instances'][0]['age']==40
    assert r['resources']['C/R']==.5


def test_shared_ground_queue_orders_calendar_before_component_then_one_preparation():
    cfg=config(preventive=True); cfg['horizon']=9
    cfg['missions']=[flight(1,4,.5),flight(8.5,9,.5,'F2')]
    cfg['planned']=[dict(id='CAL',sid='SYS',unit='U',task='',resources={},duration=1,due_times=[3],quantity=1)]
    r=run_one(cfg)
    pm=next(j for j in r['service']['jobs'] if j['kind']=='PREVENTIVE')
    assert pm['started_at']==5 and pm['ended_at']==8
    planned=r['mission']['planned']['jobs'][0]
    assert planned['started_at']==4 and planned['ended_at']==5
    prep=[e['time'] for e in r['events'] if e['event']=='开始出动保障']
    assert [t for t in prep if t<cfg['horizon']]==[.5,8]
    assert r['mission']['tasks'][1]['launched_at']==8.5


def test_fixed_mission_preventive_pauses_assignment_and_resumes():
    cfg=config(preventive=True); cfg['horizon']=8
    cfg['missions']=[dict(id='M',type='WATCH',location='U',sid='SYS',quantity=1,start=0,end=8)]
    r=run_one(cfg)
    assert r['mission']['supplied_hours']==4
    assert r['failures']==0 and r['service']['jobs'][0]['ended_at']==5

def test_parent_internal_replacement_retains_sibling_and_repairs_detached_sru_asynchronously():
    cfg=config(); cfg['children']={'L':[dict(iid='S',quantity=2,rate=0,envf=1)]}
    cfg['stock']={('C','S'):1}
    add_rule(cfg,'CHILD','L','S','C','CORRECTIVE','REPLACE')
    cfg['m3']['tables']['SimLabRepairLocation'].append(dict(IID='S',FROM_STID='C',REPAIR_STID='C'))
    cfg['m3']['tables']['SimLabOffItemService'] += [dict(IID='S',STID='C',KIND='CORRECTIVE',STEP=step,
        DURATION_H=h,DISTRIBUTION='FIXED',TASK='') for step,h in [('DIAGNOSE',0),('SERVICE',10),('TEST',0)]]
    env,parts,p,a,net,s=rig(cfg); bad,good=parts.records[p]['children']; parts.fail(p,bad)
    s.corrective(a,a['slots'][0]); env.run(until=4.01)
    assert parts.records[p]['children'][1]==good and parts.records[bad]['parent'] is None
    assert parts.records[p]['children'][0]!=bad and parts.records[bad]['broken']
    env.run(until=11.01)
    assert bad in net.available('C','S')


def test_explicit_directed_service_path_uses_shortest_sum_without_supply_reversal():
    cfg=config('REPLACE'); cfg['stock']={('C','L'):1}
    cfg['m3']['tables']['SimLabServiceRoute']=[
        dict(ROUTEID='DIRECT',IID='L',FROM_STID='C',TO_STID='A',TRANSIT_H=9),
        dict(ROUTEID='CB',IID='L',FROM_STID='C',TO_STID='B',TRANSIT_H=2),
        dict(ROUTEID='BA',IID='L',FROM_STID='B',TO_STID='A',TRANSIT_H=3)]
    env,parts,p,a,net,s=rig(cfg); parts.fail(p,p); s.corrective(a,a['slots'][0]); env.run(until=16.01)
    off=next(j for j in s.jobs if j['method']=='OFF_ITEM')
    assert off['ended_at']==16 and p in net.available('A','L')


def test_calendar_held_spare_never_gets_concurrent_offsite_service_during_install():
    cfg=config('REPLACE',preventive=True); cfg['stock']={('C','L'):1}; cfg['horizon']=8
    cfg['fleets'][0]['parts'][0]['rate']=1
    cfg['m3']['tables']['SimLabItemPreventive'][0].update(CLOCK='CALENDAR',INTERVAL_H=2)
    # Force one fault at t=.25, then hold the spare while installation waits until t=4.
    cfg['capacity']={('C','R'):1}; cfg['schedules']={('C','R'):[(4,8)]}
    cfg['m3']['tables']['TaskResource']=[dict(TID='T',RID='R',QTY=1)]
    for step in cfg['m3']['tables']['SimLabMaintenanceStep']:
        if step['STEP']=='INSTALL':step['TASK']='T'
    from simlab.m3_engine import Exposure
    old=Exposure.__init__
    def initialize(self,*args,**kwargs):
        old(self,*args,**kwargs)
        for record in self.parts.records.values():
            if self.parts.locations[record['id']]=='installed':record['budget']=.25
    from unittest.mock import patch
    with patch.object(Exposure,'__init__',initialize):r=run_one(cfg)
    ids=[x['id'] for x in r['components']['instances']]
    assert len(ids)==len(set(ids))
    assert not any(j['part']=='L#1' and j['method']=='OFF_ITEM' and j['started_at']<5 for j in r['service']['jobs'])
    assert next(x for x in r['components']['instances'] if x['id']=='L#1')['location']!='installed'

def test_same_time_ground_calendar_due_precedes_component_pm():
    cfg=config(preventive=True); cfg['horizon']=8
    cfg['missions']=[flight(6,7,0)]
    cfg['m3']['tables']['SimLabItemPreventive'][0].update(CLOCK='CALENDAR',INTERVAL_H=2)
    cfg['planned']=[dict(id='CAL',sid='SYS',unit='U',task='',resources={},duration=1,due_times=[2],quantity=1)]
    r=run_one(cfg)
    assert r['mission']['planned']['jobs'][0]['started_at']==2
    assert r['service']['jobs'][0]['started_at']==3

def test_m3_aggregate_reports_actual_mode_and_keeps_each_replication(monkeypatch):
    from simlab.engine import simulate
    cfg=config(preventive=True); cfg['replications']=2
    monkeypatch.setattr('simlab.engine.compile_model',lambda tables:cfg)
    r=simulate({})
    assert 'M3' in r['assumptions'] and '两级' not in r['assumptions']
    assert all('service' in rep and 'supply' in rep and 'aging' in rep for rep in r['replication_results'])

def test_parent_replacement_moves_pending_leaf_pm_out_of_aircraft_lock():
    from simlab.preventive import PreventiveClocks
    cfg=config('REPLACE'); cfg['children']={'L':[dict(iid='S',quantity=1,rate=0,envf=1)]}
    cfg['stock']={('C','L'):1}; cfg['aging']={'S':dict(initial=40,repair='MINIMAL')}
    add_rule(cfg,'SRU-CM','L','S','A','CORRECTIVE','IN_PLACE')
    add_rule(cfg,'SRU-PM-C','L','S','C','PREVENTIVE','IN_PLACE')
    add_rule(cfg,'SRU-PM-A','L','S','A','PREVENTIVE','IN_PLACE')
    t=cfg['m3']['tables']; t['SimLabItemPreventive']=[dict(PMID='SPM',IID='S',CLOCK='OPERATING',INTERVAL_H=2,INITIAL_H=0)]
    t['SimLabOffItemService']=[r for r in t['SimLabOffItemService'] if r['STEP']!='SERVICE']
    env,parts,p,a,net,s=rig(cfg); child=parts.records[p]['children'][0]
    s.clocks=PreventiveClocks(env,parts,t); s.clocks.clocks[child]['hours']=2; s.clocks.due()
    s.locks['A']='existing'; pm=s.preventive(child); parts.fail(p,child); job=s.corrective(a,a['slots'][0])
    s.locks.clear(); s.advance(); env.run(until=3.01)
    assert job['ended_at']==3 and a['state']=='available'
    env.run(until=8.01)
    assert pm['station']=='A' and pm['status']=='completed'
    assert parts.records[child]['age']==0
