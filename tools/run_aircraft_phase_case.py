"""Reproducible three-hour flight phase acceptance and 1000-run report."""
import argparse
import copy
import csv
import json
import math
import os
from pathlib import Path
import sys
import uuid
import numpy as np

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from simlab.engine import simulate, t95
from simlab.compiler import compile_model
from simlab.project import new_project,model_hash,save_project,load_project,export_package,import_package
parser=argparse.ArgumentParser()
parser.add_argument('action',choices=['prepare','report'])
args=parser.parse_args()
OUT=ROOT/'docs/cases/2026-09-08-aircraft-three-days/phases-v0.6'
WORK=ROOT/'build/aircraft-phases'
OUT.mkdir(parents=True,exist_ok=True);WORK.mkdir(parents=True,exist_ok=True)
if args.action=='prepare':
    tables=json.loads((OUT.parent/'reserve-v0.5/输入.json').read_text(encoding='utf-8'))
    tables['MissionType'][0].update(DURN='3',TFOUT=str(1/6),TFRET=str(1/6),DESCR='双机三阶段：出航30分钟、执行2小时、返航30分钟')
    config=compile_model(tables)
    assert config['count']==12 and config['replications']==1000
    baseline=copy.deepcopy(tables);baseline['Control'][0]['NREPS']='1'
    for row in baseline['Item']:row['FRT']='0'
    result=simulate(baseline);f=result['mission']['flight']
    assert result['mission']['supplied_hours']==54 and f['completed']==9
    assert (f['out_aircraft_hours'],f['on_station_aircraft_hours'],f['return_aircraft_hours'])==(9,36,9)
    assert f['preparation_aircraft_hours']==27
    for dest in (OUT/'输入.json',WORK/'input.json'):
        dest.write_text(json.dumps(tables,ensure_ascii=False,indent=2),encoding='utf-8')
    (OUT/'无故障验收.json').write_text(json.dumps(result,ensure_ascii=False),encoding='utf-8')
    print('PASS: phase input; no-fault OUT/ON/BACK aircraft hours = 9/36/9, 9 missions, 27 preparation hours')
    sys.exit()

tables=json.loads((WORK/'input.json').read_text(encoding='utf-8'))
result=json.loads((WORK/'result.json').read_text(encoding='utf-8'))
assert result['engine']=='0.6.0' and result['replications']==len(result['replication_results'])==1000
assert result['model_hash']==model_hash(tables)
rows=[]
for i,r in enumerate(result['replication_results'],1):
    m=r['mission'];f=m['flight']
    assert r['parts']['initial']==r['parts']['final']==48
    assert f['completed']+f['aborted']+f['cancelled']==9
    assert f['aircraft_sorties']==2*f['started']
    assert abs(m['supplied_hours']+m['gap_hours']-54)<1e-8
    actual=sum(f[k] for k in ('out_aircraft_hours','on_station_aircraft_hours','return_aircraft_hours'))
    assert abs(actual-m['supplied_hours']-f['abort_return_aircraft_hours'])<1e-8
    for task in m['tasks']:
        if task['launched_at'] is not None:
            assert task['launched_at']==task['start']
            assert len(task['members'])==2
            assert task['ended_at']<=task['landed_at']<=task['end']+1e-9
        if task['flight_status']=='completed':assert abs(task['supplied_hours']-6)<1e-8
    rows.append(dict(replication=i,availability=r['availability'],failures=r['failures'],
        effective_supply_aircraft_hours=m['supplied_hours'],gap_aircraft_hours=m['gap_hours'],
        actual_aircraft_flight_hours=actual,fulfillment=m['fulfillment'],
        completion_rate=f['completed']/9,**f))
assert sum(row['abort_return_aircraft_hours'] for row in rows)>0
with (OUT/'逐轮指标.csv').open('w',encoding='utf-8-sig',newline='') as f:
    w=csv.DictWriter(f,fieldnames=rows[0]);w.writeheader();w.writerows(rows)
with (OUT/'首轮阶段事件.csv').open('w',encoding='utf-8-sig',newline='') as f:
    w=csv.DictWriter(f,fieldnames=['time','asset','event','item']);w.writeheader();w.writerows(result['events'])
stats={}
for key in rows[0]:
    if key=='replication':continue
    a=np.array([row[key] for row in rows]);mean=float(a.mean());std=float(a.std(ddof=1))
    half=t95(1000)*std/math.sqrt(1000)
    stats[key]=dict(mean=mean,std=std,p05=float(np.quantile(a,.05)),p95=float(np.quantile(a,.95)),ci95=[mean-half,mean+half])
p=new_project('飞机三阶段 · 3小时 · 全池备用 · 1000次')
p['tables']=tables
p['runs'].append(dict(id=uuid.uuid4().hex,name='3小时：出航1/6、返航1/6',status='completed',started=result['created'],
    source_revision=p['revision'],snapshot=copy.deepcopy(tables),model_hash=model_hash(tables),result=result))
path=Path(os.environ['LOCALAPPDATA'])/'SimLab/projects'/f'aircraft-phases-{p["id"][:12]}.sqlite'
save_project(p,path);assert load_project(path)['runs'][0]['result']==result
export_package(p,OUT/'飞机三阶段-含1000次结果.simproj')
export_package(p,OUT/'飞机三阶段-模型.simproj',False)
assert import_package(OUT/'飞机三阶段-含1000次结果.simproj')['runs'][0]['result']==result
summary=dict(project_path=str(path),engine=result['engine'],replications=1000,model_hash=result['model_hash'],statistics=stats)
(OUT/'统计汇总.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
(ROOT/'打开飞机三阶段案例.cmd').write_bytes(('@echo off\r\nstart "" "%~dp0dist\\SimLab\\SimLab.exe" --project "'+str(path)+'"\r\n').encode('ascii'))
lines=[]
for key,label in [('started','起飞编队'),('completed','完整完成编队'),('aborted','中止编队'),('cancelled','起飞前取消'),
    ('out_aircraft_hours','实际出航架·小时'),('on_station_aircraft_hours','实际任务区架·小时'),('return_aircraft_hours','实际返航架·小时'),
    ('abort_return_aircraft_hours','其中中止返航架·小时'),('actual_aircraft_flight_hours','实际总飞行架·小时'),
    ('effective_supply_aircraft_hours','有效任务供给架·小时'),('fulfillment','有效任务时间满足率'),('completion_rate','编队完整完成率'),('all_completed','整轮全部完成比例')]:
    s=stats[key];scale=100 if key in ('fulfillment','completion_rate','all_completed') else 1;unit='%' if scale==100 else ''
    lines.append(f"| {label} | {s['mean']*scale:.4f}{unit} | {s['ci95'][0]*scale:.4f}–{s['ci95'][1]*scale:.4f} |")
report='''# v0.6 三阶段飞机案例：1000次

## 输入

12架、每波2架、每天09:00/12:00/15:00起飞、连续3天。MissionType：DURN=3；TFOUT=0.16666666666666666；TFRET=0.16666666666666666。对应每波出航0.5小时、任务区2小时、返航0.5小时。每天08:30开始全池保障；回收和维修后重新保障0.5小时。12点落地飞机不能直接参加12点起飞，下一波从其他已保障飞机中选取。

动力/航电/电源/液压各1件，每组件MTBF400运行小时，对应串联整机MTBF100小时。指数修复均值2小时、无初始备件、拆装时间0，无维修和保障资源容量约束。准备与待命不计运行故障；三段飞行和中止返航均继续暴露健康部件。每轮72小时、1000次独立重复，种子20260908。

## 执行规则

出航中故障：已出航时间/计划出航时间×计划返航时间；任务区故障：完整计划返航；返航中故障：剩余返航时间。任一关键故障使整队中止有效任务，但返航中仍占用原飞机。追加故障不重置返航终点。落地后故障LRU依次进入拆装和维修流程，健康机开始保障；有备件时可换件恢复。该串行处理多故障LRU规则是本地实现假设，不宣称等同原厂所有维修策略。

## 每轮三天结果

| 指标 | 均值 | 均值95%区间 |
|---|---:|---:|
'''+ '\n'.join(lines)+'''

中止返航包含在实际返航和实际总飞行时间内，但不计有效任务供给。因此不能把“实际总飞行时间”与“有效任务供给”混用；本地完成判据仍是全程未中止，尚未实现原厂MSUCPT/FMSUC成功点。比例控制时长，不设置起降独立故障倍率或轨迹模型。

无故障对照已核验：9次编队、18架次、出航9/任务区36/返航9架·小时，共54架·小时，保障27架·小时。

## 配置和打开

双击根目录“打开飞机三阶段案例.cmd”；在“模型数据→MissionType”编辑DURN、TFOUT、TFRET。比例填小数0～1，两者之和≤1；任务区比例自动取余量。须同时配置SimLabFlightRule，固定值守不接受非零比例。旧0/0比例继续有效。

“结果分析→飞行阶段”显示每波计划阶段时长及实际均值；“飞行与备用机”显示汇总；“首轮事件”可查看阶段切换、中止和落地。“逐轮指标.csv”含1000行和各阶段统计，“统计汇总.json”另含P05/P95。

复现：运行 `.venv/Scripts/python.exe tools/run_aircraft_phase_case.py prepare`，再执行 `dist/SimLab/SimLab.exe --worker build/aircraft-phases/input.json build/aircraft-phases/result.json`，最后 `.venv/Scripts/python.exe tools/run_aircraft_phase_case.py report`。

验证：逐轮48件守恒、9任务状态守恒、54小时需求守恒、阶段总时间=有效供给+中止返航、起飞/落地时刻、SQLite及simproj完整结果往返一致。原2小时案例保留；新项目应使用v0.6及后续兼容版本。
'''
(OUT/'评估报告.md').write_text(report,encoding='utf-8')
print(json.dumps(summary,ensure_ascii=True))
