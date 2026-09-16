"""Reproducible v0.9.1 inspection benchmark and packaged replay."""
import argparse,copy,csv,json,os,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from simlab.compiler import compile_model
from simlab.engine import simulate,run_one
from simlab.project import new_project,save_project,load_project,export_package,import_package,model_hash
from simlab.flight_results import export_planned,export_inspection_clocks

OUT=ROOT/'docs/cases/2026-09-15-aircraft-inspection'


def audit(result):
    jobs=0
    for rep in result['replication_results']:
        pm=rep['mission']['planned'];jobs+=len(pm['jobs'])
        assert pm['due_jobs']==sum(pm[k] for k in ('completed_jobs','deferred_jobs','waiting_jobs','working_jobs'))
        assert rep['parts']['initial']==rep['parts']['final']==48
        assert abs(pm['work_aircraft_hours']/12-rep['downtime']['planned_maintenance'])<1e-7
        assert abs(pm['wait_aircraft_hours']/12-rep['downtime']['planned_wait'])<1e-7
        for c in pm['clocks']:
            checks=[j for j in pm['jobs'] if j.get('trigger')=='flight_hours' and j['asset']==c['asset'] and j['rule']==c['rule']]
            completed=[j for j in checks if j['status']=='completed']
            assert len(completed)==c['completed_checks']
            assert abs(c['initial_hours']+c['flown_hours']-c['hours_since_check']-sum(j['cycle_hours'] for j in completed))<1e-7
            flying=sum(t['landed_at']-t['launched_at'] for t in rep['mission']['tasks'] if c['asset'] in t['members'])
            assert abs(flying-c['flown_hours'])<1e-7
            assert sum(j['status']!='completed' for j in checks)<=1
        for j in pm['jobs']:
            if j['started_at'] is None:continue
            end=j['ended_at'] if j['ended_at'] is not None else result['horizon']
            for t in rep['mission']['tasks']:
                if j['asset'] in t['members']:assert end<=t['launched_at'] or j['started_at']>=t['landed_at']
    return jobs


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--exe',type=Path);parser.add_argument('--verify-only',action='store_true')
    args=parser.parse_args();OUT.mkdir(parents=True,exist_ok=True)
    if not args.verify_only:
        old=load_project(ROOT/'docs/cases/2026-09-15-aircraft-planned/飞机日历计划维修.sqlite')
        tables=copy.deepcopy(old['tables'])
        tables['SimLabFlightInspection']=[dict(CHECKID='FLY3',SID=tables['System'][0]['SID'],USTID=tables['SystemDeployment'][0]['USTID'],INTERVAL_H='3',DURATION_H='1',TASK='TURNROUND')]
        tables['SimLabInspectionInitial']=[dict(CHECKID='FLY3',ASSET_NO=str(i),INITIAL_H=str((i-1)*.25)) for i in range(1,13)]
        result=simulate(tables);assert result['replications']==1000
        count=audit(result)
        assert any(j.get('trigger')=='flight_hours' for rep in result['replication_results'] for j in rep['mission']['planned']['jobs'])
        p=new_project('飞机飞行小时检查 · 12架 · 1000次')
        p['description']='每3在空小时检查1小时；初始0至2.75小时逐架错开；与每日10点日历维修串行。合成验证案例。'
        p['tables']=tables
        run=dict(id='inspection-1000',name='飞行小时与日历维修',status='completed',started=result['created'],
                 source_revision=p['revision'],snapshot=copy.deepcopy(tables),model_hash=model_hash(tables),result=result)
        p['runs']=[run]
        save_project(p,OUT/'飞机飞行小时检查.sqlite');export_package(p,OUT/'飞机飞行小时检查.simproj')
        assert import_package(OUT/'飞机飞行小时检查.simproj')['runs']==p['runs']
        export_planned(run,OUT/'维修工单.csv');export_inspection_clocks(run,OUT/'逐架计时.csv')
        with (OUT/'逐架计时.csv').open(encoding='utf-8-sig',newline='') as f:assert len(list(csv.DictReader(f)))==12000
        with (OUT/'维修工单.csv').open(encoding='utf-8-sig',newline='') as f:assert len(list(csv.DictReader(f)))==count
        (OUT/'输入.json').write_text(json.dumps(tables,ensure_ascii=False,indent=2),encoding='utf-8')
        print(f'PASS: 1000 replications, {count} jobs, 12000 clocks; conservation/flight separation/CSV/package',flush=True)
        legacy=simulate(old['tables'])
        for k in ('mission','events','replication_results','availability','resources','downtime'):
            assert legacy[k]==old['runs'][0]['result'][k],k
        print('PASS: v0.9 1000-replication numerical regression',flush=True)
        f=result['mission']['flight'];pm=result['mission']['planned']
        (OUT/'评估报告.md').write_text(f'''# 飞行小时检查案例（2026-09-15）

12架、每波2架、三天；保留v0.9日历维修与故障参数。新增每3在空小时检查1小时，逐架初始0至2.75小时，步长0.25小时。检查为合成输入，不代表实际维护制度。

1000轮、{count}张工单、12000条计时记录；计时守恒、飞机实际在空时间复算、部件守恒、无空中维修、CSV和项目包往返通过。
原v0.9无新规则案例1000轮数值及首轮事件一致。
每轮维修完成均值{pm['completed_jobs']:.6f}，实际维修{pm['work_aircraft_hours']:.6f}架·小时，任务成功率{f['success_rate']:.6%}。
同一检查周期仅一张到期工单；超限历史保留，完成后本项归零；不更换部件、不重置故障预算。
便携版重放结果见同目录release-verification.json（只有存在且字段为true才表示已验证）。
''',encoding='utf-8')
    if args.exe:
        p=load_project(OUT/'飞机飞行小时检查.sqlite');tables=copy.deepcopy(p['tables']);tables['Control'][0]['NREPS']='1'
        work=ROOT/'build/qa-v091-replay';work.mkdir(parents=True,exist_ok=True)
        src=work/'input.json';target=work/'result.json';src.write_text(json.dumps(tables),encoding='utf-8')
        if target.exists():target.unlink()
        subprocess.run([str(args.exe.resolve()),'--worker',str(src),str(target)],check=True,creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
        packaged=json.loads(target.read_text(encoding='utf-8'));source=run_one(compile_model(tables))
        assert packaged['events']==source['events']==p['runs'][0]['result']['events']
        for k,v in packaged['replication_results'][0].items():assert v==source[k]==p['runs'][0]['result']['replication_results'][0][k],k
        evidence=dict(engine=packaged['engine'],packaged_source_stored_first_replication_equal=True)
        (OUT/'release-verification.json').write_text(json.dumps(evidence,indent=2),encoding='utf-8')
        print(evidence,flush=True)


if __name__=='__main__':main()
