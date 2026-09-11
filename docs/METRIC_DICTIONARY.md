# v0.7 飞行评估指标字典

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
