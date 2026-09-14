"""Prepare and report the aircraft component-failure experiment; worker runs separately."""
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

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from simlab.compiler import compile_model
from simlab.engine import t95
from simlab.project import new_project, now, model_hash, save_project, load_project, export_package, import_package

parser = argparse.ArgumentParser()
parser.add_argument('action', choices=['prepare', 'report'])
parser.add_argument('--scope', choices=['component', 'aircraft'], default='component')
args = parser.parse_args()
OUT = ROOT/'docs/cases/2026-09-08-aircraft-three-days'/('random-1000-'+args.scope)
OUT.mkdir(parents=True, exist_ok=True)
work = ROOT/'build'/('aircraft-random-'+args.scope)
work.mkdir(parents=True, exist_ok=True)
components = [('POWERPLANT','动力组件'), ('AVIONICS','航电组件'), ('ELECTRICAL','电源组件'), ('HYDRAULIC','液压组件')]
if args.action == 'prepare':
    tables = json.loads((ROOT/'build/aircraft-1000/input.json').read_text(encoding='utf-8'))
    rate = 10000 if args.scope == 'component' else 2500
    tables['System'][0]['DESCR'] = '飞机：4类关键组件，随机故障与修复'
    tables['Item'] = [dict(IID=i, TYPE='LRU', DESCR=n, FRT=str(rate), OPID='OPHOURS', CRIT='1', AFFRT='1') for i,n in components]
    tables['MaterielStructure'] = [dict(MMID='AIRCRAFT', MID=i, QTYPM='1', ENVF='1') for i,n in components]
    tables['StockAllocation'] = [dict(POINT='AIRCASE', IID=i, STID='AIRPORT', STSIZ='0') for i,n in components]
    tables['ItemRepair'] = [dict(IID=i, STID='AIRPORT', DIRPT='2', DIRPD='<EXP>', SURPT='0') for i,n in components]
    tables['ItemReplacement'] = [dict(MID='AIRCRAFT', IID=i, STID='AIRPORT', SURPT='0') for i,n in components]
    config = compile_model(tables)
    assert config['count'] == 12 and config['replications'] == 1000
    assert all(len(f['parts']) == 4 for f in config['fleets'])
    assert all(abs(p['rate']-rate/1e6)<1e-12 for f in config['fleets'] for p in f['parts'])
    assert all(r['time'] == dict(mean=2.0, random=True) for r in config['repairs'].values())
    for dest in (OUT/'输入.json', work/'input.json'):
        dest.write_text(json.dumps(tables,ensure_ascii=False,indent=2),encoding='utf-8')
    print('Validated: 12 aircraft, 48 components, 1000 trials; component MTBF', 1e6/rate, 'h; exponential MTTR 2h')
    sys.exit()

tables = json.loads((work/'input.json').read_text(encoding='utf-8'))
result = json.loads((work/'result.json').read_text(encoding='utf-8'))
assert result['model_hash'] == model_hash(tables)
assert result['replications'] == len(result['replication_results']) == 1000
rows = []
for index,r in enumerate(result['replication_results'],1):
    assert r['parts']['initial'] == r['parts']['final'] == 48
    assert sum(r['item_failures'].values()) == r['failures']
    assert 0 <= r['availability'] <= 1
    flights = [t for t in r['mission']['tasks'] if t['type']=='FLIGHT']
    assert len(flights)==9
    assert abs(sum(t['demand_hours'] for t in flights)-36)<1e-8
    supplied = sum(t['supplied_hours'] for t in flights)
    gap = sum(t['gap_hours'] for t in flights)
    assert abs(supplied+gap-36)<1e-8
    assert abs(r['mission']['supplied_hours']+r['mission']['gap_hours']-45)<1e-8
    row = dict(replication=index, availability=r['availability'], failures=r['failures'],
        flight_aircraft_hours=supplied, flight_gap_aircraft_hours=gap, STF=supplied/36,
        full_flight_windows=sum(t['gap_hours']<1e-9 for t in flights),
        fully_met_three_days=int(all(t['gap_hours']<1e-9 for t in flights)),
        preparation_aircraft_hours=sum(t['supplied_hours'] for t in r['mission']['tasks'] if t['type']=='PREFLIGHT'),
        fleet_downtime_hours=sum(r['downtime'].values())*12)
    row.update({i+'_failures':r['item_failures'].get(i,0) for i,n in components})
    rows.append(row)
assert sum(r['failures'] for r in rows)>0 and np.std([r['availability'] for r in rows])>0
with (OUT/'逐轮指标.csv').open('w',encoding='utf-8-sig',newline='') as f:
    w=csv.DictWriter(f,fieldnames=rows[0]); w.writeheader(); w.writerows(rows)
stats={}
for key in rows[0]:
    if key=='replication': continue
    a=np.array([r[key] for r in rows],dtype=float)
    mean=float(a.mean()); sd=float(a.std(ddof=1)); half=t95(len(a))*sd/math.sqrt(len(a))
    stats[key]=dict(mean=mean,std=sd,p05=float(np.quantile(a,.05)),p95=float(np.quantile(a,.95)),ci95=[mean-half,mean+half])
assert abs(stats['availability']['mean']-result['availability'])<1e-10
p=new_project('飞机随机故障 · 1000次 · '+('组件MTBF100h' if args.scope=='component' else '整机MTBF100h'))
p['tables']=tables
p['runs'].append(dict(id=uuid.uuid4().hex,name='四组件随机故障：MTTR均值2小时',status='completed',
    started=result.get('created',now()),source_revision=p['revision'],snapshot=copy.deepcopy(tables),
    model_hash=model_hash(tables),result=result))
path=Path(os.environ['LOCALAPPDATA'])/'SimLab/projects'/f'aircraft-random-{p["id"][:12]}.sqlite'
save_project(p,path)
assert load_project(path)['runs'][0]['result']==result
package=OUT/'飞机随机故障1000次-含结果.simproj'
export_package(p,package)
assert import_package(package)['runs'][0]['result']==result
summary=dict(project_path=str(path),replications=1000,scope=args.scope,model_hash=result['model_hash'],statistics=stats,
    checks=['1000 replications verified','48 parts conserved each run','flight demand=supply+gap',
            'component failures sum to aircraft failures','nonzero stochastic variance','SQLite and simproj exact result roundtrip'])
(OUT/'统计汇总.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
metric_rows=[]
for key,label,unit in [('availability','健康可用度','%'),('failures','故障次数','次'),('flight_aircraft_hours','实际飞行装备时间 STACC','架·小时'),
    ('STF','飞行装备时间满足率 STF','%'),('flight_gap_aircraft_hours','飞行装备小时缺口','架·小时'),
    ('full_flight_windows','全程双机满足的飞行窗口','次'),('fully_met_three_days','三天9个飞行窗口全部满足的试验比例','%'),
    ('preparation_aircraft_hours','实际保障占用','架·小时'),('fleet_downtime_hours','全机队故障停机时间','架·小时')]:
    s=stats[key]; scale=100 if unit=='%' else 1
    metric_rows.append(f"| {label} | {s['mean']*scale:.4f} {unit} | {s['p05']*scale:.4f}–{s['p95']*scale:.4f} | {s['ci95'][0]*scale:.4f}–{s['ci95'][1]*scale:.4f} |")
component_mtbf=100 if args.scope=='component' else 400
report=f'''# 飞机组件随机故障案例：1000次运行

## 模型输入

沿用12架飞机、固定2架承担任务、10架备用但不替补的三天计划；每天09:00、12:00、15:00起飞，飞行2小时，出动前保障半小时。每轮72小时，重复1000次，种子20260908。每轮独立重置。

每架增加动力、航电、电源、液压4类LRU，各1件，全机队48件。每个组件MTBF={component_mtbf}运行小时，指数故障间隔；FRT={1e6/component_mtbf:g}次/百万运行小时。四个关键组件为独立串联，整机名义运行MTBF={component_mtbf/4:g}小时。系统独立故障率为0，避免重复计算。

各组件修复时间为指数分布，均值MTTR=2小时（不是每次固定2小时）。无初始备件，无维修人员容量限制，拆装时间0。故障件进入修复，修复返库后用于恢复飞机；引擎可能将这段飞机停机归入“等待备件”，不等于另外增加了供应延迟。随机样本平均修复时间不必恰好等于2小时，本报告未将输入均值伪装成实测MTTR。

## 结果：每轮三天场景

| 指标 | 1000轮均值 | 逐轮P05–P95 | 均值95%区间 |
|---|---:|---:|---:|
{chr(10).join(metric_rows)}

请求飞行任务仍为9次，计划18架次，STREQ为36架·小时。发生缺口时不能将计划架次直接称为完整完成架次。各组件故障均值：

'''
for iid,name in components:
    report+=f"- {name}：{stats[iid+'_failures']['mean']:.4f}次/轮。\n"
report+='''
## 解释与边界

可用度的分母包含12架飞机×72小时，其中10架始终备用且不积累运行故障，因此较高的全机队可用度不能代表双机编队任务有同等保障水平。应同时查看STF、缺口和全程满足窗口。

当前模型将PREFLIGHT作为独立值守任务，保障占用也累积故障暴露；备用和任务间等待不累积运行故障。STACC仅汇总FLIGHT阶段，排除了保障占用。

本轮是当前SimLab固定窗口引擎的随机故障试验，不是原厂SIMLOX结果。引擎允许窗口内故障退出、修复后再参与；没有真实飞行中返航/中断、双机整体起飞、保障完成依赖及备用机接替状态链。因此“全程双机满足窗口”不是原厂FMSUC，也不能解读成真实飞行成功率；部分窗口累计供给时间也不是已飞完架次。未报告语义尚不完整的MTACC、MTF或实际起飞成功率。

P05/P95为逐轮总量分位数，95%区间为跨1000轮均值的t区间；两者含义不同，也不能替代原厂所有时间聚合分位指标。资源利用率未建模，不填0%。

## 文件与运行

双击根目录“启动SimLab.cmd”，在项目库选择本案例打开保存结果；也可导入本目录“飞机随机故障1000次-含结果.simproj”。输入、逐轮CSV及统计JSON一起保存。原无故障项目保留。

复现：先运行 `.venv/Scripts/python.exe tools/run_aircraft_random_case.py prepare` 生成输入，再用 `dist/SimLab/SimLab.exe --worker build/aircraft-random-component/input.json build/aircraft-random-component/result.json` 仿真，最后执行 `.venv/Scripts/python.exe tools/run_aircraft_random_case.py report`。整机MTBF100口径需在脚本命令增加 `--scope aircraft` 并使用对应工作目录。

验证：逐轮检查部件数量守恒、任务供需守恒、组件故障合计和随机方差；保存后完整重新读取SQLite和simproj并与worker结果比较一致。
'''
(OUT/'评估报告.md').write_text(report,encoding='utf-8')
print(json.dumps(summary,ensure_ascii=True))
