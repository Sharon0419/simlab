"""v0.7 controlled 2/4/12-aircraft assessment through the desktop worker."""
import argparse
import copy
import csv
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import uuid
import numpy as np

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from simlab.engine import simulate,t95,run_one
from simlab.compiler import compile_model
from simlab.flight_results import export_tasks
from simlab.project import new_project,save_project,load_project,export_package,import_package,model_hash

OUT=ROOT/'docs/cases/2026-09-08-aircraft-three-days/success-v0.7'
WORK=ROOT/'build/aircraft-success'


def read(path):return json.loads(path.read_text(encoding='utf-8'))
def write(path,data):path.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')


def prepare():
    base=read(OUT.parent/'phases-v0.6/输入.json')
    base['MissionType'][0]['MSUCPT']=str(5/6)
    for count in (2,4,12):
        tables=copy.deepcopy(base)
        assert len(tables['SystemDeployment'])==1
        tables['SystemDeployment'][0]['QTYPS']=str(count)
        config=compile_model(tables)
        assert config['count']==count and config['replications']==1000
        write(WORK/f'input-{count}.json',tables)
        write(OUT/f'输入-{count}架.json',tables)
    nofault=copy.deepcopy(base);nofault['Control'][0]['NREPS']='1'
    for r in nofault['Item']:r['FRT']='0'
    for fraction in (0,5/6,1):
        nofault['MissionType'][0]['MSUCPT']=str(fraction)
        result=simulate(nofault);f=result['mission']['flight']
        assert f['successful']==f['completed']==9 and f['successful_aircraft_sorties']==18
        assert result['mission']['supplied_hours']==54
    write(OUT/'无故障验收.json',result)
    print('PASS: 2/4/12 inputs prepared; 0, 5/6, 1 success points verified without faults',flush=True)


def run(exe):
    for count in (2,4,12):
        output=WORK/f'result-{count}.json'
        # Worker writes an explicit result file; fail fast rather than reading stale output.
        if output.exists():output.unlink()
        process=subprocess.run([str(exe.resolve()),'--worker',str(WORK/f'input-{count}.json'),str(output)],
                               creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
        if process.returncode or not output.exists():raise RuntimeError(f'{count}-aircraft worker failed: {process.returncode}')
        result=read(output)
        assert result['engine']=='0.7.0' and result['replications']==1000
        print(f'PASS: packaged worker {count} aircraft / 1000 replications',flush=True)


def report():
    comparisons=[]
    for count in (2,4,12):
        tables=read(WORK/f'input-{count}.json');r=read(WORK/f'result-{count}.json')
        assert r['engine']=='0.7.0' and r['model_hash']==model_hash(tables)
        assert len(r['replication_results'])==r['replications']==1000
        per_rep=[]
        for i,one in enumerate(r['replication_results'],1):
            m=one['mission'];f=m['flight'];tasks=m['tasks']
            assert one['parts']['initial']==one['parts']['final']==count*4
            assert f['requested']==f['started']+f['cancelled']==9
            assert f['started']==f['completed']+f['aborted']
            assert f['successful']==sum(t['successful'] for t in tasks)
            assert f['successful_aircraft_sorties']==sum(len(t['successful_members']) for t in tasks)==2*f['successful']
            assert f['requested_aircraft_sorties']==18
            assert f['aircraft_sorties']==2*f['started']
            assert f['success_rate']==f['successful']/9
            assert f['completed']<=f['successful']<=f['started']
            assert abs(m['supplied_hours']+m['gap_hours']-54)<1e-8
            actual=sum(f[k] for k in ('out_aircraft_hours','on_station_aircraft_hours','return_aircraft_hours'))
            assert abs(actual-m['supplied_hours']-f['abort_return_aircraft_hours'])<1e-8
            for t in tasks:
                expected=t['launched_at'] is not None and t['ended_at']>=t['success_point']
                assert t['successful']==expected
                assert t['success_at']==(t['success_point'] if expected else None)
                assert t['successful_members']==(t['members'] if expected else [])
            per_rep.append(dict(replication=i,availability=one['availability'],failures=one['failures'],
                effective_supply_aircraft_hours=m['supplied_hours'],fulfillment=m['fulfillment'],**f))
        stats={}
        for key in per_rep[0]:
            if key=='replication':continue
            a=np.array([row[key] for row in per_rep]);mean=float(a.mean());std=float(a.std(ddof=1));half=t95(len(a))*std/math.sqrt(len(a))
            stats[key]=dict(mean=mean,std=std,ci95=[mean-half,mean+half],p05=float(np.quantile(a,.05)),p95=float(np.quantile(a,.95)))
            if key in r['mission']['flight']:assert abs(mean-r['mission']['flight'][key])<1e-10
        with (OUT/f'逐轮指标-{count}架.csv').open('w',encoding='utf-8-sig',newline='') as file:
            w=csv.DictWriter(file,fieldnames=per_rep[0]);w.writeheader();w.writerows(per_rep)
        project=new_project(f'飞机成功点 · {count}架备用池 · 1000次')
        project['tables']=tables
        run=dict(id=uuid.uuid4().hex,name='成功点5/6 · 每波2架 · 3天',status='completed',started=r['created'],
                 source_revision=project['revision'],snapshot=copy.deepcopy(tables),model_hash=r['model_hash'],result=r)
        project['runs']=[run]
        export_tasks(run,OUT/f'逐轮任务判定-{count}架.csv',True)
        export_tasks(run,OUT/f'任务汇总-{count}架.csv')
        with (OUT/f'逐轮任务判定-{count}架.csv').open(encoding='utf-8-sig',newline='') as file:
            rows=list(csv.DictReader(file))
        assert len(rows)==9000 and sum(x['successful']=='True' for x in rows)==sum(x['successful'] for x in per_rep)
        export_package(project,OUT/f'飞机成功点-{count}架-含1000次结果.simproj')
        export_package(project,OUT/f'飞机成功点-{count}架-模型.simproj',False)
        assert import_package(OUT/f'飞机成功点-{count}架-含1000次结果.simproj')['runs'][0]['result']==r
        summary=dict(engine=r['engine'],seed=r['seed'],replications=1000,model_hash=r['model_hash'],statistics=stats)
        if count==12:
            path=Path(os.environ['LOCALAPPDATA'])/'SimLab/projects'/f'aircraft-success-{project["id"][:12]}.sqlite'
            save_project(project,path);assert load_project(path)['runs'][0]['result']==r
            summary['project_path']=str(path)
            # Same engine and seed: first replication reproduced exactly, including events.
            again=run_one(compile_model(tables),0)
            assert again['mission']==r['replication_results'][0]['mission']
            assert again['events']==r['events']
        write(OUT/f'统计汇总-{count}架.json',summary)
        f=r['mission']['flight']
        comparisons.append(dict(aircraft=count,**{k:f[k] for k in ('started','successful','completed','aborted','cancelled','success_rate','completion_rate','all_successful')},
                                fulfillment=r['mission']['fulfillment']))
    write(OUT/'方案对照.json',comparisons)
    lines=['| 可选飞机数 | 起飞数均值 | 成功数均值 | 完整数均值 | 取消数均值 | 成功率FMSUC | 完整完成率 |',
           '|---|---:|---:|---:|---:|---:|---:|']
    for x in comparisons:
        lines.append(f'| {x["aircraft"]} | {x["started"]:.3f} | {x["successful"]:.3f} | {x["completed"]:.3f} | {x["cancelled"]:.3f} | {x["success_rate"]:.3%} | {x["completion_rate"]:.3%} |')
    text='''# v0.7 飞机任务成功点评估（2026-09-11）

## 输入与规则

主案例12架飞机，动力/航电/电源/液压各1件；每组件MTBF400运行小时，整机100小时；指数MTTR均值2小时。每波2架，每天09/12/15点起飞，连续3天共9波。DURN=3小时，出航/返航各1/6（各30分钟），任务区2小时，MSUCPT=5/6（起飞150分钟后）。每天08:30全池保障，回收或修复后重新保障30分钟；待命/准备不累计运行故障；无初始备件、拆装零耗时、维修和保障资源无容量约束，落地后多故障LRU沿用串行处理。

12点回收的飞机需重新保障，不能直接参加12点起飞；从其他就绪飞机选取。故障整队中止，空中不换机。达到成功点即成功，同刻故障也成功，后续返航中止不撤销成功。每轮72小时，种子20260908，v0.7.0桌面计算进程。

## 同版本单因素对照

每种配置1000轮；仅改变可选机池为2、4、12架，其余参数相同。采用共同主种子，但未建立按任务对应的随机流，不能据此称为成对试验或给出成对差值置信区间。

'''+ '\n'.join(lines)+'''

2架配置的取消不全由故障造成：3小时飞行+半小时重新保障使同一对飞机无法连续承担间隔3小时的波次。4/12架则可轮换。成功率和完整完成率分母均是请求的9个编队任务；成功可与中止并存，不能相加为互斥分类。

## 评估结构与复核

每配置：逐轮指标1000行、逐轮任务判定9000行、任务汇总9行、输入JSON、统计JSON（均值/标准差/95%均值区间/P05/P95）、模型与含结果simproj。逐轮判定由软件原生导出函数生成，含成功时刻、原因、阶段、起飞/中止/落地和飞机成员，可复算NMSUC/NSYSU/FMSUC。请求飞机架次每轮18，与机队数量不同。

已逐轮检查：部件数守恒、9任务状态守恒、请求54架·小时守恒、实际三阶段时间=有效供给+中止返航、成功时刻及成功成员、汇总/CSV/完整项目往返一致；12架首轮重跑与桌面事件和明细完全一致。无故障12架在成功点0、5/6、1均为9次成功及完整完成。

## 启动与复现

主案例：双击根目录“启动SimLab.cmd”，在项目库选择本案例；其他容量用“导入项目”打开对应simproj。结果分析中的“任务成功率”“首轮成功判定”“逐轮飞行CSV”分别查看汇总和全轮明细。

复现命令（在项目根目录）：

```
.venv/Scripts/python.exe tools/run_aircraft_success_case.py prepare
.venv/Scripts/python.exe tools/run_aircraft_success_case.py run --exe dist/SimLab/SimLab.exe
.venv/Scripts/python.exe tools/run_aircraft_success_case.py report
```

上述为本地固定编队子集实现；原厂手册字段口径已核对，原厂数值对照未认证。时间指标仍用本地名称，详见../../../METRIC_DICTIONARY.md。
'''
    (OUT/'评估报告.md').write_text(text,encoding='utf-8')
    print(json.dumps(comparisons,ensure_ascii=True),flush=True)
    print('PASS: 3000 replications, 27000 task rows, conservation, native CSV, package roundtrips and reproducibility',flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('action',choices=['prepare','run','report'])
    parser.add_argument('--exe',type=Path,default=ROOT/'dist/SimLab/SimLab.exe')
    args=parser.parse_args()
    OUT.mkdir(parents=True,exist_ok=True);WORK.mkdir(parents=True,exist_ok=True)
    if args.action=='prepare':prepare()
    elif args.action=='run':run(args.exe)
    else:report()
