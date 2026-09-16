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
