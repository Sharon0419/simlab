"""Physical redundancy boundaries and mission/maintenance integration."""
import pytest
from simlab.components import Components
from simlab.compiler import compile_model, ModelError
from simlab.engine import run_one
from test_m3_service import config, add_rule, flight


def capability_api():
    from importlib.util import find_spec
    assert find_spec('simlab.redundancy'), 'recursive redundancy capability is missing'
    from simlab.redundancy import capable, asset_capable
    return capable, asset_capable


def test_three_take_two_counts_physical_instances():
    capable, asset_capable = capability_api()
    p = Components({})
    slots = [dict(iid='L', token=p.create('L', 'installed')) for _ in range(3)]
    a = dict(sid='SYS', slots=slots)
    rules = {('SYS', 'L'): 2}
    assert asset_capable(p, a, rules)
    p.fail(slots[0]['token'], slots[0]['token'])
    assert asset_capable(p, a, rules)
    p.fail(slots[1]['token'], slots[1]['token'])
    assert not asset_capable(p, a, rules)


def test_sru_threshold_is_recursive_and_isolated_per_parent():
    capable, asset_capable = capability_api()
    p = Components({'L': [dict(iid='S', quantity=2)]})
    left, right = [p.create('L', 'installed') for _ in range(2)]
    a = dict(sid='SYS', slots=[dict(iid='L', token=x) for x in (left, right)])
    rules = {('L', 'S'): 1}
    for root in (left, right):
        p.fail(root, p.records[root]['children'][0])
    assert capable(p, left, rules) and capable(p, right, rules)
    assert asset_capable(p, a, rules)
    p.fail(left, p.records[left]['children'][1])
    assert not asset_capable(p, a, rules)
    assert capable(p, right, rules)


def test_all_different_type_groups_required_and_default_is_serial():
    _, asset_capable = capability_api()
    p = Components({})
    slots = [dict(iid=i, token=p.create(i, 'installed')) for i in ('L', 'L', 'S')]
    a = dict(sid='SYS', slots=slots)
    p.fail(slots[0]['token'], slots[0]['token'])
    assert not asset_capable(p, a, {})
    assert asset_capable(p, a, {('SYS', 'L'): 1})
    p.fail(slots[2]['token'], slots[2]['token'])
    assert not asset_capable(p, a, {('SYS', 'L'): 1})


def test_compile_redundancy_and_reject_invalid_relations():
    from test_flight import flight_tables
    t = flight_tables()
    row = t['MaterielStructure'][0]
    row['QTYPM'] = '3'
    t['SimLabRedundancy'] = [dict(PARENT=row['MMID'], IID=row['MID'], K='2')]
    assert compile_model(t)['redundancy'] == {(row['MMID'], row['MID']): 2}
    for k in ('0', '4', '1.5', 'nan'):
        t['SimLabRedundancy'][0]['K'] = k
        with pytest.raises(ModelError):
            compile_model(t)
    t['SimLabRedundancy'][0].update(PARENT=row['MID'], K='1')
    with pytest.raises(ModelError):
        compile_model(t)


def scenario(m3=True):
    cfg = config()
    cfg.update(horizon=12, redundancy={('SYS', 'L'): 2})
    cfg['fleets'][0]['parts'][0].update(quantity=3, rate=1)
    cfg['missions'] = [flight(0, 4), flight(4, 5, id='F2'), flight(8, 9, id='F3')]
    cfg['missions'][0]['return_fraction'] = .25
    if not m3:
        cfg.pop('m3')
        cfg['fleets'][0]['root'] = 'C'
        cfg['repairs'] = {('C', 'L'): dict(time=dict(mean=1, random=False), resources={})}
        cfg['replacements'] = {('SYS', 'L', 'C'): dict(time=dict(mean=1, random=False), resources={})}
        cfg['stock'] = {('C', 'L'): 3}
    return cfg


def set_budgets(monkeypatch, budgets):
    original = Components.create
    count = []
    def create(self, iid, location, site=''):
        part = original(self, iid, location, site)
        if location == 'installed':
            self.records[part]['budget'] = budgets[len(count)]
            count.append(part)
        return part
    monkeypatch.setattr(Components, 'create', create)


@pytest.mark.parametrize('m3', [False, True])
def test_first_fault_finishes_mission_then_blocks_departure_until_repaired(monkeypatch, m3):
    set_budgets(monkeypatch, (1, 100, 100))
    r = run_one(scenario(m3))
    tasks = r['mission']['tasks']
    assert tasks[0]['flight_status'] == 'completed'
    assert tasks[1]['flight_status'] == 'cancelled'
    assert tasks[2]['flight_status'] == 'completed'
    assert len([e for e in r['events'] if e['event'] == '发生故障' and e['time'] < 4]) == 1
    if m3:
        job = r['service']['jobs'][0]
        assert (job['due_at'], job['started_at'], job['ended_at']) == (1, 4, 7)


@pytest.mark.parametrize('m3', [False, True])
def test_second_fault_aborts_at_threshold_and_all_faults_are_repaired(monkeypatch, m3):
    set_budgets(monkeypatch, (1, 2, 100))
    r = run_one(scenario(m3))
    task = r['mission']['tasks'][0]
    assert task['flight_status'] == 'aborted'
    assert task['ended_at'] == 2
    assert task['landed_at'] == 3
    if m3:
        jobs = r['service']['jobs']
        assert len(jobs) >= 2
        assert jobs[0]['started_at'] == 3 and jobs[1]['started_at'] == 6


@pytest.mark.parametrize('m3', [False, True])
@pytest.mark.parametrize('fault_at', [0, 4])
def test_fault_at_departure_boundary_is_settled_before_dispatch(monkeypatch, m3, fault_at):
    set_budgets(monkeypatch, (fault_at, 100, 100))
    cfg = scenario(m3)
    r = run_one(cfg)
    tasks = r['mission']['tasks']
    if fault_at == 0:
        assert tasks[0]['flight_status'] == 'cancelled'
    else:
        assert tasks[0]['flight_status'] == 'completed'
        assert tasks[1]['flight_status'] == 'cancelled'


def test_same_time_faults_in_one_parent_all_registered_before_exposure_stops(monkeypatch):
    cfg = scenario()
    cfg['redundancy'] = {('SYS', 'L'): 2, ('L', 'S'): 2}
    cfg['children'] = {'L': [dict(iid='S', quantity=3, rate=1, envf=1)]}
    add_rule(cfg, 'CHILD', 'L', 'S', 'C', 'CORRECTIVE', 'IN_PLACE')
    original = Components.create
    def create(self, iid, location, site=''):
        part = original(self, iid, location, site)
        if location == 'installed':
            first = part == 'L#1'
            for ix, child in enumerate(self.records[part]['children']):
                self.records[child]['budget'] = 1 if first and ix < 2 else 100
        return part
    monkeypatch.setattr(Components, 'create', create)
    cfg['horizon'] = 4.1
    cfg['missions'] = cfg['missions'][:1]
    r = run_one(cfg)
    assert r['failures'] == 2
    rows = {x['part']: x for x in r['aging']['instances']}
    assert rows['S#4']['lifetime_hours'] == 1  # healthy sibling stops with its incapable LRU
    assert rows['S#6']['lifetime_hours'] == 4  # another physical parent keeps operating
    assert r['mission']['tasks'][0]['flight_status'] == 'completed'


@pytest.mark.parametrize('m3', [False, True])
def test_duty_retains_current_assignment_but_cannot_start_adjacent_task(monkeypatch, m3):
    set_budgets(monkeypatch, (1, 100, 100))
    cfg = scenario(m3)
    for task in cfg['missions']:
        task.pop('flight_prep_hours')
        task.pop('return_fraction', None)
        task['type'] = 'DUTY'
    r = run_one(cfg)
    tasks = r['mission']['tasks']
    assert tasks[0]['supplied_hours'] == 4
    assert tasks[1]['supplied_hours'] == 0
    assert tasks[2]['supplied_hours'] == 1


@pytest.mark.parametrize('m3,ready_at', [(False, 2), (True, 4)])
def test_repair_completion_at_exact_departure_is_dispatchable(monkeypatch, m3, ready_at):
    set_budgets(monkeypatch, (.5, 100, 100))
    cfg = scenario(m3)
    cfg['missions'] = [flight(0, 1), flight(ready_at, ready_at + 1, id='F2')]
    r = run_one(cfg)
    assert [t['flight_status'] for t in r['mission']['tasks']] == ['completed', 'completed']


@pytest.mark.parametrize('m3', [False, True])
def test_zero_duration_repairs_clear_all_pending_faults_at_landing(monkeypatch, m3):
    set_budgets(monkeypatch, (1, 1, 100))
    cfg = scenario(m3)
    cfg['missions'][0]['return_fraction'] = 0
    cfg['missions'] = [cfg['missions'][0], flight(1, 2, id='F2')]
    if m3:
        for row in cfg['m3']['tables']['SimLabMaintenanceStep']:
            row['DURATION_H'] = 0
    else:
        cfg['replacements'][('SYS', 'L', 'C')]['time']['mean'] = 0
    r = run_one(cfg)
    tasks = r['mission']['tasks']
    assert tasks[0]['flight_status'] == 'aborted'
    assert tasks[1]['launched_at'] == 1
    if m3:
        assert all(j['ended_at'] == 1 for j in r['service']['jobs'][:2])


def test_redundant_lifetime_expiry_completes_current_flight():
    from test_retirement import retiring
    cfg = retiring()
    cfg['fleets'][0]['parts'][0]['quantity'] = 2
    cfg['redundancy'] = {('SYS', 'L'): 1}
    cfg['missions'] = [flight(0, 3), flight(3, 4, id='F2')]
    result = run_one(cfg)
    assert result['mission']['tasks'][0]['flight_status'] == 'completed'
    assert result['mission']['tasks'][1]['flight_status'] == 'cancelled'
    assert result['failures'] == 0
    jobs = [j for j in result['service']['jobs'] if j['kind'] == 'RETIREMENT']
    assert [(j['due_at'], j['started_at']) for j in jobs[:2]] == [(2, 3), (2, 6)]


def test_redundancy_fault_and_preventive_jobs_remain_serial(monkeypatch):
    set_budgets(monkeypatch, (1, 100, 100))
    cfg = scenario()
    add_rule(cfg, 'PM', 'SYS', 'L', 'C', 'PREVENTIVE', 'IN_PLACE')
    cfg['m3']['tables']['SimLabItemPreventive'] = [dict(PMID='P', IID='L', CLOCK='OPERATING', INTERVAL_H=2, INITIAL_H=0)]
    cfg['missions'] = cfg['missions'][:2]
    result = run_one(cfg)
    assert result['mission']['tasks'][0]['flight_status'] == 'completed'
    assert result['mission']['tasks'][1]['flight_status'] == 'cancelled'
    jobs = [j for j in result['service']['jobs'] if j['started_at'] is not None]
    assert [(j['kind'], j['started_at']) for j in jobs] == [('CORRECTIVE', 4), ('PREVENTIVE', 7), ('PREVENTIVE', 10)]
    assert next(x for x in result['aging']['instances'] if x['part'] == 'L#1')['lifetime_hours'] == 1


def test_legacy_sru_redundancy_repairs_every_failed_leaf(monkeypatch):
    from test_maintenance import minimal
    tables = minimal(spare_lru=1, spare_sru=2, horizon=20)
    next(r for r in tables['MaterielStructure'] if r['MID'] == 'BOARD')['QTYPM'] = '3'
    tables['SimLabRedundancy'] = [dict(PARENT='POWER', IID='BOARD', K='2')]
    cfg = compile_model(tables)
    cfg['missions'] = [dict(flight(0, 4), sid='VEHICLE', location=cfg['fleets'][0]['unit'])]
    original = Components.create
    def create(self, iid, location, site=''):
        part = original(self, iid, location, site)
        if location == 'installed':
            for index, child in enumerate(self.records[part]['children']):
                self.records[child]['budget'] = (.2, .4, 100)[index]
        return part
    monkeypatch.setattr(Components, 'create', create)
    result = run_one(cfg)
    assert result['mission']['tasks'][0]['ended_at'] == 2
    assert result['maintenance']['by_kind']['SRU']['completed'] == 2
    assert result['parts']['initial'] == result['parts']['final']
    installed = [r for r in result['components']['instances'] if r['physical_location'] == 'installed']
    assert all(not r['broken'] for r in installed)


@pytest.mark.parametrize('m3', [False, True])
def test_calendar_maintenance_waits_for_redundant_fault_repair(monkeypatch, m3):
    set_budgets(monkeypatch, (1, 100, 100))
    cfg = scenario(m3)
    cfg['planned'] = [dict(id='P', sid='SYS', unit='U', task='', resources={}, duration=2, due_times=(2,))]
    result = run_one(cfg)
    job = result['mission']['planned']['jobs'][0]
    assert job['started_at'] == (7 if m3 else 5)
