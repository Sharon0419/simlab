"""Build and audit the v0.9 calendar-maintenance example without editing old cases."""
import argparse
import copy
import csv
import json
import subprocess
import sys
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from simlab.compiler import compile_model
from simlab.engine import simulate, run_one
from simlab.project import new_project, save_project, export_package, import_package
from simlab.flight_results import export_planned, export_tasks


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--exe', type=Path)
    args=parser.parse_args()
    out=ROOT/'docs/cases/2026-09-15-aircraft-planned'
    out.mkdir(parents=True,exist_ok=True)
    base=json.loads((ROOT/'docs/cases/2026-09-11-aircraft-ground/输入-2组.json').read_text(encoding='utf-8'))
    tables=copy.deepcopy(base)
    tables['SimLabPlannedMaintenance']=[dict(PMID='DAILY_CHECK',SID=tables['System'][0]['SID'],
        USTID=tables['SystemDeployment'][0]['USTID'],FIRST_H='10',INTERVAL_H='24',DURATION_H='1',TASK='TURNROUND')]
    (out/'输入.json').write_text(json.dumps(tables,ensure_ascii=False,indent=2),encoding='utf-8')
    result=simulate(tables)
    assert result['replications']==1000
    for rep in result['replication_results']:
        pm=rep['mission']['planned']
        assert pm['due_jobs']==36
        assert pm['due_jobs']==sum(pm[k] for k in ('completed_jobs','deferred_jobs','waiting_jobs','working_jobs'))
        assert abs(pm['work_aircraft_hours']/12-rep['downtime']['planned_maintenance'])<1e-7
        assert abs(pm['wait_aircraft_hours']/12-rep['downtime']['planned_wait'])<1e-7
        assert rep['parts']['initial']==rep['parts']['final']==48
        for j in pm['jobs']:
            assert all(j[k]>=0 for k in ('deferred_hours','wait_hours','work_hours'))
            if j['status']=='completed':assert abs(j['work_hours']-1)<1e-9
        # Every asset's actual maintenance operations must be disjoint from flight.
        for j in pm['jobs']:
            if j['started_at'] is None:continue
            end=j['ended_at'] if j['ended_at'] is not None else result['horizon']
            for t in rep['mission']['tasks']:
                if j['asset'] in t['members']:
                    assert end<=t['launched_at'] or j['started_at']>=t['landed_at']
    run=dict(id='calendar-1000',name='日历计划维修1000轮',status='completed',started=result['created'],
             completed=result['created'],model_hash=result['model_hash'],snapshot=copy.deepcopy(tables),result=result)
    project=new_project('飞机日历计划维修 · 12架 · 1000次')
    project['description']='每天10点到期，每架固定维修1小时，共享2个保障组；在飞先落地。合成验证案例。'
    project['tables']=tables;project['runs']=[run]
    run['source_revision']=project['revision']
    save_project(project,out/'飞机日历计划维修.sqlite')
    export_package(project,out/'飞机日历计划维修.simproj')
    assert import_package(out/'飞机日历计划维修.simproj')['runs'][0]['result']==result
    export_planned(run,out/'计划维修-全轮.csv')
    export_tasks(run,out/'任务-全轮.csv',detailed=True)
    with (out/'计划维修-全轮.csv').open(encoding='utf-8-sig',newline='') as f:rows=list(csv.DictReader(f))
    assert len(rows)==36000
    assert abs(sum(float(r['work_hours']) for r in rows)/1000-result['mission']['planned']['work_aircraft_hours'])<1e-7
    print('PASS: 1000轮、36000工单、状态/时间/部件守恒、无空中维修、CSV与项目往返',flush=True)
    # Legacy numerical comparison uses the exact same stored v0.8 input.
    legacy=simulate(base)
    old=import_package(ROOT/'docs/cases/2026-09-11-aircraft-ground/飞机保障-2组-含1000次结果.simproj')['runs'][0]['result']
    for key in ('availability','mission','events','resources','downtime','replication_results'):
        assert legacy[key]==old[key],key
    print('PASS: v0.8原案例1000轮数值与首轮事件逐项相同',flush=True)
    if args.exe:
        one=copy.deepcopy(tables);one['Control'][0]['NREPS']='1'
        work=ROOT/'build/qa-v09-replay';work.mkdir(parents=True,exist_ok=True)
        src=work/'input.json';target=work/'result.json'
        src.write_text(json.dumps(one,ensure_ascii=False),encoding='utf-8')
        if target.exists():target.unlink()
        subprocess.run([str(args.exe.resolve()),'--worker',str(src),str(target)],check=True,
                       creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
        packaged=json.loads(target.read_text(encoding='utf-8'))
        first=run_one(compile_model(one))
        assert packaged['events']==first['events']
        for key,value in packaged['replication_results'][0].items():
            assert value==first[key],key
        print('PASS: 源码/便携版首轮物理结果与事件相同',flush=True)
    pm=result['mission']['planned'];flight=result['mission']['flight']
    report=f'''# v0.9 日历计划维修案例

2026-09-15；12架、每波2架、三天每天09/12/15点起飞。沿用v0.8的故障、维修与准备参数。
新增：每天10点全机队到期，每架固定1小时，共享2个保障组。此为合成输入，不是实际维修制度。

- 重复试验：1000轮；每轮36次到期。
- 每轮完成工单均值：{pm['completed_jobs']:.6f}。
- 每轮实际计划维修作业：{pm['work_aircraft_hours']:.6f}架·小时。
- 每轮等待资源：{pm['wait_aircraft_hours']:.6f}架·小时。
- 任务成功率：{flight['success_rate']:.6%}；每轮取消：{flight['cancelled']:.6f}。
- 每轮可用度均值：{result['availability']:.6%}，含计划维修资源等待和作业停机。

已核验1000轮状态/时间/部件守恒、36000条CSV、无空中维修和项目包往返；原v0.8无新增规则案例1000轮数值及首轮事件保持一致。
源码/便携版首轮对照：{'通过' if args.exe else '本次未执行'}。
固定种子保证复现，不宣称方案间随机流配对或原厂数值等价。

导入同目录“飞机日历计划维修.simproj”，在“04 维修与保障作业 → 日历计划维修”调整输入。
结果页“日历计划维修”显示首轮明细和跨轮均值，可导出全轮CSV。
复现：`.venv/Scripts/python.exe tools/run_aircraft_planned_case.py --exe dist/SimLab/SimLab.exe`。
'''
    (out/'评估报告.md').write_text(report,encoding='utf-8')


if __name__=='__main__':main()
