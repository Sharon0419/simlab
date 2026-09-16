import numpy as np
import pytest

from simlab.compiler import compile_model, ModelError
from simlab.workflows import WorkflowExecutor
from test_ground import ground_tables, scene


def bound_tables(activity, task='IMPOSSIBLE', duration='0.5'):
    tables = ground_tables()
    tables['Tasks'].append(dict(TID='IMPOSSIBLE'))
    tables['TaskResource'].append(dict(TID='IMPOSSIBLE', RID='CREW', QTY='999'))
    rule = tables['SimLabFlightRule'][0]['MTID']
    if activity == 'PREPARATION':
        tables['SimLabFlightRule'][0]['PREP_TASK'] = task
    else:
        rule = 'CHECK'
        target = dict(SID=tables['System'][0]['SID'], USTID=tables['SystemDeployment'][0]['USTID'],
                      TASK=task, DURATION_H=duration, INTERVAL_H='1')
        if activity == 'CALENDAR':
            tables['SimLabPlannedMaintenance'] = [dict(target, PMID=rule, FIRST_H='1')]
        else:
            tables['SimLabFlightInspection'] = [dict(target, CHECKID=rule)]
    tables['SimLabWorkflow'] = [dict(WFID='P', NAME='workflow')]
    tables['SimLabWorkflowStep'] = [dict(WFID='P', STEPID='A', ACTION='CUSTOM', DURATION_H='.1')]
    tables['SimLabWorkflowBinding'] = [dict(BINDID='B', WFID='P', ACTIVITY=activity, RULEID=rule)]
    return tables


@pytest.mark.parametrize('activity', ['PREPARATION', 'CALENDAR', 'INSPECTION'])
def test_bound_ground_check_ignores_superseded_resource_demand(activity):
    assert compile_model(bound_tables(activity))['workflows']['bindings']


@pytest.mark.parametrize('activity', ['CALENDAR', 'INSPECTION'])
def test_bound_check_uses_workflow_duration_but_keeps_periodic_clock(activity):
    cfg = compile_model(bound_tables(activity, duration='0'))
    rule = cfg['planned'][0]
    assert rule['workflow_plan'] == 'P'
    assert rule.get('flight_interval', 1) == 1
    if activity == 'CALENDAR':
        assert rule['due_times'][:2] == [1, 2]


def runner_scene(nodes, shifts, until):
    env, assets, manager, pool = scene(starts=(9,), duration=2, groups=2, shifts=shifts)
    for p in manager.pools.values():
        p['ground_rule']['workflow_plan'] = 'P'
    manager.workflow_runner = WorkflowExecutor(env, pool, {'P': nodes}, np.random.default_rng(1))
    env.run(until=until)
    manager.rebalance()
    return manager, pool


def step(name, duration, predecessors=(), resource='CREW'):
    return dict(id=name, name=name, action='CUSTOM', duration=duration, random=False,
                resources={resource: 1} if resource else {}, predecessors=list(predecessors))


def test_workflow_preparation_shift_wait_matches_step_details():
    manager, pool = runner_scene([step('A', .5)], {('H', 'CREW'): [(12, 15)]}, 13)
    ground = manager.ground.snapshot()
    assert ground['wait_aircraft_hours'] == 2
    assert ground['wait_shift_aircraft_hours'] == 2
    assert ground['wait_resource_aircraft_hours'] == 0
    assert ground['work_aircraft_hours'] == 1


def test_internal_shift_gap_is_wait_and_parallel_work_is_union_at_cutoff():
    nodes = [step('A', 1, resource=''), step('B', 2, ['A']), step('C', 3, resource='')]
    manager, pool = runner_scene(nodes, {('H', 'CREW'): [(15, 20)]}, 15.5)
    ground = manager.ground.snapshot()
    # Per aircraft: union work 11..14 and 15..15.5; shift wait 14..15.
    assert ground['work_aircraft_hours'] == 7
    assert ground['wait_aircraft_hours'] == 2
    assert ground['wait_shift_aircraft_hours'] == 2
    assert ground['wait_resource_aircraft_hours'] == 0


def test_workflow_internal_wait_status_and_cancellation_accounting():
    nodes = [step('A', 1, resource=''), step('B', 2, ['A'])]
    manager, pool = runner_scene(nodes, {('H', 'CREW'): [(15, 20)]}, 14)
    ground = manager.ground.snapshot()
    assert ground['waiting_jobs'] == 2 and ground['working_jobs'] == 0
    assert ground['work_aircraft_hours'] == 2
    assert ground['wait_shift_aircraft_hours'] == 4
    for asset in manager.assets:
        manager.ground.assume_ready(asset)
    assert manager.ground.snapshot()['work_aircraft_hours'] == 2
    assert pool.free == pool.capacity and not pool.queue


@pytest.mark.parametrize('activity', ['PREPARATION', 'CALENDAR', 'INSPECTION'])
def test_bound_legacy_task_references_still_validated(activity):
    with pytest.raises(ModelError, match='UNKNOWN'):
        compile_model(bound_tables(activity, task='UNKNOWN'))


@pytest.mark.parametrize('activity', ['PREPARATION', 'CALENDAR', 'INSPECTION'])
def test_bound_no_longer_requires_legacy_task_positive_resources(activity):
    tables = bound_tables(activity)
    tables['TaskResource'] = [r for r in tables['TaskResource'] if r['TID'] != 'IMPOSSIBLE']
    assert compile_model(tables)['workflows']['bindings']


@pytest.mark.parametrize('activity', ['PREPARATION', 'CALENDAR', 'INSPECTION'])
def test_unbound_still_rejects_impossible_legacy_resources(activity):
    tables = bound_tables(activity)
    tables['SimLabWorkflowBinding'] = []
    with pytest.raises(ModelError, match='CREW'):
        compile_model(tables)


def test_planned_internal_gap_uses_same_union_accounting():
    from test_planned import scene as planned_scene
    env, assets, manager, pool = planned_scene(due=(9,), starts=(9, 20), ground=False)
    pool.schedules[('H', 'CREW')] = [(13, 20)]
    env.process(pool.openings())
    for entry in manager.planned.schedule:
        entry[3]['workflow_plan'] = 'P'
    manager.workflow_runner = WorkflowExecutor(env, pool,
        {'P': [step('A', 1, resource=''), step('B', 1, ['A'])]}, np.random.default_rng(1))
    env.run(until=12); manager.rebalance()
    result = manager.planned.snapshot()
    assert result['waiting_jobs'] == 2 and result['working_jobs'] == 0
    assert result['work_aircraft_hours'] == 2 and result['wait_aircraft_hours'] == 4
    env.run(until=14.01); manager.rebalance()
    result = manager.planned.snapshot()
    assert result['completed_jobs'] == 2
    assert result['work_aircraft_hours'] == 4 and result['wait_aircraft_hours'] == 6
    assert pool.free == pool.capacity


@pytest.mark.parametrize('activity', ['PREPARATION', 'CALENDAR', 'INSPECTION'])
def test_bound_activity_ignores_legacy_shift_with_no_opening(activity):
    tables = bound_tables(activity, task='PREP')
    if activity != 'PREPARATION':
        tables['SimLabFlightRule'][0]['PREP_TASK'] = ''
    horizon = float(tables['Control'][0]['SIMPE'])
    tables['Shift'] = [dict(SHID='CLOSED')]
    tables['ShiftProfile'] = [dict(SHPID='LATER', SSHPID='CLOSED', STIM=str(horizon+1), ETIM=str(horizon+2))]
    tables['ResourceStationData'] = [dict(RID='CREW', STID=tables['Unit'][0]['STID'], SHPID='LATER')]
    assert compile_model(tables)['workflows']['bindings']


def test_workflow_shift_and_resource_contention_partition_aircraft_hours():
    env, assets, manager, pool = scene(starts=(9,), duration=2, groups=1,
                                      shifts={('H', 'CREW'): [(12, 15)]})
    for p in manager.pools.values():
        p['ground_rule']['workflow_plan'] = 'P'
    manager.workflow_runner = WorkflowExecutor(env, pool, {'P': [step('A', .5)]}, np.random.default_rng(1))
    env.run(until=13.01); manager.rebalance()
    result = manager.ground.snapshot()
    assert result['wait_shift_aircraft_hours'] == 2
    assert result['wait_resource_aircraft_hours'] == .5
    assert result['wait_aircraft_hours'] == 2.5 and result['work_aircraft_hours'] == 1
