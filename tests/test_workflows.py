import numpy as np
import pytest
import simpy

from simlab.engine import ResourcePool
from simlab.workflows import WorkflowExecutor
from simlab.workflow_config import compile_graph


def graph(shared=False):
    return [dict(id=i, name=i, action='CUSTOM', duration=d, random=False,
                 resources={'R': 1} if shared and i in ('B', 'C') else {}, predecessors=p)
            for i, d, p in [('A', 1, []), ('B', 2, ['A']), ('C', 3, ['A']), ('D', 1, ['B', 'C'])]]


@pytest.mark.parametrize('shared,finish', [(False, 5), (True, 7)])
def test_diamond_elapsed_and_atomic_resources(shared, finish):
    env = simpy.Environment()
    pool = ResourcePool(env, {('S', 'R'): 1})
    runner = WorkflowExecutor(env, pool, {'P': graph(shared)}, np.random.default_rng(1))
    job = runner.start('P', dict(activity='TEST', owner='J1', station='S', asset='A'))
    env.run(until=job['event'])
    assert env.now == finish
    assert pool.free == pool.capacity
    rows = runner.snapshot()['steps']
    assert all(r['status'] == 'completed' for r in rows)
    assert next(r for r in rows if r['step'] == 'D')['started_at'] == finish-1


def test_shift_crossing_and_cutoff_records():
    env = simpy.Environment()
    pool = ResourcePool(env, {('S', 'R'): 1}, {('S', 'R'): [(1, 2), (5, 7)]})
    nodes = graph()[:2]
    nodes[0].update(duration=2, resources={'R': 1})
    nodes[1].update(duration=1, resources={'R': 1})
    runner = WorkflowExecutor(env, pool, {'P': nodes}, np.random.default_rng(1))
    job = runner.start('P', dict(activity='TEST', owner='J', station='S'))
    env.run(until=4)
    rows = runner.snapshot()['steps']
    assert rows[0]['ended_at'] == 3
    assert rows[0]['wait_shift_hours'] == 1
    assert rows[1]['status'] == 'waiting'
    assert rows[1]['ended_at'] is None
    env.run(until=job['event'])
    assert env.now == 6
    assert runner.snapshot()['steps'][1]['wait_shift_hours'] == 2


def test_zero_duration_settles_before_external_departure():
    env = simpy.Environment()
    runner = WorkflowExecutor(env, ResourcePool(env, {}), {'P': [dict(n, duration=0) for n in graph()]}, np.random.default_rng(1))
    job = runner.start('P', dict(activity='TEST', owner='J', station='S'))
    runner.advance()
    assert job['event'].triggered
    assert all(r['ended_at'] == 0 for r in runner.snapshot()['steps'])


def test_cancel_releases_granted_and_waiting_resources():
    env = simpy.Environment()
    pool = ResourcePool(env, {('S', 'R'): 1})
    runner = WorkflowExecutor(env, pool, {'P': graph(True)}, np.random.default_rng(1))
    job = runner.start('P', dict(activity='TEST', owner='J', station='S'))
    env.run(until=2)
    runner.cancel(job)
    assert pool.free == pool.capacity
    assert not pool.queue
    env.run(until=10)
    assert all(r['status'] in ('completed', 'cancelled') for r in runner.snapshot()['steps'])


@pytest.mark.parametrize('rows,match', [
    ([dict(id='A', predecessors=['B']), dict(id='B', predecessors=['A'])], '循环'),
    ([dict(id='A', predecessors=['A'])], '自身'),
    ([dict(id='A', predecessors=['Z'])], '不存在'),
    ([dict(id='A', predecessors=[]), dict(id='A', predecessors=[])], '重复'),
])
def test_reject_invalid_graph(rows, match):
    assert any(match in e for e in compile_graph('P', rows))


def workflow_tables():
    from tests.test_m3_config import one_leaf_new_service_tables
    tables = one_leaf_new_service_tables()
    tables['SimLabWorkflow'] = [dict(WFID='P', NAME='换件流程')]
    tables['SimLabWorkflowStep'] = [dict(WFID='P', STEPID=i, ACTION=a, DURATION_H='1', PREDECESSORS=p)
        for i,a,p in [('A','REMOVE',''),('B','INSTALL','A'),('C','TEST','B')]]
    tables['SimLabWorkflowBinding'] = [dict(BINDID='B', WFID='P', ACTIVITY='MAINTENANCE', RULEID='POWER-CM', METHOD='REPLACE')]
    return tables


def test_compiler_binds_graph_and_defaults():
    from simlab.compiler import compile_model
    from simlab.workflow_config import bound_plan
    cfg = compile_model(workflow_tables())
    assert bound_plan(cfg, 'MAINTENANCE', 'POWER-CM', 'REPLACE') == 'P'
    assert cfg['workflows']['plans']['P'][0]['random'] is False


@pytest.mark.parametrize('change,match', [
    (lambda t: t['SimLabWorkflowStep'][1].update(PREDECESSORS=''), 'INSTALL必须'),
    (lambda t: t['SimLabWorkflowStep'][0].update(ACTION='CUSTOM'), '缺少必要'),
    (lambda t: t['SimLabWorkflowStep'][2].update(DURATION_H='-1'), 'Non-negative'),
    (lambda t: t['SimLabWorkflowStep'][0].update(PREDECESSORS='C'), '循环'),
    (lambda t: t['SimLabWorkflowBinding'].append(dict(t['SimLabWorkflowBinding'][0], BINDID='B2')), '绑定重复'),
])
def test_compiler_rejects_semantically_invalid_workflow(change, match):
    from simlab.compiler import compile_model, ModelError
    tables = workflow_tables()
    change(tables)
    with pytest.raises(ModelError, match=match):
        compile_model(tables)


def test_prerequisite_wait_does_not_hold_resources():
    env = simpy.Environment()
    pool = ResourcePool(env, {('S', 'R'): 1})
    nodes = [dict(graph()[0], resources={'R': 1})]
    runner = WorkflowExecutor(env, pool, {'P': nodes}, np.random.default_rng(1))
    def before(action, node):
        yield env.timeout(3)
    job = runner.start('P', dict(activity='TEST', owner='J', station='S'), before=before)
    env.run(until=2)
    assert pool.free == pool.capacity
    env.run(until=job['event'])
    assert env.now == 4
    assert runner.snapshot()['steps'][0]['wait_prerequisite_hours'] == 3
