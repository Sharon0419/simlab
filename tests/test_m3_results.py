import copy
import csv
import importlib
import importlib.util
import json
import os

import pytest


def module():
    assert importlib.util.find_spec('simlab.m3_results') is not None, 'M3 export not implemented'
    return importlib.import_module('simlab.m3_results')


def run_fixture():
    return {'id': 'run-1', 'model_hash': 'hash-1', 'result': {
        'seed': 7, 'engine': 'test-version', 'replications': 2,
        'replication_results': [
            {'supply': {'orders': [{'id': 1, 'station': 'C', 'iid': 'P', 'quantity': 6}],
                        'shipments': [{'id': 1, 'parts': ['P#1', 'P#2'], 'quantity': 2}],
                        'truncated': False, 'detail_counts': {'orders': 1, 'shipments': 1}}},
            {'supply': {'orders': [{'id': 1, 'station': 'C', 'iid': 'P', 'quantity': 4}],
                        'shipments': [], 'truncated': True,
                        'detail_counts': {'orders': 10001, 'shipments': 0}}}
        ]}}


def test_csv_contains_all_repetitions_and_provenance_and_truncation(tmp_path):
    run = run_fixture()
    original = copy.deepcopy(run)
    path = tmp_path / 'orders.csv'
    module().export_m3(run, path, 'supply', 'orders')
    rows = list(csv.DictReader(path.open(encoding='utf-8-sig', newline='')))
    assert [(r['replication'], r['quantity']) for r in rows] == [('1', '6'), ('2', '4')]
    assert all(r['run_id'] == 'run-1' and r['model_hash'] == 'hash-1' and r['seed'] == '7' for r in rows)
    assert rows[1]['details_truncated'] == 'True'
    assert rows[1]['detail_total'] == '10001'
    assert run == original


def test_csv_keeps_nested_physical_ids_as_json(tmp_path):
    path = tmp_path / 'shipments.csv'
    module().export_m3(run_fixture(), path, 'supply', 'shipments')
    rows = list(csv.DictReader(path.open(encoding='utf-8-sig', newline='')))
    assert json.loads(rows[0]['parts']) == ['P#1', 'P#2']


def test_service_truncation_uses_full_job_count(tmp_path):
    run = {'id': 'service', 'result': {'service': {
        'jobs': [{'id': 'J1'}], 'jobs_total': 10001, 'jobs_truncated': True}}}
    path = tmp_path / 'jobs.csv'
    module().export_m3(run, path, 'service', 'jobs')
    rows = list(csv.DictReader(path.open(encoding='utf-8-sig', newline='')))
    assert rows[0]['detail_total'] == '10001'
    assert rows[0]['details_truncated'] == 'True'


def test_supply_dataset_counts_do_not_leak_other_dataset_truncation(tmp_path):
    data = {'orders': [{'id': 'O1'}], 'stocks': [{'station': 'A'}], 'truncated': True,
            'detail_counts': {'orders': {'total': 3, 'retained': 1, 'truncated': True},
                              'stocks': {'total': 1, 'retained': 1, 'truncated': False}}}
    run = {'id': 'supply', 'result': {'supply': data}}
    for dataset, count, flag in [('orders', '3', 'True'), ('stocks', '1', 'False')]:
        path = tmp_path / (dataset + '.csv')
        module().export_m3(run, path, 'supply', dataset)
        row = list(csv.DictReader(path.open(encoding='utf-8-sig', newline='')))[0]
        assert row['detail_total'] == count
        assert row['details_truncated'] == flag


def test_legacy_export_fails_clearly_without_creating_file(tmp_path):
    path = tmp_path / 'not-m3.csv'
    with pytest.raises(ValueError, match='M3'):
        module().export_m3({'id': 'x', 'result': {'replication_results': [{}]}}, path, 'supply', 'orders')
    assert not path.exists()


def test_result_page_switches_dataset_and_clears_legacy_data():
    module()
    assert importlib.util.find_spec('simlab.ui.m3_results') is not None, 'M3 result page missing'
    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    from PySide6.QtWidgets import QApplication
    from simlab.ui.m3_results import M3ResultsPage
    app = QApplication.instance() or QApplication([])
    page = M3ResultsPage('supply')
    run = run_fixture()
    page.set_run(run)
    assert page.table.rowCount() == 1
    assert page.table.horizontalHeaderItem(0).text() == '编号'
    page.selector.setCurrentIndex(page.selector.findData('shipments'))
    assert page.table.rowCount() == 1
    assert 'P#1' in page.table.item(0, 1).text()
    run['result']['replication_results'][0]['supply']['truncated'] = True
    page.set_run(run)
    assert '截断' in page.notice.text()
    page.set_run(None)
    assert page.table.rowCount() == 0
    assert not page.export_button.isEnabled()
    page.close()
    app.processEvents()

@pytest.mark.parametrize('section,dataset', [('supply', 'purchases'), ('service', 'retirements'), ('service', 'lifetimes')])
def test_purchase_retirement_exports_preserve_all_reps_and_counts(tmp_path, section, dataset):
    run = {'id': 'lifecycle', 'result': {'replication_results': [
        {section: {dataset: [{'part': 'P#1', 'corrective_repairs': 2}],
                   dataset + '_total': 10001, dataset + '_truncated': True}},
        {section: {dataset: [{'part': 'P#2', 'corrective_repairs': 0}]}}]}}
    path = tmp_path / (dataset + '.csv')
    module().export_m3(run, path, section, dataset)
    rows = list(csv.DictReader(path.open(encoding='utf-8-sig', newline='')))
    assert [(r['replication'], r['part']) for r in rows] == [('1', 'P#1'), ('2', 'P#2')]
    assert rows[0]['detail_total'] == '10001'
    assert rows[0]['details_truncated'] == 'True'
    assert rows[1]['details_truncated'] == 'False'
