# v0.7 飞行评估指标字典

## v0.8 准备资源补充（2026-09-11）

以下均为本地指标，不套用原厂代码。每轮汇总，再跨轮取均值。

| 字段 | 单位/口径 |
|---|---|
| requested_jobs | 准备作业请求次数 |
| completed_jobs | 正常做满PREP_H并完成次数 |
| assumed_jobs | 每日首波假设接续的未完作业次数，非正常完工 |
| waiting_jobs / working_jobs | 期末未开始/在做次数 |
| wait_aircraft_hours | 所有作业等待资源和共同班次的总架·小时，含期末未完及假设接续之前实际等待 |
| wait_resource_aircraft_hours | 共同班次内等待资源或FIFO队列的架·小时 |
| wait_shift_aircraft_hours | 没有共同班次时等待的架·小时；不与资源等待重复计 |
| work_aircraft_hours | 实际工作架·小时；期末在做或被首波假设接续的作业仅计算已发生部分 |
| daily_assumed_ready_aircraft | 每日首波假定已保障的健康地面飞机架次，含原本已就绪飞机；不是保障组完成数量 |
| cancel_reason / launch_readiness | 取消主要分类与当刻状态数量；可能多因素并存，不能作为因果贡献分解 |

守恒：请求=正常完成+假设接续+期末等待+期末在做；总等待=班内等待+班次等待。共享资源利用率来自原资源统计，分母为容量×完整SIMPE。作业明细CSV保留每轮每作业和实际时刻；历史结果不补算。

2026-09-11。来源：本机 SIMLOX 2017 用户手册183、561～576页与 SimLab 固定飞行模型。下列映射仅限本版支持的固定、全员编队任务；尚未通过原厂输入/输出数值对照认证。

## 聚合规则

一次试验为完整仿真期（案例72小时），先按任务累加数量，再计算该轮比率。界面汇总取重复试验的算术平均；逐轮CSV可复算。数量单位“架次”允许同一飞机参与多个任务，不能当成去重飞机数。案例9次任务、每次2架：请求18架次，机队12架。

| 原厂代码 | 本地字段 | 单位与定义（单轮全期） | 分母 | 支持情况 |
|---|---|---|---|---|
| NMREQ | requested | 计划编队任务数，含取消 | 无 | 固定任务映射 |
| NMSTA | started | 已起飞编队数 | 无 | 固定任务映射 |
| NMSUC | successful | 已达到成功点的编队数 | 无 | 固定任务映射 |
| FMSTA | started_rate | 起飞编队比例 | requested | 固定任务映射 |
| FMSUC | success_rate | 成功编队比例 | requested，非started | 固定任务映射 |
| NSYRQ | requested_aircraft_sorties | 各任务请求飞机架次之和 | 无 | 本版NOS需求映射，不支持原厂显式formation表 |
| NSYST | aircraft_sorties | 各已起飞任务成员数之和 | 无 | 固定任务映射 |
| NSYSU | successful_aircraft_sorties | 各成功任务成功成员数之和 | 无 | 整队中止规则范围内映射 |
| 无 | completed / completion_rate | 全程未中止且按计划落地的任务数/比例 | 比例除requested | 本地完整完成 |
| 无 | aborted | 飞行中故障导致整队中止数（可已成功） | 无 | 本地状态 |
| 无 | cancelled | 起飞时就绪飞机不足而取消数 | 无 | 本地状态 |
| 无 | all_successful / all_completed | 每轮全部成功/全部完整完成指示0或1 | 汇总除重复次数 | 本地整轮概率估计 |

数量在同轮内跨任务/单位累加；跨轮显示期望数量，不把1000轮累计误写为一轮数量。固定输入各轮请求数量相同，平均比率与累计比率一致。新结果保留逐任务started_rate、success_rate和完整完成/中止/取消率。

## 时间口径审计

| 原厂代码或本地字段 | 单位 | 当前结论 |
|---|---|---|
| STREQ | 系统小时 | 原厂需求系统运行时间；本地demand_hours为数量×完整DURN之和，仅本固定子集可直接比较，暂不输出该代码 |
| STACC / STF | 系统小时 / 比例 | 原厂累计系统运行与需求比，需进一步核实中止返航/任务占用定义，暂不宣称等价 |
| MTREQ / MTACC / MTF | 任务小时 / 比例 | 原厂任务层时间，不等于架·小时；部分编队与原厂任务终止口径尚未覆盖，暂不输出 |
| demand_hours | 架·小时 | ΣNOS×DURN，本例54 |
| supplied_hours / fulfillment | 架·小时 / 比例 | 整队保持有效任务至中止或计划落地；排除中止返航；fulfillment=supplied_hours/demand_hours |
| out_aircraft_hours | 架·小时 | 实际出航阶段成员占用时间 |
| on_station_aircraft_hours | 架·小时 | 实际任务区执行成员占用时间 |
| return_aircraft_hours | 架·小时 | 实际返航成员占用，包含中止返航 |
| abort_return_aircraft_hours | 架·小时 | 中止后的返航，占上述返航的子集，不可重复相加 |
| preparation_aircraft_hours / ready_aircraft_hours | 架·小时 | 准备/已保障待命状态积分，不累计运行故障 |

实际三阶段之和=有效供给+中止返航。本版无其他任务释放延迟，此等式用于回归验证。成功点只改变成功标签，不改变任一物理时间积分。

## 可复核明细与历史兼容

success_point是计划绝对小时；success_at是实际达到该点的小时（失败时为空）；success_phase为该点的OUT/ON_STATION/BACK阶段，若位于计划落地则LANDED。success_reason使用稳定代码，界面给中文解释；successful_members为成功飞机ID数组。取消的members与successful_members均为空。

旧结果没有成功字段时显示未计算，不按0计，也不按完整完成数反推。CSV空值表示历史不支持，零表示已计算且没有发生。案例报告的95%均值区间与P05/P95为独立重复试验统计，未映射原厂STLOW等结果设置。

## v0.9 日历计划维修

v0.9.1扩展：mission.planned汇总日历维修与飞行小时检查；clocks为首轮逐架/逐检查计时，全部轮次保存在replication_results。initial_hours+flown_hours=已完成检查cycle_hours之和+hours_since_check。overrun_hours=max(0,cycle_hours-interval_hours)，已完成工单保留历史超限，当前时钟完成后归零。不同检查共享同一飞机在空经历，不能相加当作总飞行时间。混合工单CSV的trigger区分calendar/flight_hours，日历工单的检查计时列为空。计时CSV含每轮编号及模型哈希。

`mission.planned`保存跨轮均值和首轮工单；`replication_results[*].mission.planned.jobs`保留全部工单。时刻从仿真开始计，单位小时。

| 字段 | 口径 |
|---|---|
| due_jobs | 已到期工单数；等于完成、等待前序、等待资源和作业中四类之和 |
| due_at / requested_at / started_at / ended_at | 到期、申请资源、实际开始、完成；未发生的时刻为空 |
| deferred_hours | 从到期到申请资源或期末；包含在飞、故障修复、已有准备和前序计划等待 |
| wait_hours | 从资源申请到实际开始或期末；包含资源队列和班次等待 |
| work_hours | 实际开始至完成或期末；完成工单等于输入固定时长 |
| planned_wait / planned_maintenance | downtime中每台平均资源等待/作业停机小时，参与可用度积分 |

同一飞机可有多个积压工单，工单延后时间可能重叠，不能把deferred_hours之和当作飞机停机时间。等待落地的工单不提前中止飞行；计划作业不会把故障件变为健康，也不重置剩余故障时钟。未配置计划时旧结果不增加这些键。


## v0.9.2部件年龄

有效年龄 age：初始装机年龄加实际运行小时乘UTIL，减去修复如新清零的年龄。终身运行 lifetime_hours：初始年龄加本轮累计运行小时，不随维修减少。恒等式：终身运行小时=当前有效年龄+历次维修抹去年龄之和。库存、运输、维修、准备及待命不累计；故障返航中仅健康叶子继续运行。风险倍数不改变年龄。首轮表格和全轮CSV均标注范围；年龄明细每轮各10000条上限。


## v0.10 M3供应与维修

- 库存位置=可用未预留库存+已申请未到货−未满足需求；在途包含在未到货中。
- 订单数量=待分配+在途+已收货；运输批次携带实物编号。
- 维修方式选中数与完成数分别汇总，只统计在位工单；拆下件工单单列，不作为再次抽签。
- 预防时钟按实物记录日历/有效运行小时，超限记录不扣减下一周期；年龄与终身运行量分别保留。
- 界面为首轮明细；CSV包含全部轮次。截断标记及总记录数与保留记录数独立，禁止把截断明细当总量。
