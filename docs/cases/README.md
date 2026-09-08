# 可复现案例

当前推荐案例：[v0.6 飞机三阶段](2026-09-08-aircraft-three-days/phases-v0.6/评估报告.md)。输入包含12架共同选机池、4类组件各MTBF400h（整机100h）、指数MTTR2h、每日三波、三天、1000次，出航/任务区/返航为0.5/2/0.5小时。

各目录保留版本、输入JSON、结果CSV/JSON、报告和可导入的simproj。可直接在v0.6软件中“导入项目”，选择“飞机三阶段-含1000次结果.simproj”查看历史结果；选择模型包可修改后重新计算。

## 从Git重新运行

1. 按根目录README安装依赖或构建Windows程序；build/dist不在Git中。
2. 在仓库根目录执行 `.venv/Scripts/python.exe tools/run_aircraft_phase_case.py prepare`。
3. 执行 `.venv/Scripts/python.exe main.py --worker build/aircraft-phases/input.json build/aircraft-phases/result.json`，或改用构建的 `dist/SimLab/SimLab.exe --worker` 和相同两个路径。
4. 执行 `.venv/Scripts/python.exe tools/run_aircraft_phase_case.py report`，生成本机新项目、报告、结果包和启动快捷脚本。

报告中的project_path和本机手册链接属于原验证机器的追溯信息，其他电脑不应直接使用这些路径。根目录“打开飞机*.cmd”也是自动生成的本机快捷方式，不进入Git；用导入案例包或上述复现流程生成自己的项目。

历史脚本针对各自发布版本和当时worker输出；严格复现旧数值应使用对应版本。不能用新引擎运行旧输入后，将结果冒充旧版本数值。当前v0.6推荐复现脚本为run_aircraft_phase_case.py。

目录索引：固定值守对照、飞机单次无故障、1000次无故障、随机故障固定双机、v0.5备用机、v0.6三阶段。原厂手册全文和用户工作数据库不随仓库发布。
