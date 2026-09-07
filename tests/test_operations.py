import pytest
import simpy

from simlab.sample import mission_project
from simlab.compiler import compile_model, ModelError
from simlab.engine import run_one, simulate, ResourcePool
from simlab.missions import MissionManager
from simlab.project import save_project, load_project, export_package, import_package


def model(quantity=2, demand=2, start=2, duration=4, horizon=12):
    p = mission_project()
    t = p['tables']
    t['Control'][0].update(SIMPE=str(horizon), RCINT='1', NREPS='2')
    t['SystemDeployment'][0]['QTYPS'] = str(quantity)
    for item in t['Item']:
        item['FRT'] = '0'
    t['MissionType'][0].update(NOS=str(demand), MNOS=str(demand), DURN=str(duration))
    t['OperationProfile'] = [{'PRID': 'DAILY', 'SPRID': 'DUTY', 'STIM': str(start)}]
    t['ShiftProfile'] = [{'SHPID': 'DAY', 'SSHPID': 'WORK', 'STIM': '0', 'ETIM': str(horizon)}]
    return p


@pytest.mark.parametrize('quantity,demand,expected', [(2, 2, 1), (1, 2, .5), (3, 2, 1)])
def test_capacity_hours_analytic(quantity, demand, expected):
    result = simulate(model(quantity, demand)['tables'])
    m = result['mission']
    assert m['fulfillment'] == expected
    assert m['demand_hours'] == demand * 4
    assert m['supplied_hours'] == min(quantity, demand) * 4
    assert m['gap_hours'] == (demand - min(quantity, demand)) * 4
    assert sum(m['gap_reasons'].values()) == m['gap_hours']
    assert result['availability'] == 1


def test_overlapping_tasks_fcfs_no_double_assignment():
    p = model(1, 1, 0, 6)
    p['tables']['OperationProfile'].append({'PRID': 'DAILY', 'SPRID': 'DUTY', 'STIM': '2'})
    m = run_one(compile_model(p['tables']))['mission']
    assert [r['supplied_hours'] for r in m['tasks']] == [6, 2]
    assert m['demand_hours'] == 12
    assert m['gap_reasons']['busy'] == 4
    assert m['full_window_rate'] == .5


def test_handoff_and_horizon_end_are_exact():
    p = model(1, 1, 0, 6)
    p['tables']['OperationProfile'].append({'PRID': 'DAILY', 'SPRID': 'DUTY', 'STIM': '6'})
    m = simulate(p['tables'])['mission']
    assert m['fulfillment'] == 1
    assert m['full_window_rate'] == 1
    assert m['gap_hours'] == 0


def test_standby_does_not_accumulate_failures():
    p = model(1, 1, 10, 2)
    for item in p['tables']['Item']:
        item['FRT'] = '100000'
    r = run_one(compile_model(p['tables']))
    assert all(e['time'] >= 10 for e in r['events'] if e['event'] == '发生故障')


def test_failure_replacement_and_exact_gap_reason():
    env = simpy.Environment()
    assets = [{'id': str(i), 'sid': 'S', 'unit': 'U', 'home': 'H', 'state': 'available',
               'mission': None, 'assignment_event': env.event()} for i in range(2)]
    tasks = [{'id': 'T', 'start': 0, 'end': 8, 'quantity': 1, 'sid': 'S', 'location': 'U'}]
    m = MissionManager(env, tasks, assets)
    env.run(until=2)
    assets[0]['state'] = 'waiting_spare'
    m.rebalance()
    assert assets[1]['mission'] == 'T'
    env.run(until=3)
    assets[1]['state'] = 'waiting_resource'
    m.rebalance()
    env.run(until=5)
    assets[0]['state'] = 'available'
    m.rebalance()
    env.run(until=8)
    result = m.finish()
    assert result['supplied_hours'] == 6
    assert result['gap_hours'] == 2
    assert sum(result['gap_reasons'].values()) == 2
    assert result['full_window_rate'] == 0


def test_resource_shift_gate_allows_overtime_but_no_new_start():
    env = simpy.Environment()
    pool = ResourcePool(env, {('H', 'R'): 1}, {('H', 'R'): [(2, 4), (8, 10)]})
    starts, ends = [], []
    def job(duration):
        yield pool.request('H', {'R': 1})
        starts.append(env.now)
        yield env.timeout(duration)
        ends.append(env.now)
        pool.release('H', {'R': 1})
    env.process(job(4))
    env.process(job(1))
    env.run(until=12)
    assert starts == [2, 8]
    assert ends == [6, 9]
    assert pool.free[('H', 'R')] == 1


def test_bundle_requires_common_shift_opening():
    env = simpy.Environment()
    pool = ResourcePool(env, {('H', 'A'): 1, ('H', 'B'): 1},
                        {('H', 'A'): [(1, 7)], ('H', 'B'): [(3, 9)]})
    event = pool.request('H', {'A': 1, 'B': 1})
    env.run(until=event)
    assert env.now == 3
    assert all(v == 0 for v in pool.free.values())


@pytest.mark.parametrize('table,key,val', [
    ('MissionType', 'DURN', '0'), ('MissionType', 'MPAT', 'EXTENDABLE'),
    ('MissionType', 'MNOS', '1'), ('MissionType', 'PRI', '2'),
    ('OperationProfile', 'IQTY', '2'), ('OperationProfile', 'STIM', '11'),
    ('ShiftProfile', 'ETIM', '0'), ('SystemDeployment', 'UTIL', '.5')])
def test_unsupported_or_ambiguous_rules_rejected(table, key, val):
    p = model()
    p['tables'][table][0][key] = val
    with pytest.raises(ModelError):
        compile_model(p['tables'])


def test_calendar_roundtrip_results_reproducible(tmp_path):
    p = model()
    for item in p['tables']['Item']:
        item['FRT'] = '50000'
    config = compile_model(p['tables'])
    assert run_one(config, 0) == run_one(config, 0)
    path = tmp_path / 'mission.sqlite'
    save_project(p, path)
    package = tmp_path / 'mission.simproj'
    export_package(load_project(path), package)
    assert import_package(package)['tables'] == p['tables']


def test_no_common_shift_rejected():
    p = model()
    p['tables']['ShiftProfile'].append({'SHPID': 'NIGHT', 'SSHPID': 'WORK', 'STIM': '10', 'ETIM': '12'})
    p['tables']['ShiftProfile'][0]['ETIM'] = '4'
    p['tables']['ResourceStationData'].append({'RID': 'BAY', 'STID': 'DEPOT', 'SHPID': 'NIGHT'})
    with pytest.raises(ModelError, match='共同班次'):
        compile_model(p['tables'])


def test_long_calendar_never_reschedules_exhausted_failure_clock(monkeypatch):
    original = simpy.events.Timeout.__init__
    def checked_timeout(self, env, delay, value=None):
        assert not (delay > 0 and env.now + delay == env.now), 'exhausted failure clock'
        original(self, env, delay, value)
    monkeypatch.setattr(simpy.events.Timeout, '__init__', checked_timeout)
    p = mission_project()
    p['tables']['MissionType'][0].update(NOS='22', MNOS='22')
    p['tables']['Control'][0]['NREPS'] = '3'
    result = simulate(p['tables'])
    assert result['mission']['gap_hours'] >= 480
    assert 0 < result['mission']['fulfillment'] < 1


def test_operating_failure_budget_survives_standby(monkeypatch):
    class FixedClock:
        def exponential(self, mean):
            return 3.0
        def choice(self, count, p):
            return 0
    monkeypatch.setattr('simlab.engine.np.random.default_rng', lambda seed: FixedClock())
    p = model(1, 1, 0, 2)
    p['tables']['Item'][0]['FRT'] = '10000'
    p['tables']['OperationProfile'].append({'PRID': 'DAILY', 'SPRID': 'DUTY', 'STIM': '10'})
    r = run_one(compile_model(p['tables']))
    failures = [e for e in r['events'] if e['event'] == '发生故障']
    assert [e['time'] for e in failures] == [11.0]
    assert r['mission']['supplied_hours'] == 3


def test_unrelated_system_cannot_supply_task():
    env = simpy.Environment()
    assets = [{'id': 'wrong-system', 'sid': 'OTHER', 'unit': 'U', 'home': 'H',
               'state': 'available', 'mission': None, 'assignment_event': env.event()}]
    m = MissionManager(env, [{'id': 'T', 'start': 0, 'end': 4, 'quantity': 1, 'sid': 'S', 'location': 'U'}], assets)
    env.run(until=4)
    r = m.finish()
    assert r['supplied_hours'] == 0
    assert r['gap_reasons']['fleet_shortage'] == 4
