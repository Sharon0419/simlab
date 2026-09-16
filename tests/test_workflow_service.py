import pytest

from tests.test_m3_service import config, rig, add_rule


def bind(cfg, activity, actions, rule='', method='', iid='', station='', kind=''):
    flows = cfg.setdefault('workflows', dict(plans={}, bindings={}))
    name = str(len(flows['plans']))
    flows['plans'][name] = [dict(id=str(i), name=action, action=action, duration=duration,
        random=False, resources={}, predecessors=[str(i-1)] if i else [])
        for i, (action, duration) in enumerate(actions)]
    flows['bindings'][(activity, rule, method, iid, station, kind)] = name
    return flows['plans'][name]


def test_bound_in_place_replaces_legacy_steps_and_counts_once():
    cfg = config()
    bind(cfg, 'MAINTENANCE', [('IN_PLACE', 4), ('TEST', 2)], rule='R', method='IN_PLACE')
    env, parts, part, asset, net, service = rig(cfg)
    parts.fail(part, part)
    job = service.corrective(asset, asset['slots'][0])
    env.run(until=6.01)
    assert job['ended_at'] == 6
    assert not parts.records[part]['broken']
    assert len(service.workflows.snapshot()['steps']) == 2


def test_replace_detaches_once_off_item_continues_independently():
    cfg = config('REPLACE'); cfg['stock'] = {('C', 'L'): 1}
    bind(cfg, 'MAINTENANCE', [('REMOVE', 2), ('INSTALL', 2), ('TEST', 2)], rule='R', method='REPLACE')
    bind(cfg, 'OFF_ITEM', [('DIAGNOSE', 1), ('SERVICE', 12), ('TEST', 1)], iid='L', station='A', kind='CORRECTIVE')
    env, parts, part, asset, net, service = rig(cfg)
    parts.fail(part, part); job = service.corrective(asset, asset['slots'][0])
    env.run(until=6.01)
    assert job['ended_at'] == 6 and asset['slots'][0]['token'] != part
    assert parts.records[part]['broken'] and len(service.jobs) == 2
    env.run(until=16.01)
    assert part in net.available('A', 'L') and service.jobs[1]['ended_at'] == 16
    assert service.pool.free == service.pool.capacity


def test_install_does_not_hold_resources_while_waiting_spare():
    cfg = config('REPLACE'); cfg['capacity'] = {('C', 'TECH'): 1}
    nodes = bind(cfg, 'MAINTENANCE', [('REMOVE', 0), ('INSTALL', 2), ('TEST', 0)], rule='R', method='REPLACE')
    nodes[1]['resources'] = {'TECH': 1}
    env, parts, part, asset, net, service = rig(cfg)
    parts.fail(part, part); job = service.corrective(asset, asset['slots'][0])
    env.run(until=3)
    assert job['status'] == 'waiting_spare'
    assert service.pool.free == service.pool.capacity
    assert service.workflows.snapshot()['steps'][1]['requested_at'] is None


def test_off_parent_service_repairs_child_without_parent_counter():
    cfg = config('REPLACE'); cfg['stock'] = {('C', 'L'): 1}
    cfg['children'] = {'L': [dict(iid='S', quantity=1, rate=0, envf=1)]}
    add_rule(cfg, 'CHILD', 'L', 'S', 'A', 'CORRECTIVE', 'IN_PLACE')
    bind(cfg, 'OFF_ITEM', [('DIAGNOSE', 1), ('SERVICE', 1), ('TEST', 1)], iid='L', station='A', kind='CORRECTIVE')
    env, parts, part, asset, net, service = rig(cfg)
    child = parts.records[part]['children'][0]
    parts.fail(part, child); service.corrective(asset, asset['slots'][0]); env.run(until=7.01)
    assert part in net.available('A', 'L')
    assert service.jobs[1]['ended_at'] == 7
    assert not parts.records[child]['broken']


def test_bound_service_compile_accepts_omitted_legacy_steps():
    from tests.test_workflows import workflow_tables
    from simlab.compiler import compile_model
    tables = workflow_tables()
    tables['SimLabMaintenanceStep'] = [r for r in tables['SimLabMaintenanceStep'] if r['RULEID'] != 'POWER-CM']
    assert compile_model(tables)['workflows']['bindings']


def test_rejected_spare_retries_install_without_redetach_or_resource_deadlock():
    cfg = config('REPLACE'); cfg['stock'] = {('C', 'L'): 2}
    cfg['capacity'] = {('C', 'TECH'): 1}
    nodes = bind(cfg, 'MAINTENANCE', [('REMOVE', 1), ('INSTALL', 2), ('TEST', 1)], rule='R', method='REPLACE')
    nodes[1]['resources'] = {'TECH': 1}
    env, parts, part, asset, net, service = rig(cfg)
    rejected, good = net.available('C', 'L')
    def expiration():
        yield env.timeout(2)
        parts.records[rejected]['preventive_due'] = True
    env.process(expiration())
    parts.fail(part, part); job = service.corrective(asset, asset['slots'][0])
    env.run(until=6.01)
    assert job['ended_at'] == 6 and asset['slots'][0]['token'] == good
    assert len(service.jobs) == 2 and rejected in service.quarantined
    assert service.pool.free == service.pool.capacity
    rows = service.workflows.snapshot()['steps']
    assert len([r for r in rows if r['action'] == 'REMOVE']) == 1
    assert len([r for r in rows if r['action'] == 'INSTALL']) == 2
    assert next(r for r in rows if r['action'] == 'TEST')['started_at'] == 5


def test_retirement_workflow_disposes_once_without_off_item_repair():
    from tests.test_retirement import retiring
    cfg = retiring(hours=2)
    bind(cfg, 'MAINTENANCE', [('REMOVE', 2), ('INSTALL', 2), ('TEST', 2)], rule='R', method='RETIREMENT')
    env, parts, part, asset, net, service = rig(cfg)
    parts.records[part]['lifetime_hours'] = 2
    service.retirement.due(); env.run(until=6.01)
    assert parts.records[part]['retired'] and len(service.jobs) == 1
    assert service.jobs[0]['ended_at'] == 6
    assert len(service.snapshot()['retirements']) == 1
    assert asset['slots'][0]['token'] != part


@pytest.mark.parametrize('kind', ['CORRECTIVE', 'PREVENTIVE'])
def test_actual_service_count_and_age_reset_once(kind):
    cfg = config(preventive=True)
    cfg['m3']['tables']['SimLabItemRetirement'] = [dict(IID='L', LIMIT_H='', LIMIT_REPAIRS=10)]
    rule = 'R' if kind == 'CORRECTIVE' else 'PM'
    bind(cfg, 'MAINTENANCE', [('IN_PLACE', 1), ('TEST', 1)], rule=rule, method='IN_PLACE')
    env, parts, part, asset, net, service = rig(cfg)
    parts.records[part].update(age=40, lifetime_hours=40)
    if kind == 'CORRECTIVE':
        parts.fail(part, part); service.corrective(asset, asset['slots'][0])
    else:
        service.preventive(part)
    env.run(until=2.01)
    assert parts.records[part]['age'] == 0
    assert parts.records[part]['lifetime_hours'] == 40
    assert parts.records[part]['corrective_repairs'] == (kind == 'CORRECTIVE')


def test_partial_mixed_binding_keeps_unbound_path_steps_required():
    from tests.test_workflows import workflow_tables
    from simlab.compiler import compile_model, ModelError
    tables = workflow_tables()
    tables['SimLabMaintenanceRule'][0].update(METHOD='MIXED', REPLACE_P='0.5')
    with pytest.raises(ModelError, match='IN_PLACE'):
        compile_model(tables)


def test_bound_off_item_compile_accepts_omitted_legacy_steps():
    from tests.test_workflows import workflow_tables
    from simlab.compiler import compile_model
    tables = workflow_tables()
    tables['SimLabWorkflow'].append(dict(WFID='OFF', NAME='off'))
    tables['SimLabWorkflowStep'] += [dict(WFID='OFF', STEPID=i, ACTION=a, DURATION_H='1', PREDECESSORS=p)
        for i, a, p in [('D', 'DIAGNOSE', ''), ('S', 'SERVICE', 'D'), ('T', 'TEST', 'S')]]
    tables['SimLabWorkflowBinding'].append(dict(BINDID='OFF', WFID='OFF', ACTIVITY='OFF_ITEM', IID='POWER', STID='DEPOT', KIND='CORRECTIVE'))
    tables['SimLabOffItemService'] = [r for r in tables['SimLabOffItemService'] if r['KIND'] != 'CORRECTIVE']
    assert compile_model(tables)['workflows']['bindings']


def test_bound_path_ignores_legacy_resource_capacity_but_shared_step_keeps_it():
    from tests.test_workflows import workflow_tables
    from simlab.compiler import compile_model, ModelError
    tables = workflow_tables()
    tables['Tasks'].append(dict(TID='IMPOSSIBLE'))
    tables['TaskResource'].append(dict(TID='IMPOSSIBLE', RID='TECH', QTY='999'))
    for row in tables['SimLabMaintenanceStep']:
        if row['RULEID'] == 'POWER-CM':
            row['TASK'] = 'IMPOSSIBLE'
    assert compile_model(tables)['workflows']['bindings']
    tables['SimLabMaintenanceRule'][0].update(METHOD='MIXED', REPLACE_P='0.5')
    tables['SimLabMaintenanceStep'].append(dict(RULEID='POWER-CM', STEP='IN_PLACE', TASK='', DURATION_H='1'))
    with pytest.raises(ModelError, match='IMPOSSIBLE'):
        compile_model(tables)


def test_internal_parallel_branch_finishes_before_unlocking_aircraft():
    cfg = config()
    nodes = bind(cfg, 'MAINTENANCE', [('IN_PLACE', 1), ('TEST', 1)], rule='R', method='IN_PLACE')
    nodes.append(dict(id='custom', name='custom', action='CUSTOM', duration=5,
                      random=False, resources={}, predecessors=[]))
    env, parts, part, asset, net, service = rig(cfg)
    parts.fail(part, part); job = service.corrective(asset, asset['slots'][0])
    env.run(until=3)
    assert service.blocked(asset) and job['ended_at'] is None
    env.run(until=5.01)
    assert job['ended_at'] == 5 and not service.blocked(asset)
