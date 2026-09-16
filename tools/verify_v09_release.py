"""Verify packaged replay and old-reader rejection against stored release evidence."""
import argparse
import copy
import json
import os
import subprocess
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from simlab.compiler import compile_model
from simlab.engine import run_one
from simlab.project import load_project, model_hash

parser=argparse.ArgumentParser()
parser.add_argument('exe',type=Path)
args=parser.parse_args()
work=ROOT/'build/qa-v09-release';work.mkdir(parents=True,exist_ok=True)
case=ROOT/'docs/cases/2026-09-15-aircraft-planned'
project=load_project(case/'飞机日历计划维修.sqlite')
assert model_hash(project['runs'][0]['snapshot'])==project['runs'][0]['model_hash']
tables=copy.deepcopy(project['tables']);tables['Control'][0]['NREPS']='1'
src=work/'input.json';target=work/'result.json'
src.write_text(json.dumps(tables,ensure_ascii=False),encoding='utf-8')
if target.exists():target.unlink()
subprocess.run([str(args.exe.resolve()),'--worker',str(src),str(target)],check=True,
               creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
packaged=json.loads(target.read_text(encoding='utf-8'))
source=run_one(compile_model(tables))
assert packaged['events']==source['events']==project['runs'][0]['result']['events']
for key,value in packaged['replication_results'][0].items():
    assert value==source[key]==project['runs'][0]['result']['replication_results'][0][key],key
old_code=subprocess.run(['git','show','8265cb3:simlab/project.py'],cwd=ROOT,check=True,capture_output=True,encoding='utf-8').stdout
old_code=old_code.replace('from .extensions import VERSION as EXTENSIONS_VERSION','EXTENSIONS_VERSION = 6')
namespace={'__name__':'simlab.v08_reader','__package__':'simlab'}
exec(compile(old_code,'v0.8-project.py','exec'),namespace)
try:namespace['load_project'](case/'飞机日历计划维修.sqlite')
except ValueError as error:assert '扩展格式版本' in str(error)
else:raise AssertionError('v0.8 reader accepted format 7')
evidence=dict(engine=packaged['engine'],source_packaged_stored_first_replication_equal=True,
              old_reader_commit='8265cb3',old_reader_rejects_format7=True)
(work/'verification.json').write_text(json.dumps(evidence,indent=2),encoding='utf-8')
print(json.dumps(evidence),flush=True)
