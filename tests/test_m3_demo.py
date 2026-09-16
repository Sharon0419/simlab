import importlib
import importlib.util


def test_m3_aircraft_example_runs_supply_and_preventive_work():
    assert importlib.util.find_spec('simlab.m3_sample') is not None, 'M3 example missing'
    factory = importlib.import_module('simlab.m3_sample').m3_project
    from simlab.engine import simulate
    from simlab.compiler import compile_model
    project = factory(replications=2)
    config = compile_model(project['tables'])
    assert config['m3']
    result = simulate(project['tables'])
    assert result['replications'] == 2
    assert result['mission']['flight']['requested'] > 0
    for rep in result['replication_results']:
        assert rep['parts']['initial'] == rep['parts']['final']
        assert rep['supply']['orders'] and rep['supply']['shipments']
        assert any(job['kind'] == 'PREVENTIVE' for job in rep['service']['jobs'])


def test_procurement_retirement_example_exposes_approved_inputs():
    from simlab.m3_sample import lifecycle_project
    project = lifecycle_project(replications=2)
    tables = project['tables']
    assert tables['Control'][0]['NREPS'] == '2'
    assert tables['SimLabPurchasePolicy']
    assert tables['SimLabItemRetirement']
    assert all(r['LEAD_H'] == '4' for r in tables['SimLabPurchasePolicy'])
    assert tables['SimLabItemRetirement'][0]['LIMIT_REPAIRS'] == '2'
    assert '采购' in project['name'] and '报废' in project['name']


def test_lifecycle_example_runs_purchases_retirements_and_package_roundtrip(tmp_path):
    from simlab.m3_sample import lifecycle_project
    from simlab.engine import simulate
    from simlab.project import export_package, import_package
    project = lifecycle_project(replications=2)
    result = simulate(project['tables'])
    for rep in result['replication_results']:
        assert rep['supply']['purchases']
        assert rep['service']['retirements']
        assert rep['service']['lifetimes']
        assert rep['parts']['final'] > rep['parts']['initial']
        assert all(r['corrective_repairs'] >= 0 for r in rep['service']['lifetimes'])
    project['runs'] = [{'id': 'lifecycle', 'status': 'completed', 'result': result}]
    path = tmp_path / 'lifecycle.simproj'
    export_package(project, path)
    assert import_package(path)['runs'][0]['result'] == result
