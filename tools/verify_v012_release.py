"""Compare saved legacy trajectories and new model source with a released EXE."""
import argparse
import copy
import json
from pathlib import Path
import subprocess
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from simlab.compiler import compile_model
from simlab.engine import run_one
from simlab.project import import_package, export_package
from simlab.m3_sample import lifecycle_project
from simlab.workflow_sample import workflow_project


def main():
    parser=argparse.ArgumentParser();parser.add_argument('exe',type=Path)
    args=parser.parse_args(); work=ROOT/'build/qa-v012-release';work.mkdir(parents=True,exist_ok=True)
    evidence={}
    paths=[ROOT/'docs/cases'/n/'m3.simproj' for n in ('2026-09-16-m3','2026-09-16-m3-periodic')]
    paths += [ROOT/'docs/cases/2026-09-15-aircraft-aging'/f'{m}.simproj' for m in ('PERFECT','MINIMAL')]
    paths += [ROOT/'docs/cases'/n/'lifecycle.simproj' for n in ('2026-09-16-lifecycle','2026-09-16-lifecycle-periodic')]
    cases=[]
    for path in paths:
        p=import_package(path); run=p['runs'][0]
        cases.append((path.parent.name+'-'+path.stem,copy.deepcopy(run['snapshot']),run['result']))
    cases.append(('redundancy-workflows',workflow_project(1)['tables'],None))
    for index,(name,tables,saved) in enumerate(cases):
        tables['Control'][0]['NREPS']='1'
        source=json.loads(json.dumps(run_one(compile_model(tables))))
        if saved:
            assert {k:source[k] for k in saved['replication_results'][0]}==saved['replication_results'][0],name
            assert source['events']==saved['events'] and source['components']==saved['components'],name
        inp,out=work/f'input-{index}.json',work/f'result-{index}.json'
        inp.write_text(json.dumps(tables,ensure_ascii=False),encoding='utf-8')
        subprocess.run([str(args.exe.resolve()),'--worker',str(inp),str(out)],check=True,timeout=120,
                       creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        actual=json.loads(out.read_text(encoding='utf-8'))
        retained = {k: v for k, v in source.items() if k not in ('samples', 'events', 'components', 'maintenance')}
        assert actual['replication_results'][0]==retained,name
        for key in ('samples', 'events', 'components'):
            assert actual[key] == source[key], (name, key)
        evidence[name]=dict(source_exe_equal=True,saved_equal=bool(saved))
    old=subprocess.run(['git','show','1fe05a8:simlab/project.py'],cwd=ROOT,capture_output=True,text=True,encoding='utf-8',check=True).stdout
    old=old.replace('from .extensions import VERSION as EXTENSIONS_VERSION','EXTENSIONS_VERSION = 11')
    namespace={'__name__':'simlab.v011_reader','__package__':'simlab'}
    exec(compile(old,'v011-reader.py','exec'),namespace)
    package=work/'new.simproj';export_package(workflow_project(1),package)
    try:namespace['import_package'](package)
    except ValueError as error:assert '扩展格式版本' in str(error)
    else:raise AssertionError('Format11 reader accepted format12')
    evidence['format11_rejects_format12']=True
    (work/'verification.json').write_text(json.dumps(evidence,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(evidence,ensure_ascii=False),flush=True)

if __name__=='__main__':main()
