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
    QTableWidget, QTableWidgetItem, QHeaderView, QTextBrowser, QTabWidget, QAbstractItemView,
    QDialog, QDialogButtonBox)
from ..schema import TABLES, SCHEMA, value
from ..project import new_project, save_project, load_project, export_package, import_package, now, model_hash
from ..sample import demo_project, mission_project, layered_project, duty_project
from .. import __version__
from ..missions import GAP_LABELS
from ..maintenance import PHASES
from ..validation import validate
from ..compiler import compile_model, ModelError
from ..flight_results import export_tasks, export_ground, export_planned, export_inspection_clocks, export_aging, REASONS, PHASES as FLIGHT_PHASES, STATUSES, CANCEL_REASONS, GROUND_STATUSES, PLANNED_STATUSES
from .flight_timing import clock
from .modeling import ModelEditor
from .structure import StructureView
from .duty import DutyPlanner
from ..project_library import ProjectLibrary,copy_model
from .library import LibraryPage
from .m3_results import M3ResultsPage
from .widgets import STYLE, label, button, card, Metric, AvailabilityChart, MissionChart

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
        self.catalog=ProjectLibrary(self.data_dir)
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
        self.nav.addItem('06   组成结构')
        self.nav.addItem('07   值守计划')
        self.nav.addItem('08   项目库')
        self.nav.currentRowChanged.connect(self.navigate)
        sl.addWidget(self.nav, 1)
        bottom = label(f'v{__version__}', 'SidebarSub')
        bottom.setToolTip('本机运行 · 数据本地保存 · SIMLOX 2017 字段基线 · 独立开发')
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
        self.structure = StructureView()
        self.pages.addWidget(self.structure)
        self.duty_planner = DutyPlanner()
        self.duty_planner.changed.connect(self.duty_changed)
        self.duty_planner.example_requested.connect(self.new_duty_demo)
        self.pages.addWidget(self.duty_planner)
        self.library=LibraryPage(self.catalog)
        self.library.open_requested.connect(self.library_open)
        self.library.copy_requested.connect(self.library_copy)
        self.library.import_requested.connect(self.import_dialog)
        self.pages.addWidget(self.library)
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
        head.addWidget(button('进入项目库',lambda:self.nav.setCurrentRow(7)))
        head.addStretch()
        head.addWidget(button('重命名项目', self.rename_project))
        self.mission_demo_button = button('新建任务日历示例', self.new_mission_demo, True)
        head.addWidget(self.mission_demo_button)
        self.layered_demo_button = button('新建多层维修示例', self.new_layered_demo)
        head.addWidget(self.layered_demo_button)
        layout.addLayout(head)
        self.m3_demo_button = button('新建三级供应与维修方式示例', self.new_m3_demo)
        m3_actions = QHBoxLayout()
        m3_actions.addWidget(self.m3_demo_button)
        m3_actions.addWidget(button('新建采购与报废示例', self.new_lifecycle_demo))
        m3_actions.addWidget(button('预览并迁移当前项目到 M3', self.migrate_m3))
        layout.addLayout(m3_actions)
        metrics = QHBoxLayout()
        self.overview_metrics = []
        for title, subtitle in [('部署设备', 'SystemDeployment · QTYPS'), ('部件类型', 'Item · IID'),
                                ('保障站点', 'Station · STID'), ('已完成实验', '模型快照与结果保留在项目中')]:
            metric = Metric(title, subtitle)
            self.overview_metrics.append(metric)
            metrics.addWidget(metric)
        layout.addLayout(metrics)
        hero, hl = card()
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
        self.path_label.hide()
        details = button("项目详情")
        details.setCheckable(True)
        details.toggled.connect(self.path_label.setVisible)
        layout.addWidget(details, 0, Qt.AlignLeft)
        layout.addWidget(self.path_label)
        self.pages.addWidget(page)

    def build_experiment(self):
        page = QWidget()
        outer = QVBoxLayout(page)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(label('仿真实验', 'PageTitle'))
        body = QHBoxLayout()
        config, cl = card()
        cl.addWidget(label('实验配置'))
        form = QFormLayout()
        form.setVerticalSpacing(17)
        self.run_name = QLineEdit('基线方案')
        form.addRow('实验名称', self.run_name)
        self.repetitions = QSpinBox()
        self.repetitions.setRange(1, 1000)
        form.addRow('重复次数', self.repetitions)
        self.horizon = QDoubleSpinBox()
        self.horizon.setRange(0.01, 876000)
        self.horizon.setDecimals(2)
        self.horizon.setSuffix(' 小时')
        form.addRow('仿真时长', self.horizon)
        self.interval = QDoubleSpinBox()
        self.interval.setRange(0.01, 876000)
        self.interval.setSuffix(' 小时')
        form.addRow('采样间隔', self.interval)
        self.seed = QLineEdit()
        form.addRow('随机种子', self.seed)
        self.point = QLineEdit()
        form.addRow('配置方案', self.point)
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
        text.setHtml('''<p>支持 System→LRU→SRU 串联结构。基地整换 LRU，修理站检测、换修 SRU、测试后返库。</p>
        <p>故障率单位为每百万运行小时。系统按 UTIL 连续折算运行量，故障后暂停使用。</p>
        <p>旧模式支持两级保障；M3支持三级显式供应、维修分流及叶件预防维修。支持运输延迟及组合资源排队。</p>
        <p>建模界面仅展示当前支持的表，按 01–07 建模流程排列。尚未接入的高级规则会在运行前指出并拦截。</p>
        <p><b>结果口径：</b>可用度按状态持续时间精确积分；曲线为各重复试验的采样均值。</p>
        <p>填写 Operations 后启用固定值守窗口：UTIL=1，待命和补位准备不累计运行故障；按优先级分配空闲设备，不抢占。SimLabDutyRule 可配置最低保障、补位时间和连续不达标容忍时间。</p>
        <p>资源班次按 ShiftProfile 显式时间窗执行：班内开始，允许跨班完成。任务满足率是设备小时供给比例，不等同原厂任务成功率。</p>
        <p>从项目概览“新建任务日历示例”开始；不支持原厂二进制 .sxi 文件直接导入。</p>''')
        nl.addWidget(text, 1)
        self.calculation_notes = notes
        notes.hide()
        self.notes_button = button("计算说明")
        self.notes_button.setCheckable(True)
        self.notes_button.toggled.connect(notes.setVisible)
        cl.addWidget(self.notes_button, 0, Qt.AlignLeft)
        body.addWidget(notes, 2)
        outer.addLayout(body, 1)
        self.validation_box = QTextBrowser()
        self.validation_box.setMaximumHeight(200)
        self.validation_box.hide()
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
        self.mission_export_button = button('导出任务 CSV', self.export_missions)
        head.addWidget(self.mission_export_button)
        head.addWidget(button('逐轮飞行 CSV', self.export_flight_details))
        self.maintenance_export_button = button('维修 CSV', self.export_maintenance)
        head.addWidget(self.maintenance_export_button)
        head.addWidget(button('从快照建立分支', self.branch_from_result))
        layout.addLayout(head)
        self.result_meta = label('暂无实验结果', 'Muted', True)
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
        self.chart_tabs = QTabWidget()
        self.chart_tabs.addTab(chart_card, '可用度曲线')
        mission_card, mission_layout = card()
        self.mission_summary = label('本实验没有任务日历。', 'Muted', True)
        mission_layout.addWidget(self.mission_summary)
        self.mission_chart = MissionChart()
        mission_layout.addWidget(self.mission_chart)
        self.chart_tabs.addTab(mission_card, '任务供需')
        layout.addWidget(self.chart_tabs, 3)
        tabs = QTabWidget()
        self.downtime_table = readonly_table(['停机原因', '平均小时 / 台', '停机占比'])
        self.resource_table = readonly_table(['站点 / 资源', '平均占用率'])
        self.events_table = readonly_table(['仿真时间 / 小时', '对象', '事件', '部件'])
        self.compare_table = readonly_table(['实验', '可用度', '任务满足率', 'P05 / P95', '配置方案', '重复次数', '模型指纹'])
        self.mission_table = readonly_table(['任务窗口', '开始 / 小时', '结束 / 小时', '需求设备', '供给设备小时', '缺口设备小时', '全程无缺口比例'])
        self.gap_table = readonly_table(['缺口原因', '平均缺口设备小时'])
        self.maintenance_table = readonly_table(['层级', '平均送修数', '平均完成数', '平均未完成数', '已完成平均周转 / 小时'])
        self.phase_table = readonly_table(['层级', '维修工序', '平均总耗时 / 小时'])
        self.component_table = readonly_table(['实物编号', '部件类型', '父实物', '自身状态', '所在流程', '站点', '健康状态'])
        self.duty_table = readonly_table(['窗口', '目标 / 最低', '达标时间比例', '窗口合格率', '平均不达标 / 小时', '最长连续均值 / 小时'])
        self.duty_intervals = readonly_table(['首轮不达标窗口', '开始 / 小时', '结束 / 小时', '实际 / 最低', '缺口原因分摊（设备数）'])
        self.flight_table = readonly_table(['飞行评估指标', '跨重复试验均值'])
        self.success_table = readonly_table(['任务', '计划成功点', '成功点比例', '起飞率', '成功率 FMSUC', '完整完成率', '成功架次均值'])
        self.success_details = readonly_table(['首轮任务', '物理终态', '成功判定', '实际成功时间', '成功阶段', '判定原因', '成员', '成功成员'])
        self.ground_table=readonly_table(['准备评估指标','跨轮均值'])
        self.ground_jobs=readonly_table(['首轮飞机','作业','排队时刻/h','开始/h','结束/h','等待/h','作业/h','状态'])
        self.cancel_table=readonly_table(['首轮取消任务','主要分类','起飞时飞机状态分布'])
        ground_page=QWidget();ground_layout=QVBoxLayout(ground_page)
        ground_layout.addWidget(button('导出全部轮次准备作业 CSV',self.export_ground_details))
        ground_layout.addWidget(self.ground_jobs)
        self.planned_table = readonly_table(['计划维修指标','跨轮均值'])
        self.planned_jobs = readonly_table(['首轮飞机','计划','到期/h','申请/h','开始/h','结束/h','延后/h','等资源/h','作业/h','状态'])
        planned_page = QWidget(); planned_layout = QVBoxLayout(planned_page)
        planned_layout.addWidget(button('导出全部轮次计划维修 CSV', self.export_planned_details))
        planned_layout.addWidget(self.planned_table)
        planned_layout.addWidget(self.planned_jobs)
        self.inspection_clocks = readonly_table(['首轮飞机','检查','初始/h','本轮在空/h','距上次检查/h','间隔/h','完成次数','是否到期','超限/h'])
        self.inspection_jobs = readonly_table(['首轮飞机','检查','到期/h','开始/h','完成/h','周期已飞/h','超限/h','状态'])
        inspection_page = QWidget(); inspection_layout = QVBoxLayout(inspection_page)
        inspection_layout.addWidget(button('导出全部轮次检查计时 CSV', self.export_inspection_details))
        inspection_layout.addWidget(button('导出全部轮次维修工单 CSV', self.export_planned_details))
        inspection_layout.addWidget(self.inspection_clocks)
        inspection_layout.addWidget(self.inspection_jobs)
        self.age_instances = readonly_table(['首轮实物号','部件','有效年龄/h','终身运行/h','状态','位置'])
        self.age_events = readonly_table(['首轮时间/h','实物号','部件','事件','处理前年龄/h','处理后年龄/h','终身运行/h','修复方式'])
        aging_page = QWidget(); aging_layout = QVBoxLayout(aging_page)
        self.age_notice = label('配置部件老化后运行实验以查看年龄。')
        aging_layout.addWidget(self.age_notice)
        aging_layout.addWidget(button('导出全部轮次部件年龄 CSV', lambda: self.export_age_details(False)))
        aging_layout.addWidget(button('导出全部轮次故障修复年龄 CSV', lambda: self.export_age_details(True)))
        aging_layout.addWidget(self.age_instances)
        aging_layout.addWidget(self.age_events)
        self.flight_phase_table = readonly_table(['飞行任务', '计划出航 / 小时', '计划执行 / 小时', '计划返航 / 小时',
                                                  '实际出航 / 架·小时', '实际执行 / 架·小时', '实际返航 / 架·小时', '其中中止返航 / 架·小时'])
        for title, widget in [('停机原因', self.downtime_table), ('资源利用率', self.resource_table),
                              ('首轮事件', self.events_table), ('实验对比', self.compare_table),
                              ('任务窗口', self.mission_table), ('任务缺口', self.gap_table),
                              ('维修统计', self.maintenance_table), ('工序耗时', self.phase_table), ('部件实例', self.component_table),
                              ('值守达标', self.duty_table), ('不达标时段', self.duty_intervals), ('飞行与备用机', self.flight_table), ('飞行阶段', self.flight_phase_table),
                              ('任务成功率', self.success_table), ('首轮成功判定', self.success_details),
                              ('准备资源评估',self.ground_table),('再次出动准备',ground_page),('取消原因',self.cancel_table),('计划维修汇总',planned_page),('飞行小时检查',inspection_page)]:
            tabs.addTab(widget, title)
        self.result_tabs = tabs
        tabs.addTab(aging_page, '部件老化')
        self.m3_supply_page = M3ResultsPage('supply')
        self.m3_service_page = M3ResultsPage('service')
        tabs.addTab(self.m3_supply_page, '调运与采购')
        tabs.addTab(self.m3_service_page, '维修与寿命')
        tabs.currentChanged.connect(lambda index: self.chart_tabs.setVisible(tabs.widget(index) not in (
            planned_page, inspection_page, aging_page, self.m3_supply_page, self.m3_service_page)))
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
        <h3>三级供应与维修方式</h3>
        <p>在项目概览点击“新建三级供应与维修方式示例”，可直接体验飞机案例。M3执行模式使用三级地点、显式供货与送修路线；没有配置直达策略就不能跳过中间仓。</p>
        <p>补货按库存位置（可用＋已申请未到货－未满足需求）补到目标值。临界库存与周期调运二选一，短时且有货的路线优先，允许拆分；缺货申请持续等待，有货即可履行。运输只计时间，不设容量。</p>
        <p>修复性和预防性维修分别设置原位/换件方式、换件比例及各工序时间与资源。每次只抽一次方式，缺件不改抽；预防性部件完成作业后修复如新，普通飞行小时检查不改变年龄。</p>
        <p>在项目概览新建“采购与报废示例”，可配置任意地点的外部采购、固定交期及部件寿命限值。采购按目标库存补足，与调运同时可用时优先较早到货；新采购件从零寿命开始。累计运行小时或修复次数任一到限即报废，飞行中到限则落地后换件。报废后处置不模拟。</p>
        <p>“调运与采购”和“维修与寿命”结果页显示首轮明细，导出包含全部轮次。旧模型未启用M3时保持原有计算规则；以下两级操作说明针对旧模式。</p>
        <p>1. 在 System 定义系统，在 Item 定义 LRU。用 MaterielStructure 关联系统与部件。</p>
        <p>2. 在 Station 定义站点，用 StationStructure 定义两级运输关系。</p>
        <p>3. 在 SystemDeployment 配置数量与使用率；USTID 可引用 Station 或 Unit。</p>
        <p>4. 在 StockAllocation 配置本地与修理中心库存；POINT 与 Control.APID 对应。</p>
        <p>5. 在 ItemRepair 定义上级修理中心的修复时间，在 ItemReplacement 定义使用站点的拆装时间。</p>
        <p>6. Tasks / TaskResource / Resource / ResourceAllocation 描述共享资源需求与数量。</p>
        <p>7. 校验模型，运行实验，比较库存和资源配置变化后的结果。</p>
        <h3>字段基线</h3>
        <p>0.3 新增独立 SimLabDepotProcess 扩展表：LRU/STATION 标识维修路由，DIAG_H/DIAG_TASK 为检测时间和资源任务，TEST_H/TEST_TASK 为修后测试。不是原厂表；原字典仍为 133 表/891 字段。</p>
        <h3>多层维修</h3>
        <p>带 SRU 的 LRU 要求 FRT=0、AFFRT=1，故障来自叶子 SRU。MaterielStructure 描述两层组成；ItemReplacement 描述基地 System/LRU 与站内 LRU/SRU 拆装；ItemRepair 仅描述叶子直接修复。</p>
        <p>备用 LRU 隐含完整健康子件，SRU 库存数量表示额外散件。等待 SRU 时释放工序资源，故障 SRU 单独修复；父 LRU 安装完成并通过测试后返库。车辆有备用 LRU 时可先恢复，不等待故障模块修复。</p>
        <p>维修统计包含未完成工单已发生的工序耗时；平均周转仅计已完成工单。部件实例与维修 CSV 是首轮样本，最多 1000 条，不能当成所有重复的完整历史。</p>
        <p>本机 SIMLOX 2017 的 DatabaseDictionary_SIMLOX.txt：133 张表，891 个字段。保留原字段代码、顺序、数据类型、默认值、单位、约束与关联。中文为辅助标签。</p>
        <p>字段层面的对齐不代表原厂引擎的数值等价。仅当前已实现的基础模型可以运行，其他表仍可编辑和交换。</p>
        <h3>运行口径</h3>
        <p>0.6 飞行模式：在SimLabFlightRule填MTID、PREP_H；在MissionType填DURN、TFOUT、TFRET。比例各为0～1，和≤1；任务区比例自动为剩余部分。例如DURN=3、TFOUT=TFRET=1/6，对应出航0.5h、执行2h、返航0.5h。表格中比例须填数值小数。零比例兼容旧案例。飞行不得跨日，保障时间另算。出航中止按已出航比例折算返航，任务区中止按完整返航，返航中止按剩余时间；健康部件返航时仍可故障，飞机落地后才能维修或准备。多故障LRU落地后依次处理。</p>
        <p>全部任务须为飞行模式，不能混用值守规则；同池保障时长一致。每日首波前全池保障，按累计出动少者优先选机。准点凑齐整队才能起飞，不足取消；故障整队中止、空中不补位。保障无资源约束、不累计故障。“飞行阶段”区分实际三阶段时间和中止返航时间；后者不计有效任务供给。本地完成判据不是原厂MSUCPT成功点。</p>
        <p>0.7 增加 MSUCPT 成功点（0～1，默认1）。起飞后达到该点即成功，同刻故障优先算成功；之后中止不撤销成功。结果分别显示任务成功率FMSUC与完整完成率。模型数据下方可按分钟输入并预览；逐轮飞行CSV导出所有任务判定。旧结果不推算成功值，需要重跑。</p>
        <p>0.8 可在SimLabFlightRule配置PREP_TASK，引用Tasks/TaskResource及ResourceAllocation的保障资源。半小时为一次完整再次出动准备；资源全部到齐才开始，班内开始、跨班继续，同刻准备完成先于起飞。DAILY_READY=Y表示每天首波健康地面飞机假定已提前保障，未完准备单独记作“首波假设接续完成”，不计正常完工且释放资源。故障机仍需修复。准备资源评估和再次出动准备页可查看及导出。</p>
        <p>0.9 在“维修与保障作业 → 日历计划维修”填写部署位置、首次到期、重复间隔、固定时长及资源作业。仅支持固定飞行；到期停派，在飞先落地，已有故障维修及准备先完成。重复到期逐次排队，计划维修后重新准备；首波假设不能跳过。结果页可查看首轮工单和导出全轮CSV。</p>
        <p>FRT=1000 且 OPID=OPHOURS，表示平均每 1000 个运行小时发生一次故障。UTIL=0.5 表示每个可用日历小时累计 0.5 个运行小时。</p>
        <p>串联关键部件故障使设备停机，停机期间不累计运行故障。层级模式保留健康叶子的剩余故障预算，修复叶子下次运行再抽样。暂不支持冗余、老化、预防性维修和供应中断。</p>
        <h3>0.2 任务与班次</h3>
        <p>Operations → OperationProfile → MissionType / MissionSystem 定义固定需求窗口，STIM 为从仿真开始算起的小时，DURN 为持续小时。每行启动一个窗口；不支持递归、随机或延后启动。NOS=MNOS；只绑定一种系统。</p>
        <p>任务模式要求 UTIL=1。仅实际值守设备累计运行故障，待命和补位准备不累计。无扩展规则时先到先服务、即时补位；v0.4 可在“值守计划”配置优先级、最低数量和补位准备小时，不抢占已有分配，窗口按原定时间结束。</p>
        <p>最低保障达标率按任务窗口小时加权；最长连续不达标时间不超过容忍时间即窗口合格。不达标期间仍继续补位，不取消任务。SimLabDutyRule 为独立扩展，原厂 MNOS/MNOSA 仍按原受限契约填写。首轮不达标区间最多5000条，总指标覆盖所有事件；各窗口最长连续值显示跨重复试验的均值。</p>
        <p>任务满足率=供给设备小时/需求设备小时；全程无缺口比例独立计算。两者不宣称与原厂任务成功判定一致。统计精确积分，曲线是采样显示，可能漏掉短时缺口。</p>
        <p>ShiftProfile 直接引用 Shift，STIM/ETIM 为绝对小时；ResourceStationData.SHPID 绑定资源。班内才能开始拆装或修复，已开始允许跨班完成；未绑定资源为全天可用。资源占用率仍以整个日历时间为分母。</p>
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
            if index == 6:
                self.duty_planner.set_project(self.project)
            if index == 5:
                self.structure.set_project(self.project)
            if index == 2:
                self.sync_controls()
            if index == 0:
                self.refresh_overview()
            if index == 7:
                self.library.refresh()

    def library_open(self,path):
        try:
            self.open_path(path)
            self.nav.setCurrentRow(0)
        except Exception as error:self.warn('打开项目失败',str(error))

    def library_copy(self,path):
        if self.process is not None:
            self.warn('计算仍在运行','请结束当前实验后复制方案。');return
        if self.dirty and not self.save():return
        try:
            project=copy_model(path)
            self.adopt_project(project,self.data_dir/'projects'/f'{project["id"][:12]}.sqlite')
            self.nav.setCurrentRow(0)
        except Exception as error:self.warn('复制模型失败',str(error))

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
        try:self.catalog.remember(path)
        except (OSError,ValueError) as error:self.statusBar().showMessage('项目已打开，但项目库索引未更新：'+str(error),15000)
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
        self.structure.set_project(project)
        self.duty_planner.set_project(project)
        self.sync_controls()
        self.refresh_overview()
        self.refresh_results()
        self.statusBar().showMessage('已打开 '+str(path), 7000)

    def open_path(self, path):
        if self.dirty and not self.save():
            return
        project = load_project(path)
        self.adopt_project(project, path, save=False)

    def new_mission_demo(self):
        if self.process is not None:
            self.warn('计算仍在运行', '请先结束当前实验再新建任务示例。')
            return
        if self.dirty and not self.save():
            return
        project = mission_project()
        try:
            self.adopt_project(project, self.data_dir/'projects'/f'mission-{project["id"][:12]}.sqlite')
            self.nav.setCurrentRow(1)
            self.editor.select_table('MissionType')
        except Exception as error:
            self.warn('创建任务示例失败', str(error))

    def migrate_m3(self):
        if self.process is not None:
            self.warn('计算仍在运行', '请先结束当前实验。')
            return
        if self.dirty and not self.save():
            return
        from ..m3_migrate import prepare_migration
        try:
            candidate, preview = prepare_migration(self.project)
            dialog = QDialog(self)
            dialog.setWindowTitle('M3 迁移预览 · 新建独立副本')
            dialog.resize(820, 620)
            layout = QVBoxLayout(dialog)
            content = QTextBrowser()
            content.setPlainText(preview)
            layout.addWidget(content)
            buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
            buttons.button(QDialogButtonBox.Ok).setText('按预览创建 M3 副本')
            buttons.button(QDialogButtonBox.Cancel).setText('取消')
            buttons.accepted.connect(dialog.accept)
            buttons.rejected.connect(dialog.reject)
            layout.addWidget(buttons)
            if dialog.exec() != QDialog.Accepted:
                return
            self.adopt_project(candidate, self.data_dir/'projects'/f'm3-{candidate["id"][:12]}.sqlite')
            self.nav.setCurrentRow(1)
            self.editor.select_table('SimLabSupplyPolicy')
        except Exception as error:
            self.warn('迁移未完成', str(error))

    def new_m3_demo(self):
        if self.process is not None:
            self.warn('计算仍在运行', '请先结束当前实验。')
            return
        if self.dirty and not self.save():
            return
        from ..m3_sample import m3_project
        project = m3_project()
        try:
            self.adopt_project(project, self.data_dir/'projects'/f'm3-{project["id"][:12]}.sqlite')
            self.nav.setCurrentRow(1)
            self.editor.select_table('SimLabSupplyPolicy')
        except Exception as error:
            self.warn('创建三级供应示例失败', str(error))

    def new_lifecycle_demo(self):
        if self.process is not None:
            self.warn('计算仍在运行', '请先结束当前实验。')
            return
        if self.dirty and not self.save():
            return
        from ..m3_sample import lifecycle_project
        project = lifecycle_project()
        try:
            self.adopt_project(project, self.data_dir/'projects'/f'lifecycle-{project["id"][:12]}.sqlite')
            self.nav.setCurrentRow(1)
            self.editor.select_table('SimLabPurchasePolicy')
        except Exception as error:
            self.warn('创建采购与报废示例失败', str(error))

    def new_layered_demo(self):
        if self.process is not None:
            self.warn('计算仍在运行', '请先结束当前实验。')
            return
        if self.dirty and not self.save():
            return
        project = layered_project()
        try:
            self.adopt_project(project, self.data_dir/'projects'/f'layered-{project["id"][:12]}.sqlite')
            self.nav.setCurrentRow(5)
        except Exception as error:
            self.warn('创建多层维修示例失败', str(error))

    def new_duty_demo(self):
        if self.process is not None or (self.dirty and not self.save()):
            return
        project = duty_project()
        try:
            self.adopt_project(project, self.data_dir/'projects'/f'duty-{project["id"][:12]}.sqlite')
            self.nav.setCurrentRow(6)
        except Exception as error:
            self.warn('创建值守示例失败', str(error))

    def duty_changed(self):
        self.editor.set_project(self.project)
        self.model_changed()

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
        self.validation_box.show()
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
        self.duty_planner.setEnabled(not busy)
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
            mission = result.get('mission')
            comparisons.append([run['name'], f'{result["availability"]:.2%}', f'{mission["fulfillment"]:.2%}' if mission else '—', f'{result["p05"]:.2%} / {result["p95"]:.2%}', result['point'], result['replications'], result['model_hash'][:12]])
        fill_table(self.compare_table, comparisons)
        self.show_result()
    def selected_run(self):
        return next((r for r in self.complete_runs if r['id'] == self.run_selector.currentData()), None)
    def show_result(self, *args):
        self.mission_summary.setToolTip('')
        self.age_notice.setToolTip('')
        self.age_instances.setRowCount(0)
        self.age_events.setRowCount(0)
        self.age_notice.setText('暂无部件年龄结果')
        self.inspection_clocks.setRowCount(0)
        self.inspection_jobs.setRowCount(0)
        run = self.selected_run() if hasattr(self, 'complete_runs') else None
        self.m3_supply_page.set_run(run)
        self.m3_service_page.set_run(run)
        if run and run['result'].get('aging'):
            aging = run['result']['aging']
            self.age_notice.setToolTip('年龄按实际运行小时累计；维修方式以模型配置为准。')
            self.age_notice.setText('首轮部件年龄' +
                (' 明细已截断，请缩小实验规模。' if aging['instances_truncated'] or aging['events_truncated'] else ''))
            fill_table(self.age_instances, [[r['part'],r['iid'],f"{r['age']:.6f}",f"{r['lifetime_hours']:.6f}",
                '故障' if r['broken'] else '完好',
                {'installed':'装机','stock':'库存','attached':'附属','held':'待安装','transport':'运输',
                 'repair_queue':'待维修','repair':'维修','wait_resource':'等资源','diagnosis':'检测',
                 'remove':'拆卸','wait_sru':'等子件','install':'安装','test':'测试'}.get(r['location'],r['location'])]
                for r in sorted(aging['instances'],key=lambda r: -r['age'])])
            fill_table(self.age_events, [[f"{r['time']:.6f}",r['part'],r['iid'],
                '故障' if r['event']=='failure' else '修复完成',f"{r['age_before']:.6f}",
                f"{r['age_after']:.6f}",f"{r['lifetime_hours']:.6f}",
                '修复如新' if r['repair']=='PERFECT' else '最小修复'] for r in aging['events']])
        self.mission_export_button.setEnabled(bool(run and run['result'].get('mission')))
        self.maintenance_export_button.setEnabled(bool(run and run['result'].get('maintenance')))
        for table in (self.maintenance_table, self.phase_table, self.component_table, self.duty_table, self.duty_intervals, self.flight_table, self.flight_phase_table, self.success_table, self.success_details,self.ground_table,self.ground_jobs,self.cancel_table,self.planned_table,self.planned_jobs):
            table.setRowCount(0)
        if not run:
            for metric in self.result_cards:
                metric.number.setText('—')
            self.chart.set_samples([])
            self.result_meta.setText('暂无实验结果')
            self.mission_chart.set_samples([])
            self.mission_summary.setText('本实验没有任务日历。')
            for table in (self.downtime_table, self.resource_table, self.events_table, self.mission_table, self.gap_table):
                table.setRowCount(0)
            return
        result = run['result']
        maintenance = result.get('maintenance')
        if maintenance:
            fill_table(self.maintenance_table, [[kind, f'{v["started"]:.1f}', f'{v["completed"]:.1f}', f'{v["in_progress"]:.1f}', f'{v["mean_tat"]:.2f}' if v['mean_tat'] is not None else '尚无完成'] for kind, v in maintenance['by_kind'].items()])
            fill_table(self.phase_table, [[kind, PHASES[key], f'{hours:.2f}'] for kind, v in maintenance['by_kind'].items() for key, hours in v['phase_hours'].items()])
            locs = {'installed': '装在设备', 'attached': '装在父件', 'stock': '在库', 'held': '已领待装', **PHASES}
            fill_table(self.component_table, [[r['id'], r['iid'], r['parent'] or '—', locs.get(r['location'], r['location']), locs.get(r['physical_location'], r['physical_location']), r['site'], '故障/待修复' if r['broken'] else '健康'] for r in result['components']['instances']])
        confidence = result['ci95']
        numbers = [f'{result["availability"]:.2%}', f'{confidence[0]:.1%} – {confidence[1]:.1%}' if confidence else '单次试验',
                   f'{result["failures"]:.1f}', str(result['fleet_size'])]
        for metric, number in zip(self.result_cards, numbers):
            metric.number.setText(number)
        changed = '当前模型已修改，以下为历史快照结果' if model_hash(self.project['tables']) != result['model_hash'] else '与当前模型一致'
        extra = ' · 首轮事件已截断至 5000 条' if result.get('events_truncated') else ''
        if maintenance:
            extra += ' · 部件/维修明细为首轮，最多1000条；周转仅计已完成工单'
        self.result_meta.setText(f'{result["horizon"]/24:g} 天 / {result["replications"]} 次试验 / 种子 {result["seed"]} / {changed}{extra}')
        self.chart.set_samples(result['samples'])
        mission = result.get('mission')
        self.mission_chart.set_samples(result['samples'] if mission else [])
        if mission:
            flight = mission.get('flight')
            ground=mission.get('ground')
            planned = mission.get('planned')
            if planned:
                labels = dict(due_jobs='到期作业 / 次',completed_jobs='已完成 / 次',deferred_jobs='期末等待前序 / 次',
                    waiting_jobs='期末等待资源 / 次',working_jobs='期末维修中 / 次',
                    deferred_aircraft_hours='落地、修复及前序延后 / 架·小时',wait_aircraft_hours='资源及班次等待 / 架·小时',
                    work_aircraft_hours='实际维修作业 / 架·小时')
                fill_table(self.planned_table, [[labels[k], f'{v:.3f}'] for k,v in planned.items() if k not in ('jobs','clocks')])
                fill_table(self.planned_jobs, [[j['asset'],j['rule']]+
                    [f'{j[k]:.3f}' if j[k] is not None else '—' for k in
                     ('due_at','requested_at','started_at','ended_at','deferred_hours','wait_hours','work_hours')]+
                    [PLANNED_STATUSES[j['status']]] for j in planned['jobs']])
                fill_table(self.inspection_clocks, [[c['asset'],c['rule']]+
                    [f'{c[k]:.3f}' for k in ('initial_hours','flown_hours','hours_since_check','interval_hours')]+
                    [str(c['completed_checks']),'是' if c['due'] else '否',f'{c["overrun_hours"]:.3f}'] for c in planned.get('clocks',[])])
                fill_table(self.inspection_jobs, [[j['asset'],j['rule']]+
                    [f'{j[k]:.3f}' if j[k] is not None else '—' for k in ('due_at','started_at','ended_at','cycle_hours','overrun_hours')]+
                    [PLANNED_STATUSES[j['status']]] for j in planned['jobs'] if j.get('trigger')=='flight_hours'])
            if ground:
                labels={'requested_jobs':'请求准备作业 / 次','completed_jobs':'正常完成 / 次','assumed_jobs':'每日首波假设接续未完作业 / 次',
                    'waiting_jobs':'期末排队 / 次','working_jobs':'期末作业中 / 次','wait_aircraft_hours':'准备总等待 / 架·小时',
                    'work_aircraft_hours':'实际准备作业 / 架·小时','wait_resource_aircraft_hours':'班内等待资源或队列 / 架·小时',
                    'wait_shift_aircraft_hours':'等待共同班次 / 架·小时','daily_assumed_ready_aircraft':'每日首波假定已保障 / 架次'}
                fill_table(self.ground_table,[[labels[k],f'{v:.3f}'] for k,v in ground.items() if k!='jobs'])
                fill_table(self.ground_jobs,[[j['asset'],j['task'],f'{j["requested_at"]:.3f}',
                    f'{j["started_at"]:.3f}' if j['started_at'] is not None else '—',
                    f'{j["ended_at"]:.3f}' if j['ended_at'] is not None else '—',f'{j["wait_hours"]:.3f}',f'{j["work_hours"]:.3f}',
                    GROUND_STATUSES[j['status']]] for j in ground['jobs']])
            if flight:
                fill_table(self.cancel_table,[[t['id'],CANCEL_REASONS.get(t.get('cancel_reason'),'历史结果未分类'),
                    '；'.join(f'{dict(maintenance="维修中",planned_maintenance="计划维修到期或执行中",airborne="飞行占用",ready="已就绪",preparing="准备作业中",waiting_preparation="准备排队",idle="未准备").get(k,k)} {v}架' for k,v in (t.get('launch_readiness') or {}).items())]
                    for t in result['replication_results'][0]['mission']['tasks'] if t['flight_status']=='cancelled'])
            if flight:
                labels = {'requested':'计划编队任务 / 次', 'started':'实际起飞编队 / 次',
                          'completed':'完整完成编队 / 次', 'aborted':'飞行中止编队 / 次',
                          'cancelled':'起飞前取消 / 次', 'aircraft_sorties':'实际起飞 / 架次',
                          'completed_aircraft_sorties':'完整完成 / 架次',
                          'preparation_aircraft_hours':'出动保障 / 架·小时',
                          'ready_aircraft_hours':'已保障待命 / 架·小时', 'all_completed':'整轮全部任务完成比例',
                          'out_aircraft_hours':'实际出航 / 架·小时', 'on_station_aircraft_hours':'实际任务区执行 / 架·小时',
                          'return_aircraft_hours':'实际返航 / 架·小时（含中止返航）', 'abort_return_aircraft_hours':'其中中止返航 / 架·小时'}
                labels.update(requested='计划编队任务 NMREQ / 次',started='实际起飞编队 NMSTA / 次',
                    successful='成功编队 NMSUC / 次',requested_aircraft_sorties='请求 NSYRQ / 架次',
                    aircraft_sorties='起飞 NSYST / 架次',successful_aircraft_sorties='成功 NSYSU / 架次',
                    started_rate='起飞率 FMSTA',success_rate='成功率 FMSUC',completion_rate='完整完成率',all_successful='整轮全部任务成功比例')
                fill_table(self.flight_table, [[labels.get(k,k), f'{v:.2%}' if k.endswith('_rate') or k in ('all_completed','all_successful') else f'{v:.3f}'] for k,v in flight.items()])
                if 'success_rate' in flight:
                    fill_table(self.success_table,[[t['id'],clock(t['success_point']),f'{t["success_fraction"]:.2%}',
                        f'{t["started_rate"]:.2%}',f'{t["success_rate"]:.2%}',f'{t["flight_rates"]["completed"]:.2%}',
                        f'{t["successful_aircraft_sorties"]:.3f}'] for t in mission['tasks']])
                    fill_table(self.success_details,[[t['id'],STATUSES.get(t['flight_status'],t['flight_status']),
                        '成功' if t['successful'] else '未成功',clock(t['success_at']) if t['success_at'] is not None else '—',
                        FLIGHT_PHASES.get(t['success_phase'],'—'),REASONS.get(t['success_reason'],t['success_reason']),
                        ', '.join(t['members']),', '.join(t['successful_members'])]
                        for t in result['replication_results'][0]['mission']['tasks']])
                phase_rows=[]
                for t in mission['tasks']:
                    if 'out_fraction' not in t:
                        continue
                    duration=t['end']-t['start']
                    phase_rows.append([t['id'], f'{duration*t["out_fraction"]:.3f}',
                        f'{duration*(1-t["out_fraction"]-t["return_fraction"]):.3f}', f'{duration*t["return_fraction"]:.3f}',
                        *[f'{t[k]:.3f}' for k in ('out_aircraft_hours','on_station_aircraft_hours','return_aircraft_hours','abort_return_aircraft_hours')]])
                fill_table(self.flight_phase_table,phase_rows)
            ci = mission['ci95']
            interval = f'{ci[0]:.1%}–{ci[1]:.1%}' if ci else '单次试验'
            self.mission_summary.setText(f'设备小时满足率 {mission["fulfillment"]:.2%} · 均值95%区间 {interval} · 全程无缺口窗口 {mission["full_window_rate"]:.1%}\n平均缺口 {mission["gap_hours"]:.2f} 设备小时；曲线按采样间隔显示，指标按事件积分。')
            if flight:
                phase_note='三阶段时间见“飞行阶段”；中止后返航不计有效任务供给。' if 'return_aircraft_hours' in flight else '历史结果：返航耗时按0。'
                self.mission_summary.setText(self.mission_summary.text()+f'\n飞行模式：整队起飞、故障中止、空中不补位；完整完成 {flight["completed"]:.3f}/{flight["requested"]:g} 次，整轮全部完成 {flight["all_completed"]:.2%}。{phase_note}')
                self.mission_summary.setText(self.mission_summary.text()+('\n成功率 FMSUC '+f'{flight["success_rate"]:.2%}；成功与中止可同时发生。逐轮飞行CSV包含所有轮次判定。' if 'success_rate' in flight else '\n历史结果未计算成功点，请使用v0.7重新运行；原结果保留。'))
            if 'minimum_rate' in mission and not flight:
                detail_note = '（已截断）' if mission.get('intervals_truncated') else ''
                self.mission_summary.setText(self.mission_summary.text() + f'\n最低保障达标率 {mission["minimum_rate"]:.2%} · 值守窗口合格率 {mission["qualified_rate"]:.2%}；不达标时段为首轮、最多5000条{detail_note}。合计曲线不能代替各任务判定。')
                fill_table(self.duty_table, [[t['id'], f'{t["quantity"]} / {t["minimum"]}', f'{t["minimum_rate"]:.2%}',
                    f'{t["qualified_rate"]:.2%}', f'{t["below_hours"]:.3f}', f'{t["longest_below_hours"]:.3f}'] for t in mission['tasks']])
                fill_table(self.duty_intervals, [[t['task'], f'{t["start"]:.3f}', f'{t["end"]:.3f}',
                    f'{t["supplied"]} / {t["minimum"]}', '；'.join(f'{GAP_LABELS[k]}: {v}' for k, v in t['reasons'].items())] for t in mission.get('intervals', [])])
            fill_table(self.mission_table, [[t['id'], f'{t["start"]:g}', f'{t["end"]:g}', t['quantity'], f'{t["supplied_hours"]:.2f}', f'{t["gap_hours"]:.2f}', f'{t["full_window_rate"]:.1%}'] for t in mission['tasks']])
            fill_table(self.gap_table, [[GAP_LABELS[key], f'{v:.2f}'] for key, v in mission['gap_reasons'].items()])
            self.mission_summary.setToolTip(self.mission_summary.text())
            brief = f'小时满足率 {mission["fulfillment"]:.2%} · 缺口 {mission["gap_hours"]:.2f} 设备小时 · 95%区间 {interval}'
            if flight and 'success_rate' in flight:
                brief += f' · 任务成功率 {flight["success_rate"]:.2%}'
            if not flight and 'minimum_rate' in mission:
                brief += f' · 最低保障达标率 {mission["minimum_rate"]:.2%} · 窗口合格率 {mission["qualified_rate"]:.2%}'
            brief += ' · 时段明细：首轮'
            if mission.get('intervals_truncated'):
                brief += '（已截断）'
            self.mission_summary.setText(brief)
        else:
            self.mission_summary.setText('无任务日历结果')
            self.mission_table.setRowCount(0)
            self.gap_table.setRowCount(0)
        names = {'waiting_spare': '等待备件（含供应运输）', 'waiting_resource': '等待拆装资源或班次', 'replacement': '拆卸与安装作业', 'returning_failed':'故障返航（尚未落地）',
                 'planned_wait':'计划维修等待资源或班次','planned_maintenance':'计划维修作业'}
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

    def export_missions_path(self, path):
        run = self.selected_run()
        if not run or not run['result'].get('mission'):
            raise ValueError('本实验没有任务结果。')
        export_tasks(run,path)

    def export_flight_details(self):
        run=self.selected_run()
        if not run or not (run['result'].get('mission') or {}).get('flight'):
            self.warn('没有飞行结果','请先选择固定飞行实验。')
            return
        path,_=QFileDialog.getSaveFileName(self,'导出所有轮次飞行判定','逐轮飞行判定.csv','CSV (*.csv)')
        if path:
            try:
                export_tasks(run,path,detailed=True)
                self.statusBar().showMessage('逐轮飞行明细已导出：'+path,10000)
            except Exception as error:
                self.warn('导出失败',str(error))

    def export_ground_details(self):
        run=self.selected_run()
        if not run or not (run['result'].get('mission') or {}).get('ground'):
            self.warn('没有准备作业结果','请选择配置准备资源或每日首波就绪假设的实验。');return
        path,_=QFileDialog.getSaveFileName(self,'导出全部准备作业','再次出动准备.csv','CSV (*.csv)')
        if path:
            try:export_ground(run,path)
            except Exception as error:self.warn('导出失败',str(error))

    def export_planned_details(self):
        run = self.selected_run()
        if not run or not (run['result'].get('mission') or {}).get('planned'):
            self.warn('没有计划维修结果','请选择已配置日历计划维修的实验。');return
        path, _ = QFileDialog.getSaveFileName(self,'导出全部计划维修','日历计划维修.csv','CSV (*.csv)')
        if path:
            try:export_planned(run,path)
            except Exception as error:self.warn('导出失败',str(error))

    def export_missions(self):
        path, _ = QFileDialog.getSaveFileName(self, '导出任务窗口结果', '任务结果.csv', 'CSV (*.csv)')
        if path:
            try:
                self.export_missions_path(path)
                self.statusBar().showMessage('任务结果已导出：'+path, 10000)
            except Exception as error:
                self.warn('导出失败', str(error))

    def export_inspection_details(self):
        run=self.selected_run()
        if not run or 'clocks' not in ((run['result'].get('mission') or {}).get('planned') or {}):
            self.warn('没有检查计时结果','请选择已配置飞行小时检查的实验。');return
        path,_=QFileDialog.getSaveFileName(self,'导出检查计时','飞行小时检查.csv','CSV (*.csv)')
        if path:
            try:export_inspection_clocks(run,path)
            except Exception as error:self.warn('导出失败',str(error))

    def export_age_details(self, events=False):
        run = self.selected_run()
        if not run or 'aging' not in run['result']:
            self.warn('没有年龄结果', '请选择已配置部件老化的实验。')
            return
        path, _ = QFileDialog.getSaveFileName(self, '导出部件年龄', '故障修复年龄.csv' if events else '部件年龄.csv', 'CSV (*.csv)')
        if path:
            try:
                export_aging(run, path, events)
            except Exception as error:
                self.warn('导出失败', str(error))

    def export_maintenance_path(self, path):
        run = self.selected_run()
        if not run or not run['result'].get('maintenance'):
            raise ValueError('本实验没有多层维修数据。')
        with open(path, 'w', encoding='utf-8-sig', newline='') as file:
            writer = csv.writer(file)
            writer.writerow(['run_id', 'model_hash', 'replication', 'seed', 'job_id', 'part', 'kind', 'parent', 'station', 'start', 'end', 'phase', 'phase_hours'])
            for job in run['result']['maintenance']['jobs']:
                for phase, hours in job['phase_hours'].items():
                    writer.writerow([run['id'], run['model_hash'], 0, run['result']['seed'], job['id'], job['part'], job['kind'], job['parent'], job['station'], job['start'], job['end'], phase, hours])

    def export_maintenance(self):
        path, _ = QFileDialog.getSaveFileName(self, '导出首轮维修工序（最多1000工单）', '维修工序.csv', 'CSV (*.csv)')
        if path:
            try:
                self.export_maintenance_path(path)
                self.statusBar().showMessage('首轮维修工序已导出：'+path, 10000)
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
