"""Verify final executable against saved M3 and legacy physical trajectories."""
import argparse
import copy
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from simlab.compiler import compile_model
from simlab.engine import run_one
from simlab.project import import_package

parser = argparse.ArgumentParser()
parser.add_argument('exe', type=Path)
args = parser.parse_args()
work = ROOT/'build/qa-m3-release'
work.mkdir(parents=True, exist_ok=True)
evidence = {}
paths = [ROOT/'docs/cases'/name/'m3.simproj' for name in
         ('2026-09-16-m3', '2026-09-16-m3-periodic')]
paths += [ROOT/'docs/cases/2026-09-15-aircraft-aging'/f'{mode}.simproj'
          for mode in ('PERFECT', 'MINIMAL')]
for index, path in enumerate(paths):
    project = import_package(path)
    run = project['runs'][0]
    tables = copy.deepcopy(run['snapshot'])
    tables['Control'][0]['NREPS'] = '1'
    source = json.loads(json.dumps(run_one(compile_model(tables))))
    saved = run['result']['replication_results'][0]
    retained = {key: source[key] for key in saved}
    assert retained == saved, f'Source vs saved mismatch: {path}'
    for key in ('events', 'components'):
        assert source[key] == run['result'][key], (path, key)
    inp, out = work/f'input-{index}.json', work/f'result-{index}.json'
    inp.write_text(json.dumps(tables, ensure_ascii=False), encoding='utf-8')
    if out.exists():
        out.unlink()
    subprocess.run([str(args.exe.resolve()), '--worker', str(inp), str(out)], check=True,
                   timeout=120, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    packaged = json.loads(out.read_text(encoding='utf-8'))
    assert packaged['replication_results'][0] == retained, f'EXE mismatch: {path}'
    for key in ('events', 'components', 'samples'):
        assert packaged[key] == source[key], (path, key)
    key = path.parent.name if index < 2 else 'legacy-' + path.stem
    evidence[key] = dict(source_saved_exe_first_replication_equal=True)
    if index < 2:
        verification = path.parent/'verification.json'
        data = json.loads(verification.read_text(encoding='utf-8'))
        data['source_exe_saved_first_replication_equal'] = True
        verification.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
old = subprocess.run(['git', 'show', 'ada3f00:simlab/project.py'], cwd=ROOT,
                     capture_output=True, text=True, encoding='utf-8', check=True).stdout
old = old.replace('from .extensions import VERSION as EXTENSIONS_VERSION', 'EXTENSIONS_VERSION = 9')
namespace = {'__name__': 'simlab.v092_reader', '__package__': 'simlab'}
exec(compile(old, 'v092-project.py', 'exec'), namespace)
try:
    namespace['import_package'](paths[0])
except ValueError as error:
    assert '扩展格式版本' in str(error)
else:
    raise AssertionError('Old reader accepted format10')
evidence['format9_reader_rejects_format10'] = True
(work/'verification.json').write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps(evidence, ensure_ascii=False), flush=True)
