"""Deterministic aircraft schedule acceptance in the existing v0.4 engine."""
import argparse
import copy
import csv
import json
import os
from pathlib import Path
import sys
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from simlab.compiler import compile_model
from simlab.engine import simulate
from simlab.project import new_project, now, model_hash, save_project, load_project, export_package, import_package

parser = argparse.ArgumentParser()
parser.add_argument('--formations', type=int, choices=(1, 6), default=1)
args = parser.parse_args()
OUT = ROOT/'docs'/'cases'/'2026-09-08-aircraft-three-days'
OUT.mkdir(parents=True, exist_ok=True)
formations = args.formations
spacing = 3
schedule = []
for day in range(3):
    for wave in range(3):
        departure = day*24 + 9 + wave*spacing
        preparation = departure - (.5 if wave == 0 else 1)
        schedule.append(dict(day=day+1, wave=wave+1, preparation=preparation, preparation_end=preparation+.5,
                             departure=departure, landing=departure+2, formations=formations, aircraft=2*formations))

p = new_project('飞机出动案例 · 12架 · 双机编队 · 三天三波')
units = [dict(UNID=f'F{i+1:02d}', STID='AIRPORT', DESCR=f'第{i+1}双机编队') for i in range(formations)]
deployments = [dict(SID='AIRCRAFT', USTID=u['UNID'], QTYPS='2', UTIL='1') for u in units]
if formations == 1:
    units.append(dict(UNID='RESERVE', STID='AIRPORT', DESCR='10架备用飞机（本排程不轮换）'))
    deployments.append(dict(SID='AIRCRAFT', USTID='RESERVE', QTYPS='10', UTIL='1'))
p['tables'] = {
    'System': [dict(SID='AIRCRAFT', DESCR='飞机（无故障排程验收）', FRT='0')],
    'Item': [dict(IID='AIRFRAME', TYPE='LRU', DESCR='机体占位件；FRT=0，不作可靠性预测', FRT='0')],
    'MaterielStructure': [dict(MMID='AIRCRAFT', MID='AIRFRAME', QTYPM='1')],
    'Station': [dict(STID='AIRPORT', TYPE='OP', DESCR='机场')],
    'Unit': units,
    'SystemDeployment': deployments,
    'StockAllocation': [dict(POINT='AIRCASE', IID='AIRFRAME', STID='AIRPORT', STSIZ='0')],
    # The current compiler requires a repair route even for a zero-failure asset.
    # These zero-time placeholders are never triggered in this acceptance case.
    'ItemRepair': [dict(IID='AIRFRAME', STID='AIRPORT', DIRPT='0', SURPT='0')],
    'ItemReplacement': [dict(MID='AIRCRAFT', IID='AIRFRAME', STID='AIRPORT', SURPT='0')],
    'MissionType': [dict(MTID='PREFLIGHT', DESCR='出动前保障（地面阶段）', NOS='2', MNOS='2', DURN='.5'),
                    dict(MTID='FLIGHT', DESCR='双机编队飞行', NOS='2', MNOS='2', DURN='2')],
    'MissionSystem': [dict(MTID=tid, SID='AIRCRAFT') for tid in ('PREFLIGHT', 'FLIGHT')],
    'Operations': [dict(USTID=f'F{i+1:02d}', PRID='THREE_DAYS') for i in range(formations)],
    'OperationProfile': [dict(PRID='THREE_DAYS', SPRID=tid, STIM=str(row[key]))
                         for row in schedule for tid, key in [('PREFLIGHT','preparation'), ('FLIGHT','departure')]],
    'SimLabDutyRule': [dict(MTID=tid, MIN_QTY='2', PRIORITY='1', RELIEF_H='0', TOLERANCE_H='0')
                       for tid in ('PREFLIGHT', 'FLIGHT')],
    'Control': [dict(NREPS='1', SIMPE='72', RSEED='20260908', APID='AIRCASE', RCINT=str(1/12),
                     ENPM='N', ENLAT='N', ENALU='N', RELOP='SERIAL', ENLOG='Y')],
}
config = compile_model(p['tables'])
assert config['count'] == 12
result = simulate(p['tables'])
m = result['mission']
flight = [t for t in m['tasks'] if t['type'] == 'FLIGHT']
ground = [t for t in m['tasks'] if t['type'] == 'PREFLIGHT']
expected_flights = formations * 9
assert len(flight) == len(ground) == expected_flights
assert sum(t['supplied_hours'] for t in flight) == expected_flights * 4
assert sum(t['supplied_hours'] for t in ground) == expected_flights
assert m['gap_hours'] == 0 and m['minimum_rate'] == m['qualified_rate'] == 1
assert result['failures'] == 0 and result['availability'] == 1
assert result['fleet_size'] == 12
assert result['replication_results'][0]['parts']['initial'] == result['replication_results'][0]['parts']['final'] == 12

# Read actual assignment events, rather than inferring aircraft identity from capacity.
assigned = {}
for event in result['events']:
    if event['event'] == '任务分配':
        assigned.setdefault(event['item'], set()).add(event['asset'])
for task in flight:
    prep = max((t for t in ground if t['location'] == task['location'] and t['end'] <= task['start']), key=lambda t:t['end'])
    assert prep['end']-prep['start'] == .5
    assert 0 <= task['start']-prep['end'] <= .5
    assert len(assigned[task['id']]) == 2
    assert assigned[task['id']] == assigned[prep['id']]
for unit in range(formations):
    ordered = sorted([t for t in m['tasks'] if t['location'] == f'F{unit+1:02d}'], key=lambda t:t['start'])
    assert all(a['end'] <= b['start'] for a,b in zip(ordered, ordered[1:]))
for day in range(1,4):
    waves = [r for r in schedule if r['day']==day]
    for a,b in zip(waves,waves[1:]):
        assert b['departure']-a['landing'] == 1
        assert b['preparation'] == a['landing']

p['runs'].append(dict(id=uuid.uuid4().hex, name='三天排程验收（无故障，1次确定性试验）', status='completed',
    started=now(), source_revision=p['revision'], snapshot=copy.deepcopy(p['tables']),
    model_hash=model_hash(p['tables']), result=result))
project_path = Path(os.getenv('LOCALAPPDATA', str(Path.home())))/'SimLab'/'projects'/f'aircraft-three-days-{p["id"][:12]}.sqlite'
project_path.parent.mkdir(parents=True, exist_ok=True)
save_project(p, project_path)
assert load_project(project_path)['runs'][0]['result']['mission'] == m
export_package(p, OUT/'飞机三天出动-模型.simproj', False)
export_package(p, OUT/'飞机三天出动-含结果.simproj')
assert import_package(OUT/'飞机三天出动-含结果.simproj')['runs'][0]['result']['mission'] == m
(OUT/'输入.json').write_text(json.dumps(p['tables'], ensure_ascii=False, indent=2), encoding='utf-8')
summary = dict(project_path=str(project_path), aircraft=12, formations_per_wave=formations, days=3, waves_per_day=3,
    total_waves=9, formation_sorties=expected_flights, aircraft_sorties=2*expected_flights,
    aircraft_flight_hours=4*expected_flights, aircraft_preparation_hours=expected_flights,
    combined_activity_hours=5*expected_flights, mission_gap_hours=m['gap_hours'],
    minimum_rate=m['minimum_rate'], qualified_rate=m['qualified_rate'],
    seed=result['seed'], model_hash=result['model_hash'], schedule=schedule,
    checks=['input compile','12 aircraft conservation','9 waves','flight/preparation hour arithmetic',
            'same two aircraft complete preparation before flight','no formation overlap',
            'one hour turnaround interpretation','SQLite reopen','simproj import roundtrip'])
(OUT/'结果汇总.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
with (OUT/'任务阶段结果.csv').open('w',encoding='utf-8-sig',newline='') as f:
    keys=['id','type','location','start','end','quantity','supplied_hours','gap_hours','qualified_rate']
    writer=csv.DictWriter(f,fieldnames=keys,extrasaction='ignore')
    writer.writeheader()
    writer.writerows(m['tasks'])
with (OUT/'飞机分配.csv').open('w',encoding='utf-8-sig',newline='') as f:
    writer=csv.writer(f)
    writer.writerow(['任务','阶段','编队','开始小时','结束小时','飞机1','飞机2'])
    for t in m['tasks']:
        writer.writerow([t['id'],t['type'],t['location'],t['start'],t['end'],*sorted(assigned[t['id']])])
def clock(hour):
    minutes=round((hour%24)*60)
    return f'{minutes//60:02d}:{minutes%60:02d}'
report=f'''# 飞机案例：12架、双机编队、三天重复出动

## 输入和采用口径

共有12架飞机，每个编队2架；本次每波出动{formations}个编队、{2*formations}架飞机，每天3波，连续3天。采用用户确认口径：每日09:00、12:00、15:00起飞，分别11:00、14:00、17:00回收。第一波08:30–09:00完成保障；回收后11:00–11:30、14:00–14:30完成再次出动准备，随后等待计划起飞。落地至下次起飞1小时，其中保障0.5h、准备后等待0.5h。

这是无故障、地勤保障容量充足、无天气/机场容量限制的确定性排程验收。未提供故障率、维修工时和地勤人数，因此不虚构可靠性或维修预测参数，不重复100次相同确定性试验。每个编队固定使用自己的两架飞机，不进行跨编队轮换。

## 三天时刻表

|日期|波次|保障开始|保障完成|起飞|落地|出动架数|
|---|---:|---|---|---|---|---:|
'''
for r in schedule:
    report+=f'|第{r["day"]}天|{r["wave"]}|{clock(r["preparation"])}|{clock(r["preparation_end"])}|{clock(r["departure"])}|{clock(r["landing"])}|{r["aircraft"]}|\n'
report+=f'''
## 实际计算结果

|指标|结果|
|---|---:|
|飞机总数|12架|
|总波次|9|
|编队出动次数|{expected_flights}|
|飞机出动架次|{2*expected_flights}|
|累计飞机飞行小时|{4*expected_flights}|
|累计飞机地面保障占用小时|{expected_flights}|
|两阶段总任务设备小时|{5*expected_flights}|
|任务缺口设备小时|0|
|两阶段窗口合格率|100%|

小时口径：飞行小时=编队数×9次×2架×2h；地面保障占用=编队数×9次×2架×0.5h，不是人员工时。所有结论来自本次实际模拟，且与手算相等。100%表示本次无故障和无资源约束假设下的排程通过，不表示真实飞机任务成功率。

## 在当前软件中的表达与限制

每个双机编队用独立使用单位部署2架飞机；其余10架放在备用单位，本次无故障排程不轮换或调拨。PREFLIGHT是0.5h地面保障窗口，FLIGHT是2h飞行窗口，两阶段均要求2架。读取实际任务分配事件，逐一验证每个飞行窗口使用的两架飞机与前一保障窗口完全相同，且保障完成不晚于起飞。第二、三波保障后有0.5h等待，无其他任务插入。

v0.4没有独立的出动前保障工序或原子编队放飞规则，本案例通过固定阶段窗口验证零故障排程。地面保障阶段在现有引擎中也属于任务运行；因为故障率为0，本案例不存在由此产生的故障偏差。不能直接把该项目故障率改为非零后解释为真实航空出动模型：保障完成依赖、地勤资源申请、双机齐备才放飞、从备用池调拨、空中故障处置及禁止空中即时补位需要进一步实现。

为满足当前编译器，放置了一个零故障机体占位件、零时长修复和拆装路由；本次均不会触发，不是飞机维修参数。软件总任务小时包含保障和飞行，请用任务阶段CSV或本报告分别查看飞行小时。

## 新项目与复现

本机已创建独立项目：`{project_path}`。原项目未覆盖。在软件点击“打开”选择该文件；也可“导入项目”选择“飞机三天出动-含结果.simproj”，导入为另一独立分支。

复现：`.venv/Scripts/python.exe tools/run_aircraft_case.py`。默认按本次确认口径，每波只出动一个双机编队。每次复现创建新的本机项目，并更新本目录案例文件。

已通过9组检查：编译、总数守恒、9波计划、分阶段小时手算、同机完成保障再飞行、编队不重叠、间隔时间、数据库重开、项目包往返。详细数据见结果汇总JSON、任务阶段结果CSV和飞机分配CSV。
'''
(OUT/'案例报告.md').write_text(report,encoding='utf-8')
print(json.dumps(summary,ensure_ascii=False,indent=2))
