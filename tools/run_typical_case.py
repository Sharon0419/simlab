"""Reproduce the synthetic v0.4 duty evaluation; no application code changes."""
import copy
import csv
import json
from pathlib import Path
import sys
import uuid
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from simlab.sample import duty_project
from simlab.duty import daily_plan
from simlab.engine import simulate, t95
from simlab.project import export_package, import_package, model_hash, now
from simlab.missions import GAP_LABELS

OUT = ROOT/'docs'/'cases'/'2026-09-08-fixed-duty'
OUT.mkdir(parents=True, exist_ok=True)


def interval(values):
    values = np.asarray(values, dtype=float)
    mean = float(values.mean())
    half = t95(len(values)) * float(values.std(ddof=1)) / np.sqrt(len(values))
    return dict(mean=mean, low=max(0, mean-half), high=min(1, mean+half))


base = duty_project()
base['tables']['Control'][0].update(NREPS='100', RSEED='20260908', RCINT='0.25')
base['tables']['SimLabDutyRule'][0].update(MIN_QTY='13', PRIORITY='2', RELIEF_H='.5', TOLERANCE_H='.25')
base['tables'], _, _ = daily_plan(base['tables'], 'PEAK', 'VEHICLE', 'FLEET', 1, 30, 10, 14, 4, 3, 1, .5, .25)
control = copy.deepcopy(base['tables'])
control['Control'][0]['NREPS'] = '1'
for row in control['Item']:
    row['FRT'] = '0'
control_result = simulate(control)
assert control_result['mission']['demand_hours'] == control_result['mission']['supplied_hours'] == 4080
assert control_result['mission']['qualified_rate'] == control_result['mission']['minimum_rate'] == 1
assert control_result['availability'] == 1
variants = [('A', '现状', False, False), ('B', '补位准备30→15分钟', True, False),
            ('C', '维修站人员与工位各2→4', False, True), ('D', '补位提速＋维修站扩容', True, True)]
summaries = []
all_results = {}
for code, label, fast, capacity in variants:
    p = copy.deepcopy(base)
    p['id'] = str(uuid.uuid4())
    p['name'] = f'典型案例{code} · {label}'
    if fast:
        for row in p['tables']['SimLabDutyRule']:
            row['RELIEF_H'] = '.25'
    if capacity:
        for row in p['tables']['ResourceAllocation']:
            if row['STID'] == 'DEPOT':
                row['RQTY'] = '4'
    print(f'Running {code}: {label}, 100 replications', flush=True)
    if '--report-only' in sys.argv:
        result = import_package(OUT/f'{code}-含结果.simproj')['runs'][0]['result']
        assert result['model_hash'] == model_hash(p['tables']), 'Stored case inputs changed; rerun simulation'
    else:
        result = simulate(p['tables'])
    m = result['mission']
    assert m['demand_hours'] == 4080
    assert abs(sum(m['gap_reasons'].values()) - m['gap_hours']) < 1e-6
    assert abs(m['supplied_hours'] + m['gap_hours'] - 4080) < 1e-6
    assert len(m['tasks']) == 60
    groups = {}
    for kind in ('DUTY', 'PEAK'):
        tasks = [t for t in m['tasks'] if t['type'] == kind]
        groups[kind] = dict(fulfillment=sum(t['supplied_hours'] for t in tasks)/sum(t['demand_hours'] for t in tasks),
                           minimum_rate=float(np.mean([t['minimum_rate'] for t in tasks])),
                           qualified_rate=float(np.mean([t['qualified_rate'] for t in tasks])),
                           gap_hours=sum(t['gap_hours'] for t in tasks))
    metrics = {key: interval([r['mission'][key] for r in result['replication_results']])
               for key in ('fulfillment', 'minimum_rate', 'qualified_rate')}
    summary = dict(code=code, name=label, model_hash=result['model_hash'], seed=result['seed'],
                   availability=result['availability'], metrics=metrics, gap_hours=m['gap_hours'],
                   gap_reasons=m['gap_reasons'], groups=groups, resources=result['resources'],
                   maintenance=result['maintenance']['by_kind'])
    summaries.append(summary)
    all_results[code] = result
    p['runs'].append(dict(id=uuid.uuid4().hex, name='30天固定值守评估 · 100次重复', status='completed',
                          started=now(), source_revision=p['revision'], snapshot=copy.deepcopy(p['tables']),
                          model_hash=model_hash(p['tables']), result=result))
    export_package(p, OUT/f'{code}-模型.simproj', False)
    export_package(p, OUT/f'{code}-含结果.simproj', True)
    restored = import_package(OUT/f'{code}-含结果.simproj')
    assert restored['runs'][0]['result']['mission'] == m
    (OUT/f'{code}-输入.json').write_text(json.dumps(p['tables'], ensure_ascii=False, indent=2), encoding='utf-8')
    with (OUT/f'{code}-任务窗口.csv').open('w', encoding='utf-8-sig', newline='') as f:
        columns = ['id', 'type', 'start', 'end', 'quantity', 'minimum', 'priority', 'relief_hours', 'tolerance_hours',
                   'demand_hours', 'supplied_hours', 'gap_hours', 'minimum_rate', 'qualified_rate', 'below_hours', 'longest_below_hours']
        writer = csv.DictWriter(f, fieldnames=columns, extrasaction='ignore')
        writer.writeheader()
        writer.writerows(m['tasks'])
    print(f'{code}: availability={result["availability"]:.4%}; fulfillment={m["fulfillment"]:.4%}; '
          f'minimum={m["minimum_rate"]:.4%}; qualified={m["qualified_rate"]:.4%}; gap={m["gap_hours"]:.3f}', flush=True)

(OUT/'summary.json').write_text(json.dumps(summaries, ensure_ascii=False, indent=2), encoding='utf-8')
with (OUT/'方案对比.csv').open('w', encoding='utf-8-sig', newline='') as f:
    writer = csv.writer(f)
    writer.writerow(['方案','可用度','设备小时满足率','最低保障达标率','窗口合格率','缺口设备小时','重点窗口合格率'])
    for s in summaries:
        writer.writerow([s['name'], s['availability'], *[s['metrics'][k]['mean'] for k in ('fulfillment','minimum_rate','qualified_rate')],
                         s['gap_hours'], s['groups']['PEAK']['qualified_rate']])

report = '''# 典型案例：30天车辆固定值守与重点保障

这是按 SimLab v0.4 实际执行的合成案例，不代表任何真实装备。目的：区分设备可用、任务供给和最低保障合格，比较补位提速与维修资源投入的作用。软件源代码不作修改。

## 1. 业务场景与输入

20台同型保障车辆部署在车辆分队FLEET，归属BASE基地，送DEPOT维修站维修。仿真30天/720小时；初始全部设备健康。固定随机种子20260908，每方案100次独立重复，曲线每0.25小时采样。相同种子用于复现，各方案运行行为不同，不保证逐次故障一一对应。

|任务|每日时间|目标数量|最低数量|优先级|补位准备|连续低于最低容忍|
|---|---|---:|---:|---:|---:|---:|
|常规值守 DUTY|08:00–16:00|15|13|2|30分钟|15分钟|
|重点保障 PEAK|10:00–14:00|4|3|1|30分钟|15分钟|

每日峰值目标19台，最低合计16台，但各任务分别判定。重点任务10点开始时不能抢占常规任务已有设备；优先级只决定空闲设备分配顺序。开始时可用设备直接上岗，之后分配需准备；结束固定，缺口不顺延弥补。低于最低数量继续值守，不中止。

需求手算：常规15×8×30=3600设备小时，重点4×4×30=480，合计4080。共60个任务窗口、360任务窗口小时。即使完全无故障，投入全部20台也不能把多余设备算成超额供给。

|部件|每车数量|故障强度（每百万运行小时）|维修|
|---|---:|---:|---|
|动力LRU POWER|1|父件为0，故障来自内部BOARD|站内检测1h、内部SRU拆装总2h、测试1h|
|控制板SRU BOARD|每POWER内1件|6000|固定直接修复16h|
|控制LRU CONTROL|1|800|指数分布，均值24h|
|液压泵LRU PUMP|2|每件1600|指数分布，均值36h|

串联关键件；指数运行故障，待命和补位准备不累计故障。全车运行故障强度为(6000+800+2×1600)/1000000=0.01/运行小时；连续工作、完好状态下到首故障的均值为100运行小时，不是日历MTBF预测。父动力件不重复叠加故障率。

基地与维修站各有POWER 2件、CONTROL 2件、PUMP 3件备用LRU，维修站另有1件散装BOARD。库存POWER自带健康BOARD，这些内部子件不计入散件库存。基地LRU拆装总2h，默认拆卸/安装各1h；基地至维修站、维修站至基地运输各12h。

基地3名拆装人员；维修站2名维修人员、2个工位。控制模块/泵修复、BOARD修复和动力检测测试占用人员＋工位，内部拆装使用拆装任务所需人员。维修人员每天08:00–17:00可开始新工序，已开始允许跨班完成；工位未单独限班，运输不受班次限制。每阶段分别申请资源，待SRU不占维修资源。固定样例按原支持规则计算，不包含采购、报废、预防维修与路径容量。

## 2. 评估结构及预先约定的演示目标

输入模型 → 任务/故障/换修/补位事件 → 事件积分 → 总体指标 → 分任务评估 → 缺口与维修诊断 → 方案比较。

|层次|输出|含义|
|---|---|---|
|总体|可用度|全部设备日历时间中健康可用的比例，包括待命和准备|
|供给|设备小时满足率、缺口设备小时|以原目标4080设备小时为分母，不因短缺缩小|
|保障|最低保障达标率|达到最低数量的任务窗口小时/360小时；并发分别计时|
|合格|窗口合格率|每轮每窗口最长不达标≤15分钟即合格，再跨100轮平均|
|任务分组|DUTY与PEAK各自供给、达标、合格|避免总体结果掩盖重点任务不足|
|诊断|缺口原因、人员/工位占用、LRU/SRU周转|原因是描述性分摊；周转均值只计完成工单|
|追溯|模型指纹、种子、100轮结果、首轮事件/区间|可从项目包查看和复算|

本案例演示目标预先设定为：总供给满足率≥98%、最低保障达标率≥95%、窗口合格率≥90%，重点窗口合格率≥90%。这是演示用验收线，不是行业标准。均值达线仅表示本轮估计达线；若95%均值区间跨越阈值，应增加证据，不能宣称稳定达标。

## 3. 对照方案

- A现状：上述全部输入。
- B补位提速：两类任务补位30→15分钟，其余不变。
- C维修扩容：维修站人员与工位分别2→4，其余不变；基地仍3人。
- D组合：同时实施B与C，库存与故障参数不变。

## 4. 实际运行结果

|方案|可用度|设备小时满足率|最低保障达标率|窗口合格率|缺口设备小时|重点窗口合格率|
|---|---:|---:|---:|---:|---:|---:|
'''
for s in summaries:
    report += f'|{s["code"]} {s["name"]}|{s["availability"]:.2%}|{s["metrics"]["fulfillment"]["mean"]:.2%}|{s["metrics"]["minimum_rate"]["mean"]:.2%}|{s["metrics"]["qualified_rate"]["mean"]:.2%}|{s["gap_hours"]:.2f}|{s["groups"]["PEAK"]["qualified_rate"]:.2%}|\n'
report += '\n### 95%均值置信区间\n\n以100轮独立试验为统计单位，Student-t近似，比例边界裁剪为0–1；不将6000个窗口误当独立样本。\n\n|方案|供给满足率|最低保障达标率|窗口合格率|\n|---|---|---|---|\n'
for s in summaries:
    report += '|'+s['code']+'|'+ '|'.join(f'{s["metrics"][k]["low"]:.2%}–{s["metrics"][k]["high"]:.2%}' for k in ('fulfillment','minimum_rate','qualified_rate'))+'|\n'
report += '\n### 分任务结果\n\n|方案|任务|供给满足率|最低保障达标率|窗口合格率|缺口设备小时|\n|---|---|---:|---:|---:|---:|\n'
for s in summaries:
    for k, g in s['groups'].items():
        report += f'|{s["code"]}|{k}|{g["fulfillment"]:.2%}|{g["minimum_rate"]:.2%}|{g["qualified_rate"]:.2%}|{g["gap_hours"]:.2f}|\n'
report += '\n### 缺口诊断（平均设备小时）\n\n|方案|'+'|'.join(GAP_LABELS.values())+'|\n|---|'+'---:|'*len(GAP_LABELS)+'\n'
for s in summaries:
    report += '|'+s['code']+'|'+'|'.join(f'{s["gap_reasons"][k]:.2f}' for k in GAP_LABELS)+'|\n'
report += '\n资源利用率分母为配置数量×720日历小时，含跨班作业；不能解读为班内忙碌比例。下表LRU周转含直修及站内换SRU工单，从基地拆卸结束送修至维修站返库，不含回基地运输和装机。\n\n|方案|基地人员占用|站内人员占用|站内工位占用|LRU已完成均值周转h|SRU已完成均值周转h|\n|---|---:|---:|---:|---:|---:|\n'
for s in summaries:
    res=s['resources']
    report += '|'+s['code']+'|'+'|'.join(f'{res[k]:.2%}' for k in ('BASE/TECH','DEPOT/TECH','DEPOT/BAY'))+'|'+ '|'.join(f'{s["maintenance"][k]["mean_tat"]:.2f}' for k in ('LRU','SRU'))+'|\n'
report += '\n## 5. 验收与交付\n\n每方案断言60个窗口、总需求4080、供给＋缺口=需求、原因合计=缺口；运行引擎内置部件守恒检查。四个含结果项目包导入往返验证通过。所有方案输入逐项保存在对应输入JSON；不凭截图读取指标。\n\n在软件中点击“导入项目”，选择本目录 A/B/C/D-含结果.simproj，可直接看结果；选择对应模型包可自行修改并重新运行。导入创建独立分支，不覆盖现有项目。任务CSV是跨100轮均值，首轮明细不是所有试验的完整事件日志。\n\n复现命令：`.venv/Scripts/python.exe tools/run_typical_case.py`。程序重新运行将更新本目录案例输出。原始结果在含结果项目包中；summary.json为汇总，方案对比.csv用于比较。\n'
report += '\n零故障独立对照也通过：保持任务与数量不变，将所有叶子故障率设0，1次试验需求=供给=4080设备小时，最低保障与窗口合格率均为100%。\n'
a, b, c, d = summaries
report += f'''\n## 6. 如何解释结果

1. **现状存在重点任务保障不足。** A的总体设备小时满足率为{a['metrics']['fulfillment']['mean']:.2%}，但重点任务只有{a['groups']['PEAK']['fulfillment']:.2%}，重点窗口合格率{a['groups']['PEAK']['qualified_rate']:.2%}。先开始的常规任务不被抢占，重点任务虽优先级高，仍可能拿不到设备。不能只看总体可用度或总满足率。
2. **补位提速不能单独解决维修积压。** B的补位缺口从{a['gap_reasons']['relief']:.2f}降至{b['gap_reasons']['relief']:.2f}设备小时，但供给满足率仅提高{(b['metrics']['fulfillment']['mean']-a['metrics']['fulfillment']['mean'])*100:.2f}个百分点；维修周转几乎不变。B最低保障率的轻微下降不能据此判断提速有害，当前均值区间较宽且方案改变运行暴露与后续随机路径，未做差值显著性检验。
3. **维修资源扩容在这些假设下改善明显。** C的已完成LRU周转从{a['maintenance']['LRU']['mean_tat']:.2f}降至{c['maintenance']['LRU']['mean_tat']:.2f}小时，待件缺口从{a['gap_reasons']['waiting_spare']:.2f}降至{c['gap_reasons']['waiting_spare']:.2f}设备小时；总缺口减少{(1-c['gap_hours']/a['gap_hours']):.1%}。任务缺口中“等待维修资源”仅指设备拆装层状态，站内排队的影响会通过库存短缺反映到“待件”，应结合维修工单读取，不能只看一个原因栏。
4. **扩容后再看补位。** C中补位准备仍占缺口{c['gap_reasons']['relief']/c['gap_hours']:.1%}。D在C基础上进一步减少{c['gap_hours']-d['gap_hours']:.2f}设备小时缺口，总满足率达到{d['metrics']['fulfillment']['mean']:.2%}。

按照预先约定的四条演示验收线，A/B均值未全部达标，C/D均值全部达标。C/D的三个总体指标95%均值区间下界也高于对应阈值；重点窗口这里只有点估计，不以该总体区间代替重点任务区间。当前结果支持优先核验维修站容量，再评估补位流程；没有人员/工位成本、班次调整成本和真实故障数据，不能称为最低成本配置或全局最优方案。

所有数字均为本案例100轮模拟结果。单次30天运行仍可能低于均值；真实应用应替换故障率、维修工时、运输时长、人员日历和初始库存后重算。
'''
(OUT/'案例报告.md').write_text(report, encoding='utf-8')
print(json.dumps(summaries, ensure_ascii=False, indent=2), flush=True)
