"""Prepare/review the v0.5 shared-reserve aircraft case using a real worker result."""
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
from simlab.compiler import compile_model
from simlab.engine import simulate, t95
from simlab.project import new_project, model_hash, save_project, load_project, export_package, import_package

parser=argparse.ArgumentParser()
parser.add_argument('action',choices=['prepare','report'])
args=parser.parse_args()
OUT=ROOT/'docs/cases/2026-09-08-aircraft-three-days/reserve-v0.5'
WORK=ROOT/'build/aircraft-reserve'
OUT.mkdir(parents=True,exist_ok=True); WORK.mkdir(parents=True,exist_ok=True)
if args.action=='prepare':
    tables=json.loads((OUT.parent/'random-1000-aircraft/输入.json').read_text(encoding='utf-8'))
    tables['Unit']=[dict(UNID='FLIGHT_POOL',STID='AIRPORT',DESCR='12架已保障共同选机池')]
    tables['SystemDeployment']=[dict(SID='AIRCRAFT',USTID='FLIGHT_POOL',QTYPS='12',UTIL='1')]
    tables['MissionType']=[dict(MTID='FLIGHT',NOS='2',MNOS='2',MNOSA='2',DURN='2',DESCR='双机固定飞行：空中故障整队中止')]
    tables['MissionSystem']=[dict(MTID='FLIGHT',SID='AIRCRAFT')]
    tables['Operations']=[dict(USTID='FLIGHT_POOL',PRID='THREE_DAYS')]
    tables['OperationProfile']=[dict(PRID='THREE_DAYS',SPRID='FLIGHT',STIM=str(d*24+h)) for d in range(3) for h in (9,12,15)]
    tables.pop('SimLabDutyRule',None)
    tables['SimLabFlightRule']=[dict(MTID='FLIGHT',PREP_H='.5')]
    config=compile_model(tables)
    assert config['replications']==1000 and config['count']==12 and len(config['missions'])==9
    assert all(abs(p['rate']-.0025)<1e-12 for p in config['fleets'][0]['parts'])
    baseline=copy.deepcopy(tables)
    baseline['Control'][0]['NREPS']='1'
    for r in baseline['Item']: r['FRT']='0'
    result=simulate(baseline)
    assert result['mission']['supplied_hours']==36
    assert result['mission']['flight']['completed']==9
    assert result['mission']['flight']['preparation_aircraft_hours']==27
    for dest in (OUT/'输入.json',WORK/'input.json'):
        dest.write_text(json.dumps(tables,ensure_ascii=False,indent=2),encoding='utf-8')
    (OUT/'无故障验收.json').write_text(json.dumps(result,ensure_ascii=False),encoding='utf-8')
    print('Prepared: 12-aircraft pool, 4 components x MTBF400h, EXP MTTR2h, 1000 trials; no-failure acceptance PASS')
    sys.exit()

tables=json.loads((WORK/'input.json').read_text(encoding='utf-8'))
result=json.loads((WORK/'result.json').read_text(encoding='utf-8'))
assert result['engine']=='0.5.0' and result['model_hash']==model_hash(tables)
assert result['replications']==len(result['replication_results'])==1000
rows=[]
for i,r in enumerate(result['replication_results'],1):
    m=r['mission']; f=m['flight']
    assert r['parts']['initial']==r['parts']['final']==48
    assert f['completed']+f['aborted']+f['cancelled']==f['requested']==9
    assert f['started']==f['completed']+f['aborted']
    assert f['aircraft_sorties']==2*f['started']
    assert abs(m['supplied_hours']+m['gap_hours']-36)<1e-8
    assert r['failures']==sum(r['item_failures'].values())
    assert r['failures']>=f['aborted']
    assert all(t['flight_status'] in ('completed','aborted','cancelled') for t in m['tasks'])
    for t in m['tasks']:
        assert len(t['members']) in (0,2) and len(set(t['members']))==len(t['members'])
        assert t['launched_at'] is None or t['launched_at']==t['start']
        if t['flight_status']=='completed': assert abs(t['supplied_hours']-4)<1e-8
    rows.append(dict(replication=i,availability=r['availability'],failures=r['failures'],
        flight_aircraft_hours=m['supplied_hours'],flight_gap_aircraft_hours=m['gap_hours'],STF=m['fulfillment'],
        completion_rate=f['completed']/9,**f))
assert sum(r['failures'] for r in rows)>0
with (OUT/'逐轮指标.csv').open('w',encoding='utf-8-sig',newline='') as f:
    w=csv.DictWriter(f,fieldnames=rows[0]);w.writeheader();w.writerows(rows)
with (OUT/'首轮事件.csv').open('w',encoding='utf-8-sig',newline='') as f:
    w=csv.DictWriter(f,fieldnames=['time','asset','event','item']);w.writeheader();w.writerows(result['events'])
stats={}
for key in rows[0]:
    if key=='replication':continue
    values=np.array([r[key] for r in rows]);mean=float(values.mean());sd=float(values.std(ddof=1))
    half=t95(1000)*sd/math.sqrt(1000)
    stats[key]=dict(mean=mean,std=sd,p05=float(np.quantile(values,.05)),p95=float(np.quantile(values,.95)),ci95=[mean-half,mean+half])
p=new_project('飞机备用机案例 · v0.5 · 全池保障 · 1000次')
p['tables']=tables
p['runs'].append(dict(id=uuid.uuid4().hex,name='整机MTBF100h / MTTR2h / 全池备用',status='completed',started=result['created'],
    source_revision=p['revision'],snapshot=copy.deepcopy(tables),model_hash=model_hash(tables),result=result))
path=Path(os.environ['LOCALAPPDATA'])/'SimLab/projects'/f'aircraft-reserve-{p["id"][:12]}.sqlite'
save_project(p,path)
assert load_project(path)['runs'][0]['result']==result
export_package(p,OUT/'飞机备用机-含1000次结果.simproj')
export_package(p,OUT/'飞机备用机-模型.simproj',False)
assert import_package(OUT/'飞机备用机-含1000次结果.simproj')['runs'][0]['result']==result
summary=dict(project_path=str(path),replications=1000,statistics=stats,model_hash=result['model_hash'],engine=result['engine'])
(OUT/'统计汇总.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
lines=[]
for key,label in [('availability','健康可用度'),('failures','故障次数'),('started','起飞编队数'),('completed','完整完成编队数'),('aborted','中止编队数'),('cancelled','起飞前取消数'),('aircraft_sorties','实际起飞架次'),('completed_aircraft_sorties','完整完成架次'),('flight_aircraft_hours','飞行装备时间'),('STF','飞行装备时间满足率'),('completion_rate','编队完整完成率'),('all_completed','整轮9项全部完成比例'),('preparation_aircraft_hours','保障装备时间'),('ready_aircraft_hours','已保障待命装备时间')]:
    s=stats[key]; scale=100 if key in ('availability','STF','completion_rate','all_completed') else 1
    suffix='%' if scale==100 else ''
    lines.append(f"| {label} | {s['mean']*scale:.4f}{suffix} | {s['p05']*scale:.4f}–{s['p95']*scale:.4f} | {s['ci95'][0]*scale:.4f}–{s['ci95'][1]*scale:.4f} |")
report='''# 飞机备用机案例：v0.5、1000次

## 输入与新规则

12架飞机进入同一选机池，每天08:30开始全池半小时保障；09:00、12:00、15:00各起飞一个双机编队，计划飞行2小时，连续3天。首波前12架全部保障好；其余未出动飞机保持当天已保障待命状态。回收或修复后重新执行半小时保障，包括每日最后一次回收。选机按累计出动次数少者优先，同次数按飞机编号；不再固定两架一直执行。

起飞时必须有2架健康且已保障飞机，原子分配并起飞，否则取消（不允许延迟）。出动前可从整个就绪池选机；飞行后任一关键组件故障则整队中止，不能用地面备用机补入，也不能修好后恢复该次任务。返航耗时本版明确按0处理，未模拟飞行轨迹；若需要真实返航耗时，需进一步扩展。

动力、航电、电源、液压各1件/架，共48组件；每组件MTBF400运行小时，串联整机名义MTBF100运行小时。各组件修复时间指数分布，均值2小时。无初始备件、拆装耗时0、维修和保障无人员容量约束。仅飞行累积随机故障；准备、已保障待命和维修不累积运行故障。每轮72小时独立重置，1000次，种子20260908。

## 每轮三天结果

| 指标 | 均值 | 逐轮P05–P95 | 均值95%区间 |
|---|---:|---:|---:|
'''+ '\n'.join(lines)+'''

准备时间与飞行时间分别统计；STREQ=36架·小时，计划9个编队任务、18架次。完整完成必须从起飞到计划落地均无关键故障；这是本地固定飞行完成判据，不声称等价于原厂FMSUC。均值区间表示重复试验统计精度，不包含模型假设误差。

## 与上一轮的区别

旧版随机案例：固定2架、备用不参与；保障也计故障暴露；飞行窗口允许退出后恢复，允许部分供给。新版：全池选机、保障独立、不在空中补位、整队中止。两轮同时改变了多个机制，因此数值变化不能全部解释为“备用机效益”。如要单独测备用效益，应在同一新版引擎下只改变可选机数量。

无故障验收：9次编队任务、18架次、36架·小时飞行，27架·小时保障（每日全机首次保障18，加18架次回收后保障9）。已保存无故障验收结果供复核。

## 打开与复现

双击根目录“启动SimLab.cmd”，在项目库选择本案例。软件“结果分析→飞行与备用机”查看独立统计，“首轮事件”查看选机和准备日志；“模型数据”修改SimLabFlightRule.PREP_H及运行计划。案例包可导入v0.5及后续兼容版本，旧v0.4不支持新增规则。

复现：`.venv/Scripts/python.exe tools/run_aircraft_reserve_case.py prepare`，再用 `dist/SimLab/SimLab.exe --worker build/aircraft-reserve/input.json build/aircraft-reserve/result.json`，最后运行 `.venv/Scripts/python.exe tools/run_aircraft_reserve_case.py report`。

验证逐轮48件守恒、9项状态守恒、供需小时守恒、整队成员数和准点启动；结果保存后SQLite与simproj完整读取一致。每个重复的任务对象保留成员、起飞与结束时间；首轮详细事件另导出CSV。
'''
(OUT/'评估报告.md').write_text(report,encoding='utf-8')
print(json.dumps(summary,ensure_ascii=True))
