"""Migration produces a reviewable independent candidate, never edits its source."""
import copy
import importlib

import pytest

from simlab.compiler import compile_model
from simlab.sample import demo_project, layered_project, mission_project
from simlab.m3_sample import m3_project


def migrate(project):
    assert importlib.util.find_spec('simlab.m3_migrate'), 'M3 migration is not implemented'
    return importlib.import_module('simlab.m3_migrate').prepare_migration(project)


def test_leaf_demo_migrates_to_compilable_independent_project_without_history():
    source = demo_project()
    source['runs'] = [{'id': 'old-run', 'result': {'availability': .5}}]
    before = copy.deepcopy(source)
    candidate, preview = migrate(source)
    assert source == before
    assert candidate['id'] != source['id'] and candidate['revision'] != source['revision']
    assert candidate['parent_revision'] == source['revision']
    assert candidate['runs'] == []
    config = compile_model(candidate['tables'])
    assert config['m3'] and config['stock'] == compile_model(source['tables'])['stock']
    assert candidate['tables']['ItemReplacement'] == []
    assert candidate['tables']['ItemRepair'] == []
    assert candidate['tables'].get('SimLabItemPreventive', []) == []
    assert all(r['KIND'] == 'CORRECTIVE' and r['METHOD'] == 'REPLACE'
               for r in candidate['tables']['SimLabMaintenanceRule'])
    assert '新增假设' in preview and '不保证' in preview and '历史' in preview
    candidate['tables']['Item'][0]['DESCR'] = 'changed'
    assert source == before


def test_duration_resource_and_direction_sources_are_preserved_and_previewed():
    source = demo_project()
    source['tables']['Control'][0]['RMVFR'] = '.25'
    source['tables']['StationStructure'][0].update(TFRMS='3', TTOMS='7')
    candidate, preview = migrate(source)
    tables = candidate['tables']
    rid = next(r['RULEID'] for r in tables['SimLabMaintenanceRule'] if r['IID'] == 'POWER')
    steps = {r['STEP']: r for r in tables['SimLabMaintenanceStep'] if r['RULEID'] == rid}
    assert float(steps['REMOVE']['DURATION_H']) == .5
    assert float(steps['INSTALL']['DURATION_H']) == 1.5
    assert steps['REMOVE']['TASK'] == steps['INSTALL']['TASK'] == 'REPLACE'
    assert steps['TEST']['DURATION_H'] == '0' and steps['TEST']['TASK'] == ''
    off = {r['STEP']: r for r in tables['SimLabOffItemService'] if r['IID'] == 'POWER'}
    assert off['SERVICE']['DURATION_H'] == '48'
    assert off['SERVICE']['DISTRIBUTION'] == 'EXPONENTIAL'
    assert off['SERVICE']['TASK'] == 'REPAIR'
    assert off['DIAGNOSE']['DURATION_H'] == off['TEST']['DURATION_H'] == '0'
    assert all((r['FROM_STID'], r['TO_STID'], r['TRANSIT_H']) == ('DEPOT', 'BASE', '3')
               for r in tables['SimLabSupplyRoute'])
    assert all((r['FROM_STID'], r['TO_STID'], r['TRANSIT_H']) == ('BASE', 'DEPOT', '7')
               for r in tables['SimLabServiceRoute'])
    assert tables['StationStructure'][0]['TFRMS'] == tables['StationStructure'][0]['TTOMS'] == '0'
    for field in ('ItemReplacement.SURPT', 'Control.RMVFR', 'ItemRepair.DIRPT', 'ItemRepair.DIRPD',
                  'StationStructure.TFRMS', 'StationStructure.TTOMS', 'DIAGNOSE', 'TEST'):
        assert field in preview


def test_selected_initial_stock_drives_explicit_target_and_zero_stock_assumption():
    source = demo_project()
    stock = source['tables']['StockAllocation']
    next(r for r in stock if r['STID'] == 'BASE' and r['IID'] == 'POWER')['ISTOH'] = '0'
    next(r for r in stock if r['STID'] == 'BASE' and r['IID'] == 'CONTROL')['ISTOH'] = '4'
    stock.append(dict(POINT='UNSELECTED', IID='POWER', STID='BASE', STSIZ='9'))
    candidate, preview = migrate(source)
    policies = {r['IID']: r for r in candidate['tables']['SimLabSupplyPolicy']}
    assert policies['POWER']['TARGET_QTY'] == '1'
    assert policies['CONTROL']['TARGET_QTY'] == '4'
    assert policies['PUMP']['TARGET_QTY'] == '3'
    assert policies['CONTROL']['REORDER_QTY'] == '3'
    assert all(r['POINT'] == 'BASELINE' for r in policies.values())
    assert 'ISTOH' in preview and 'STSIZ' in preview and '库存为 0' in preview
    compile_model(candidate['tables'])


def test_task_calendar_and_shifts_survive_supported_leaf_migration():
    source = mission_project()
    candidate, _ = migrate(source)
    for name in ('Operations', 'OperationProfile', 'Shift', 'ShiftProfile', 'TaskResource'):
        assert candidate['tables'][name] == source['tables'][name]
    assert compile_model(candidate['tables'])['missions']


@pytest.mark.parametrize('source, message', [(m3_project, 'M3'), (layered_project, '子件|总成|DepotProcess')])
def test_unsupported_source_is_rejected_without_mutation(source, message):
    project = source()
    before = copy.deepcopy(project)
    with pytest.raises(ValueError, match=message):
        migrate(project)
    assert project == before


def test_shared_exponential_replacement_cannot_silently_become_independent_draws():
    source = demo_project()
    source['tables']['ItemReplacement'][0]['SURPD'] = '<EXP>'
    with pytest.raises(ValueError, match='抽样|指数|相关'):
        migrate(source)


def test_incomplete_m3_rows_are_rejected_instead_of_overwritten():
    source = demo_project()
    source['tables']['SimLabSupplyRoute'] = [dict(ROUTEID='CUSTOM', IID='POWER',
        FROM_STID='DEPOT', TO_STID='BASE', TRANSIT_H='1')]
    with pytest.raises(ValueError, match='已有|显式|M3'):
        migrate(source)
