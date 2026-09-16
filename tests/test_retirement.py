import pytest
from test_m3_service import config, add_rule, rig, flight
from simlab.engine import run_one


def retiring(iid='L', hours=2, repairs='', method='IN_PLACE'):
    cfg = config(method)
    cfg['horizon'] = 8
    cfg['stock'] = {('C', iid): 2}
    cfg['m3']['tables']['SimLabItemRetirement'] = [dict(IID=iid, LIMIT_H=hours, LIMIT_REPAIRS=repairs)]
    if method == 'IN_PLACE':
        cfg['m3']['tables']['SimLabMaintenanceStep'] += [dict(RULEID='R', STEP=s, DURATION_H=1, TASK='') for s in ('REMOVE','INSTALL')]
    return cfg


def test_hour_expiry_reuses_replacement_and_preserves_lifetime():
    result = run_one(retiring())
    retired = result['service']['retirements']
    assert retired[0]['lifetime_hours'] == 2
    jobs = [j for j in result['service']['jobs'] if j['kind']=='RETIREMENT']
    assert (jobs[0]['due_at'], jobs[0]['started_at'], jobs[0]['ended_at']) == (2,2,5)
    assert result['failures'] == 0
    assert not any(j['method']=='OFF_ITEM' for j in result['service']['jobs'])


def test_flight_expiry_finishes_flight_then_replaces_before_next_mission():
    cfg=retiring(); cfg['missions']=[flight(),flight(3,4,id='F2')]
    result=run_one(cfg)
    row=result['service']['retirements'][0]
    assert row['lifetime_hours']==3
    job=next(j for j in result['service']['jobs'] if j['kind']=='RETIREMENT')
    assert (job['due_at'],job['started_at'],job['ended_at'])==(2,3,6)
    assert result['mission']['tasks'][0]['flight_status']=='completed'
    assert result['mission']['tasks'][1]['flight_status']=='cancelled'


def test_nth_actual_repair_retires_perfect_leaf_and_never_returns_off_item():
    cfg=retiring(hours='', repairs=1, method='REPLACE')
    env,parts,p,a,net,s=rig(cfg); parts.fail(p,p)
    s.corrective(a,a['slots'][0]); env.run(until=12)
    assert parts.records[p]['corrective_repairs']==1
    assert parts.records[p]['age']==0
    assert parts.locations[p]=='retired'
    assert p not in net.available('A','L')
    assert s.snapshot()['retirements'][0]['reason']=='LIMIT_REPAIRS'


def test_parent_hours_and_subtree_disposal_no_child_salvage():
    cfg=retiring(); cfg['children']={'L':[dict(iid='S',quantity=2,rate=0,envf=1)]}
    result=run_one(cfg)
    lives=result['service']['lifetimes']
    old=next(r for r in lives if r['iid']=='L' and r['retired'])
    children=[r for r in lives if r['parent']==old['part']]
    assert old['lifetime_hours']==2 and len(children)==2
    assert all(r['retired'] and r['lifetime_hours']==2 and r['corrective_repairs']==0 for r in children)


def test_preventive_does_not_count_as_repair():
    cfg=retiring(hours='', repairs=1)
    add_rule(cfg,'PM','SYS','L','C','PREVENTIVE','IN_PLACE')
    cfg['m3']['tables']['SimLabItemPreventive']=[dict(PMID='P',IID='L',CLOCK='OPERATING',INTERVAL_H=2,INITIAL_H=0)]
    result=run_one(cfg)
    assert not result['service']['retirements']
    assert all(r['corrective_repairs']==0 for r in result['service']['lifetimes'])


def test_child_hours_expire_at_home_even_when_parent_corrective_replaces():
    cfg=retiring('S', method='REPLACE'); cfg['children']={'L':[dict(iid='S',quantity=2,rate=0,envf=1)]}
    add_rule(cfg,'S-C','L','S','C','CORRECTIVE','REPLACE')
    result=run_one(cfg)
    assert result['service']['retirements'][0]['iid']=='S'
    assert result['service']['jobs'][0]['parent']=='L'
    assert not any(r['retired'] for r in result['service']['lifetimes'] if r['iid']=='L')


def test_same_time_preventive_expiry_cannot_leave_stale_clock_or_job():
    cfg=retiring(); add_rule(cfg,'PM','SYS','L','C','PREVENTIVE','IN_PLACE')
    cfg['m3']['tables']['SimLabItemPreventive']=[dict(PMID='P',IID='L',CLOCK='OPERATING',INTERVAL_H=2,INITIAL_H=0)]
    result=run_one(cfg)
    retired={r['part'] for r in result['service']['retirements']}
    assert all(c['part'] not in retired for c in result['service']['clocks'])
    assert not any(j['part'] in retired and j['kind']=='PREVENTIVE' and j['ended_at'] is None for j in result['service']['jobs'])


def test_parent_and_child_simultaneously_due_in_flight_do_not_spin_or_salvage():
    cfg=retiring(); cfg['horizon']=7; cfg['missions']=[flight()]
    cfg['children']={'L':[dict(iid='S',quantity=1,rate=0,envf=1)]}
    cfg['m3']['tables']['SimLabItemRetirement'].append(dict(IID='S',LIMIT_H=2,LIMIT_REPAIRS=''))
    result=run_one(cfg)
    jobs=result['service']['jobs']
    assert len(jobs)==1 and jobs[0]['iid']=='L'
    assert [(r['iid'],r['reason'],r['lifetime_hours']) for r in result['service']['retirements']]==[
        ('L','LIMIT_H',3),('S','PARENT_RETIREMENT',3)]


def test_second_in_place_repair_retires_but_first_perfect_repair_does_not_reset_count():
    cfg=retiring(hours='', repairs=2)
    env,parts,p,a,net,s=rig(cfg)
    parts.records[p]['lifetime_hours']=9
    parts.fail(p,p); s.corrective(a,a['slots'][0]); env.run(until=3.1)
    assert parts.records[p]['corrective_repairs']==1 and not parts.records[p].get('retired')
    parts.fail(p,p); s.corrective(a,a['slots'][0]); env.run(until=10)
    assert parts.records[p]['corrective_repairs']==2 and parts.records[p]['lifetime_hours']==9
    assert parts.locations[p]=='retired' and a['state']=='available'
    assert len([j for j in s.jobs if j['kind']=='RETIREMENT'])==1


def test_nested_actual_repair_does_not_increment_parent_and_retires_child():
    cfg=retiring('S',hours='',repairs=1)
    cfg['children']={'L':[dict(iid='S',quantity=2,rate=0,envf=1)]}
    add_rule(cfg,'SC','L','S','C','CORRECTIVE','MIXED',p=0)
    env,parts,p,a,net,s=rig(cfg); child,healthy=parts.records[p]['children']
    parts.fail(p,child); s.corrective(a,a['slots'][0]); env.run(until=10)
    assert parts.records[p]['corrective_repairs']==0
    assert parts.records[child]['corrective_repairs']==1 and parts.records[child]['retired']
    assert parts.records[healthy]['corrective_repairs']==0
    assert parts.records[p]['children'][1]==healthy and a['state']=='available'


def test_expired_spare_cannot_be_installed_and_does_not_repeat_retirement():
    cfg=retiring(hours=2,method='REPLACE')
    env,parts,p,a,net,s=rig(cfg); expired,good=net.available('C','L')
    parts.records[expired]['lifetime_hours']=2
    s.retirement.due()
    parts.fail(p,p); s.corrective(a,a['slots'][0]); env.run(until=5)
    assert a['slots'][0]['token']==good and parts.locations[expired]=='retired'
    for _ in range(3):s.retirement.due()
    assert len([r for r in s.snapshot()['retirements'] if r['part']==expired])==1


def test_purchase_pm_calendar_clock_starts_at_arrival_and_tree_lifetimes_are_zero():
    cfg=config(); cfg['horizon']=9; cfg['fleets'][0]['util']=0
    cfg['children']={'L':[dict(iid='S',quantity=1,rate=0,envf=1)]}
    cfg['m3']['tables']['SimLabPurchasePolicy']=[dict(POINT='P',STID='C',IID='L',TRIGGER='PERIODIC',
        TARGET_QTY=1,REORDER_QTY='',FIRST_H=1,INTERVAL_H=100,LEAD_H=4)]
    cfg['m3']['tables']['SimLabItemPreventive']=[dict(PMID='SPM',IID='S',CLOCK='CALENDAR',INTERVAL_H=100,INITIAL_H=0)]
    result=run_one(cfg)
    purchased=result['supply']['purchases'][0]['parts'][0]
    lives=result['service']['lifetimes']
    child=next(r['part'] for r in lives if r['parent']==purchased)
    assert next(c['hours'] for c in result['service']['clocks'] if c['part']==child)==4
    assert all(r['lifetime_hours']==0 and r['corrective_repairs']==0 for r in lives)


def test_exact_fault_and_hour_limit_and_pm_do_not_leave_blocked_stale_work(monkeypatch):
    from simlab.m3_engine import Exposure
    cfg=retiring(); cfg['fleets'][0]['parts'][0]['rate']=1
    add_rule(cfg,'PM','SYS','L','C','PREVENTIVE','IN_PLACE')
    cfg['m3']['tables']['SimLabItemPreventive']=[dict(PMID='P',IID='L',CLOCK='OPERATING',INTERVAL_H=2,INITIAL_H=0)]
    old=Exposure.__init__
    def init(self,*args,**kwargs):
        old(self,*args,**kwargs)
        for record in self.parts.records.values():record['budget']=2
    monkeypatch.setattr(Exposure,'__init__',init)
    result=run_one(cfg)
    assert result['service']['jobs'][0]['kind']=='RETIREMENT'
    assert result['service']['jobs'][0]['ended_at']==5
    assert result['availability']==pytest.approx(4/8)
    assert not any(j['kind']!='RETIREMENT' and j['ended_at'] is None for j in result['service']['jobs'])


def test_off_item_parent_with_child_count_retirement_is_quarantined_until_child_replaced():
    cfg=retiring('S',hours='',repairs=1,method='REPLACE')
    cfg['children']={'L':[dict(iid='S',quantity=1,rate=0,envf=1)]}
    cfg['stock']={('C','L'):1,('A','S'):1}
    add_rule(cfg,'SC','L','S','A','CORRECTIVE','MIXED',p=0)
    env,parts,p,a,net,s=rig(cfg); child=parts.records[p]['children'][0]
    parts.fail(p,child); s.corrective(a,a['slots'][0]); env.run(until=4.1)
    assert p not in net.available('A','L')
    env.run(until=10)
    assert parts.records[child]['retired'] and parts.records[p]['corrective_repairs']==0
    assert p in net.available('A','L')


def test_legacy_replacement_definition_can_execute_retirement():
    cfg=retiring(); t=cfg['m3']['tables']; t['SimLabMaintenanceRule']=[]; t['SimLabMaintenanceStep']=[]
    cfg['replacements']={('SYS','L','C'):dict(time=dict(mean=4,random=False),resources={})}
    result=run_one(cfg)
    job=result['service']['jobs'][0]
    assert job['kind']=='RETIREMENT' and job['ended_at']==6
    assert result['service']['retirements'][0]['corrective_repairs']==0
