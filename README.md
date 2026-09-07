# SimLab 本机保障仿真工作台

当前版本 **0.2.0**：任务日历、维修班次、任务满足率、缺口原因与任务 CSV 已接入真实仿真。更新说明与验证基准见 [0.2 使用及计算口径](docs/V0.2.md)。

从软件架构了解实现、领域模型与后续开发路线，请阅读 [架构与交付方案](docs/ARCHITECTURE.md)。

本项目是独立开发的 Windows 桌面应用。建模字段依据用户本机安装的 **SIMLOX 2017** 数据字典对齐；仿真引擎为自主实现的基础子集，不宣称与原厂计算结果等价。

## 启动

界面默认使用深蓝色主题。更新后请关闭旧窗口，再通过下方入口重新启动。

双击根目录 `启动SimLab.cmd`，或打开 `dist/SimLab/SimLab.exe`。便携版需要保留整个 `SimLab` 文件夹中的 `_internal` 目录，不要只复制 exe。运行不需要服务器、账号或互联网。

首次启动加载一个可运行的车辆保障示例。默认项目与计算工作文件存放在 `%LOCALAPPDATA%/SimLab/`。源码、交付文件与用户工作数据分离。

体验新功能：打开后到“项目概览”，点击“新建任务日历示例”；在“模型数据”修改 MissionType 的 NOS 与 MNOS（两者保持一致），进入“仿真实验”运行，再在“结果分析 → 任务供需 / 任务窗口 / 任务缺口”查看结果。示例单独创建，不覆盖原项目。

便携版的 `examples/` 包含“车辆保障-模型.simproj”和“车辆保障-含结果.simproj”，可直接通过“导入项目”打开。

## 已实现

- 中文 Qt 桌面界面：项目概览、模型数据、仿真实验、结果分析、建模说明。
- 133 张输入表、891 个字段：保持原表名、字段代码与顺序，保留原类型、单位、默认值、约束、关联关系。中文仅作辅助标签。灰色单元格表示采用字典默认值。
- 表格编辑、添加/删除行、字段搜索、引用/枚举下拉选项、Excel 复制粘贴、UTF-8/GB18030 CSV 导入、UTF-8 CSV 导出。CSV 导入追加行，重复组合键会在校验中提示。
- SQLite 项目、新建/打开/重命名/另存为、自动保存、写入锁、覆盖前保留单个 `.bak` 备份。
- `.simproj` 完整包/模型包导出、清单与 SHA256 校验、格式/字典版本校验、导入自动创建分支并记录父修订。
- 独立后台进程执行重复仿真、进度反馈、取消、异常记录。意外退出后将运行中的实验标记为中断。
- 可用度时间曲线、停机原因、资源利用率、首轮事件、实验对比、结果 CSV、历史输入快照与基于快照创建分支。

## 推荐操作顺序

1. 启动后点击“模型数据”，选择 `Item` 查看 FRT 等字段。右侧可以查看原始定义、默认值、单位与关联表。
2. 选择 `StockAllocation` 修改备件数量，或 `ResourceAllocation` 修改资源数量。
3. 进入“仿真实验”，点击“校验模型”；修复提示后运行。
4. 查看“结果分析”。修改方案、再次运行后，在“实验对比”中比较两次结果。
5. 点击“导出项目”，选模型包或完整项目。另一台电脑使用本软件“导入项目”，创建一个独立分支。

新建空项目时，按 System → Item → MaterielStructure → Station → Unit/SystemDeployment → StockAllocation → ItemRepair/ItemReplacement → Resource/Tasks → Control 的顺序填写。也可直接将示例另存为自己的方案。

## 计算模型与口径

当前支持一层系统—LRU 串联结构、多个系统类型和部署地点、恒定连续使用率、两级保障网络、有限备件、直接修复与返库、运输延迟及组合资源排队。

- `Item.FRT` 的基本单位是 `1/MOPIDs`。在 `OPID=OPHOURS` 下，MTBF=1,000,000/FRT 小时。不可将 FRT 当作每小时故障率直接使用。
- 系统处于可用状态时，以 UTIL 比例累计运行量。故障等待时间为指数分布；任何已建模 LRU 故障均导致整机暂停运行。停机期间暂停运行故障累积。
- 上一条适用于没有 Operations 的连续使用模式。任务模式要求 UTIL=1，仅分配到需求窗口的设备累计运行量；待命时保留剩余故障时钟，故障后可由空闲设备补位。
- `MaterielStructure` 的 QTYPM、ENVF 与 `Item.AFFRT` 共同影响故障强度。
- `Control.APID` 选择 `StockAllocation.POINT` / `ResourceAllocation.POINT`。
- 初始化在库数量取 `ISTOH`，未填写则取 `STSIZ`。本版采用闭环一件换一件补充；库存不足时等待修复件或上级补充。
- `ItemReplacement.SURPT` 为总拆装时间，按 `Control.RMVFR` 分为拆卸和安装。两段分别原子申请全部任务资源，等待备件时不占拆装资源。
- 故障件沿 TTOMS 运往上级直接修复，修复时间来自 `ItemRepair.DIRPT`；修复件进入上级库。使用站点每次备件请求触发一件补充请求，沿 TFRMS 运回使用站点。无上级时在本站修复。
- 时间分布字段留空代表固定时长；`<EXP>` 代表相应均值的指数分布。其他分布可建模但暂不能执行。
- 每次独立试验使用确定的随机流标识。固定模型、版本、种子与重复编号可复现计算结果。
- 可用度按整个 SIMPE 区间的状态持续时间积分。初始系统全部可用，没有预热期删除。曲线为离散采样的跨重复试验均值，不能用曲线点的简单平均代替积分结果。
- 等待备件、等待拆装资源、拆装作业为互斥停机状态；等待备件包含供应运输等待。
- 均值 95% 置信区间采用跨重复结果的 Student-t 近似并限制到 [0,1]。单轮不给区间，P05/P95 为重复试验结果分位数。少量重复时分位数不稳定。
- ENLOG=Y 保存首轮最多 5000 条事件并标明截断；其余重复保留汇总结果。

## 支持边界

**字段可以编辑和交换，不表示对应仿真规则均已实现。** 运行编译器会阻止未支持的非空表及改变模型含义的非默认字段值，并显示具体表、行、字段。

本版尚未实现：多层 SRU/PRU 维修结构、冗余/RBD、非关键故障、老化、复杂任务调度和原厂任务成功判定、预防性维修、采购报废、多级/横向供应、时变扰动、自动优化及多人修改自动合并。已实现固定需求窗口的先到先服务调度，以及显式时间窗控制的维修启动班次。

本版不读取原厂二进制 `.sxi`/`.sxt` 文件，不声称 `.simproj` 可由 SIMLOX 打开。字段兼容基线为 **2017**；其他 SIMLOX 版本需要单独核对字典。未实现跨字典迁移时会明确拒绝不匹配的项目。

便携版已在本机 Windows 11 验证；其他操作系统版本尚未测试。Qt 使用 Windows 自带 ICU，打包脚本会排除 PATH 上误收集的其他 ICU 版本。

当前限制：2000 台设备、装机部件与库存共 200000 件、1000 次重复、10000 个采样点、单次预估故障事件不超过 500 万、项目包 128 MB。重复试验在后台进程中顺序运行。

## 工程结构

```text
main.py                    桌面/worker 入口
simlab/schema.py           原字段元数据与中文标签
simlab/data/schema.json    133 表、891 字段字典
simlab/validation.py       字段、数值、引用、组合键与组成循环检查
simlab/project.py          SQLite 持久化、备份、项目包交换
simlab/compiler.py         模型编译与计算支持范围检查
simlab/operations.py       固定需求窗口与维修班次编译
simlab/missions.py         FCFS 分配、供需积分与缺口归集
simlab/engine.py           离散事件内核适配与领域仿真
simlab/worker.py           文件通信的独立计算进程
simlab/ui/                 Qt 界面、建模编辑器、图表
simlab/smoke.py            源码与便携版桌面端到端检查
tests/test_core.py         守恒、复现、解析基准、交换包验证
tools/extract_schema.py    从本机官方数据字典生成元数据
tools/build_windows.ps1    Windows 便携版打包
```

项目数据库包含 metadata、model_tables、runs 三张内部表。业务输入表保持原字段结构，以 JSON 记录保存，便于无损保留尚未计算的模型信息。运行结果和输入快照保存在 runs 中。本版工作数据量较小时无需另设分析数据库。

项目包包含 manifest.json 与 project.sqlite，不包含原厂手册、二进制软件或许可证文件。字典源文件位置及 SHA256 记录在 schema.json 中。

## 从源码开发与验证

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe main.py
.\.venv\Scripts\python.exe -m pytest -q
$env:QT_QPA_PLATFORM = 'offscreen'
.\.venv\Scripts\python.exe main.py --smoke build\qa-source
powershell -ExecutionPolicy Bypass -File tools\build_windows.ps1
.\dist\SimLab\SimLab.exe --smoke build\qa-package
```

自动化桌面检查涵盖字段编辑、保存重开、CSV 导出、取消、后台完成、结果持久化、项目交换与分支追溯，产出三张界面截图和 smoke-result.json。执行正常桌面启动前移除 QT_QPA_PLATFORM 环境覆盖。

模型校核包含零故障可用度为 1、固定种子的重复性、部件守恒、无备件单机模型与 100/(100+20) 理论可用度的长期比较。仍需使用实际保障数据做领域校准。
