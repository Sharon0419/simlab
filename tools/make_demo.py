"""Generate self-contained exchange examples from synthetic data."""
import sys
import uuid
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from simlab.sample import demo_project, mission_project, layered_project, duty_project
from simlab.engine import simulate
from simlab.project import export_package, model_hash, now

directory = Path(sys.argv[1] if len(sys.argv) > 1 else 'dist/SimLab/examples')
directory.mkdir(parents=True, exist_ok=True)
p = demo_project()
export_package(p, directory/'车辆保障-模型.simproj', False)
result = simulate(p['tables'])
p['runs'].append({'id': uuid.uuid4().hex, 'name': '示例基线', 'status': 'completed',
                  'started': now(), 'snapshot': p['tables'].copy(), 'model_hash': model_hash(p['tables']),
                  'source_revision': p['revision'], 'result': result})
export_package(p, directory/'车辆保障-含结果.simproj')
print(f'Generated 2 example packages; availability={result["availability"]:.6f}')
p = mission_project()
export_package(p, directory/'任务日历-模型.simproj', False)
result = simulate(p['tables'])
p['runs'].append({'id': uuid.uuid4().hex, 'name': '任务日历基线', 'status': 'completed',
                  'started': now(), 'snapshot': p['tables'].copy(), 'model_hash': model_hash(p['tables']),
                  'source_revision': p['revision'], 'result': result})
export_package(p, directory/'任务日历-含结果.simproj')
print(f'Generated 2 mission packages; fulfillment={result["mission"]["fulfillment"]:.6f}')
p = layered_project()
export_package(p, directory/'多层维修-模型.simproj', False)
result = simulate(p['tables'])
p['runs'].append({'id': uuid.uuid4().hex, 'name': '多层维修基线', 'status': 'completed',
                  'started': now(), 'snapshot': p['tables'].copy(), 'model_hash': model_hash(p['tables']),
                  'source_revision': p['revision'], 'result': result})
export_package(p, directory/'多层维修-含结果.simproj')
print(f'Generated 2 layered packages; availability={result["availability"]:.6f}')
p = duty_project()
export_package(p, directory/'固定值守-模型.simproj', False)
result = simulate(p['tables'])
p['runs'].append({'id': uuid.uuid4().hex, 'name': '固定值守基线', 'status': 'completed',
                  'started': now(), 'snapshot': p['tables'].copy(), 'model_hash': model_hash(p['tables']),
                  'source_revision': p['revision'], 'result': result})
export_package(p, directory/'固定值守-含结果.simproj')
print(f'Generated 2 duty packages; minimum_rate={result["mission"]["minimum_rate"]:.6f}')
