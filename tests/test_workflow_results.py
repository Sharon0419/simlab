import copy
import csv
from collections import Counter

from simlab.compiler import compile_model
from simlab.engine import simulate, run_one
from simlab.m3_results import export_m3
from simlab.project import export_package, import_package
from simlab.workflow_sample import workflow_project


def test_combined_example_executes_all_activities_and_roundtrips(tmp_path):
    project = workflow_project(2)
    tables = copy.deepcopy(project['tables'])
    result = simulate(tables)
    assert tables == project['tables']
    assert set(row['activity'] for row in result['workflows']['activities']) == {
        'MAINTENANCE','OFF_ITEM','PREPARATION','CALENDAR','INSPECTION'}
    assert set(row['kind'] for row in result['service']['jobs']) >= {'CORRECTIVE','PREVENTIVE'}
    for rep in result['replication_results']:
        assert rep['parts']['initial'] == rep['parts']['final']
        steps = rep['workflows']['steps']
        for activity in rep['workflows']['activities']:
            own = [row for row in steps if row['workflow'] == activity['id']]
            if activity['status'] == 'completed':
                assert activity['ended_at'] == max(row['ended_at'] for row in own)
                assert all(row['status'] in ('completed','retry') for row in own)
        completed = {(r['workflow'],r['step']):r['ended_at'] for r in steps if r['status']=='completed'}
        for row in steps:
            assert row['started_at'] is None or all(completed[row['workflow'],p] <= row['started_at'] for p in row['predecessors'])
            assert all(row[key] >= 0 for key in ('wait_dependency_hours','wait_prerequisite_hours',
                                               'wait_shift_hours','wait_resource_hours','work_hours'))
    run = dict(id='verification', status='completed', snapshot=tables, result=result)
    export_m3(run, tmp_path/'steps.csv', 'workflows', 'steps')
    with (tmp_path/'steps.csv').open(encoding='utf-8-sig', newline='') as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == sum(len(r['workflows']['steps']) for r in result['replication_results'])
    assert {r['replication'] for r in rows} == {'1','2'}
    project['runs'] = [run]
    export_package(project, tmp_path/'workflow.simproj')
    assert import_package(tmp_path/'workflow.simproj')['runs'][0]['result'] == result


def test_preparation_and_inspection_workflows_in_legacy_execution():
    from test_ground import ground_tables
    t = ground_tables()
    t['SimLabWorkflow'] = [dict(WFID='P')]
    t['SimLabWorkflowStep'] = [dict(WFID='P', STEPID='A', DURATION_H='.1'),
        dict(WFID='P', STEPID='B', DURATION_H='.1', PREDECESSORS='A')]
    t['SimLabWorkflowBinding'] = [dict(BINDID='B',WFID='P',ACTIVITY='PREPARATION',RULEID=t['SimLabFlightRule'][0]['MTID'])]
    t['SimLabFlightInspection'] = [dict(CHECKID='C', SID=t['System'][0]['SID'],
        USTID=t['SystemDeployment'][0]['USTID'], INTERVAL_H='1', DURATION_H='.5')]
    t['SimLabWorkflowBinding'].append(dict(BINDID='C',WFID='P',ACTIVITY='INSPECTION',RULEID='C'))
    cfg = compile_model(t)
    result = run_one(cfg)
    assert set(r['activity'] for r in result['workflows']['activities']) == {'PREPARATION','INSPECTION'}
    assert any(j['status'] == 'completed' for j in result['mission']['planned']['jobs'])


def test_workflow_sample_is_reproducible_with_fixed_seed():
    cfg = compile_model(workflow_project(1)['tables'])
    assert run_one(cfg) == run_one(cfg)
