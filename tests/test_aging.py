import math

import pytest

from simlab.aging import remaining_age, risk_increment
from simlab.compiler import compile_model, ModelError
from test_maintenance import minimal
from simlab.engine import run_one
from simlab.engine import simulate
from test_inspection import inspection_tables


def aging_tables(**overrides):
    tables = minimal()
    next(r for r in tables['Item'] if r['IID'] == 'BOARD')['FRT'] = '0'
    tables['SimLabItemAging'] = [dict(IID='BOARD', SHAPE='2', SCALE_H='100', INITIAL_H='60', **overrides)]
    return tables


def test_compiles_default_perfect_repair():
    rule = compile_model(aging_tables())['aging']['BOARD']
    assert rule == dict(shape=2., scale=100., initial=60., repair='PERFECT', application=1.)


@pytest.mark.parametrize('field,value', [('SHAPE','0'), ('SHAPE','11'), ('SCALE_H','0'),
    ('SCALE_H','nan'), ('INITIAL_H','inf'), ('REPAIR','BAD'), ('IID','POWER')])
def test_rejects_invalid_aging_input(field, value):
    tables = aging_tables()
    tables['SimLabItemAging'][0][field] = value
    with pytest.raises(ModelError):
        compile_model(tables)


def test_rejects_conflicting_failure_rate():
    tables = aging_tables()
    next(r for r in tables['Item'] if r['IID'] == 'BOARD')['FRT'] = '1'
    with pytest.raises(ModelError, match='FRT'):
        compile_model(tables)


@pytest.mark.parametrize('age,shape,budget,multiplier,expected', [
    (60, 1, .4, 1, 40),
    (60, 2, .64, 1, 40),
    (0, 2, .64, 1, 80),
    (60, 2, 1.28, 2, 40),
    (100, 2, 1.25, 1, 50),
    (0, 2, 1.25, 1, 111.80339887498948),
])
def test_conditional_lifetime_analytic(age, shape, budget, multiplier, expected):
    assert remaining_age(age, shape, 100, budget, multiplier) == pytest.approx(expected)


def test_consumed_hazard_independent_analytic_value():
    assert risk_increment(60, 40, 2, 100, 1) == pytest.approx(.64)
    assert risk_increment(60, 40, 2, 100, 2) == pytest.approx(1.28)


def test_zero_risk_has_no_failure():
    assert remaining_age(60, 2, 100, 1, 0) == math.inf
    assert risk_increment(60, 40, 2, 100, 0) == 0


def test_tiny_budget_at_large_age_does_not_cancel_to_zero():
    # Quadratic hazard derivative is 2a/scale^2 = 2 at this point.
    assert remaining_age(1e12, 2, 1e6, 1e-12, 1) == pytest.approx(5e-13, rel=1e-12, abs=0)
    assert risk_increment(1e12, 5e-13, 2, 1e6, 1) == pytest.approx(1e-12, rel=1e-12, abs=0)


def test_layered_age_settles_at_horizon_without_failure():
    result = run_one(compile_model(aging_tables()))
    board = next(r for r in result['aging']['instances'] if r['iid'] == 'BOARD')
    assert board['age'] == pytest.approx(76)
    assert board['lifetime_hours'] == pytest.approx(76)


@pytest.mark.parametrize('repair,expected', [('PERFECT', 0), ('MINIMAL', 100)])
def test_real_repair_updates_failed_leaf_age(monkeypatch, repair, expected):
    class FixedBudget:
        def exponential(self, mean):
            return .64
    monkeypatch.setattr('simlab.engine.np.random.default_rng', lambda seed: FixedBudget())
    tables = aging_tables(REPAIR=repair)
    tables['Control'][0]['SIMPE'] = '55'
    result = run_one(compile_model(tables))
    events = result['aging']['events']
    failure = next(e for e in events if e['event'] == 'failure')
    repaired = next(e for e in events if e['event'] == 'repair')
    assert failure['time'] == pytest.approx(40)
    assert failure['age_before'] == pytest.approx(100)
    assert repaired['age_before'] == pytest.approx(100)
    assert repaired['age_after'] == pytest.approx(expected)
    assert repaired['lifetime_hours'] == pytest.approx(100)


def test_direct_lru_inspections_do_not_reset_age():
    tables = inspection_tables()
    iid = tables['Item'][0]['IID']
    tables['SimLabItemAging'] = [dict(IID=iid, SHAPE='2', SCALE_H='100', INITIAL_H='60')]
    for row in tables['Item']:
        row['FRT'] = '0'
        row['AFFRT'] = '0'
    result = simulate(tables)
    assert 'aging' in result
    for rep in result['replication_results']:
        clocks = rep['mission']['planned']['clocks']
        assert any(c['completed_checks'] for c in clocks)
        rows = [r for r in rep['aging']['instances'] if r['iid'] == iid and r['location'] == 'installed']
        assert len(rows) == len(clocks)
        for row, clock in zip(rows, clocks):
            assert row['age'] == pytest.approx(60 + clock['flown_hours'])


def test_age_csv_exports_all_replications(tmp_path):
    import csv
    from simlab.flight_results import export_aging
    tables = aging_tables()
    tables['Control'][0]['NREPS'] = '2'
    result = simulate(tables)
    run = dict(id='age', model_hash=result['model_hash'], result=result)
    export_aging(run, tmp_path / 'ages.csv')
    with (tmp_path / 'ages.csv').open(encoding='utf-8-sig', newline='') as f:
        rows = list(csv.DictReader(f))
    assert {r['replication'] for r in rows} == {'1', '2'}
    assert all(r['model_hash'] == result['model_hash'] for r in rows)


def test_rejects_excessive_aging_event_rate():
    tables = aging_tables()
    tables['SimLabItemAging'][0].update(SCALE_H='0.000001', INITIAL_H='0')
    with pytest.raises(ModelError, match='规模'):
        compile_model(tables)


def test_util_scales_age_but_zero_risk_does_not_stop_age():
    tables = aging_tables()
    tables['SystemDeployment'][0]['UTIL'] = '.5'
    next(r for r in tables['Item'] if r['IID'] == 'BOARD')['AFFRT'] = '0'
    result = run_one(compile_model(tables))
    board = result['aging']['instances'][0]
    assert board['age'] == 68
    assert not result['aging']['events']


def test_initial_stock_is_new_and_healthy_sibling_keeps_age(monkeypatch):
    class FixedBudget:
        def exponential(self, mean):
            return .64
    monkeypatch.setattr('simlab.engine.np.random.default_rng', lambda seed: FixedBudget())
    tables = aging_tables()
    tables['Control'][0]['SIMPE'] = '55'
    tables['Item'].append(dict(IID='HEALTHY', TYPE='SRU', FRT='0', AFFRT='0'))
    tables['MaterielStructure'].append(dict(MMID='POWER', MID='HEALTHY', QTYPM='1', ENVF='1'))
    tables['ItemRepair'].append(dict(IID='HEALTHY', STID='DEPOT', DIRPT='4', SURPT='0'))
    tables['ItemReplacement'].append(dict(MID='POWER', IID='HEALTHY', STID='DEPOT', SURPT='2'))
    tables['SimLabItemAging'].append(dict(IID='HEALTHY', SCALE_H='100', INITIAL_H='200'))
    tables['StockAllocation'][1]['STSIZ'] = '1'
    result = run_one(compile_model(tables))
    rows = result['aging']['instances']
    sibling = next(r for r in rows if r['iid'] == 'HEALTHY')
    assert sibling['age'] > 240
    assert not any(e['iid'] == 'HEALTHY' for e in result['aging']['events'])
    boards = [r for r in rows if r['iid'] == 'BOARD']
    assert len(boards) == 2
    assert any(r['age'] < 10 and r['lifetime_hours'] < 10 for r in boards)


def test_tiny_initial_age_does_not_produce_nan():
    assert risk_increment(1e-320, 100, 2, 100, 1) == pytest.approx(1)
    assert remaining_age(1e-150, 2, 100, 1, 1) == pytest.approx(100)


def test_actual_simpy_assignment_pauses_preserve_budget_and_age():
    import simpy
    from simlab.aging_components import AgingComponents
    env = simpy.Environment()
    parts = AgingComponents({}, {'L':dict(shape=2, scale=100, initial=60, repair='PERFECT', application=1)}, env)
    token = parts.create('L', 'installed')
    asset = dict(id='A', slots=[dict(iid='L', token=token, envf=1, rate=0)], mission='flight', assignment_event=env.event())
    class FixedBudget:
        def exponential(self, mean):
            return .64
    done = []
    def operate():
        yield from parts.failure(env, asset, {'util':.5}, FixedBudget(), True)
        done.append(env.now)
    def schedule():
        yield env.timeout(20)
        asset['mission'] = None
        old = asset['assignment_event']; asset['assignment_event'] = env.event(); old.succeed()
        yield env.timeout(100)
        asset['mission'] = 'flight'
        old = asset['assignment_event']; asset['assignment_event'] = env.event(); old.succeed()
    env.process(operate()); env.process(schedule())
    env.run(until=181)
    assert done == pytest.approx([180])
    assert parts.records[token]['age'] == pytest.approx(100)


def test_two_failed_srus_in_same_returned_lru_are_both_repaired():
    import simpy
    import numpy as np
    from simlab.aging_components import AgingComponents
    from simlab.maintenance import Workshop
    from simlab.engine import ResourcePool
    tables = aging_tables()
    next(r for r in tables['MaterielStructure'] if r['MID'] == 'BOARD')['QTYPM'] = '2'
    config = compile_model(tables)
    env = simpy.Environment()
    parts = AgingComponents(config['children'], config['aging'], env)
    parent = parts.create('POWER', 'installed', 'BASE')
    for child in parts.records[parent]['children']:
        parts.fail(parent, child)
    stores = {}
    def store(station, iid):
        return stores.setdefault((station, iid), simpy.Store(env))
    shop = Workshop(env, config, parts, ResourcePool(env, config['capacity']), store,
                    np.random.default_rng(1), lambda *args: None)
    env.process(shop.repair(config['fleets'][0], 'POWER', parent))
    env.run(until=30)
    assert parts.locations[parent] == 'stock'
    assert all(not parts.records[c]['broken'] and parts.records[c]['age'] == 0 for c in parts.records[parent]['children'])


def test_repeated_failure_trajectories_differ_after_repair(monkeypatch):
    class FixedBudget:
        def exponential(self, mean):
            return .64
    monkeypatch.setattr('simlab.engine.np.random.default_rng', lambda seed: FixedBudget())
    times = {}
    for mode in ('PERFECT', 'MINIMAL'):
        tables = aging_tables(REPAIR=mode)
        tables['Control'][0]['SIMPE'] = '140'
        result = run_one(compile_model(tables))
        times[mode] = [e['time'] for e in result['aging']['events'] if e['event']=='failure']
    assert times['PERFECT'] == pytest.approx([40,130])
    assert times['MINIMAL'][0] == pytest.approx(40)
    assert times['MINIMAL'][1] == pytest.approx(78.06248474865697)


def test_format8_readable_but_format8_reader_rejects_aging(monkeypatch):
    import simlab.project as project
    old = project.new_project()
    old['extensions_version'] = 8
    project.check_structure(old)
    new = project.new_project()
    new['tables'] = aging_tables()
    monkeypatch.setattr(project, 'EXTENSIONS_VERSION', 8)
    with pytest.raises(ValueError, match='扩展格式版本'):
        project.check_structure(new)
