# Aircraft Reserve Implementation Plan

**Goal:** 实现独立飞行任务状态机，并将12架飞机案例改为每日全机保障、共同选机池、双机起飞和故障中止，重新运行1000次。

**Architecture:** 新增 SimLabFlightRule 扩展输入和 FlightManager。旧固定值守模式保持原行为；飞行模式整套计划必须使用相容规则，准备不作为运行任务。复用现有故障、修复、库存、项目与统计机制。

**Tech Stack:** Python、SimPy、NumPy、PySide6、pytest、PyInstaller。

- [x] 输入：extensions.py/operations.py/compiler.py/schema.py。PREP_H=0.5；每日首波前开始全机保障；同一池规则一致；拒绝混合模式和跨日任务。扩展版本3兼容旧版本1、2。
- [x] 状态机：flight.py。准备/已准备/飞行；起飞时原子选足NOS，否则取消。飞行故障整项中止，禁止补位；修复后重新保障。返航耗时本版按0，准备无故障、无资源容量约束；健康可用度仍为技术状态。
- [x] 输出：engine.py聚合启动/完成/中止/取消、架次、准备小时、待命小时；UI独立飞行结果页和运行说明。事件记录首轮选机、准备与故障。
- [x] 验证：tests/test_flight.py，保障截止边界、每日重置、故障前/中/后、恢复后不能加入旧任务、共同池、无故障36飞行小时、准备27飞机小时、旧版本往返。
- [x] 案例：独立生成脚本，将12架部署于共同单位；4类组件各MTBF400h、指数MTTR2h；只保留9个FLIGHT任务。对照原1000次结果，不能将不同任务中止规则下的差异全部归因于备用机。
- [x] 发布：运行完整pytest和桌面检查；构建v0.5.0；用新exe实际运行1000次；保存sqlite/simproj/CSV/MD；保留旧程序备份并更新启动入口。
