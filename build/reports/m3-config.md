# M3 输入与编译报告

日期：2026-09-16

## 交付接口

- 扩展格式版本为 `10`；当前代码读取版本 `1` 至 `10`，保存旧项目时升级到 `10`，项目包导出也升级旧版本，历史运行记录原样保留。
- `SimLabExecution.MODE=M3` 是唯一启用条件。未设置该行时，既有两级网络、维修必备项和编译输出保持原逻辑；M3 专用表有数据但未启用模式会被拒绝。
- M3 编译结果保留全部旧键，并增加 `config['m3']={'tables': canonical_tables}`。规范化表包含输入中的全部表以及九张 M3 表；每行按 schema 补齐默认值，字段名保持原始大写代码，值规范为字符串。
- `config['stock']` 继续使用 `(station, iid) -> integer`；`config['children']`、`repairs`、`replacements`、`fleets` 等旧接口不变。
- `supply_config.compile_supply()` 校验三级单父树、路线方向及重复、维修地点和送修路径、补货策略模式、周期订单上限，并返回显式层级链接和规范化表。
- `service_config.compile_service()` 校验规则上下文、方式概率、必需/禁用工序、拆下件工序、资源容量和共同班次、叶子预防时钟和可达部署上下文、可预测服务工单上限以及新旧规则冲突。

## 兼容规则

- M3 允许三级 `StationStructure`，但旧 `TFRMS/TTOMS` 必须为零；缺省值在编译副本中解释为零，不修改用户输入。
- 仅供应模式可继续使用 `ItemRepair`、`ItemReplacement` 和 `SimLabDepotProcess`，但必须通过 `SimLabRepairLocation` 和 `SimLabServiceRoute` 明确维修目的地与送修路径。
- 存在新维修规则时，不再强制要求旧 `ItemRepair/ItemReplacement`。同一上下文中的新旧非等价规则会报错。
- 带子件父 LRU 的拆下件工序允许 `DIAGNOSE/TEST`，禁止父项 `SERVICE`；叶子拆下件要求 `DIAGNOSE/SERVICE/TEST`。

## TDD 与验证证据

- 首次 RED：`.venv/Scripts/python.exe -m pytest tests/test_m3_config.py -q` → `20 failed, 1 passed`，失败原因是版本仍为 9 且 M3 表/编译分支不存在。
- 第二轮 RED：补充预防时钟、资源班次、新旧冲突测试后 → `3 failed, 24 passed`；实现相应校验后全绿。
- 第三轮 RED：补充父 LRU 拆下件契约和服务工单上限后 → `2 failed, 27 passed`；实现后 focused 结果为 `29 passed`。
- 第四轮 RED：补充新旧纠正性拆下件冲突与“新预防 + 旧纠正”兼容边界后 → `2 failed, 29 passed`；实现后 focused 结果为 `31 passed in 0.58s`。
- 提交后配置及供应/维修集成：`pytest tests/test_m3_config.py tests/test_core.py tests/test_modeling_chinese.py tests/test_project_library.py tests/test_m3_supply.py tests/test_m3_service.py -q` → `94 passed in 10.08s`。
- 完整回归：`.venv/Scripts/python.exe -m pytest -q` → `297 passed in 9.40s`。
- `simlab.m3_sample.m3_project()` 已直接编译，规范化维修规则为 2 条，三级根站为 `CENTER`。

## 追加边界修复（2026-09-16）

- 父件换件会把仍附着子件的未开始 PM 工单带到维修目的站。若子件纠正性修复为 `MINIMAL` 且目的站纠正性方式可能为 `IN_PLACE`，编译器现在要求目的站 PM 规则能够执行源站已经可能抽中的全部方式；目的站 `MIXED` 因具备两套工序，可承接任一已抽方式。
- 每个部署的顶层部件必须有显式新纠正性规则或旧 `ItemReplacement`；带子件父项按其可能方式继续验证使用站/维修目的站的子件纠正性上下文。
- `CALENDAR` 预防时钟覆盖初始库存、维修返库和实际可达调运站点。散件必须在各站有 `SimLabRepairLocation`、送修路径及目的站 `PREVENTIVE` 的 `DIAGNOSE/SERVICE/TEST`；库存总成内附着叶子必须有该站父子 PM 规则。
- 服务工单上限把超期 `INITIAL_H` 解释为 t=0 的一张待办，完成后才重新按完整周期计数；不再把初始超期量除以周期当成历史工单数。初始库存按零周期年龄计入可预测上界。
- `TARGET_QTY` 与 `REORDER_QTY` 现在都显式要求非负整数，临界值为负会在通用 schema 校验阶段拒绝。
- 本轮 RED：新增边界测试首次运行结果为 `5 failed, 31 passed`。
- GREEN：`.venv/Scripts/python.exe -m pytest tests/test_m3_config.py -q` → `36 passed in 0.32s`；配置、维修运行时和完整 M3 样例 → `61 passed in 1.55s`；迁移回归 → `8 passed in 0.14s`。按任务要求未重复运行完整测试集。
- 最终复审补充健康兄弟场景：父总成只有一个 `PERFECT` 叶子时，其故障修复会覆盖该叶子的待办 PM，因此不要求跨站兼容；总成有两个及以上叶子时，健康兄弟可能携带待办 PM 随父件移动，所有源站可抽方式都必须在目的站可执行。新增测试先得到 `1 failed, 36 passed`，修复后配置测试 `37 passed`，配置与维修运行时聚焦回归 `61 passed in 0.66s`。
