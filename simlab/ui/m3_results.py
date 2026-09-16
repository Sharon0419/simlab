"""One focused M3 dataset at a time, with explicit first-replication labeling."""
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QComboBox, QLabel,
    QPushButton, QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView,
    QFileDialog, QMessageBox)

from ..m3_results import DATASETS, LABELS, display, snapshot, truncated, detail_total, export_m3


class M3ResultsPage(QWidget):
    def __init__(self, section, parent=None):
        super().__init__(parent)
        self.section, self.run = section, None
        layout = QVBoxLayout(self)
        controls = QHBoxLayout()
        self.selector = QComboBox()
        for key, title in DATASETS[section].items():
            self.selector.addItem(title, key)
        controls.addWidget(self.selector)
        controls.addStretch()
        self.export_button = QPushButton('导出此项全部轮次 CSV')
        self.export_button.clicked.connect(self.export_dialog)
        controls.addWidget(self.export_button)
        layout.addLayout(controls)
        self.notice = QLabel()
        self.notice.setWordWrap(True)
        self.notice.setToolTip('界面显示首轮；CSV导出全部轮次，含模型、种子和版本。')
        layout.addWidget(self.notice)
        self.summary = QLabel()
        self.summary.setWordWrap(True)
        layout.addWidget(self.summary)
        self.table = QTableWidget()
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self.table)
        self.selector.currentIndexChanged.connect(self.refresh)
        self.refresh()

    def set_run(self, run):
        self.run = run
        self.refresh()

    def refresh(self, *_):
        data = snapshot(self.run['result'], self.section) if self.run else {}
        dataset = self.selector.currentData()
        rows = data.get(dataset) or []
        columns = list(dict.fromkeys(key for row in rows for key in row if not key.startswith('_')))
        self.table.clear()
        self.table.setColumnCount(len(columns))
        self.table.setRowCount(len(rows))
        self.table.setHorizontalHeaderLabels([LABELS.get(key, key) for key in columns])
        for i, row in enumerate(rows):
            for j, key in enumerate(columns):
                self.table.setItem(i, j, QTableWidgetItem(display(row.get(key))))
        self.export_button.setEnabled(bool(data))
        if not data:
            self.notice.setText('本实验没有 M3 结果；请打开三级供应示例或配置 M3 模式后运行。')
            self.summary.clear()
            return
        notice = f'首轮明细 · {len(rows)} 条'
        if truncated(data, dataset):
            notice += f' · 已截断（总数 {detail_total(data, dataset)}）'
        self.notice.setText(notice)
        totals = data.get('totals') or {}
        if dataset == 'purchases':
            self.summary.setText(f"采购 {totals.get('purchase_count', 0)} 批 · "
                                 f"订购 {totals.get('purchased', 0)} 件 · "
                                 f"已到货 {totals.get('purchase_received', 0)} 件")
        elif dataset == 'retirements':
            self.summary.setText(f'报废及随整件退出 {detail_total(data, dataset)} 件')
        elif dataset == 'lifetimes':
            self.summary.setText(f'实物总数 {detail_total(data, dataset)} 件')
        else:
            self.summary.setText('首轮汇总：' + '；'.join(
                f'{LABELS.get(key, key)} {display(value)}' for key, value in totals.items()))

    def export_path(self, path):
        if not self.run:
            raise ValueError('请选择已完成的 M3 实验。')
        export_m3(self.run, path, self.section, self.selector.currentData())

    def export_dialog(self):
        if not self.run:
            return
        path, _ = QFileDialog.getSaveFileName(self, '导出 M3 全部轮次',
            self.selector.currentText() + '-全轮.csv', 'CSV 文件 (*.csv)')
        if path:
            try:
                self.export_path(path)
            except Exception as error:
                QMessageBox.warning(self, '导出失败', str(error))
