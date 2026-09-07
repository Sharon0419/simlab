import copy
import json
import zipfile
import pytest
from simlab.schema import TABLES, SCHEMA
from simlab.validation import validate
from simlab.sample import demo_project
from simlab.project import save_project, load_project, export_package, import_package
from simlab.compiler import compile_model, ModelError
from simlab.engine import simulate, run_one

def small():
    p = demo_project()
    p['tables']['Control'][0].update(SIMPE='240', NREPS='3')
    return p

def test_dictionary_counts_and_units():
    assert len(TABLES) == 133
    assert sum(map(len, TABLES.values())) == 891
    field = next(f for f in TABLES['Item'] if f['id'] == 'FRT')
    assert field['unit'] == '1/MOPIDs'
    assert [f['id'] for f in TABLES['SystemDeployment']] == ['SID', 'USTID', 'QTYPS', 'UTIL', 'PLID', 'NOTE']

def test_demo_valid_and_rate_scaling():
    p = small()
    assert validate(p['tables']) == []
    c = compile_model(p['tables'])
    assert c['fleets'][0]['parts'][0]['rate'] == pytest.approx(0.00125)

@pytest.mark.parametrize('value', ['-1', 'nan', 'inf', 'abc'])
def test_bad_failure_rate(value):
    p = small()
    p['tables']['Item'][0]['FRT'] = value
    assert any('.FRT' in x for x in validate(p['tables']))

def test_missing_reference_and_duplicates():
    p = small()
    p['tables']['MaterielStructure'][0]['MID'] = 'ABSENT'
    p['tables']['Item'].append(copy.deepcopy(p['tables']['Item'][0]))
    errors = validate(p['tables'])
    assert any('不存在' in x for x in errors)
    assert any('组合键重复' in x for x in errors)

def test_unsupported_settings_are_never_silently_used():
    p = small()
    p['tables']['Item'][0]['NSIMI'] = '2'
    with pytest.raises(ModelError, match='NSIMI'):
        compile_model(p['tables'])

def test_atomic_project_roundtrip_and_branch(tmp_path):
    p = small()
    path = tmp_path/'a.sqlite'
    save_project(p, path)
    assert load_project(path) == p
    p['name'] = 'modified'
    save_project(p, path)
    assert load_project(tmp_path/'a.sqlite.bak')['name'] != p['name']
    package = tmp_path/'exchange.simproj'
    export_package(p, package)
    imported = import_package(package)
    assert imported['tables'] == p['tables']
    assert imported['id'] != p['id']
    assert imported['parent_revision'] == p['revision']

def test_package_rejects_traversal_and_tampering(tmp_path):
    bad = tmp_path/'bad.simproj'
    with zipfile.ZipFile(bad, 'w') as z:
        z.writestr('../escape.txt', 'no')
    with pytest.raises(ValueError, match='拒绝未知路径'):
        import_package(bad)
    original = tmp_path/'ok.simproj'
    export_package(small(), original)
    with zipfile.ZipFile(original) as z:
        manifest, data = z.read('manifest.json'), z.read('project.sqlite')
    with zipfile.ZipFile(bad, 'w') as z:
        z.writestr('manifest.json', manifest)
        z.writestr('project.sqlite', data + b'bad')
    with pytest.raises(ValueError, match='校验失败'):
        import_package(bad)

def test_model_only_package_excludes_results(tmp_path):
    p = small()
    p['runs'] = [{'id': 'result', 'result': {'test': 1}}]
    package = tmp_path/'model.simproj'
    export_package(p, package, False)
    assert import_package(package)['runs'] == []
    assert len(p['runs']) == 1

def test_reproducible_conservative_and_zero_failure():
    p = small()
    c = compile_model(p['tables'])
    assert run_one(c, 2) == run_one(c, 2)
    result = run_one(c, 0)
    assert result['parts']['initial'] == result['parts']['final']
    assert 0 < result['availability'] <= 1
    for item in p['tables']['Item']:
        item['FRT'] = '0'
    result = simulate(p['tables'])
    assert result['availability'] == 1
    assert result['failures'] == 0
    assert sum(result['downtime'].values()) == 0

def test_no_spares_renewal_analytic_benchmark():
    p = small()
    t = p['tables']
    t['Item'] = [t['Item'][0]]
    t['Item'][0]['FRT'] = '10000' # mean up time = 100 hours
    t['MaterielStructure'] = [t['MaterielStructure'][0]]
    t['StationStructure'] = []
    t['SystemDeployment'][0].update(QTYPS='1', UTIL='1')
    t['StockAllocation'] = [{'POINT': 'BASELINE', 'IID': 'POWER', 'STID': 'BASE', 'STSIZ': '0'}]
    t['ItemRepair'] = [{'IID': 'POWER', 'STID': 'BASE', 'DIRPT': '20', 'SURPT': '0'}]
    t['ItemReplacement'] = [{'MID': 'VEHICLE', 'IID': 'POWER', 'STID': 'BASE', 'SURPT': '0'}]
    t['Control'][0].update(NREPS='1', SIMPE='500000', RCINT='100', ENLOG='N')
    result = simulate(t)
    assert result['availability'] == pytest.approx(100/120, abs=0.012)
    assert result['ci95'] is None

def test_impossible_resource_bundle_rejected():
    p = small()
    p['tables']['TaskResource'][0]['QTY'] = '100'
    with pytest.raises(ModelError, match='数量不足'):
        compile_model(p['tables'])
