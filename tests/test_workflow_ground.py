import numpy as np
from test_ground import scene
from test_workflows import graph
from simlab.workflows import WorkflowExecutor


def setup(starts=(9, 16), prep=5, daily_ready=True):
    env, assets, manager, pool = scene(starts=starts, duration=2, prep=prep, count=2,
                                       groups=2, daily_ready=daily_ready)
    for p in manager.pools.values():
        p['ground_rule']['workflow_plan'] = 'P'
    manager.workflow_runner = WorkflowExecutor(env, pool, {'P': graph()}, np.random.default_rng(1))
    return env, assets, manager, pool


def test_preparation_dag_finishes_at_exact_departure():
    env, assets, manager, pool = setup()
    env.run(until=16.01)
    assert manager.tasks[1]['flight_status'] == 'launched'
    workflows = manager.workflow_runner.snapshot()
    assert len(workflows['steps']) == 8
    assert {a['elapsed_hours'] for a in workflows['activities']} == {5}
    assert manager.ground.snapshot()['completed_jobs'] == 2


def test_workflow_duration_replaces_single_prep_work_time():
    env, assets, manager, pool = setup(starts=(9, 15), prep=.5)
    env.run(until=15.01)
    assert manager.tasks[1]['flight_status'] == 'cancelled'
    assert len(manager.workflow_runner.snapshot()['steps']) == 8


def test_daily_ready_cancels_whole_workflow_cleanly():
    env, assets, manager, pool = setup(starts=(9,33), prep=30)
    for node in manager.workflow_runner.plans['P']:
        node['duration'] = 30
        node['resources'] = {'CREW': 1}
    env.run(until=33.01)
    assert manager.tasks[1]['flight_status'] == 'launched'
    assert pool.free == pool.capacity
    assert not pool.queue
    assert len(manager.workflow_runner.jobs) == 2
    assert all(j['status'] == 'cancelled' for j in manager.workflow_runner.jobs)


def test_calendar_dag_holds_aircraft_and_serializes_next_activity():
    from test_planned import scene as planned_scene
    env, assets, manager, pool = planned_scene(due=(9, 10), starts=(9, 20), duration=.1)
    for entry in manager.planned.schedule:
        entry[3]['workflow_plan'] = 'P'
    manager.workflow_runner = WorkflowExecutor(env, pool, {'P': graph()}, np.random.default_rng(1))
    env.run(until=19.01)
    jobs = manager.planned.snapshot()['jobs']
    assert [j['ended_at'] for j in jobs] == [14, 14, 19, 19]
    assert manager.tasks[0]['flight_status'] == 'cancelled'
    assert len(manager.workflow_runner.snapshot()['steps']) == 16
    assert all(a['flight_phase'] == 'preparing' for a in assets)
    env.run(until=19.51)
    assert pool.free == pool.capacity
