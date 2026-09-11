"""v0.8 resource preparation cases, worker execution and audited native exports."""
import argparse,copy,csv,json,os,subprocess,sys,uuid
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from simlab.engine import simulate,run_one,t95
from simlab.compiler import compile_model
from simlab.project import new_project,save_project,export_package,import_package,model_hash
from simlab.flight_results import export_tasks,export_ground
import numpy as np

OUT=ROOT/'docs/cases/2026-09-11-aircraft-ground'
WORK=ROOT/'build/aircraft-ground'


def read(p):return json.loads(p.read_text(encoding='utf-8'))
def write(p,v):p.write_text(json.dumps(v,ensure_ascii=False,indent=2),encoding='utf-8')


def prepare():
    base=read(ROOT/'docs/cases/2026-09-08-aircraft-three-days/success-v0.7/输入-12架.json')
    home=compile_model(base)['fleets'][0]['home'];point=base['Control'][0]['APID']
    for groups in (1,2,4):
        tables=copy.deepcopy(base)
        tables['Resource']=[dict(RID='GROUND_CREW',DESCR='再次出动保障组，每组同时1架')]
        tables['Tasks']=[dict(TID='TURNROUND',DESCR='完整再次出动准备，固定半小时')]
        tables['TaskResource']=[dict(TID='TURNROUND',RID='GROUND_CREW',QTY='1')]
        tables['ResourceAllocation']=[dict(POINT=point,RID='GROUND_CREW',STID=home,RQTY=str(groups))]
        tables['ResourceStationData']=[]
        tables['SimLabFlightRule'][0].update(PREP_TASK='TURNROUND',DAILY_READY='Y')
        assert compile_model(tables)['count']==12
        write(WORK/f'input-{groups}.json',tables);write(OUT/f'输入-{groups}组.json',tables)
    stress=[]
    for groups in (1,2):
        t=read(WORK/f'input-{groups}.json');t['Control'][0]['NREPS']='1'
        t['SystemDeployment'][0]['QTYPS']='2';t['MissionType'][0]['DURN']='2.5'
        for item in t['Item']:item['FRT']='0'
        result=simulate(t)
        assert result['mission']['flight']['started']==(6 if groups==1 else 9)
        stress.append(dict(groups=groups,input=t,result=result))
    write(OUT/'无故障紧周转验收.json',stress)
    # Legacy opt-out still reproduces old physical trajectory and numeric flight summary.
    legacy=simulate(base)
    previous=import_package(ROOT/'docs/cases/2026-09-08-aircraft-three-days/success-v0.7/飞机成功点-12架-含1000次结果.simproj')['runs'][0]['result']
    assert legacy['mission']['flight']==previous['mission']['flight']
    assert legacy['events']==previous['events']
    write(OUT/'旧案例兼容验收.json',dict(replications=1000,legacy_engine=previous['engine'],engine=legacy['engine'],
        flight=legacy['mission']['flight'],events_equal=True))
    print('PASS: inputs; tight-turnround 1/2 groups starts 6/9; legacy 1000-run flight metrics and events unchanged',flush=True)


def run(exe):
    for groups in (1,2,4):
        output=WORK/f'result-{groups}.json'
        if output.exists():output.unlink()
        p=subprocess.run([str(exe.resolve()),'--worker',str(WORK/f'input-{groups}.json'),str(output)],
                         creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
        assert p.returncode==0 and output.exists()
        print(f'PASS: {groups} preparation groups, packaged worker completed',flush=True)


def report():
    comparisons=[]
    for groups in (1,2,4):
        tables=read(WORK/f'input-{groups}.json');r=read(WORK/f'result-{groups}.json')
        config=compile_model(tables)
        assert r['engine']=='0.8.0' and r['replications']==len(r['replication_results'])==1000
        assert r['model_hash']==model_hash(tables)
        rows=[]
        for i,one in enumerate(r['replication_results'],1):
            m=one['mission'];g=m['ground'];f=m['flight']
            assert one['parts']['initial']==one['parts']['final']==48
            assert f['completed']+f['aborted']+f['cancelled']==9
            assert f['successful']==sum(t['successful'] for t in m['tasks'])
            assert g['requested_jobs']==g['completed_jobs']+g['assumed_jobs']+g['waiting_jobs']+g['working_jobs']
            assert abs(g['wait_aircraft_hours']-g['wait_resource_aircraft_hours']-g['wait_shift_aircraft_hours'])<1e-7
            assert abs(g['work_aircraft_hours']-f['preparation_aircraft_hours'])<1e-7
            for j in g['jobs']:
                if j['status']=='completed':assert abs(j['work_hours']-.5)<1e-9
                assert j['wait_hours']>=0 and j['work_hours']>=0
            for t in m['tasks']:
                if t['flight_status']=='cancelled':assert t['cancel_reason'] and t['launch_readiness'] is not None
            row=dict(replication=i,success_rate=f['success_rate'],completed=f['completed'],cancelled=f['cancelled'],
                failures=one['failures'],resource_utilization=one['resources'][f'{config["fleets"][0]["home"]}/GROUND_CREW'],
                **{k:v for k,v in g.items() if k!='jobs'})
            rows.append(row)
        with (OUT/f'逐轮指标-{groups}组.csv').open('w',encoding='utf-8-sig',newline='') as file:
            writer=csv.DictWriter(file,fieldnames=rows[0]);writer.writeheader();writer.writerows(rows)
        stats={}
        for key in rows[0]:
            if key=='replication':continue
            a=np.array([row[key] for row in rows]);half=t95(len(a))*a.std(ddof=1)/np.sqrt(len(a))
            stats[key]=dict(mean=float(a.mean()),ci95=[float(a.mean()-half),float(a.mean()+half)])
        p=new_project(f'飞机再次出动保障 · {groups}组 · 12架 · 1000次')
        p['description']=f'半小时完整准备；{groups}个保障组；每日首波健康机假定已准备；3天每波2架'
        p['tables']=tables
        record=dict(id=uuid.uuid4().hex,name='每日首波就绪 · 保障资源约束',status='completed',started=r['created'],
                    source_revision=p['revision'],snapshot=copy.deepcopy(tables),model_hash=r['model_hash'],result=r)
        p['runs']=[record]
        export_tasks(record,OUT/f'逐轮任务-{groups}组.csv',True)
        export_ground(record,OUT/f'逐轮准备作业-{groups}组.csv')
        with (OUT/f'逐轮准备作业-{groups}组.csv').open(encoding='utf-8-sig',newline='') as file:
            exported=list(csv.DictReader(file))
        assert len(exported)==sum(row['requested_jobs'] for row in rows)
        assert abs(sum(float(x['wait_hours']) for x in exported)-sum(x['wait_aircraft_hours'] for x in rows))<1e-6
        export_package(p,OUT/f'飞机保障-{groups}组-含1000次结果.simproj')
        export_package(p,OUT/f'飞机保障-{groups}组-模型.simproj',False)
        assert import_package(OUT/f'飞机保障-{groups}组-含1000次结果.simproj')['runs'][0]['result']==r
        path=Path(os.environ['LOCALAPPDATA'])/'SimLab/projects'/f'aircraft-ground-{groups}-{p["id"][:8]}.sqlite'
        save_project(p,path)
        write(OUT/f'统计汇总-{groups}组.json',dict(project_path=str(path),engine=r['engine'],model_hash=r['model_hash'],seed=r['seed'],statistics=stats))
        replay=run_one(compile_model(tables),0)
        assert replay['mission']==r['replication_results'][0]['mission'] and replay['events']==r['events']
        comparisons.append(dict(groups=groups,**{k:stats[k]['mean'] for k in ('success_rate','completed','cancelled','wait_aircraft_hours','work_aircraft_hours','resource_utilization')}))
    write(OUT/'方案对照.json',comparisons)
    lines=['| 保障组 | 成功率 | 完整任务均值 | 取消均值 | 等待架·小时 | 作业架·小时 | 72h资源利用率 |','|---|---:|---:|---:|---:|---:|---:|']
    for x in comparisons:lines.append(f'| {x["groups"]} | {x["success_rate"]:.3%} | {x["completed"]:.3f} | {x["cancelled"]:.3f} | {x["wait_aircraft_hours"]:.3f} | {x["work_aircraft_hours"]:.3f} | {x["resource_utilization"]:.3%} |')
    report='''# v0.8 再次出动保障案例（2026-09-11）

12架飞机，4类组件各MTBF400运行小时，整机100小时，指数MTTR均值2小时。每天09/12/15起飞，连续3天，每波2架；DURN3小时，出航/返航各1/6，成功点5/6。故障整队中止、空中不替补；返航期间故障仍累计，落地后维修。无初始备件、拆装零耗时。

半小时为回收或修复后的一次完整再次出动准备，等待不计入半小时；每架同时需要1个GROUND_CREW，组合资源原子申请，连续24h可用。1/2/4组分别1000轮，仅改变组数；主方案2组。用户确认DAILY_READY=Y：每天首波健康地面飞机假定提前准备好；未完准备可由假设接续完成并释放资源，另记assumed_jobs，不算正常完工；不修复故障飞机。此假设将首波保障能力排除在本模型资源评估之外。

## 主案例结果

'''+ '\n'.join(lines)+'''

均为每轮3天的统计。资源利用率按忙碌组·小时/(组数×72小时)，不是仅在保障作业时段的利用率。成功率若相同，应解释为此机队和任务密度下备用余量吸收了等待，不能据此认为资源约束无效。主种子20260908；未建立按任务配对随机流，不称为成对试验。

## 确定性紧周转用例

单独使用2架、无故障、任务飞行2.5小时（09:00→11:30），准备半小时，仍09/12/15起飞。1组先完成1架，另一架12:30才就绪，12点双机任务取消：3天起飞6次；2组并行可在12点同时完成并起飞，3天9次。此用例明确改变飞行时长，仅用于验证资源和同刻边界，不与主案例混算。

## 复核与使用

每方案包含输入、1000行逐轮指标、9000条任务判定、全部准备作业CSV、统计区间、模型与完整结果包。逐轮核验48部件、9任务与准备作业状态守恒；准备等待=班内资源/队列等待+班次等待；实际作业时间与飞机准备状态积分一致。原生CSV复算一致，首轮源码重放与exe一致。未配置新字段的v0.7原案例重新1000轮，飞行数值与首轮事件保持一致。

双击根目录“启动SimLab.cmd”，在项目库搜索“飞机再次出动保障”，选2组方案。其他电脑可导入本目录的simproj。资源组数在ResourceAllocation.RQTY；准备资源需求在TaskResource.QTY；半小时在SimLabFlightRule.PREP_H。结果分析查看准备资源评估、再次出动准备、取消原因；可原生导出全轮作业CSV。

复现：依次运行`.venv/Scripts/python.exe tools/run_aircraft_ground_case.py prepare`、同脚本`run --exe dist/SimLab/SimLab.exe`、同脚本`report`。首波假设、固定FIFO、跨班继续及单作业为本版明确口径；后续多工序拆分尚未实现，原厂数值等价未认证。
'''
    (OUT/'评估报告.md').write_text(report,encoding='utf-8')
    print(json.dumps(comparisons),flush=True)
    print('PASS: 3000 runs, native exports, job/aircraft/component accounting, package roundtrip and replay',flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('action',choices=['prepare','run','report']);parser.add_argument('--exe',type=Path,default=ROOT/'dist/SimLab/SimLab.exe')
    args=parser.parse_args();OUT.mkdir(parents=True,exist_ok=True);WORK.mkdir(parents=True,exist_ok=True)
    if args.action=='prepare':prepare()
    elif args.action=='run':run(args.exe)
    else:report()
