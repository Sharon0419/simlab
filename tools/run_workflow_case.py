"""Reproducible combined P0 case with all-replication evidence."""
import argparse
from collections import Counter
import json
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from simlab.workflow_sample import workflow_project
from simlab.engine import simulate
from simlab.project import export_package, model_hash
from simlab.m3_results import export_m3


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--reps', type=int, default=100)
    parser.add_argument('--out', type=Path, default=ROOT/'docs/cases/2026-09-16-workflows')
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    project = workflow_project(args.reps)
    result = simulate(project['tables'])
    activities, steps, failures = Counter(), Counter(), 0
    for rep in result['replication_results']:
        assert rep['parts']['initial'] == rep['parts']['final']
        rows = rep['workflows']['steps']
        complete = {(r['workflow'],r['step']): r['ended_at'] for r in rows if r['status']=='completed'}
        for row in rows:
            if row['started_at'] is not None:
                assert all(complete[row['workflow'],p] <= row['started_at']+1e-9 for p in row['predecessors'])
            assert all(row[k] >= -1e-9 for k in ('wait_dependency_hours','wait_prerequisite_hours',
                                               'wait_shift_hours','wait_resource_hours','work_hours'))
        for activity in rep['workflows']['activities']:
            own = [r for r in rows if r['workflow']==activity['id']]
            if activity['status']=='completed':
                assert max(r['ended_at'] for r in own)==activity['ended_at']
        activities.update(r['activity'] for r in rep['workflows']['activities'])
        steps.update(r['status'] for r in rows)
        failures += rep['failures']
    run = dict(id='workflow-verification-20260916',name='两层冗余与保障多工序验证',status='completed',
               snapshot=project['tables'],model_hash=model_hash(project['tables']),result=result)
    project['runs'] = [run]
    export_package(project,args.out/'workflows.simproj')
    (args.out/'input.json').write_text(json.dumps(project['tables'],ensure_ascii=False,indent=2),encoding='utf-8')
    for section,datasets in [('workflows',['activities','steps']),('service',['jobs']),('supply',['orders','stocks'])]:
        for dataset in datasets:
            export_m3(run,args.out/f'{section}-{dataset}.csv',section,dataset)
    evidence = dict(replications=args.reps,activities=dict(activities),steps=dict(steps),failures=failures,
                    physical_conservation=True,dependency_order=True,nonnegative_waits=True,
                    activity_elapsed_verified=True,seed=result['seed'],engine=result['engine'])
    (args.out/'verification.json').write_text(json.dumps(evidence,ensure_ascii=False,indent=2),encoding='utf-8')
    (args.out/'评估报告.md').write_text('# 两层冗余与保障多工序组合验证\n\n'
        f'合成示例，固定种子 {result["seed"]}，{args.reps} 轮。\n\n'
        '系统3取2，每个总成内部2取1；覆盖原位、换件、拆下件、出动准备、日历检查和飞行小时检查。\n\n'
        f'活动：{dict(activities)}。工序状态：{dict(steps)}。故障总数：{failures}。\n\n'
        '逐轮实物守恒、依赖完成先后、等待时间非负和完成活动结束时刻检查通过。全部轮次CSV和完整项目包随附。\n'
        '这是一致性和功能验证，未做真实参数校准或原厂数值等价认证。\n',encoding='utf-8')
    print(json.dumps(evidence,ensure_ascii=False),flush=True)


if __name__=='__main__':
    main()
