# SimLab 实际软件架构与数据流

2026-09-07，按当前源码核对。界面与后台计算均在本机执行，后台是独立计算进程，没有 HTTP API 或远程服务器。

## 软件架构图

```mermaid
flowchart TB
    U["用户"] --> UI
    subgraph desktop["桌面主进程 · PySide6 / Qt"]
        UI["中文界面：建模 / 实验 / 结果"]
        V["模型校验与编译入口"]
        PM["项目管理 · project.py"]
        JOB["作业管理 · QProcess / QTimer"]
        UI --> V
        UI <--> PM
        UI <--> JOB
    end
    subgraph compute["独立计算进程 · 同一程序的 --worker 模式"]
        W["worker.py · 输入输出与进度"]
        C["compiler.py · 校验 / 单位换算 / 执行配置"]
        E["engine.py · SimPy 故障、维修、库存、运输、排队"]
        S["NumPy · 随机数与重复试验统计"]
        W --> C --> E
        E <--> S
    end
    subgraph storage["本机文件"]
        D["schema.json · 字段字典"]
        DB[("SQLite · 模型 / 快照 / 运行结果")]
        F["作业 JSON · 模型 / 进度 / 结果"]
        PK["simproj 交换包"]
    end
    D -.-> V
    D -.-> C
    JOB -->|启动与取消| W
    JOB <-->|写输入、读输出| F
    W <-->|读输入、写输出| F
    PM <--> DB
    PM <-->|导入导出| PK
    classDef blue fill:#112139,stroke:#60a5fa,color:#eff6ff;
    class U,UI,V,PM,JOB,W,C,E,S,D,DB,F,PK blue;
    style desktop fill:#0b1426,stroke:#365477,color:#eff6ff
    style compute fill:#0b1426,stroke:#365477,color:#eff6ff
    style storage fill:#0b1426,stroke:#365477,color:#eff6ff
```

## 数据流图

```mermaid
flowchart TB
    INPUT["用户编辑 / CSV 导入 / 项目打开"] --> MODEL["内存中的模型表与实验参数"]
    MODEL --> CHECK{"校验与支持范围检查"}
    CHECK -->|不通过：字段或规则问题| INPUT
    CHECK -->|通过| SNAP["冻结快照、模型哈希、创建运行记录"]
    SNAP --> DB[("项目 SQLite")]
    SNAP --> INFILE["model.json"]
    INFILE --> COMP["后台读取并编译执行配置"]
    COMP --> SIM["多次离散事件仿真"]
    SIM --> PROG["result.progress.json"]
    PROG -->|界面每 250 ms 读取| BAR["进度显示"]
    SIM --> STAT["可用度积分、停机原因、资源利用率、置信区间"]
    STAT --> OUT["result.json · 临时文件写完后替换"]
    OUT --> VERIFY{"进程正常退出且模型哈希匹配"}
    VERIFY -->|是| DONE["记录 completed、保存结果"]
    VERIFY -->|否| FAIL["记录 failed 与错误信息"]
    DONE --> DB
    FAIL --> DB
    DB --> VIEW["结果曲线 / 历史实验对比"]
    VIEW --> EXPORT["结果 CSV / 项目交换包"]
    VIEW -.->|调整方案再运行| MODEL
    classDef blue fill:#112139,stroke:#60a5fa,color:#eff6ff;
    class INPUT,MODEL,CHECK,SNAP,DB,INFILE,COMP,SIM,PROG,BAR,STAT,OUT,VERIFY,DONE,FAIL,VIEW,EXPORT blue;
```

取消是额外的控制流：用户点击取消 → QProcess.kill → 主进程记录 cancelled 并保存，不产生完成结果。后台异常也会生成错误日志。两个图描述当前实现，不把未来的任务调度、优化或云端服务画成现成功能。

## 可执行证据

- 2026-09-07 本次核心测试：`14 passed in 0.84s`。
- 当前 Windows 可执行版端到端检查：八项 passed，退出码 0。
- 证据文件：`build/qa-architecture-check/smoke-result.json`。
- 合成示例重复 10 次，计算可用度为 `0.9596487296178109`；这不是实际装备指标。
- 调用入口：`simlab/ui/window.py:start_run` → `main.py --worker` → `simlab/worker.py:main` → `simlab/engine.py:simulate`。

能力边界：字段可编辑不代表全部规则可仿真。当前支持基础故障、维修、库存、运输和资源排队；多层维修结构、任务调度、冗余和自动优化尚未实现。
