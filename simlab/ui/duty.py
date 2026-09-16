"""Chinese duty rule editor and preview-before-append daily planner."""
from PySide6.QtCore import Signal
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QFormLayout, QComboBox,
    QSpinBox, QDoubleSpinBox, QLineEdit, QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView)
from ..schema import value
from ..compiler import compile_model
from ..project import model_hash
from ..duty import set_rule, daily_plan
from .widgets import label, button, card


def spin(minimum, maximum, initial, decimals=None):
    widget = QSpinBox() if decimals is None else QDoubleSpinBox()
    if decimals is not None:
        widget.setDecimals(decimals)
    widget.setRange(minimum, maximum)
    widget.setValue(initial)
    return widget


class DutyPlanner(QWidget):
    changed = Signal()
    example_requested = Signal()

    def __init__(self):
        super().__init__()
        self.project = None
        self.preview = None
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        title = QHBoxLayout()
        title.addWidget(label('固定时段值守', 'PageTitle'))
        title.addStretch()
        self.example_button = button('新建值守示例', self.example_requested.emit)
        title.addWidget(self.example_button)
        root.addLayout(title)
        self.setToolTip('到点开始、到点结束；数量不足持续补位。准备期间不供给，已有分配不被抢占。')
        panels = QHBoxLayout()
        rules, rules_layout = card()
        rules_layout.addWidget(label('值守规则 · 保存会作用于该类型的所有窗口'))
        form = QFormLayout()
        self.task = QComboBox()
        self.target = spin(1, 2000, 15)
        self.minimum = spin(1, 2000, 12)
        self.priority = spin(1, 1000000, 1)
        self.relief = spin(0, 876000, .5, 4)
        self.tolerance = spin(0, 876000, .25, 4)
        for caption, widget in [('已有任务类型', self.task), ('目标数量 / 台', self.target), ('最低保障 / 台', self.minimum),
                                ('优先级（小数值优先）', self.priority), ('补位准备 / 小时', self.relief), ('连续不达标容忍 / 小时', self.tolerance)]:
            form.addRow(caption, widget)
        rules_layout.addLayout(form)
        self.save_button = button('保存所选任务规则', self.save_rule)
        rules_layout.addWidget(self.save_button)
        panels.addWidget(rules)
        generation, generation_layout = card()
        generation_layout.addWidget(label('按日新增计划 · 使用左侧规则'))
        form = QFormLayout()
        self.name = QLineEdit('新增值守')
        self.system = QComboBox()
        self.location = QComboBox()
        self.first_day = spin(1, 36500, 1)
        self.days = spin(1, 2000, 7)
        self.start_hour = spin(0, 24, 8, 4)
        self.end_hour = spin(0, 24, 16, 4)
        for caption, widget in [('计划名称（唯一）', self.name), ('系统类型', self.system), ('值守单位 / 站点', self.location),
                                ('首日（仿真第几天）', self.first_day), ('连续天数', self.days),
                                ('每日开始 / 时', self.start_hour), ('每日结束 / 时', self.end_hour)]:
            form.addRow(caption, widget)
        generation_layout.addLayout(form)
        actions = QHBoxLayout()
        self.preview_button = button('预览新增计划', self.preview_plan)
        self.apply_button = button('添加预览计划', self.apply_plan, True)
        self.apply_button.setEnabled(False)
        actions.addWidget(self.preview_button)
        actions.addWidget(self.apply_button)
        generation_layout.addLayout(actions)
        panels.addWidget(generation)
        root.addLayout(panels)
        self.message = label('', 'Muted', True)
        self.preview_button.setToolTip('检查仿真边界及潜在设备竞争；添加后可在模型数据中编辑具体窗口。')
        root.addWidget(self.message)
        self.grid = QTableWidget(0, 7)
        self.grid.setHorizontalHeaderLabels(['任务类型', '单位 / 站点', '第几天', '开始 / 小时', '结束 / 小时', '目标 / 最低', '优先级'])
        self.grid.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.grid.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.grid.verticalHeader().setVisible(False)
        self.grid.setAlternatingRowColors(True)
        root.addWidget(self.grid, 1)
        self.task.currentIndexChanged.connect(self.load_rule)
        for widget in (self.target, self.minimum, self.priority, self.relief, self.tolerance,
                       self.first_day, self.days, self.start_hour, self.end_hour):
            widget.valueChanged.connect(self.invalidate)
        self.name.textChanged.connect(self.invalidate)
        self.system.currentIndexChanged.connect(self.invalidate)
        self.location.currentIndexChanged.connect(self.invalidate)

    def invalidate(self, *args):
        self.preview = None
        self.apply_button.setEnabled(False)

    def set_project(self, project):
        self.project = project
        self.invalidate()
        tables = project['tables']
        previous = self.task.currentData()
        self.task.blockSignals(True)
        self.task.clear()
        for row in tables.get('MissionType', []):
            self.task.addItem(row.get('DESCR') or row['MTID'], row['MTID'])
        index = self.task.findData(previous)
        self.task.setCurrentIndex(max(0, index))
        self.task.blockSignals(False)
        self.system.clear()
        self.location.clear()
        for row in tables.get('System', []):
            self.system.addItem(row.get('DESCR') or row['SID'], row['SID'])
        for table, key in [('Unit', 'UNID'), ('Station', 'STID')]:
            for row in tables.get(table, []):
                self.location.addItem(f'{row[key]} · {row.get("DESCR", "")}', row[key])
        self.save_button.setEnabled(self.task.count() > 0)
        self.load_rule()
        try:
            self.show_windows(compile_model(tables)['missions'])
            self.message.setText('当前全部值守窗口。新增计划先预览再添加；结束时刻固定，补齐不消除历史缺口。')
            if tables.get('SimLabFlightRule'):
                self.message.setText('当前为飞行计划：仅查看起飞时段。请在模型数据编辑 SimLabFlightRule 和 OperationProfile；值守补位规则不适用于飞行。')
                self.save_button.setEnabled(False)
        except ValueError as error:
            self.grid.setRowCount(0)
            self.message.setText('模型尚未通过校验：' + str(error)[:1000])

    def load_rule(self, *args):
        self.invalidate()
        if not self.project or not self.task.currentData():
            return
        tables = self.project['tables']
        spec = next(r for r in tables['MissionType'] if r['MTID'] == self.task.currentData())
        rule = next((r for r in tables.get('SimLabDutyRule', []) if r['MTID'] == spec['MTID']), {})
        try:
            target = int(value('MissionType', spec, 'NOS'))
            self.target.setValue(target)
            self.minimum.setValue(int(rule.get('MIN_QTY') or target))
            self.priority.setValue(int(value('SimLabDutyRule', rule, 'PRIORITY')))
            self.relief.setValue(float(value('SimLabDutyRule', rule, 'RELIEF_H')))
            self.tolerance.setValue(float(value('SimLabDutyRule', rule, 'TOLERANCE_H')))
        except (ValueError, OverflowError):
            self.message.setText('所选规则含非法数值，请在模型数据页修正。')

    def values(self):
        return tuple(w.value() for w in (self.target, self.minimum, self.priority, self.relief, self.tolerance))

    def save_rule(self):
        if not self.project or not self.task.currentData():
            return
        try:
            candidate = set_rule(self.project['tables'], self.task.currentData(), *self.values())
            compile_model(candidate)
            self.project['tables'] = candidate
            self.changed.emit()
            self.set_project(self.project)
            self.message.setText('值守规则已应用并触发项目自动保存；历史实验保持原快照。')
        except ValueError as error:
            self.message.setText('未保存：' + str(error)[:1000])

    def preview_plan(self):
        self.invalidate()
        try:
            candidate, windows, conflicts = daily_plan(self.project['tables'], self.name.text(),
                self.system.currentData(), self.location.currentData(), self.first_day.value(), self.days.value(),
                self.start_hour.value(), self.end_hour.value(), *self.values())
            self.preview = (model_hash(self.project['tables']), candidate)
            self.show_windows(windows)
            self.apply_button.setEnabled(True)
            self.message.setText(f'预览：新增 {len(windows)} 个窗口；与已有计划有 {conflicts} 对重叠且共享设备池，可能竞争。尚未写入项目。')
        except (ValueError, KeyError, TypeError) as error:
            self.message.setText('无法新增：' + str(error)[:1000])

    def apply_plan(self):
        if not self.preview:
            return
        fingerprint, candidate = self.preview
        if fingerprint != model_hash(self.project['tables']):
            self.invalidate()
            self.message.setText('模型已变化，请重新预览。')
            return
        self.project['tables'] = candidate
        self.changed.emit()
        self.set_project(self.project)
        self.message.setText('新增计划已应用并触发自动保存；原有任务窗口保留。')

    def show_windows(self, windows):
        self.grid.setRowCount(len(windows))
        for i, t in enumerate(windows):
            for j, cell in enumerate((t['type'], t['location'], int(t['start']//24)+1,
                                      f'{t["start"]:g}', f'{t["end"]:g}', f'{t["quantity"]} / {t["minimum"]}', t['priority'])):
                self.grid.setItem(i, j, QTableWidgetItem(str(cell)))
