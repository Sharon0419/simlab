"""Bounded read-only type structure, safe to show before validation."""
from PySide6.QtWidgets import QWidget, QVBoxLayout, QTreeWidget, QTreeWidgetItem
from .widgets import label


class StructureView(QWidget):
    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(label('组成结构', 'PageTitle'))
        self.setToolTip('只读类型结构；在模型数据中编辑组成关系。实物位置见结果的部件实例。')
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(['系统 / 部件', '类型', '每母件数量', '最低可用数量', '名称'])
        self.tree.setColumnWidth(0, 350)
        self.tree.setColumnWidth(1, 100)
        self.tree.setColumnWidth(2, 130)
        layout.addWidget(self.tree)

    def set_project(self, project):
        self.tree.clear()
        tables = project['tables']
        thresholds = {(r.get('PARENT'), r.get('IID')): str(r.get('K', ''))
                      for r in tables.get('SimLabRedundancy', [])}
        items = {r.get('IID'): r for r in tables.get('Item', [])}
        edges = {}
        for row in tables.get('MaterielStructure', []):
            edges.setdefault(row.get('MMID'), []).append(row)
        count = 0
        def descend(node, parent, seen, depth):
            nonlocal count
            for row in edges.get(parent, []):
                if count >= 5000:
                    QTreeWidgetItem(node, ['结构预览达到 5000 节点上限'])
                    return
                count += 1
                iid = row.get('MID', '')
                item = items.get(iid, {})
                quantity = str(row.get('QTYPM', '1'))
                child = QTreeWidgetItem(node, [iid, item.get('TYPE', 'LRU'), quantity,
                    thresholds.get((parent, iid), quantity), item.get('DESCR', '')])
                if iid in seen or depth >= 2:
                    if edges.get(iid):
                        QTreeWidgetItem(child, ['循环或超过两层部件，请校验模型'])
                else:
                    descend(child, iid, seen | {iid}, depth+1)
        for system in tables.get('System', []):
            sid = system.get('SID', '')
            root = QTreeWidgetItem(self.tree, [sid, 'System', '—', '—', system.get('DESCR', '')])
            descend(root, sid, {sid}, 1)
        self.tree.expandAll()
