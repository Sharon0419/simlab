from pathlib import Path
from datetime import datetime
from PySide6.QtCore import Signal,Qt
from PySide6.QtWidgets import QWidget,QVBoxLayout,QHBoxLayout,QLineEdit,QTableWidget,QTableWidgetItem,QAbstractItemView,QHeaderView
from .widgets import label,button


class LibraryPage(QWidget):
    open_requested=Signal(str)
    copy_requested=Signal(str)
    import_requested=Signal()

    def __init__(self,catalog):
        super().__init__()
        self.catalog=catalog
        self.entries=[]
        layout=QVBoxLayout(self)
        layout.setContentsMargins(0,0,0,0)
        layout.addWidget(label('项目库','PageTitle'))
        layout.addWidget(label('统一查找案例与方案；复制模型会创建独立项目，保留原项目和历史结果。','Muted',True))
        actions=QHBoxLayout()
        self.search=QLineEdit();self.search.setPlaceholderText('搜索项目名称、说明或路径…')
        self.search.textChanged.connect(self.render)
        actions.addWidget(self.search,1)
        actions.addWidget(button('刷新',self.refresh))
        actions.addWidget(button('导入案例包',self.import_requested.emit))
        self.open_button=button('打开选中项目',lambda:self.choose(False),True)
        self.copy_button=button('复制模型为新方案',lambda:self.choose(True))
        actions.addWidget(self.open_button);actions.addWidget(self.copy_button)
        layout.addLayout(actions)
        self.table=QTableWidget(0,6)
        self.table.setHorizontalHeaderLabels(['项目名称','案例说明','最近运行','计算版本','运行状态','数据库位置'])
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setAlternatingRowColors(True)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.verticalHeader().setVisible(False)
        self.table.cellDoubleClicked.connect(lambda *_:self.choose(False))
        layout.addWidget(self.table,1)
        self.message=label('','Muted',True);layout.addWidget(self.message)

    def refresh(self):
        try:self.entries=self.catalog.entries();self.render()
        except Exception as error:self.message.setText('项目库索引读取失败，可通过顶部“打开”继续使用：'+str(error))

    def render(self):
        term=self.search.text().strip().lower()
        rows=[r for r in self.entries if term in (r['name']+' '+r['description']+' '+r['path']).lower()]
        self.table.setRowCount(len(rows))
        statuses={'completed':'已完成','cancelled':'已取消','failed':'失败','running':'运行中','interrupted':'已中断'}
        for i,r in enumerate(rows):
            try:last=datetime.fromisoformat(r['last_run']).astimezone().strftime('%Y-%m-%d %H:%M')
            except (ValueError,TypeError):last=r['last_run'] or '—'
            values=[r['name'],r['description'],last,r['engine'] or '—',statuses.get(r['status'],r['status']),r['path']]
            for col,v in enumerate(values):
                item=QTableWidgetItem(v)
                item.setToolTip(r['error'] or v)
                if col==0:item.setData(Qt.UserRole,r)
                self.table.setItem(i,col,item)
        self.message.setText(f'显示 {len(rows)} 个项目。双击打开；数据库位置完整路径可悬停查看。旧cmd仍可使用，无需逐个寻找启动脚本。')

    def choose(self,copy):
        row=self.table.currentRow()
        if row<0:return
        entry=self.table.item(row,0).data(Qt.UserRole)
        if entry['error']:
            self.message.setText(entry['error']);return
        (self.copy_requested if copy else self.open_requested).emit(entry['path'])
