"""Reproducible synthetic M3 acceptance case and packaged-worker comparison."""
import argparse
import copy
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from simlab.engine import simulate
from simlab.m3_sample import m3_project
from simlab.m3_results import DATASETS, export_m3
from simlab.project import save_project, export_package, import_package, now


def audit(result):
    total_orders = total_shipments = total_services = total_preventive = 0
    for rep in result['replication_results']:
        assert rep['parts']['initial'] == rep['parts']['final']
        supply, service = rep['supply'], rep['service']
        assert not supply.get('truncated'), 'Acceptance requires complete supply detail'
        assert not service.get('jobs_truncated') and not service.get('clocks_truncated')
        orders = {row['id']: row for row in supply['orders']}
        seen = set()
        for batch in supply['shipments']:
            assert batch['order'] in orders
            assert batch['quantity'] == len(batch['parts'])
            assert batch['arrival'] >= batch['departure']
            if not batch['received']:
                assert not seen.intersection(batch['parts'])
                seen.update(batch['parts'])
        for order in orders.values():
            assert order['quantity'] == order['unallocated'] + order['in_transit'] + order['received']
            received = sum(b['quantity'] for b in supply['shipments']
                           if b['order'] == order['id'] and b['received'])
            transit = sum(b['quantity'] for b in supply['shipments']
                          if b['order'] == order['id'] and not b['received'])
            assert (received, transit) == (order['received'], order['in_transit'])
        for stock in supply['stocks']:
            assert stock['available'] >= 0
            assert stock['inventory_position'] == stock['available'] + stock['unreceived'] - stock['unmet']
        for job in service['jobs']:
            if job['status'] == 'completed':
                assert job['ended_at'] >= job['started_at']
        total_orders += len(orders)
        total_shipments += len(supply['shipments'])
        total_services += len(service['jobs'])
        total_preventive += sum(j['kind'] == 'PREVENTIVE' for j in service['jobs'])
    assert total_orders and total_shipments and total_services and total_preventive
    return dict(replications=result['replications'], orders=total_orders, shipments=total_shipments,
                service_jobs=total_services, preventive_jobs=total_preventive,
                physical_and_order_conservation=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--reps', type=int, default=1000)
    parser.add_argument('--output', type=Path, default=ROOT/'docs/cases/2026-09-16-m3')
    parser.add_argument('--exe', type=Path)
    parser.add_argument('--periodic', action='store_true')
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    project = m3_project(args.reps)
    if args.periodic:
        for policy in project['tables']['SimLabSupplyPolicy']:
            policy.pop('REORDER_QTY', None)
            policy.update(TRIGGER='PERIODIC', FIRST_H='0', INTERVAL_H='8')
    project['name'] = f'飞机三级供应 · {"周期" if args.periodic else "临界库存"}调运 · {args.reps}次'
    tables = project['tables']
    result = simulate(tables)
    evidence = audit(result)
    run = dict(id='m3-periodic' if args.periodic else 'm3-threshold', name=project['name'], status='completed',
               started=now(), source_revision=project['revision'], snapshot=copy.deepcopy(tables),
               model_hash=result['model_hash'], result=result)
    project['runs'] = [run]
    save_project(project, output/'m3.sqlite')
    export_package(project, output/'m3.simproj')
    assert import_package(output/'m3.simproj')['runs'][0]['result'] == result
    (output/'input.json').write_text(json.dumps(tables, ensure_ascii=False, indent=2), encoding='utf-8')
    for section, datasets in DATASETS.items():
        if not result.get(section):
            continue
        for dataset in datasets:
            export_m3(run, output/f'{section}-{dataset}.csv', section, dataset)
    evidence.update(model_hash=result['model_hash'], seed=result['seed'], engine=result['engine'],
                    availability=result['availability'],
                    mission_success_rate=result['mission']['flight']['success_rate'], package_roundtrip=True)
    if args.exe:
        tables = copy.deepcopy(tables)
        tables['Control'][0]['NREPS'] = '1'
        inp, dest = output/'replay-input.json', output/'replay-result.json'
        inp.write_text(json.dumps(tables, ensure_ascii=False), encoding='utf-8')
        completed = subprocess.run([str(args.exe.resolve()), '--worker', str(inp), str(dest)],
                                   timeout=120, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        assert completed.returncode == 0, f'Packaged worker failed: {completed.returncode}'
        replay = json.loads(dest.read_text(encoding='utf-8'))
        assert replay['replication_results'][0] == result['replication_results'][0]
        evidence['source_exe_replay_identical'] = True
    (output/'verification.json').write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding='utf-8')
    (output/'评估报告.md').write_text(
        '# 飞机三级供应与维修方式案例\n\n'
        '输入均为合成演示假设，不代表实际维修制度或原厂数值认证。\n\n'
        '三级地点，4架飞机，9个双机飞行窗口；动力模块允许原位和换件，运行3小时触发预防性作业。'
        '初始库存基地0、区域1、中心6；允许中心直达基地，优先较短且有货的策略，运输无容量限制。\n\n'
        f'验证结果：\n\n```json\n{json.dumps(evidence, ensure_ascii=False, indent=2)}\n```\n', encoding='utf-8')
    print(json.dumps(evidence, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
