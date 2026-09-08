import copy
import pytest
import simpy
from simlab.missions import MissionManager
from simlab.compiler import compile_model, ModelError
from simlab.sample import mission_project
from simlab.project import new_project, save_project, load_project, export_package, import_package
from simlab.duty import daily_plan
from simlab.engine import simulate
from simlab.sample import duty_project


def setup(count=3, tasks=None):
    env = simpy.Environment()
    assets = [dict(id=str(i), sid='S', unit='U', home='H', state='available',
                   mission=None, assignment_event=env.event()) for i in range(count)]
    tasks = tasks or [dict(id='T', start=0, end=8, quantity=2, minimum=2, priority=1,
                          relief_hours=.5, tolerance_hours=.5, sid='S', location='U')]
    return env, assets, MissionManager(env, tasks, assets)


def test_relief_exact_hours_and_tolerance_boundary():
    env, assets, manager = setup()
    env.run(until=2)
    assets[0]['state'] = 'waiting_spare'
    manager.rebalance()
    assert assets[2]['mission'] is None
    assert '2' in manager.pending
    env.run(until=8)
    manager.rebalance()
    result = manager.finish()
    assert result['supplied_hours'] == 15.5
    assert result['gap_hours'] == .5
    assert result['gap_reasons']['relief'] == .5
    assert result['minimum_rate'] == 7.5/8
    assert result['qualified_rate'] == 1
    assert result['tasks'][0]['longest_below_hours'] == .5
    assert result['intervals'][0]['start'] == 2
    assert result['intervals'][0]['end'] == 2.5
    assert not manager.pending
    assert all(a['mission'] is None for a in assets)
    manager.tasks[0]['tolerance_hours'] = .25
    assert manager.finish()['qualified_rate'] == 0


def test_late_relief_does_not_extend_end_or_steal_next_window():
    tasks = [dict(id='T', start=0, end=4, quantity=1, relief_hours=2, sid='S', location='U'),
             dict(id='NEXT', start=4, end=8, quantity=1, sid='S', location='U')]
    env, assets, m = setup(2, tasks)
    env.run(until=3)
    assets[0]['state'] = 'waiting_spare'
    m.rebalance()
    env.run(until=5.5)
    assert assets[1]['mission'] == 'NEXT'
    assert not m.pending
    env.run(until=8)
    m.rebalance()
    result = m.finish()
    assert [t['supplied_hours'] for t in result['tasks']] == [3, 4]
    assert result['gap_hours'] == 1


def test_priority_orders_free_assets_without_preemption():
    tasks = [dict(id='LOW', start=0, end=4, quantity=1, priority=5, sid='S', location='U'),
             dict(id='HIGH', start=0, end=8, quantity=1, priority=1, sid='S', location='U'),
             dict(id='URGENT', start=2, end=8, quantity=1, priority=0, sid='S', location='U')]
    env, assets, m = setup(1, tasks)
    env.run(until=3)
    assert assets[0]['mission'] == 'HIGH'
    env.run(until=8)
    r = m.finish()
    assert [t['supplied_hours'] for t in r['tasks']] == [0, 8, 0]


def test_continuous_shortage_survives_samples_but_recovery_breaks_it():
    env, assets, m = setup(2)
    env.run(until=1)
    assets[0]['state'] = 'waiting_spare'
    m.rebalance()
    for time in (2, 3):
        env.run(until=time)
        m.rebalance()
    assets[0]['state'] = 'available'
    m.rebalance()
    env.run(until=5)
    assets[0]['state'] = 'waiting_spare'
    m.rebalance()
    env.run(until=6)
    assets[0]['state'] = 'available'
    m.rebalance()
    env.run(until=8)
    r = m.finish()
    assert r['tasks'][0]['longest_below_hours'] == 2.5
    assert r['below_hours'] == 4


def test_minimum_distinct_from_target_and_weighted_rates():
    tasks = [dict(id='T', start=0, end=4, quantity=2, minimum=1, sid='S', location='U'),
             dict(id='U', start=4, end=6, quantity=2, minimum=2, sid='S', location='U')]
    env, assets, m = setup(1, tasks)
    env.run(until=6)
    r = m.finish()
    assert r['fulfillment'] == .5
    assert r['minimum_rate'] == pytest.approx(4/6)
    assert r['qualified_rate'] == .5


@pytest.mark.parametrize('field,value', [('MIN_QTY','0'),('MIN_QTY','16'),('PRIORITY','0'),
                                       ('PRIORITY','1.5'),('RELIEF_H','-1'),('TOLERANCE_H','nan')])
def test_invalid_rules_rejected(field, value):
    tables = mission_project()['tables']
    tables['SimLabDutyRule'] = [dict(MTID='DUTY', MIN_QTY='12', PRIORITY='1', RELIEF_H='.5', TOLERANCE_H='.25')]
    tables['SimLabDutyRule'][0][field] = value
    with pytest.raises(ModelError):
        compile_model(tables)


def test_legacy_defaults_and_version_upgrade(tmp_path):
    project = mission_project()
    project['extensions_version'] = 1
    config = compile_model(project['tables'])
    assert config['missions'][0]['minimum'] == 15
    assert config['missions'][0]['relief_hours'] == 0
    save_project(project, tmp_path/'old.sqlite')
    assert load_project(tmp_path/'old.sqlite')['extensions_version'] == 4
    project['tables']['SimLabDutyRule'] = [dict(MTID='DUTY', MIN_QTY='12')]
    export_package(project, tmp_path/'duty.simproj')
    restored = import_package(tmp_path/'duty.simproj')
    assert compile_model(restored['tables'])['missions'][0]['minimum'] == 12


def test_daily_plan_preview_atomic_and_conflicts():
    tables = mission_project()['tables']
    before = copy.deepcopy(tables)
    candidate, windows, conflicts = daily_plan(tables, 'NEW', 'VEHICLE', 'FLEET', 2, 3, 10, 18, 10, 8, 1, .5, .25)
    assert tables == before
    assert [t['start'] for t in windows] == [34, 58, 82]
    assert [t['end'] for t in windows] == [42, 66, 90]
    assert conflicts == 3
    assert len(compile_model(candidate)['missions']) == 33
    with pytest.raises(ValueError):
        daily_plan(candidate, 'NEW', 'VEHICLE', 'FLEET', 1, 1, 8, 16, 10, 8, 1, 0, 0)
    with pytest.raises(ModelError):
        daily_plan(tables, 'OUTSIDE', 'VEHICLE', 'FLEET', 30, 2, 8, 16, 10, 8, 1, 0, 0)
    assert tables == before


def test_shared_profile_is_branched_only_for_selected_location():
    tables = mission_project()['tables']
    tables['Operations'].append(dict(USTID='BASE', PRID='DAILY'))
    candidate, windows, _ = daily_plan(tables, 'EXTRA', 'VEHICLE', 'FLEET', 1, 1, 18, 20, 2, 1, 1, 0, 0)
    missions = compile_model(candidate)['missions']
    assert len([t for t in missions if t['location'] == 'BASE']) == 30
    assert len([t for t in missions if t['location'] == 'FLEET']) == 31
    assert len(windows) == 1
    assert next(r for r in candidate['Operations'] if r['USTID'] == 'BASE')['PRID'] == 'DAILY'


def test_duty_reproducibility_and_result_package(tmp_path):
    project = duty_project()
    project['tables']['Control'][0]['NREPS'] = '2'
    first = simulate(project['tables'])
    second = simulate(project['tables'])
    assert first['mission'] == second['mission']
    assert first['availability'] == second['availability']
    assert all(s['minimum'] <= s['demand'] for s in first['samples'])
    assert 0 <= first['mission']['qualified_rate'] <= 1
    assert first['mission']['minimum_rate'] >= first['mission']['full_window_rate']
    assert first['replication_results'][1]['mission']['intervals'] == []
    project['runs'].append(dict(id='run', status='completed', result=first))
    export_package(project, tmp_path/'result.simproj')
    assert import_package(tmp_path/'result.simproj')['runs'][0]['result']['mission'] == first['mission']


def test_cancelled_reservation_cannot_complete_after_new_assignment():
    env, assets, m = setup(3)
    env.run(until=2)
    assets[0]['state'] = 'waiting_spare'
    m.rebalance()
    env.run(until=2.2)
    assets[2]['state'] = 'waiting_resource'
    m.rebalance()
    assert '2' not in m.pending
    assets[0]['state'] = 'available'
    m.rebalance()
    env.run(until=2.6)
    assert assets[0]['mission'] is None
    assert assets[2]['mission'] is None
    env.run(until=2.8)
    assert assets[0]['mission'] == 'T'
    assert assets[2]['mission'] is None


def test_unknown_extension_version_cannot_be_exported_as_current(tmp_path):
    project = duty_project()
    project['extensions_version'] = 99
    with pytest.raises(ValueError):
        export_package(project, tmp_path/'unknown.simproj')
    assert not (tmp_path/'unknown.simproj').exists()
