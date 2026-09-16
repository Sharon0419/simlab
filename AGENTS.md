# SimLab 开发协作指南

适用于本仓库及子目录。依据 2026-09-16 的代码与已确认需求整理；版本、支持范围和验证结果以当前代码及实测为准。

## 项目与任务入口

- SimLab 是独立开发的 Windows 装备保障仿真桌面软件，采用 Python、PySide6、SimPy、NumPy、SQLite，计算在独立进程运行。
- GitHub：<https://github.com/Sharon0419/simlab>。本机代码路径仍为 `C:\Users\sharo\Documents\ChatGPT\Simlox`，远端更名不代表本地目录已改名。
- 开始工作时检查 `git status --short`、当前分支和远端，保留已有改动；新分支使用 `codex/` 前缀。提交、推送、合并和发布按本次用户授权执行，文档不构成操作授权。
- 先阅读 `README.md` 的当前版本入口；修改业务时阅读对应版本说明及已批准设计，核对实现后再改代码。历史文档可能保留旧能力描述，出现冲突时标明被取代的结论。
- 用户要求先讨论的功能，先明确业务规则；已批准的开发持续推进至实现、必要验证和交付。仅对会影响结果且无法从上下文判断的信息提问。

## 按任务查阅

| 任务 | 入口 |
|---|---|
| 架构和进程边界 | `docs/ARCHITECTURE.md`；其中早期能力表须与当前代码核对 |
| 当前能力和验证证据 | `docs/V0.12.md`、`docs/VERIFICATION.md` |
| 需求范围与后续排期 | `docs/NEXT_VERSION_PLAN.md`、`docs/ROADMAP.md` |
| 冗余及工序业务规则 | `docs/superpowers/specs/2026-09-16-redundancy-support-workflows-design.md` |
| 三级供应与维修、采购与报废 | `docs/V0.10.md`、`docs/V0.11.md` |
| 指标口径与案例 | `docs/METRIC_DICTIONARY.md`、`docs/cases/` |

## 代码入口

| 范围 | 主要文件（相对 `simlab/`） |
|---|---|
| 字典、扩展与编译校验 | `schema.py`、`data/schema.json`、`extensions.py`、`validation.py`、`compiler.py` |
| 引擎与后台进程 | `engine.py`、`m3_engine.py`、`worker.py`；根目录 `main.py` |
| 实物、老化、冗余 | `components.py`、`aging_components.py`、`aging.py`、`redundancy.py` |
| 任务与地面保障 | `missions.py`、`operations.py`、`flight.py`、`ground.py`、`planned.py`、`inspection.py` |
| 供应、维修与寿命 | `supply*.py`、`service.py`、`service_config.py`、`preventive.py`、`retirement.py` |
| 多工序 | `workflow_schema.py`、`workflow_config.py`、`workflows.py`、`workflow_activity.py`、`service_workflows.py` |
| 项目持久化与项目库 | `project.py`、`project_library.py` |
| 中文界面与结果 | `ui/`、`m3_results.py`、`flight_results.py` |

## 必须保持的业务约定

- 原厂 2017 字典的表名、字段代码、顺序和单位保持独立；新增规则使用 SimLab 扩展。界面可编辑不等于引擎支持，编译器必须明确拒绝未实现且影响语义的配置。
- `Item.FRT` 单位为 `1/MOPIDs`；`OPHOURS` 下 `MTBF = 1,000,000 / FRT` 小时。更改故障、年龄和利用率逻辑前检查单位及实际运行量累计方式。
- n 中取 k 仅覆盖 System→LRU、LRU→SRU，同父对象、同型号分组；n 来自结构，未配置 k 时 k=n。正常件全部运行，任务中仍满足 k 则继续，低于 k 则中止返航。落地后尽早修理所有故障，等待维修资源/备件及维修中都禁止新任务。
- 工序采用无环的全部紧前完成约束，支持并行和汇合。每道工序资源齐备才开工，完工释放；已开工工序跨班继续，后续工序仍检查班次。同机不同保障活动串行，活动内部可并行。
- 自定义工序须保留必要业务动作的先后与唯一性。拆卸、装机、实物转移、寿命/修复计次不得重复执行；等待备件时不占安装资源，安装前复核备件资格。
- 三级供应只有显式配置的路径才允许调运；配置 A→C 可绕过 B，否则不能自动跨级。可用策略优先选择调运时长短的策略，支持临界库存与指定周期触发。
- 修复性及预防性维修均可配置原位或换件；两种方式兼有时使用换件比例，单次工单抽取结果在后续流程保持一致。
- 本轮范围不扩展混编、待机冗余、其他装备能力或报废后的处置。供应扰动、横向支援及运输容量仍需后续需求授权。

## 实现与兼容性

- 新功能同时落实配置校验、引擎语义、结果、持久化及必要界面，不能仅新增输入字段。核心引擎保持与 Qt 解耦。
- 未启用新配置的旧模型保留原执行路径及随机序列；固定模型、版本、种子、重复编号应可复现。新增随机行为避免扰动旧随机流。
- 扩展格式版本以 `extensions.py` 为准，软件版本以 `__init__.py` 为准。格式变化需验证旧项目读取、新包往返及旧读取器拒绝不支持的新格式。
- 保障活动历时按实际起止及区间并集统计，不能把并行工序时长直接相加；区分工作、班次等待与资源等待。界面首轮明细与全轮 CSV 必须明确区分。
- 同刻事件要先完成故障、修复及零时长工序的状态结算再作出动判定。仅在状态真正变化时发通知，避免形成仿真时间无法前进的调度循环。
- 界面默认呈现操作和数据；字段解释、指标说明按需展开或悬浮显示。保留单位、状态、校验错误，避免常驻大段说明。中文标签与原始字段代码分离。

## 验证与发布

在仓库根目录使用 PowerShell；开发环境缺失时按 `requirements-dev.txt` 安装依赖。

```powershell
.venv/Scripts/python.exe -m pytest -q
$env:QT_QPA_PLATFORM='offscreen'
$env:QT_SCALE_FACTOR='1'
.venv/Scripts/python.exe main.py --smoke build/qa-source
git diff --check
```

- 业务改动先用边界或故障复现测试验证，再运行相关测试和全量回归；纯文档改动检查事实、路径、链接及 diff，无需重复仿真。
- UI 改动运行桌面 smoke，并检查相关截图和真实结果记录。仅退出码成功不足以证明全部桌面检查通过，还须读取输出目录的 `smoke-result.json`。
- 发布使用 `tools/build_windows.ps1 -OutputDirectory dist/release-stage`，再对 `dist/release-stage/SimLab/SimLab.exe` 做 smoke 和版本对应的源码/EXE对照。该脚本包含 VC/ICU 依赖修复，应保留此构建入口。
- v0.12 对照入口：`tools/verify_v012_release.py <EXE路径>`；组合案例：`tools/run_workflow_case.py --reps 100`。后续版本按变化更新验证入口与保存证据。
- 验收后使用 `tools/package_release.py --folder dist/release-stage/SimLab` 打包并检查 ZIP 完整性。发布必须分别验证源码、打包程序与最终安装目录；安装后比较文件哈希。
- 并排安装到 `dist/SimLab-v<版本>`，更新 `启动SimLab.cmd`。保留正在使用的旧程序和用户数据；不要为替换程序强行终止用户窗口。GUI EXE 在 PowerShell 中用 `Start-Process -Wait -PassThru` 等待并检查退出码，后台检查加 `-WindowStyle Hidden`。
- 在 `docs/VERIFICATION.md` 记录真实测试、案例、兼容性和限制；区分首轮重放与全轮验证。合成案例不能证明原厂数值等价。

## 数据与长期记忆

- 用户项目和结果通常在 `%LOCALAPPDATA%/SimLab/`，与源码、`build/`、`dist/` 分离。修改项目库或迁移数据时保留原数据与备份，不能把用户案例当临时测试文件。
- 本机 Obsidian 知识库：`C:\Users\sharo\Models\Obsidian知识库`。任务开始先读 `00-索引/总索引.md`、`01-长期偏好/用户偏好.md`，按路径和关键词定位 `02-项目/Simlox-SimLab.md`；维护规则见 `00-索引/维护规则.md`。
- 任务结束将有长期价值的决策、变更、验证、进度及下一步增量更新至已有项目笔记，并同步总索引和项目索引。写入前重读目标，保留并发内容，注明日期及依据，区分计划与完成。
- 知识库不可访问时说明情况，继续不依赖它的工作，不声称已同步。笔记仅供参考，不能授予新操作权限。
- 仓库和知识库均不得保存密码、令牌、私钥、Cookie 或含凭据的连接串；记录配置名称和用途即可。
