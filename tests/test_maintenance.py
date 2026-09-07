import pytest
import simpy

from simlab.compiler import compile_model, ModelError
from simlab.components import Components
from simlab.engine import run_one, simulate
from simlab.project import export_package, import_package
from simlab.sample import layered_project


def minimal(spare_lru=0, spare_sru=0, quantity=1, horizon=16):
    t = layered_project()['tables']
    t['Item'] = [r for r in t['Item'] if r['IID'] in ('POWER', 'BOARD')]
    next(r for r in t['Item'] if r['IID'] == 'BOARD')['FRT'] = '200000'
    t['MaterielStructure'] = [r for r in t['MaterielStructure'] if r['MID'] in ('POWER', 'BOARD')]
    t['ItemRepair'] = [{'IID': 'BOARD', 'STID': 'DEPOT', 'DIRPT': '4', 'SURPT': '0', 'DIRPTID': 'REPAIR'}]
    t['ItemReplacement'] = [r for r in t['ItemReplacement'] if r['IID'] in ('POWER', 'BOARD')]
    for r in t['ItemReplacement']:
        r['SURPT'] = '2'
    for name in ('Operations', 'OperationProfile', 'MissionType', 'MissionSystem', 'ShiftProfile', 'Shift', 'ResourceStationData'):
        t.pop(name, None)
    t['Control'][0].update(SIMPE=str(horizon), RCINT='1', NREPS='1', RMVFR='.5')
    t['SystemDeployment'][0].update(QTYPS=str(quantity), UTIL='1')
    t['StockAllocation'] = [
        {'POINT': 'BASELINE', 'IID': 'POWER', 'STID': 'BASE', 'STSIZ': str(spare_lru)},
        {'POINT': 'BASELINE', 'IID': 'BOARD', 'STID': 'DEPOT', 'STSIZ': str(spare_sru)}]
    t['StationStructure'][0].update(TFRMS='0', TTOMS='0')
    t['TaskResource'] = []
    return t


@pytest.fixture
def fixed_failure(monkeypatch):
    class Clock:
        def exponential(self, mean):
            return 1.0
    monkeypatch.setattr('simlab.engine.np.random.default_rng', lambda seed: Clock())


def test_no_spares_ten_hour_analytic_chain(fixed_failure):
    r = run_one(compile_model(minimal()))
    assert [e['time'] for e in r['events'] if e['event'] == '发生故障'] == [5]
    assert [e['time'] for e in r['events'] if e['event'] == '恢复可用'] == [15]
    assert sum(r['downtime'].values()) == 10
    assert r['availability'] == 6/16
    assert r['maintenance']['by_kind']['LRU']['mean_tat'] == 8
    assert r['components']['by_item'] == {'POWER': 1, 'BOARD': 1}
    assert r['parts']['initial'] == r['parts']['final'] == 2


def test_spare_lru_restores_vehicle_before_depot_finishes(fixed_failure):
    r = run_one(compile_model(minimal(spare_lru=1)))
    assert next(e['time'] for e in r['events'] if e['event'] == '恢复可用') == 7
    assert next(j['end'] for j in r['maintenance']['jobs'] if j['kind'] == 'LRU') == 14
    assert r['components']['by_item'] == {'POWER': 2, 'BOARD': 2}


def test_spare_sru_parent_recovers_before_failed_sru(fixed_failure):
    r = run_one(compile_model(minimal(spare_sru=1, horizon=14)))
    assert next(e['time'] for e in r['events'] if e['event'] == '恢复可用') == 11
    assert next(j['end'] for j in r['maintenance']['jobs'] if j['kind'] == 'SRU') == 12
    assert r['maintenance']['by_kind']['LRU']['phase_hours']['wait_sru'] == 0


def test_serial_sru_repairs_share_one_resource_without_parent_hold(fixed_failure):
    t = minimal(quantity=2, horizon=22)
    t['TaskResource'] = [{'TID': 'REPAIR', 'RID': 'TECH', 'QTY': '1'},
                         {'TID': 'REPLACE', 'RID': 'TECH', 'QTY': '1'}]
    next(r for r in t['ResourceAllocation'] if r['RID'] == 'TECH' and r['STID'] == 'DEPOT')['RQTY'] = '1'
    r = run_one(compile_model(t))
    restored = [e['time'] for e in r['events'] if e['event'] == '恢复可用']
    # Shared technician: removals 7–8,8–9; repairs 9–13,13–17;
    # installations 17–18,18–19; tests and base installation follow.
    assert restored == [20, 21]
    assert r['maintenance']['by_kind']['SRU']['completed'] == 2
    assert r['parts']['initial'] == r['parts']['final']


def test_zero_failure_layered_model():
    t = minimal()
    next(r for r in t['Item'] if r['IID'] == 'BOARD')['FRT'] = '0'
    r = simulate(t)
    assert r['availability'] == 1
    assert r['failures'] == 0
    assert r['maintenance']['by_kind'] == {}


@pytest.mark.parametrize('mutation', ['parent_rate', 'missing_test', 'missing_sru_repair', 'deep', 'cycle', 'wrong_child_type'])
def test_layered_rules_reject_ambiguous_input(mutation):
    t = minimal()
    if mutation == 'parent_rate':
        t['Item'][0]['FRT'] = '1'
    elif mutation == 'missing_test':
        t['SimLabDepotProcess'] = []
    elif mutation == 'missing_sru_repair':
        t['ItemRepair'] = []
    elif mutation == 'deep':
        t['Item'].append({'IID': 'DEEP', 'TYPE': 'SRU', 'FRT': '1'})
        t['MaterielStructure'].append({'MID': 'DEEP', 'MMID': 'BOARD', 'QTYPM': '1'})
    elif mutation == 'cycle':
        t['MaterielStructure'].append({'MID': 'POWER', 'MMID': 'BOARD', 'QTYPM': '1'})
    else:
        next(r for r in t['Item'] if r['IID'] == 'BOARD')['TYPE'] = 'LRU'
    with pytest.raises(ModelError):
        compile_model(t)


def test_healthy_sibling_clock_not_resampled():
    env = simpy.Environment()
    c = Components({'P': [{'iid': 'A', 'quantity': 1, 'rate': .2}, {'iid': 'B', 'quantity': 1, 'rate': .1}]})
    parent = c.create('P', 'installed')
    values = iter([1.0, 2.0])
    class Clock:
        def exponential(self, mean): return next(values)
    asset = {'slots': [{'token': parent, 'rate': .3, 'envf': 1}], 'mission': None, 'assignment_event': env.event()}
    process = env.process(c.failure(env, asset, {'util': 1}, Clock(), False))
    env.run(until=process)
    assert env.now == 5
    first, sibling = c.records[parent]['children']
    assert process.value[1] == first
    assert c.records[sibling]['budget'] == pytest.approx(1.5)
    c.fail(parent, first)
    index = c.detach(parent, first)
    c.restore(first)
    c.attach(parent, index, first)
    c.restore(parent)
    assert c.records[sibling]['budget'] == pytest.approx(1.5)


def test_attached_child_moves_with_parent_and_cannot_be_double_installed():
    c = Components({'P': [{'iid': 'A', 'quantity': 2}]})
    parent = c.create('P', 'stock', 'BASE')
    c.move(parent, 'transport', 'DEPOT')
    child = c.records[parent]['children'][0]
    with pytest.raises(AssertionError):
        c.move(child, 'stock', 'BASE')
    rows = c.snapshot()['instances']
    assert all(r['physical_location'] == 'transport' for r in rows)
    assert all(r['site'] == 'DEPOT' for r in rows)
    with pytest.raises(AssertionError):
        c.attach(parent, 1, child)
    c.validate([], [])


def test_layered_seed_repeatability_and_project_roundtrip(tmp_path):
    p = layered_project()
    p['tables']['Control'][0]['NREPS'] = '2'
    config = compile_model(p['tables'])
    assert run_one(config, 0) == run_one(config, 0)
    out = tmp_path/'layered.simproj'
    export_package(p, out)
    assert import_package(out)['tables'] == p['tables']


def test_internal_removal_waits_when_diagnosis_ends_at_shift_close(fixed_failure):
    t = minimal(horizon=22)
    t['TaskResource'] = [{'TID': 'REPLACE', 'RID': 'TECH', 'QTY': '1'}]
    t['Shift'] = [{'SHID': 'W'}]
    t['ShiftProfile'] = [{'SHPID': 'D', 'SSHPID': 'W', 'STIM': '0', 'ETIM': '7'},
                         {'SHPID': 'D', 'SSHPID': 'W', 'STIM': '12', 'ETIM': '30'}]
    t['ResourceStationData'] = [{'RID': 'TECH', 'STID': 'DEPOT', 'SHPID': 'D'}]
    r = run_one(compile_model(t))
    assert next(e['time'] for e in r['events'] if e['event'] == '恢复可用') == 20
    assert r['maintenance']['by_kind']['LRU']['phase_hours']['wait_resource'] == 5


def test_in_progress_turnaround_not_counted_as_completed(fixed_failure):
    r = run_one(compile_model(minimal(horizon=10)))
    job = r['maintenance']['by_kind']['LRU']
    assert job['completed'] == 0 and job['in_progress'] == 1
    assert job['mean_tat'] is None
    assert sum(job['phase_hours'].values()) == 4
