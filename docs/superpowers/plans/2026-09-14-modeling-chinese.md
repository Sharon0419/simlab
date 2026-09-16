# 建模中文显示 Implementation Plan

**Goal:** 定位飞机主案例，将25张建模表的名称、字段与元数据、固定选项改为中文显示，保留原始数据。

**Architecture:** schema维护中文字段标签；独立UI格式化模块翻译元数据和枚举，delegate仅转换显示及选项文本，保存与交换沿用原始代码。项目库沿用现有入口。

**Tech Stack:** Python、PySide6、SQLite、PyInstaller。

- [x] 只读核验项目库飞机案例名称、路径和可读性。
- [x] 补齐schema中文标签，新增ui/modeling_labels.py处理单位、约束、选项及关联字段。
- [x] 修改ui/modeling.py中文标题、搜索与delegate；flight_timing移除正文中的字段代码；保留悬浮代码提示。
- [x] Qt专项验证中文覆盖、枚举编辑往返、不改变项目数据，更新smoke的中文表头断言，运行pytest与桌面检查。
- [x] 使用tools/build_windows.ps1构建暂存版，安装前等待用户关闭程序，备份旧版并验证安装版；同步README、验证记录和知识库。
