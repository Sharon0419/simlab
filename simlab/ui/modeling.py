import csv
import html
import io
from pathlib import Path
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QKeySequence
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QTreeWidget, QTreeWidgetItem,
    QLineEdit, QCheckBox, QTableWidget, QTableWidgetItem, QSplitter, QTextBrowser,
    QFileDialog, QMessageBox, QApplication, QAbstractItemView, QStyledItemDelegate, QComboBox)
from ..schema import TABLES, CORE_TABLES, table_label, field_label, category, defaults, effective
from ..compiler import SUPPORTED, DOCUMENTARY
from ..validation import choices
from .widgets import label, button

class FieldDelegate(QStyledItemDelegate):
    def __init__(self, editor):
        super().__init__(editor)
        self.editor = editor
    def createEditor(self, parent, option, index):
        field = TABLES[self.editor.current_table][index.column()]
        options = choices(field)
        if field['references']:
            for ref in field['references'].split(','):
                pair = ref.strip().split()
                if len(pair) == 2:
                    options += [str(r.get(pair[1], '')) for r in self.editor.project['tables'].get(pair[0], [])]
        if options:
            widget = QComboBox(parent)
            widget.setEditable(True)
            widget.addItems([''] + sorted(set(x for x in options if x)))
            return widget
        return super().createEditor(parent, option, index)
    def setEditorData(self, widget, index):
        if isinstance(widget, QComboBox):
            widget.setCurrentText(index.data() or '')
        else:
            super().setEditorData(widget, index)
    def setModelData(self, widget, model, index):
        if isinstance(widget, QComboBox):
            model.setData(index, widget.currentText(), Qt.EditRole)
        else:
            super().setModelData(widget, model, index)

class Grid(QTableWidget):
    paste_requested = Signal(str)
    def keyPressEvent(self, event):
        if event.matches(QKeySequence.Paste):
            self.paste_requested.emit(QApplication.clipboard().text())
            return
        if event.matches(QKeySequence.Copy):
            ranges = self.selectedRanges()
            if ranges:
                r = ranges[0]
                output = io.StringIO()
                writer = csv.writer(output, delimiter='\t', lineterminator='\n')
                for row in range(r.topRow(), r.bottomRow()+1):
                    writer.writerow([self.item(row, col).text() if self.item(row, col) else '' for col in range(r.leftColumn(), r.rightColumn()+1)])
                QApplication.clipboard().setText(output.getvalue())
            return
        super().keyPressEvent(event)

class ModelEditor(QWidget):
    changed = Signal()
    def __init__(self):
        super().__init__()
        self.project = None
        self.current_table = 'Item'
        self.loading = False
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(label('模型数据', 'PageTitle'))
        outer.addWidget(label('SIMLOX 2017 原始字段 · 单位与约束来自本机数据字典', 'Muted'))
        splitter = QSplitter()
        outer.addWidget(splitter, 1)
        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 10, 8, 0)
        self.search = QLineEdit()
        self.search.setPlaceholderText('搜索表名、字段代码…')
        self.search.textChanged.connect(self.filter_tree)
        ll.addWidget(self.search)
        self.all_tables = QCheckBox('显示全部 133 张表')
        self.all_tables.toggled.connect(self.filter_tree)
        ll.addWidget(self.all_tables)
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.itemSelectionChanged.connect(self.tree_selected)
        ll.addWidget(self.tree)
        splitter.addWidget(left)
        middle = QWidget()
        ml = QVBoxLayout(middle)
        ml.setContentsMargins(3, 10, 3, 0)
        top = QHBoxLayout()
        self.title = label('Item · 备件 / 部件')
        self.title.setStyleSheet('font-size:16px; font-weight:650;')
        top.addWidget(self.title)
        top.addStretch()
        self.count_label = label('', 'Muted')
        top.addWidget(self.count_label)
        ml.addLayout(top)
        toolbar = QHBoxLayout()
        toolbar.addWidget(button('＋ 添加行', self.add_row))
        toolbar.addWidget(button('删除选中行', self.delete_rows))
        toolbar.addStretch()
        toolbar.addWidget(button('导入 CSV', self.import_csv))
        toolbar.addWidget(button('导出 CSV', self.export_csv))
        ml.addLayout(toolbar)
        self.grid = Grid()
        self.grid.setAlternatingRowColors(True)
        self.grid.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.grid.setItemDelegate(FieldDelegate(self))
        self.grid.verticalHeader().setDefaultSectionSize(36)
        self.grid.itemChanged.connect(self.cell_changed)
        self.grid.currentCellChanged.connect(self.selected_field)
        self.grid.paste_requested.connect(self.paste)
        ml.addWidget(self.grid, 1)
        self.support_label = label('', 'Muted', True)
        ml.addWidget(self.support_label)
        splitter.addWidget(middle)
        self.info = QTextBrowser()
        self.info.setMinimumWidth(220)
        self.info.setMaximumWidth(300)
        splitter.addWidget(self.info)
        splitter.setSizes([225, 800, 245])
        self.nodes = {}
        groups = {}
        for name in TABLES:
            group = category(name)
            if group not in groups:
                groups[group] = QTreeWidgetItem(self.tree, [group])
            node = QTreeWidgetItem(groups[group], [f'{name}  {table_label(name) if table_label(name) != name else ""}'])
            node.setData(0, Qt.UserRole, name)
            node.setToolTip(0, f'{name} · {len(TABLES[name])} 字段')
            self.nodes[name] = node
        self.tree.expandAll()
        self.filter_tree()
    def set_project(self, project):
        self.project = project
        self.select_table(self.current_table)
    def filter_tree(self):
        term = self.search.text().strip().lower()
        for name, node in self.nodes.items():
            haystack = name + ' ' + table_label(name) + ' ' + ' '.join(f['id'] for f in TABLES[name])
            visible = (self.all_tables.isChecked() or name in CORE_TABLES or bool(term)) and term in haystack.lower()
            node.setHidden(not visible)
        for i in range(self.tree.topLevelItemCount()):
            group = self.tree.topLevelItem(i)
            group.setHidden(all(group.child(j).isHidden() for j in range(group.childCount())))
    def tree_selected(self):
        nodes = self.tree.selectedItems()
        if nodes and nodes[0].data(0, Qt.UserRole):
            self.select_table(nodes[0].data(0, Qt.UserRole))
    def select_table(self, name):
        self.current_table = name
        if not self.project:
            return
        self.loading = True
        fields = TABLES[name]
        rows = self.project['tables'].get(name, [])
        self.grid.clear()
        self.grid.setColumnCount(len(fields))
        self.grid.setRowCount(len(rows))
        self.grid.setHorizontalHeaderLabels([f"{f['id']}\n{field_label(f)}" for f in fields])
        for col, field in enumerate(fields):
            self.grid.setColumnWidth(col, 165 if len(field_label(field)) > 12 else 135)
            self.grid.horizontalHeaderItem(col).setToolTip(f"{field['description']}\n单位: {field['unit'] or '无量纲 / 文本'}\n{field['constraints']}")
        for i, row in enumerate(rows):
            for j, field in enumerate(fields):
                raw = row.get(field['id'], '')
                displayed_default = raw in ('', None) and bool(field['default'])
                item = QTableWidgetItem(field['default'] if displayed_default else (str(raw) if raw is not None else ''))
                if field['kind'] == 'Index':
                    item.setForeground(QColor('#8fc5ff'))
                if displayed_default:
                    item.setForeground(QColor('#91a5bf'))
                    item.setToolTip('留空时使用默认值：' + field['default'])
                self.grid.setItem(i, j, item)
        self.title.setText(f'{name} · {table_label(name)}')
        self.count_label.setText(f'{len(rows)} 行 / {len(fields)} 字段')
        self.support_label.setText('双击编辑 · Ctrl+C / Ctrl+V 可与 Excel 交换 · 留空字段按字典默认值解释。' if name in SUPPORTED else '此表可编辑、保存和交换；本版引擎暂不支持计算，含数据时会阻止运行。')
        self.loading = False
        self.tree.blockSignals(True)
        self.tree.setCurrentItem(self.nodes[name])
        self.tree.blockSignals(False)
        self.show_field(fields[0])
    def show_field(self, field):
        esc = html.escape
        supported = field['id'] in SUPPORTED.get(self.current_table, set()) | DOCUMENTARY
        def line(title, content):
            return f'<p style="color:#9fb4d1;margin-bottom:3px">{title}</p><p style="margin-top:0;color:#dce8fa">{esc(str(content or "—"))}</p>'
        text = f'<h3 style="color:#8fc5ff">{esc(field["id"])}</h3><b>{esc(field_label(field))}</b>'
        text += line('原始定义', field['description'])
        text += line('数据类型 / 字段类型', field['type']+' / '+field['kind'])
        text += line('基本单位', field['unit'])
        text += line('默认值', field['default'])
        text += line('约束', field['constraints'])
        text += line('关联表', field['references'])
        text += line('计算支持', '支持基础规则，具体值在运行前校验' if supported else '保存与交换；仅允许不改变基础模型的默认值参与本版运行')
        if field['id'] == 'FRT':
            text += '<p style="color:#f3c77a">FRT 按每百万运行参数单位计。OPHOURS 下 MTBF = 1,000,000 / FRT 小时。</p>'
        self.info.setHtml('<div style="font-family:Microsoft YaHei UI;font-size:12px;padding:10px">'+text+'</div>')
    def selected_field(self, row, col, prevrow, prevcol):
        if col >= 0:
            self.show_field(TABLES[self.current_table][col])
    def cell_changed(self, item):
        if self.loading or not self.project:
            return
        self.project['tables'][self.current_table][item.row()][TABLES[self.current_table][item.column()]['id']] = item.text()
        self.changed.emit()
    def add_row(self):
        if not self.project:
            return
        rows = self.project['tables'].setdefault(self.current_table, [])
        rows.append(defaults(self.current_table))
        self.select_table(self.current_table)
        self.grid.setCurrentCell(len(rows)-1, 0)
        self.changed.emit()
    def delete_rows(self):
        indexes = sorted({i.row() for i in self.grid.selectedIndexes()}, reverse=True)
        if not indexes:
            return
        for index in indexes:
            del self.project['tables'][self.current_table][index]
        self.select_table(self.current_table)
        self.changed.emit()
    def paste(self, text):
        data = list(csv.reader(io.StringIO(text), delimiter='\t'))
        if not data:
            return
        row, col = max(0, self.grid.currentRow()), max(0, self.grid.currentColumn())
        if len(data) > 50000 or max(map(len, data)) + col > len(TABLES[self.current_table]):
            QMessageBox.warning(self, '无法粘贴', '粘贴范围超出当前表的字段数量或行数限制。')
            return
        rows = self.project['tables'].setdefault(self.current_table, [])
        while len(rows) < row+len(data):
            rows.append(defaults(self.current_table))
        for i, cells in enumerate(data):
            for j, text in enumerate(cells):
                rows[row+i][TABLES[self.current_table][col+j]['id']] = text
        self.select_table(self.current_table)
        self.changed.emit()
    def import_csv(self):
        path, _ = QFileDialog.getOpenFileName(self, '导入当前表（表头必须使用原字段代码）', '', 'CSV (*.csv);;文本 (*.txt)')
        if not path:
            return
        try:
            self.import_csv_path(path)
        except Exception as error:
            QMessageBox.warning(self, '导入失败', str(error))
    def import_csv_path(self, path):
        raw = Path(path).read_bytes()
        if len(raw) > 20*1024*1024:
            raise ValueError('CSV 超过 20 MB 限制。')
        try:
            text = raw.decode('utf-8-sig')
        except UnicodeDecodeError:
            text = raw.decode('gb18030')
        try:
            dialect = csv.Sniffer().sniff(text[:4096], delimiters=',;\t')
        except csv.Error:
            dialect = csv.excel
        reader = csv.DictReader(io.StringIO(text), dialect=dialect)
        headers = reader.fieldnames or []
        allowed = {f['id'] for f in TABLES[self.current_table]}
        if not headers or len(headers) != len(set(headers)) or set(headers)-allowed:
            raise ValueError('CSV 表头存在未知或重复字段：请使用 '+', '.join(sorted(allowed)))
        data = list(reader)
        if len(data) > 50000 or any(None in row or any(v is None for v in row.values()) for row in data):
            raise ValueError('CSV 行数过多或列数不一致。')
        # Append preserves existing records. Validation reports conflicting keys.
        self.project['tables'].setdefault(self.current_table, []).extend(data)
        self.select_table(self.current_table)
        self.changed.emit()
    def export_csv(self):
        path, _ = QFileDialog.getSaveFileName(self, '导出当前表', self.current_table+'.csv', 'CSV (*.csv)')
        if path:
            try:
                self.export_csv_path(path)
            except Exception as error:
                QMessageBox.warning(self, '导出失败', str(error))
    def export_csv_path(self, path):
        with open(path, 'w', encoding='utf-8-sig', newline='') as file:
            writer = csv.DictWriter(file, fieldnames=[f['id'] for f in TABLES[self.current_table]])
            writer.writeheader()
            writer.writerows(self.project['tables'].get(self.current_table, []))
