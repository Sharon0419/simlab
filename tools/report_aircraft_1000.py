"""Verify the installed worker's deterministic case and publish a metric crosswalk."""
import copy
import csv
import hashlib
import json
import os
from pathlib import Path
import statistics
import sys
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from simlab.project import new_project, now, model_hash, save_project, load_project, export_package, import_package
from simlab.compiler import compile_model

SOURCE = ROOT / 'build/aircraft-1000'
OUT = ROOT / 'docs/cases/2026-09-08-aircraft-three-days/evaluation-1000'
OUT.mkdir(parents=True, exist_ok=True)
tables = json.loads((SOURCE / 'input.json').read_text(encoding='utf-8'))
result = json.loads((SOURCE / 'result.json').read_text(encoding='utf-8'))
assert tables['Control'][0]['NREPS'] == '1000'
assert compile_model(tables)['count'] == result['fleet_size'] == 12
assert result['model_hash'] == model_hash(tables)
assert len(result['replication_results']) == result['replications'] == 1000
rows = []
for index, rep in enumerate(result['replication_results'], 1):
    flight = [t for t in rep['mission']['tasks'] if t['type'] == 'FLIGHT']
    prep = [t for t in rep['mission']['tasks'] if t['type'] == 'PREFLIGHT']
    assert len(flight) == len(prep) == 9
    assert sorted(t['start'] for t in flight) == [d*24+h for d in range(3) for h in (9,12,15)]
    assert all(t['quantity'] == 2 and t['end']-t['start'] == 2 and t['gap_hours'] == 0 for t in flight)
    assert rep['parts']['initial'] == rep['parts']['final'] == 12
    assert rep['availability'] == 1 and rep['failures'] == rep['mission']['gap_hours'] == 0
    requested = sum(t['demand_hours'] for t in flight)
    achieved = sum(t['supplied_hours'] for t in flight)
    prep_hours = sum(t['supplied_hours'] for t in prep)
    assert requested == achieved == 36 and prep_hours == 9
    # MTACC only derived for this fully served fixed-pair case; no partial-mission extrapolation.
    duration = sum(t['end']-t['start'] for t in flight)
    rows.append(dict(replication=index, NMREQ=9, NMSTA_case=9, FMSTA_case=1,
        NSYRQ_total=18, NSYST_total_case=18, MTREQ=duration, MTACC_case=duration,
        MTF_case=1, STREQ=requested, STACC=achieved, STF=achieved/requested,
        completed_flight_windows=9, full_flight_window_rate=1,
        preparation_aircraft_hours=prep_hours, flight_gap_aircraft_hours=0,
        healthy_availability=rep['availability'], failures=rep['failures'],
        fleet_flight_utilization=achieved/(12*72)))
with (OUT/'逐轮指标.csv').open('w', encoding='utf-8-sig', newline='') as f:
    writer = csv.DictWriter(f, fieldnames=rows[0].keys())
    writer.writeheader()
    writer.writerows(rows)
stats = {}
for key in rows[0]:
    if key == 'replication':
        continue
    values = [r[key] for r in rows]
    assert min(values) == max(values)
    stats[key] = dict(mean=statistics.mean(values), std=statistics.stdev(values),
        p05=min(values), p95=max(values), mean_ci95=[min(values), max(values)])
p = new_project('飞机三天出动 · 1000次评估 · 无故障基线')
p['tables'] = tables
p['runs'].append(dict(id=uuid.uuid4().hex, name='1000次重复试验（确定性排程基线）',
    status='completed', started=result.get('created', now()), source_revision=p['revision'],
    snapshot=copy.deepcopy(tables), model_hash=model_hash(tables), result=result))
project_path = Path(os.environ['LOCALAPPDATA'])/'SimLab/projects'/f'aircraft-1000-{p["id"][:12]}.sqlite'
project_path.parent.mkdir(parents=True, exist_ok=True)
save_project(p, project_path)
assert load_project(project_path)['runs'][0]['result'] == result
package = OUT/'飞机1000次评估-含结果.simproj'
export_package(p, package)
assert import_package(package)['runs'][0]['result'] == result
(OUT/'输入.json').write_text(json.dumps(tables, ensure_ascii=False, indent=2), encoding='utf-8')
summary = dict(replications=1000, horizon_hours=72, model_hash=model_hash(tables),
    raw_result_sha256=hashlib.sha256((SOURCE/'result.json').read_bytes()).hexdigest(),
    project_path=str(project_path), statistics=stats,
    verification=['1000 per-replication assertions', 'input/result hash equality',
                  'SQLite full result roundtrip', 'simproj full result roundtrip'])
(OUT/'统计汇总.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
launcher = ROOT/'打开飞机1000次评估.cmd'
launcher.write_bytes(('@echo off\r\nstart "" "%~dp0dist\\SimLab\\SimLab.exe" --project "'
                      +str(project_path)+'"\r\n').encode('ascii'))
report = '''# 飞机三天出动：1000 次评估与 SIMLOX 指标对照

已用本机 dist/SimLab/SimLab.exe 的 worker 实际执行 1000 次，并逐轮核验。每轮独立重置为同一三天场景；不是连续运行 3000 天。没有执行原厂 SIMLOX 对照仿真，也不代表两套引擎已通过一致性认证。

## 输入与统计解释

12 架飞机，每波同一双机编队出动，其余 10 架备用但不参与替补。连续 3 天，每天 09:00、12:00、15:00 起飞，飞行 2 小时。首次保障 08:30–09:00；后两次保障 11:00–11:30、14:00–14:30，随后等待下一次起飞。仿真窗口为第 1 天 00:00 至第 4 天 00:00，共 72 小时；随机种子 20260908，记录间隔 5 分钟。

故障率为 0，未设置随机保障时长和地面资源约束。因此 1000 轮完全相同；下表的标准差均为 0，P05、P95 和均值置信区间端点均等于均值。这只是确定性模型的重复性结果，不能作为真实任务成功概率为 100% 的证据。

## 每轮（三天）结果与口径

| 指标 | 1000 轮均值 | 与 SIMLOX 的对应程度 |
|---|---:|---|
| 请求飞行任务 NMREQ | 9 次 | 仅统计 FLIGHT，不将保障阶段算作飞行任务 |
| 开始飞行任务 NMSTA / FMSTA | 9 次 / 100% | 本无缺口固定窗口案例可推导；尚无完整延迟起飞状态机制 |
| 请求/投入飞机 NSYRQ / NSYST（跨任务累计） | 18 架次 / 18 架次 | 本案例推导；不是机队规模 12 架 |
| 请求/完成任务时间 MTREQ / MTACC | 18 / 18 小时 | 按编队任务时长累计，本案例全程满足时可对应 |
| 任务时间满足比例 MTF | 100% | MTACC / MTREQ，本案例推导 |
| 请求/完成系统运行时间 STREQ / STACC | 36 / 36 架·小时 | 从实际逐轮 FLIGHT 结果汇总，排除保障时间 |
| 系统运行时间满足比例 STF | 100% | STACC / STREQ |
| 全程双机满足的飞行窗口 | 9 次，100% | 自定义完成指标，不能改名为原厂 FMSUC |
| 飞行装备小时缺口 | 0 架·小时 | 逐轮 FLIGHT 的 gap_hours 总和 |
| 出动前保障占用 | 9 架·小时 | 单列，不计入 STACC；不是保障人员工时 |
| 健康可用度 | 100% | 当前引擎口径，包含执行任务的健康飞机 |
| 故障次数 | 0 | 零故障输入的直接结果 |
| 全机队飞行时间利用率 | 4.1667% | 自定义：36 / (12×72)，不是人员资源利用率 |

当前界面的“任务装备小时”仍包含保障和飞行，共 45 架·小时；不能将该字段原样当作 SIMLOX STACC。原生界面还会显示 18 个阶段窗口；真正飞行任务是 9 次。本报告在外部按 FLIGHT 筛选并计算对照指标，未修改界面或引擎。

## 尚不能声称等价的指标

| 原厂评估项 | 当前状态与补足条件 |
|---|---|
| NMSUC / FMSUC / NSYSU | 尚未实现成功点 MSUCPT；需定义任务成功条件、途中中断及双机编队整体判定 |
| NSYRY、NSYMA 及准备/等待/周转状态分布 | 当前独立保障窗口不能完整表达原厂任务状态链；健康可用数不能直接代替待命数 |
| 保障资源利用率、资源排队与等待分布 | 未输入人员/设备数量、班次及任务资源需求，无法评价；不能填 0% |
| MTBF、MTTR、备件短缺风险与修复能力 | 缺少有效故障、修理及备件需求样本；本案例不具备估计条件 |
| STLOW 等原厂低分位指标 | 原厂包含时间聚合规则；本报告逐轮总量 P05 不是 STLOW 的通用替代 |

当前版本未强制实现保障完成后才能起飞、双机整体起飞、飞行中禁止替换、备用机接替等状态约束。在这个无故障排程中结果成立；加入故障后，需要先完善上述机制再评价可靠性。

## 使用及复核

双击仓库根目录“打开飞机1000次评估.cmd”，打开独立项目查看已保存的 1000 次结果；也可在软件导入同目录“飞机1000次评估-含结果.simproj”。原先单次案例保留。

“逐轮指标.csv”提供 1000 行数据；“统计汇总.json”保存均值、标准差、P05/P95、均值区间、输入哈希和实际 worker 原始结果的 SHA-256。原始结果位于 build/aircraft-1000/result.json，并完整封装于项目包。

复核脚本：`.venv/Scripts/python.exe tools/report_aircraft_1000.py`。它读取已完成的 worker 输出，逐轮断言并创建新的评估项目，不重新运行仿真。

## 指标依据

本机原厂《SIMLOX User’s Manual》（2017）：第 561–564 页 MTF/MTACC/MTREQ；第 565–568 页 FMSTA/FMSUC/AVSTD/STF；第 568–576 页系统时间、飞机数和任务数；第 629–638 页系统状态；第 750–759 页资源结果。指标版本以该手册为准。

[本机原厂手册](<C:/Program Files/Systecon/SIMLOX/UserDoc/SIMLOX.pdf>)；[Systecon 官方产品说明](https://www.systecongroup.com/gl/software/simlox-ensuring-performance)。原厂产品包含任务、可用度、保障资源等评估能力；本报告仅对实际具备条件的指标做口径对照。
'''
(OUT/'评估报告.md').write_text(report, encoding='utf-8')
print(json.dumps(dict(verified_replications=len(rows), project_path=str(project_path),
    package=str(package), report=str(OUT/'评估报告.md')), ensure_ascii=True))
