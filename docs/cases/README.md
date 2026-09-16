# v0.11采购与寿命报废

[临界采购](2026-09-16-lifecycle/评估报告.md)与[周期采购](2026-09-16-lifecycle-periodic/评估报告.md)各100轮，含输入、可导入项目包、全轮CSV和守恒证据。复现：`tools/run_lifecycle_case.py`，周期加`--periodic`，EXE对照加`--exe`。

# M3三级供应与维修方式（v0.10）

[临界库存调运](2026-09-16-m3/评估报告.md)与[周期调运](2026-09-16-m3-periodic/评估报告.md)各1000轮，合成4架飞机案例。输入、simproj、六类全轮CSV及数量守恒验证同目录。复现：`tools/run_m3_case.py`，周期方案加`--periodic --output docs/cases/2026-09-16-m3-periodic`；EXE重放加`--exe dist/SimLab/SimLab.exe`。演示结果不代表实际策略优劣结论。

# 新增M2老化案例

[飞机部件老化：修复如新与最小修复](2026-09-15-aircraft-aging/评估报告.md)，各1000轮，保留日历维修与小时检查。

# 可复现案例

v0.9.1新增：[飞行小时检查](2026-09-15-aircraft-inspection/评估报告.md)。1000轮混合日历与小时维修、逐架初始小时、41778工单和12000条计时；复现tools/run_aircraft_inspection_case.py，便携版重放加--verify-only --exe dist/SimLab/SimLab.exe。

v0.9新增：[日历计划维修案例](2026-09-15-aircraft-planned/评估报告.md)。在v0.8主方案上添加每天10点全机队到期、固定1小时计划维修。脚本tools/run_aircraft_planned_case.py生成1000轮结果、全轮工单、项目包，并核对旧案例无新增规则时保持原数值。

v0.8当前案例：[再次出动保障资源对照](2026-09-11-aircraft-ground/评估报告.md)。12架、每波2架、半小时完整准备、每日首波健康机假定已准备，1/2/4组各1000轮；另有2架无故障紧周转确定性验收。统一启动后从项目库选择，复现脚本为`tools/run_aircraft_ground_case.py`，依次prepare/run/report。旧版本案例继续保留用于回溯。

v0.7历史案例：[飞机成功点及2/4/12架对照](2026-09-08-aircraft-three-days/success-v0.7/评估报告.md)。主案例12架共同选机池、4类组件各MTBF400h（整机100h）、指数MTTR2h、每日三波、三天、1000次，出航/任务区/返航为0.5/2/0.5小时，成功点5/6。

各目录保留版本、输入JSON、结果CSV/JSON、报告和可导入的simproj。可直接在v0.7软件中“导入项目”，选择“飞机成功点-12架-含1000次结果.simproj”；选择模型包可修改后重新计算。旧v0.6三阶段及此前结果保留原样。

## 从Git重现v0.7历史案例（使用v0.7.0标签）

1. 按根目录README安装依赖或构建Windows程序；build/dist不在Git中。
2. 在仓库根目录执行 `.venv/Scripts/python.exe tools/run_aircraft_success_case.py prepare`。
3. 执行 `.venv/Scripts/python.exe tools/run_aircraft_success_case.py run --exe dist/SimLab/SimLab.exe`，运行三种容量各1000轮。
4. 执行 `.venv/Scripts/python.exe tools/run_aircraft_success_case.py report`，生成本机新项目、报告、结果包和启动快捷脚本。

报告中的project_path和本机手册链接属于原验证机器的追溯信息，其他电脑不应直接使用这些路径。根目录“打开飞机*.cmd”也是自动生成的本机快捷方式，不进入Git；用导入案例包或上述复现流程生成自己的项目。

历史脚本针对各自发布版本和当时worker输出；严格复现旧数值应使用对应版本。不能用新引擎运行旧输入后，将结果冒充旧版本数值。当前v0.7推荐复现脚本为run_aircraft_success_case.py。

目录索引：固定值守对照、飞机单次无故障、1000次无故障、随机故障固定双机、v0.5备用机、v0.6三阶段。原厂手册全文和用户工作数据库不随仓库发布。
