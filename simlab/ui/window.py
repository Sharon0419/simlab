import copy
import csv
import html
import json
import os
from pathlib import Path
import sys
import uuid
from PySide6.QtCore import Qt, QLockFile, QProcess, QTimer, QSettings, Signal
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (QMainWindow, QWidget, QFrame, QHBoxLayout, QVBoxLayout,
    QListWidget, QStackedWidget, QGridLayout, QLineEdit, QSpinBox, QDoubleSpinBox,
    QComboBox, QFormLayout, QProgressBar, QFileDialog, QMessageBox, QInputDialog,
    QTableWidget, QTableWidgetItem, QHeaderView, QTextBrowser, QTabWidget, QAbstractItemView)
from ..schema import TABLES, SCHEMA, value
from ..project import new_project, save_project, load_project, export_package, import_package, now, model_hash
from ..sample import demo_project
from ..validation import validate
from ..compiler import compile_model, ModelError
from .modeling import ModelEditor
from .widgets import STYLE, label, button, card, Metric, AvailabilityChart

def readonly_table(headers):
    table = QTableWidget(0, len(headers))
    table.setHorizontalHeaderLabels(headers)
    table.setEditTriggers(QAbstractItemView.NoEditTriggers)
    table.setSelectionBehavior(QAbstractItemView.SelectRows)
    table.setAlternatingRowColors(True)
    table.verticalHeader().setVisible(False)
    table.verticalHeader().setDefaultSectionSize(34)
    table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
    return table

def fill_table(table, rows):
    table.setRowCount(len(rows))
    for i, row in enumerate(rows):
        for j, cell in enumerate(row):
            table.setItem(i, j, QTableWidgetItem(str(cell)))

class MainWindow(QMainWindow):
    run_finished = Signal()
    def __init__(self, data_dir=None, restore=True):
        super().__init__()
        self.data_dir = Path(data_dir or Path(os.getenv('LOCALAPPDATA', str(Path.home()))) / 'SimLab')
        self.data_dir.mkdir(parents=True, exist_ok=True)
        (self.data_dir/'projects').mkdir(exist_ok=True)
        (self.data_dir/'jobs').mkdir(exist_ok=True)
        self.settings = QSettings('SimLab', 'Desktop')
        self.restore = restore
        self.project = None
        self.project_path = None
        self.lock = None
        self.dirty = False
        self.process = None
        self.active_run = None
        self.cancelled = False
        self.loading_controls = False
        self.setWindowTitle('SimLab · 本机保障仿真工作台')
        self.resize(1480, 940)
        self.setMinimumSize(1120, 760)
        self.setStyleSheet(STYLE)
        self.build_ui()
        self.autosave = QTimer(self)
        self.autosave.setInterval(1500)
        self.autosave.setSingleShot(True)
        self.autosave.timeout.connect(self.auto_save)
        self.progress_timer = QTimer(self)
        self.progress_timer.setInterval(250)
        self.progress_timer.timeout.connect(self.poll_progress)
        QShortcut(QKeySequence.Save, self, activated=self.save)
        QShortcut(QKeySequence.Open, self, activated=self.open_dialog)
        startup = self.settings.value('last_project', '') if restore else ''
        try:
            if startup and Path(startup).is_file():
                self.open_path(startup)
            else:
                path = self.data_dir/'projects'/'示例车辆保障.sqlite'
                if path.exists():
                    self.open_path(path)
                else:
                    self.adopt_project(demo_project(), path)
        except Exception as error:
            self.adopt_project(demo_project(), self.data_dir/'projects'/f'示例-{uuid.uuid4().hex[:8]}.sqlite')
            self.statusBar().showMessage('原项目未打开，已建立独立示例：'+str(error), 15000)

    def build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        sidebar = QFrame()
        sidebar.setObjectName('Sidebar')
        sidebar.setFixedWidth(204)
        sl = QVBoxLayout(sidebar)
        sl.setContentsMargins(8, 30, 8, 22)
        brand = label('SIMLAB', 'Brand')
        brand.setContentsMargins(22, 0, 0, 0)
        sl.addWidget(brand)
        sub = label('  保障仿真工作台', 'SidebarSub')
        sub.setContentsMargins(18, 2, 0, 24)
        sl.addWidget(sub)
        self.nav = QListWidget()
        self.nav.setObjectName('Navigation')
        self.nav.addItems(['01   项目概览', '02   模型数据', '03   仿真实验', '04   结果分析', '05   建模说明'])
        self.nav.currentRowChanged.connect(self.navigate)
        sl.addWidget(self.nav, 1)
        bottom = label('●  本机运行 · 数据本地保存\n\nSIMLOX 2017 字段基线\nv0.1.0  /  独立开发', 'SidebarSub')
        bottom.setContentsMargins(19, 0, 0, 0)
        sl.addWidget(bottom)
        root.addWidget(sidebar)
        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(26, 18, 26, 18)
        rl.setSpacing(22)
        top = QFrame()
        top.setObjectName('Topbar')
        tl = QHBoxLayout(top)
        tl.setContentsMargins(15, 10, 15, 10)
        self.project_title = label('')
        self.project_title.setStyleSheet('font-weight:650;')
        tl.addWidget(self.project_title, 1)
        self.project_buttons = []
        for text, callback in [('新建', self.new_dialog), ('打开', self.open_dialog), ('保存', self.save),
                               ('另存为', self.save_as), ('导入项目', self.import_dialog), ('导出项目', self.export_dialog)]:
            b = button(text, callback)
            tl.addWidget(b)
            self.project_buttons.append(b)
        rl.addWidget(top)
        self.pages = QStackedWidget()
        self.build_overview()
        self.editor = ModelEditor()
        self.editor.changed.connect(self.model_changed)
        self.pages.addWidget(self.editor)
        self.build_experiment()
        self.build_results()
        self.build_help()
        rl.addWidget(self.pages, 1)
        root.addWidget(right, 1)
        self.nav.setCurrentRow(0)
        self.statusBar().showMessage('就绪')

    def build_overview(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        head = QHBoxLayout()
        head.addWidget(label('项目概览', 'PageTitle'))
        head.addStretch()
        head.addWidget(button('重命名项目', self.rename_project))
        layout.addLayout(head)
        layout.addWidget(label('从装备模型到保障能力，用可复现的实验比较你的方案。', 'Muted'))
        metrics = QHBoxLayout()
        self.overview_metrics = []
        for title, subtitle in [('部署设备', 'SystemDeployment · QTYPS'), ('部件类型', 'Item · IID'),
                                ('保障站点', 'Station · STID'), ('已完成实验', '模型快照与结果保留在项目中')]:
            metric = Metric(title, subtitle)
            self.overview_metrics.append(metric)
            metrics.addWidget(metric)
        layout.addLayout(metrics)
        hero, hl = card()
        h = QHBoxLayout()
        h.addWidget(label('建模 → 校验 → 仿真 → 方案比较'))
        h.addStretch()
        h.addWidget(label('OFFLINE  /  本机版', 'Badge'))
        hl.addLayout(h)
        hl.addWidget(label('模型字段与本机 SIMLOX 2017 数据字典对齐。\n运行时采用独立开发的基础保障仿真引擎，每次实验都会记录输入快照、随机种子和统计结果。', 'Muted', True))
        flow = QHBoxLayout()
        for title, desc in [('01  装备与部件', 'System / Item\nMaterielStructure'),
                            ('02  保障与资源', 'Station / StockAllocation\nItemRepair / TaskResource'),
                            ('03  运行与比较', 'SystemDeployment / Control\n独立重复试验 / 结果追溯')]:
            box, bl = card()
            bl.addWidget(label(title))
            bl.addWidget(label(desc, 'Muted'))
            flow.addWidget(box)
        hl.addLayout(flow)
        actions = QHBoxLayout()
        actions.addWidget(button('编辑模型数据', lambda: self.nav.setCurrentRow(1), True))
        actions.addWidget(button('配置仿真实验', lambda: self.nav.setCurrentRow(2)))
        actions.addStretch()
        hl.addLayout(actions)
        layout.addWidget(hero)
        recent, recent_layout = card()
        recent_layout.addWidget(label('最近实验'))
        self.recent = readonly_table(['实验名称', '运行状态', '可用度', '重复次数', '开始时间'])
        self.recent.cellDoubleClicked.connect(lambda row, col: self.show_recent(row))
        recent_layout.addWidget(self.recent)
        layout.addWidget(recent, 1)
        self.path_label = label('', 'Muted', True)
        self.path_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(self.path_label)
        self.pages.addWidget(page)

    def build_experiment(self):
        page = QWidget()
        outer = QVBoxLayout(page)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(label('仿真实验', 'PageTitle'))
        outer.addWidget(label('参数直接对应 Control 表。运行前冻结模型，计算在独立子进程完成。', 'Muted'))
        body = QHBoxLayout()
        config, cl = card()
        cl.addWidget(label('实验配置'))
        form = QFormLayout()
        form.setVerticalSpacing(17)
        self.run_name = QLineEdit('基线方案')
        form.addRow('实验名称', self.run_name)
        self.repetitions = QSpinBox()
        self.repetitions.setRange(1, 1000)
        form.addRow('NREPS · 重复次数', self.repetitions)
        self.horizon = QDoubleSpinBox()
        self.horizon.setRange(0.01, 876000)
        self.horizon.setDecimals(2)
        self.horizon.setSuffix(' 小时')
        form.addRow('SIMPE · 仿真时长', self.horizon)
        self.interval = QDoubleSpinBox()
        self.interval.setRange(0.01, 876000)
        self.interval.setSuffix(' 小时')
        form.addRow('RCINT · 采样间隔', self.interval)
        self.seed = QLineEdit()
        form.addRow('RSEED · 随机种子', self.seed)
        self.point = QLineEdit()
        form.addRow('APID · 配置方案', self.point)
        cl.addLayout(form)
        cl.addStretch()
        self.experiment_controls = [self.repetitions, self.horizon, self.interval, self.seed, self.point]
        for control in self.experiment_controls:
            signal = control.valueChanged if isinstance(control, (QSpinBox, QDoubleSpinBox)) else control.textEdited
            signal.connect(self.controls_changed)
        controls = QHBoxLayout()
        controls.addWidget(button('校验模型', self.check_model))
        self.run_button = button('▶  开始仿真', self.start_run, True)
        controls.addWidget(self.run_button)
        self.cancel_button = button('取消', self.cancel_run)
        self.cancel_button.setEnabled(False)
        controls.addWidget(self.cancel_button)
        cl.addLayout(controls)
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        cl.addWidget(self.progress)
        self.run_status = label('等待运行', 'Muted', True)
        cl.addWidget(self.run_status)
        body.addWidget(config, 3)
        notes, nl = card()
        nl.addWidget(label('当前引擎的计算边界'))
        text = QTextBrowser()
        text.setHtml('''<p>支持系统直接安装多种 LRU，各部件组成串聯系统。</p>
        <p>故障率单位为每百万运行小时。系统按 UTIL 连续折算运行量，故障后暂停使用。</p>
        <p>支持两级保障网络、部件拆装、修复返库、运输延迟及组合资源排队。</p>
        <p>全量建模表均可保存交换；高级规则尚未接入的，会在运行前指出并拦截。</p>
        <p><b>结果口径：</b>可用度按状态持续时间精确积分；曲线为各重复试验的采样均值。</p>
        <p>本版不计算任务成功率，不支持原厂二进制 .sxi 文件直接导入。</p>''')
        nl.addWidget(text, 1)
        body.addWidget(notes, 2)
        outer.addLayout(body, 1)
        self.validation_box = QTextBrowser()
        self.validation_box.setMaximumHeight(200)
        self.validation_box.setPlainText('点击“校验模型”可检查字段、引用和本版计算支持范围。')
        outer.addWidget(self.validation_box)
        self.pages.addWidget(page)

    def build_results(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        head = QHBoxLayout()
        head.addWidget(label('结果分析', 'PageTitle'))
        head.addStretch()
        self.run_selector = QComboBox()
        self.run_selector.setMinimumWidth(230)
        self.run_selector.currentIndexChanged.connect(self.show_result)
        head.addWidget(self.run_selector)
        head.addWidget(button('导出结果 CSV', self.export_results))
        head.addWidget(button('从快照建立分支', self.branch_from_result))
        layout.addLayout(head)
        self.result_meta = label('运行一个实验，查看可用度、停机原因与资源瓶颈。', 'Muted', True)
        layout.addWidget(self.result_meta)
        self.result_cards = []
        metrics = QHBoxLayout()
        for title, subtitle in [('平均可用度', '按设备状态持续时间积分'), ('均值 95% 置信区间', '独立重复试验 · Student-t 近似'),
                                ('平均故障次数', '每次试验 / 全部设备'), ('设备数量', '本次实验的模型快照')]:
            metric = Metric(title, subtitle)
            if title == '均值 95% 置信区间':
                metric.number.setStyleSheet('font-size:22px;font-weight:700;')
            self.result_cards.append(metric)
            metrics.addWidget(metric)
        layout.addLayout(metrics)
        chart_card, chart_layout = card()
        chart_layout.addWidget(label('可用度随时间变化  /  各重复试验均值'))
        self.chart = AvailabilityChart()
        chart_layout.addWidget(self.chart)
        layout.addWidget(chart_card, 3)
        tabs = QTabWidget()
        self.downtime_table = readonly_table(['停机原因', '平均小时 / 台', '停机占比'])
        self.resource_table = readonly_table(['站点 / 资源', '平均占用率'])
        self.events_table = readonly_table(['仿真时间 / 小时', '对象', '事件', '部件'])
        self.compare_table = readonly_table(['实验', '可用度', 'P05 / P95', '配置方案', '重复次数', '模型指纹'])
        for title, widget in [('停机原因', self.downtime_table), ('资源利用率', self.resource_table),
                              ('首轮事件', self.events_table), ('实验对比', self.compare_table)]:
            tabs.addTab(widget, title)
        layout.addWidget(tabs, 2)
        self.pages.addWidget(page)

    def build_help(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(label('建模说明', 'PageTitle'))
        self.help = QTextBrowser()
        self.help.setOpenExternalLinks(False)
        self.help.setHtml('''<div style="padding:22px;line-height:1.7">
        <h2>从一个可核验的保障模型开始</h2>
        <p>1. 在 System 定义系统，在 Item 定义 LRU。用 MaterielStructure 关联系统与部件。</p>
        <p>2. 在 Station 定义站点，用 StationStructure 定义两级运输关系。</p>
        <p>3. 在 SystemDeployment 配置数量与使用率；USTID 可引用 Station 或 Unit。</p>
        <p>4. 在 StockAllocation 配置本地与修理中心库存；POINT 与 Control.APID 对应。</p>
        <p>5. 在 ItemRepair 定义上级修理中心的修复时间，在 ItemReplacement 定义使用站点的拆装时间。</p>
        <p>6. Tasks / TaskResource / Resource / ResourceAllocation 描述共享资源需求与数量。</p>
        <p>7. 校验模型，运行实验，比较库存和资源配置变化后的结果。</p>
        <h3>字段基线</h3>
        <p>本机 SIMLOX 2017 的 DatabaseDictionary_SIMLOX.txt：133 张表，891 个字段。保留原字段代码、顺序、数据类型、默认值、单位、约束与关联。中文为辅助标签。</p>
        <p>字段层面的对齐不代表原厂引擎的数值等价。仅当前已实现的基础模型可以运行，其他表仍可编辑和交换。</p>
        <h3>运行口径</h3>
        <p>FRT=1000 且 OPID=OPHOURS，表示平均每 1000 个运行小时发生一次故障。UTIL=0.5 表示每个可用日历小时累计 0.5 个运行小时。</p>
        <p>所有 LRU 故障均使设备停机，设备停机期间不累计运行故障。修复后按指数无记忆假设继续运行。暂不支持冗余、老化、班次、预防性维修、任务调度和供应中断。</p>
        <p>拆装总时间按 Control.RMVFR 分成拆卸和安装两段，各段原子申请全部资源。拆下部件送上级修理中心；每次备件请求向上级发出一件补充请求，修复件回到上级库。无上级时在本站修复返库。</p>
        <p>初始库存取 ISTOH（如填写）或 STSIZ。零库存也可运行，设备等待故障件修复返库。等待备件包含缺货与供应运输时间。</p>
        <p>可用度按整个 SIMPE 时间窗积分，初始设备全部可用，不丢弃预热期。置信区间估计均值精度；P05/P95 描述独立试验结果的波动。单次试验不提供置信区间。</p>
        <h3>项目与协作</h3>
        <p>编辑自动保存到本机 .sqlite 项目。每次覆盖前保留一个 .bak 备份。项目写入锁防止两个本软件实例同时编辑。</p>
        <p>.simproj 是带 SHA256 清单的项目快照。可以导出模型包或包含结果的完整包。导入自动创建新项目分支，保留来源项目与父修订，不覆盖原项目。</p>
        <p>不自动合并他人修改。CSV 表头使用原始字段代码，导入追加记录，重复键在校验时提示。原厂 .sxi 二进制文件不能直接导入。</p>
        <h3>结果追溯与限制</h3>
        <p>每次实验记录输入快照、版本、种子与模型哈希。历史结果不会随当前模型编辑改变。可从结果快照建立新项目重算。</p>
        <p>ENLOG=Y 时保存首轮最多 5000 条事件。批量重复试验在一个独立后台进程内顺序运行。当前限制：2000 台设备、1000 次重复、10000 个采样点、项目包 128 MB。</p>
        <p>这是独立开发的基础验证版，不是 Systecon 官方产品。用于探索与核验模型，工程决策前应通过真实案例校准。</p></div>''')
        layout.addWidget(self.help)
        self.pages.addWidget(page)

    def navigate(self, index):
        if not hasattr(self, 'pages'):
            return
        self.pages.setCurrentIndex(index)
        if self.project:
            if index == 2:
                self.sync_controls()
            if index == 0:
                self.refresh_overview()

    def adopt_project(self, project, path, save=True):
        if self.process is not None:
            raise ValueError('请先结束当前实验。')
        path = Path(path).resolve()
        path.parent.mkdir(parents=True, exist_ok=True)
        same = self.project_path == path and self.lock is not None
        new_lock = self.lock if same else QLockFile(str(path)+'.lock')
        if not same and not new_lock.tryLock(0):
            raise ValueError('项目正在另一个程序实例中使用。请另存为副本。')
        try:
            if save:
                save_project(project, path)
        except Exception:
            if not same:
                new_lock.unlock()
            raise
        if self.lock and not same:
            self.lock.unlock()
        self.lock = new_lock
        self.project, self.project_path, self.dirty = project, path, False
        interrupted = False
        for run in project['runs']:
            if run.get('status') == 'running':
                run['status'] = 'interrupted'
                run['error'] = '上次程序退出时实验未完成。'
                interrupted = True
        if interrupted:
            save_project(project, path)
        if self.restore:
            self.settings.setValue('last_project', str(path))
        self.editor.set_project(project)
        self.sync_controls()
        self.refresh_overview()
        self.refresh_results()
        self.statusBar().showMessage('已打开 '+str(path), 7000)

    def open_path(self, path):
        if self.dirty and not self.save():
            return
        project = load_project(path)
        self.adopt_project(project, path, save=False)

    def refresh_overview(self):
        if not self.project:
            return
        self.project_title.setText(self.project['name'])
        self.project_title.setToolTip(self.project['name'])
        self.project_title.setMaximumWidth(390)
        tables = self.project['tables']
        try:
            count = sum(int(float(value('SystemDeployment', r, 'QTYPS'))) for r in tables.get('SystemDeployment', []))
        except ValueError:
            count = '待校验'
        numbers = [count, len(tables.get('Item', [])), len(tables.get('Station', [])), sum(r.get('status') == 'completed' for r in self.project['runs'])]
        for metric, number in zip(self.overview_metrics, numbers):
            metric.number.setText(str(number))
        status = {'completed': '已完成', 'running': '运行中', 'cancelled': '已取消', 'failed': '失败', 'interrupted': '已中断'}
        rows = []
        for run in reversed(self.project['runs']):
            result = run.get('result', {})
            rows.append([run['name'], status.get(run['status'], run['status']),
                         f"{result['availability']:.2%}" if result else '—', result.get('replications', '—'), run['started']])
        fill_table(self.recent, rows)
        self.path_label.setText(f'项目位置：{self.project_path}\n项目 ID：{self.project["id"][:12]}   /   父修订：{self.project.get("parent_revision") or "初始项目"}')

    def model_changed(self):
        self.dirty = True
        self.autosave.start()
        self.statusBar().showMessage('模型已修改，正在等待自动保存…')
    def auto_save(self):
        if self.dirty:
            self.save()
    def save(self):
        if not self.project:
            return False
        try:
            self.autosave.stop()
            save_project(self.project, self.project_path)
            self.dirty = False
            self.refresh_overview()
            self.statusBar().showMessage('已保存 · '+str(self.project_path), 7000)
            return True
        except Exception as error:
            self.statusBar().showMessage('保存失败：'+str(error))
            self.warn('保存失败', str(error))
            return False
    def warn(self, title, message):
        QMessageBox.warning(self, title, message)
    def new_dialog(self):
        if self.process is not None:
            return
        name, ok = QInputDialog.getText(self, '新建项目', '项目名称')
        if ok and name.strip():
            if self.dirty and not self.save():
                return
            project = new_project(name.strip())
            project['tables']['Control'] = copy.deepcopy(demo_project()['tables']['Control'])
            try:
                self.adopt_project(project, self.data_dir/'projects'/f'{project["id"][:12]}.sqlite')
                self.nav.setCurrentRow(1)
                self.editor.select_table('System')
            except Exception as error:
                self.warn('新建失败', str(error))
    def rename_project(self):
        if self.process is not None:
            return
        name, ok = QInputDialog.getText(self, '项目名称', '名称', text=self.project['name'])
        if ok and name.strip():
            self.project['name'] = name.strip()
            self.model_changed()
            self.refresh_overview()
    def open_dialog(self):
        if self.process is not None:
            return
        path, _ = QFileDialog.getOpenFileName(self, '打开本机项目', str(self.data_dir/'projects'), 'SimLab 项目 (*.sqlite);;备份 (*.bak)')
        if path:
            try:
                self.open_path(path)
            except Exception as error:
                self.warn('打开失败', str(error))
    def save_as(self):
        if self.process is not None:
            return
        path, _ = QFileDialog.getSaveFileName(self, '另存项目分支', str(self.data_dir/'projects'/'新方案.sqlite'), '项目 (*.sqlite)')
        if path:
            try:
                if Path(path).resolve() == self.project_path:
                    self.save()
                    return
                branch = copy.deepcopy(self.project)
                branch['source_project_id'] = branch['id']
                branch['parent_revision'] = branch['revision']
                branch['id'] = str(uuid.uuid4())
                self.adopt_project(branch, path)
            except Exception as error:
                self.warn('另存失败', str(error))
    def export_dialog(self):
        modes = ['完整项目（包含已完成结果）', '模型项目（不含计算结果）']
        mode, ok = QInputDialog.getItem(self, '导出项目', '导出内容', modes, 0, False)
        if not ok:
            return
        path, _ = QFileDialog.getSaveFileName(self, '导出项目包', '项目交接.simproj', 'SimLab 项目包 (*.simproj)')
        if path and self.save():
            try:
                snapshot = copy.deepcopy(self.project)
                snapshot['runs'] = [r for r in snapshot['runs'] if r['status'] == 'completed']
                export_package(snapshot, path, mode == modes[0])
                self.statusBar().showMessage('项目包已导出：'+path, 10000)
            except Exception as error:
                self.warn('导出失败', str(error))
    def import_dialog(self):
        if self.process is not None:
            return
        path, _ = QFileDialog.getOpenFileName(self, '导入为独立项目分支', '', 'SimLab 项目包 (*.simproj)')
        if path:
            try:
                project = import_package(path)
                if self.dirty and not self.save():
                    return
                self.adopt_project(project, self.data_dir/'projects'/f'{project["id"][:12]}.sqlite')
                self.nav.setCurrentRow(0)
            except Exception as error:
                self.warn('导入失败', str(error))

    def sync_controls(self):
        self.loading_controls = True
        rows = self.project['tables'].get('Control', [])
        row = rows[0] if rows else {}
        for widget, column in [(self.repetitions, 'NREPS'), (self.horizon, 'SIMPE'), (self.interval, 'RCINT')]:
            try:
                number = float(value('Control', row, column, '1'))
                widget.setValue(int(number) if isinstance(widget, QSpinBox) else number)
            except (ValueError, OverflowError):
                widget.setValue(widget.minimum())
        self.seed.setText(value('Control', row, 'RSEED'))
        self.point.setText(value('Control', row, 'APID'))
        self.loading_controls = False
    def controls_changed(self, *args):
        if self.loading_controls or not self.project:
            return
        rows = self.project['tables'].setdefault('Control', [])
        if not rows:
            rows.append({})
        rows[0].update(NREPS=str(self.repetitions.value()), SIMPE=str(self.horizon.value()), RCINT=str(self.interval.value()),
                       RSEED=self.seed.text().strip(), APID=self.point.text().strip())
        if self.editor.current_table == 'Control':
            self.editor.select_table('Control')
        self.model_changed()
    def check_model(self):
        try:
            config = compile_model(self.project['tables'])
            self.validation_box.setHtml(f'<p style="color:#82d9b5">校验通过：{config["count"]} 台设备，{config["replications"]} 次重复试验。</p><p>字段、引用关系及当前计算范围均可接受。</p>')
            return True
        except ModelError as error:
            self.validation_box.setHtml('<b style="color:#ff9b99">请处理以下模型问题：</b><br>'+ '<br>'.join(html.escape(x) for x in error.errors[:100]) + (f'<br>共 {len(error.errors)} 项' if len(error.errors) > 100 else ''))
            return False
        except Exception as error:
            self.validation_box.setPlainText('模型无效：'+str(error))
            return False
    def set_busy(self, busy):
        self.editor.setEnabled(not busy)
        for widget in self.experiment_controls + self.project_buttons + [self.run_name]:
            widget.setEnabled(not busy)
        self.run_button.setEnabled(not busy)
        self.cancel_button.setEnabled(busy)
    def start_run(self):
        if self.process is not None or not self.check_model():
            return
        if not self.save():
            return
        run_id = uuid.uuid4().hex
        self.job_dir = self.data_dir/'jobs'/run_id
        self.job_dir.mkdir()
        self.output_path = self.job_dir/'result.json'
        source = self.job_dir/'model.json'
        snapshot = copy.deepcopy(self.project['tables'])
        source.write_text(json.dumps(snapshot, ensure_ascii=False), encoding='utf-8')
        self.active_run = {'id': run_id, 'name': self.run_name.text().strip() or '未命名实验', 'status': 'running',
                           'started': now(), 'snapshot': snapshot, 'model_hash': model_hash(snapshot),
                           'source_revision': self.project['revision']}
        self.project['runs'].append(self.active_run)
        if not self.save():
            self.project['runs'].remove(self.active_run)
            self.active_run = None
            return
        self.cancelled = False
        self.worker_error = ''
        self.progress.setValue(0)
        self.run_status.setText('正在后台计算…')
        self.process = QProcess(self)
        self.process.setWorkingDirectory(str(Path(__file__).resolve().parents[2]))
        self.process.finished.connect(self.worker_finished)
        self.process.errorOccurred.connect(self.worker_failed)
        if getattr(sys, 'frozen', False):
            args = ['--worker', str(source), str(self.output_path)]
        else:
            args = [str(Path(__file__).resolve().parents[2]/'main.py'), '--worker', str(source), str(self.output_path)]
        self.set_busy(True)
        self.process.start(sys.executable, args)
        self.progress_timer.start()
    def poll_progress(self):
        if self.process is None:
            return
        path = self.output_path.with_suffix('.progress.json')
        try:
            message = json.loads(path.read_text(encoding='utf-8'))
            if 'progress' in message:
                self.progress.setValue(message['progress'])
                self.run_status.setText(f'后台计算中 · {message["progress"]}%')
            if 'error' in message:
                self.worker_error = message['error']
        except (OSError, ValueError):
            pass
    def worker_failed(self, error):
        if error == QProcess.FailedToStart:
            self.worker_error = '无法启动计算进程：'+self.process.errorString()
            self.worker_finished(-1, QProcess.CrashExit)
    def worker_finished(self, exit_code, status):
        if self.process is None:
            return
        self.poll_progress()
        self.progress_timer.stop()
        # Saving replaces nested lists with the durable snapshot. Resolve by ID,
        # rather than mutating the pre-save run object which may now be stale.
        run = next(r for r in self.project['runs'] if r['id'] == self.active_run['id'])
        if self.cancelled:
            run['status'] = 'cancelled'
            self.run_status.setText('实验已取消；未生成完成结果。')
        elif exit_code == 0 and self.output_path.exists():
            try:
                result = json.loads(self.output_path.read_text(encoding='utf-8'))
                if result['model_hash'] != run['model_hash']:
                    raise ValueError('结果与模型快照不匹配。')
                run['status'], run['result'] = 'completed', result
                self.progress.setValue(100)
                self.run_status.setText(f'已完成 · 平均可用度 {result["availability"]:.2%}')
            except Exception as error:
                run['status'], run['error'] = 'failed', str(error)
        else:
            run['status'] = 'failed'
            run['error'] = self.worker_error or f'计算进程异常退出（{exit_code}）。诊断目录：{self.job_dir}'
        if run['status'] == 'failed':
            self.run_status.setText('运行失败：'+run['error'])
        self.process.deleteLater()
        self.process = None
        self.active_run = None
        self.set_busy(False)
        self.save()
        self.refresh_results()
        if run['status'] == 'completed':
            self.nav.setCurrentRow(3)
            self.run_selector.setCurrentIndex(self.run_selector.count()-1)
        self.run_finished.emit()
    def cancel_run(self):
        if self.process is not None:
            self.cancelled = True
            self.process.kill()

    def refresh_results(self):
        previous = self.run_selector.currentData()
        self.run_selector.blockSignals(True)
        self.run_selector.clear()
        self.complete_runs = [r for r in self.project['runs'] if r.get('status') == 'completed' and r.get('result')]
        for run in self.complete_runs:
            self.run_selector.addItem(run['name']+' · '+run['id'][:6], run['id'])
        index = self.run_selector.findData(previous)
        self.run_selector.setCurrentIndex(index if index >= 0 else self.run_selector.count()-1)
        self.run_selector.blockSignals(False)
        comparisons = []
        for run in self.complete_runs:
            result = run['result']
            comparisons.append([run['name'], f'{result["availability"]:.2%}', f'{result["p05"]:.2%} / {result["p95"]:.2%}', result['point'], result['replications'], result['model_hash'][:12]])
        fill_table(self.compare_table, comparisons)
        self.show_result()
    def selected_run(self):
        return next((r for r in self.complete_runs if r['id'] == self.run_selector.currentData()), None)
    def show_result(self, *args):
        run = self.selected_run() if hasattr(self, 'complete_runs') else None
        if not run:
            for metric in self.result_cards:
                metric.number.setText('—')
            self.chart.set_samples([])
            self.result_meta.setText('运行一个实验，查看可用度、停机原因与资源瓶颈。')
            for table in (self.downtime_table, self.resource_table, self.events_table):
                table.setRowCount(0)
            return
        result = run['result']
        confidence = result['ci95']
        numbers = [f'{result["availability"]:.2%}', f'{confidence[0]:.1%} – {confidence[1]:.1%}' if confidence else '单次试验',
                   f'{result["failures"]:.1f}', str(result['fleet_size'])]
        for metric, number in zip(self.result_cards, numbers):
            metric.number.setText(number)
        changed = '当前模型已修改，以下为历史快照结果' if model_hash(self.project['tables']) != result['model_hash'] else '与当前模型一致'
        extra = ' · 首轮事件已截断至 5000 条' if result.get('events_truncated') else ''
        self.result_meta.setText(f'{result["horizon"]/24:g} 天 / {result["replications"]} 次试验 / 种子 {result["seed"]} / {changed}{extra}')
        self.chart.set_samples(result['samples'])
        names = {'waiting_spare': '等待备件（含供应运输）', 'waiting_resource': '等待拆装资源', 'replacement': '拆卸与安装作业'}
        total = sum(result['downtime'].values())
        fill_table(self.downtime_table, [[names[key], f'{val:.2f}', f'{val/total:.1%}' if total else '0%'] for key, val in result['downtime'].items()])
        fill_table(self.resource_table, [[key, f'{val:.1%}'] for key, val in result['resources'].items()])
        fill_table(self.events_table, [[f'{e["time"]:.2f}', e['asset'], e['event'], e['item']] for e in result['events']])
    def show_recent(self, row):
        runs = list(reversed(self.project['runs']))
        if row < len(runs):
            index = self.run_selector.findData(runs[row]['id'])
            if index >= 0:
                self.run_selector.setCurrentIndex(index)
                self.nav.setCurrentRow(3)
    def branch_from_result(self):
        run = self.selected_run()
        if not run or self.process is not None:
            return
        if self.dirty and not self.save():
            return
        branch = new_project(self.project['name']+' · 实验快照')
        branch['parent_revision'] = run['source_revision']
        branch['source_project_id'] = self.project['id']
        branch['tables'] = copy.deepcopy(run['snapshot'])
        try:
            self.adopt_project(branch, self.data_dir/'projects'/f'{branch["id"][:12]}.sqlite')
            self.nav.setCurrentRow(1)
        except Exception as error:
            self.warn('创建分支失败', str(error))
    def export_results(self):
        run = self.selected_run()
        if not run:
            return
        path, _ = QFileDialog.getSaveFileName(self, '导出当前结果时间曲线', '可用度结果.csv', 'CSV (*.csv)')
        if path:
            try:
                with open(path, 'w', encoding='utf-8-sig', newline='') as file:
                    writer = csv.writer(file)
                    writer.writerow(['run_id', 'model_hash', 'seed', 'time_hours', 'availability'])
                    for sample in run['result']['samples']:
                        writer.writerow([run['id'], run['model_hash'], run['result']['seed'], sample['time'], sample['available']])
                self.statusBar().showMessage('结果已导出：'+path, 10000)
            except Exception as error:
                self.warn('导出失败', str(error))
    def closeEvent(self, event):
        if self.process is not None:
            if QMessageBox.question(self, '实验仍在运行', '取消当前实验并退出？') != QMessageBox.Yes:
                event.ignore()
                return
            self.cancelled = True
            process = self.process
            process.kill()
            process.waitForFinished(5000)
        if self.dirty and not self.save():
            event.ignore()
            return
        self.autosave.stop()
        if self.lock:
            self.lock.unlock()
        event.accept()
