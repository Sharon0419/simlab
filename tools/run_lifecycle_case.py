"""Synthetic procurement/retirement acceptance; no real operations data."""
import argparse
import copy
import json
import math
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from simlab.engine import simulate
from simlab.m3_sample import lifecycle_project
from simlab.m3_results import DATASETS, export_m3
from simlab.project import save_project, export_package, import_package, now


def audit(result):
    purchased = retired = 0
    for rep in result['replication_results']:
        supply, service = rep['supply'], rep['service']
        assert not supply['truncated']
        assert not any(service.get(k, False) for k in ('jobs_truncated', 'retirements_truncated', 'lifetimes_truncated'))
        batches = supply['shipments'] + supply['purchases']
        arrivals = sum(p['quantity'] for p in supply['purchases'] if p['received'])
        # This case uses leaf modules, hence one purchased root = one identity.
        assert rep['parts']['initial'] + arrivals == rep['parts']['final']
        for order in supply['orders']:
            assert order['quantity'] == order['unallocated'] + order['in_transit'] + order['received']
            for flag, column in ((True, 'received'), (False, 'in_transit')):
                assert sum(b['quantity'] for b in batches if b['order']==order['id'] and b['received']==flag)==order[column]
        for stock in supply['stocks']:
            assert stock['inventory_position']==stock['available']+stock['unreceived']-stock['unmet']
        for purchase in supply['purchases']:
            assert math.isclose(purchase['arrival']-purchase['created'], 4, abs_tol=1e-9)
            assert len(purchase['parts'])==(purchase['quantity'] if purchase['received'] else 0)
        assert len({r['part'] for r in service['retirements']})==len(service['retirements'])
        purchased += arrivals
        retired += len(service['retirements'])
    assert purchased and retired
    return dict(replications=result['replications'], purchased_arrived=purchased, retired=retired,
                physical_and_order_conservation=True)


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--reps',type=int,default=100)
    parser.add_argument('--output',type=Path,default=ROOT/'docs/cases/2026-09-16-lifecycle')
    parser.add_argument('--periodic',action='store_true')
    parser.add_argument('--exe',type=Path)
    args=parser.parse_args()
    output=args.output.resolve(); output.mkdir(parents=True,exist_ok=True)
    project=lifecycle_project(args.reps)
    if args.periodic:
        for row in project['tables']['SimLabPurchasePolicy']:
            row.pop('REORDER_QTY',None)
            row.update(TRIGGER='PERIODIC',FIRST_H='0',INTERVAL_H='6')
    tables=project['tables']
    result=simulate(tables)
    evidence=audit(result)
    run=dict(id='lifecycle',name=project['name'],status='completed',started=now(),
             source_revision=project['revision'],snapshot=copy.deepcopy(tables),model_hash=result['model_hash'],result=result)
    project['runs']=[run]
    save_project(project,output/'lifecycle.sqlite')
    export_package(project,output/'lifecycle.simproj')
    assert import_package(output/'lifecycle.simproj')['runs'][0]['result']==result
    (output/'input.json').write_text(json.dumps(tables,ensure_ascii=False,indent=2),encoding='utf-8')
    for section,datasets in DATASETS.items():
        if not result.get(section):
            continue
        for dataset in datasets:
            export_m3(run,output/f'{section}-{dataset}.csv',section,dataset)
    evidence.update(engine=result['engine'],seed=result['seed'],model_hash=result['model_hash'],package_roundtrip=True)
    if args.exe:
        one=copy.deepcopy(tables); one['Control'][0]['NREPS']='1'
        inp,out=output/'replay-input.json',output/'replay-result.json'
        inp.write_text(json.dumps(one,ensure_ascii=False),encoding='utf-8')
        subprocess.run([str(args.exe.resolve()),'--worker',str(inp),str(out)],check=True,timeout=120,
                       creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        actual=json.loads(out.read_text(encoding='utf-8'))
        assert actual['replication_results'][0]==result['replication_results'][0]
        evidence['source_exe_first_replication_equal']=True
    (output/'verification.json').write_text(json.dumps(evidence,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(evidence,ensure_ascii=False),flush=True)


if __name__=='__main__':
    main()
