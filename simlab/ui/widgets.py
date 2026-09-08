from PySide6.QtCore import Qt, QRectF, QPointF
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen, QFont, QLinearGradient
from PySide6.QtWidgets import QWidget, QFrame, QVBoxLayout, QLabel, QPushButton

STYLE = '''
QWidget { color: #dce8fa; font-family: "Microsoft YaHei UI", "Segoe UI"; font-size: 13px; }
QMainWindow { background: #0b1426; }
QFrame#Sidebar { background: #081122; border: none; }
QLabel#Brand { color: white; font-size: 27px; font-weight: 750; letter-spacing: 2px; }
QLabel#SidebarSub { color: #95aed0; font-size: 11px; }
QListWidget#Navigation { background: transparent; border: none; color: #b9cce7; outline: none; }
QListWidget#Navigation::item { height: 45px; padding-left: 17px; margin: 4px 10px; border-radius: 7px; }
QListWidget#Navigation::item:selected { background: #193b65; color: white; border-left: 3px solid #60a5fa; }
QFrame#Topbar, QFrame#Card { background: #112139; border: 1px solid #29415f; border-radius: 9px; }
QLabel#PageTitle { color: #eff6ff; font-size: 25px; font-weight: 700; }
QLabel#Muted { color: #9fb4d1; font-size: 12px; }
QLabel#Metric { color: #eff6ff; font-size: 30px; font-weight: 750; }
QLabel#Badge { background: #15395c; color: #8fc5ff; padding: 5px 10px; border-radius: 5px; font-size: 11px; }
QPushButton { background: #112139; border: 1px solid #365477; border-radius: 6px; padding: 8px 14px; color: #dce8fa; }
QPushButton:hover { background: #203e62; border-color: #60a5fa; }
QPushButton:pressed { background: #294e79; }
QPushButton:disabled { color: #778da9; background: #142237; }
QPushButton#Primary { background: #2563eb; border-color: #2563eb; color: white; font-weight: 600; }
QPushButton#Primary:hover { background: #3478f6; }
QPushButton#Primary:disabled { background: #27436c; border-color: #27436c; }
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox { background: #112139; border: 1px solid #365477; border-radius: 5px; padding: 7px; selection-background-color: #2563eb; }
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus { border-color: #2563eb; }
QTreeWidget, QTableWidget, QTextBrowser { background: #112139; border: 1px solid #29415f; border-radius: 5px; }
QTreeWidget::item { height: 28px; padding: 2px; }
QTreeWidget::item:selected { background: #204d7c; color: #eff6ff; }
QHeaderView { background: #112139; }
QHeaderView::section { background: #192e49; padding: 9px 8px; border: none; border-right: 1px solid #29415f; border-bottom: 1px solid #365477; color: #bfd3ed; }
QTableWidget { gridline-color: #243b57; selection-background-color: #24538a; selection-color: #ffffff; alternate-background-color: #15263e; }
QTableWidget::item { padding: 5px; }
QTabWidget::pane { border: 1px solid #29415f; background: #112139; }
QTabBar::tab { padding: 10px 18px; background: #14253d; color: #a4bbd8; }
QTabBar::tab:selected { background: #112139; color: #93c5fd; border-top: 2px solid #2563eb; }
QProgressBar { background: #1b304c; border: none; height: 12px; border-radius: 6px; text-align: center; }
QProgressBar::chunk { background: #3b82f6; border-radius: 6px; }
QStatusBar { background: #101e33; color: #9fb4d1; }
QSplitter::handle { background: #0b1426; }
QDialog, QMessageBox, QInputDialog { background: #112139; }
QComboBox QAbstractItemView { background: #162b46; color: #dce8fa; selection-background-color: #24538a; selection-color: white; border: 1px solid #365477; }
QToolTip { background: #203e62; color: #eff6ff; border: 1px solid #60a5fa; padding: 5px; }
QTableCornerButton::section { background: #192e49; border: 1px solid #29415f; }
QScrollBar:vertical { background: #0e1b2e; width: 12px; margin: 0; }
QScrollBar:horizontal { background: #0e1b2e; height: 12px; margin: 0; }
QScrollBar::handle { background: #365477; border-radius: 5px; min-width: 24px; min-height: 24px; }
QScrollBar::handle:hover { background: #5077a6; }
QScrollBar::add-line, QScrollBar::sub-line { width: 0; height: 0; }
QScrollBar::add-page, QScrollBar::sub-page { background: transparent; }
QPushButton:focus { border: 1px solid #93c5fd; }
QTextBrowser { selection-background-color: #24538a; selection-color: white; }

'''

def label(text, object_name=None, wrap=False):
    widget = QLabel(text)
    if object_name:
        widget.setObjectName(object_name)
    widget.setWordWrap(wrap)
    return widget

def button(text, callback=None, primary=False):
    widget = QPushButton(text)
    if primary:
        widget.setObjectName('Primary')
    if callback:
        widget.clicked.connect(callback)
    return widget

def card():
    frame = QFrame()
    frame.setObjectName('Card')
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(22, 18, 22, 18)
    layout.setSpacing(12)
    return frame, layout

class Metric(QFrame):
    def __init__(self, title, subtitle):
        super().__init__()
        self.setObjectName('Card')
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 17, 20, 17)
        layout.addWidget(label(title, 'Muted'))
        self.number = label('—', 'Metric')
        layout.addWidget(self.number)
        self.subtitle = label(subtitle, 'Muted', True)
        layout.addWidget(self.subtitle)

class AvailabilityChart(QWidget):
    def __init__(self):
        super().__init__()
        self.samples = []
        self.setMinimumHeight(260)
    def set_samples(self, samples):
        self.samples = samples
        self.update()
    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.fillRect(self.rect(), QColor('#112139'))
        area = QRectF(55, 22, max(10, self.width()-80), max(10, self.height()-65))
        painter.setFont(QFont('Microsoft YaHei UI', 9))
        for percent in range(0, 101, 25):
            y = area.bottom() - area.height()*percent/100
            painter.setPen(QPen(QColor('#29415f'), 1, Qt.DashLine))
            painter.drawLine(QPointF(area.left(), y), QPointF(area.right(), y))
            painter.setPen(QColor('#a4bbd8'))
            painter.drawText(QRectF(0, y-10, 45, 20), Qt.AlignRight | Qt.AlignVCenter, f'{percent}%')
        if not self.samples:
            painter.setPen(QColor('#a4bbd8'))
            painter.drawText(area, Qt.AlignCenter, '运行实验后，将在这里显示可用度随时间的变化')
            return
        horizon = self.samples[-1]['time'] or 1
        points = [QPointF(area.left()+s['time']/horizon*area.width(), area.bottom()-s['available']*area.height()) for s in self.samples]
        path = QPainterPath(points[0])
        for point in points[1:]:
            path.lineTo(point)
        fill = QPainterPath(path)
        fill.lineTo(area.right(), area.bottom())
        fill.lineTo(area.left(), area.bottom())
        fill.closeSubpath()
        gradient = QLinearGradient(area.topLeft(), area.bottomLeft())
        gradient.setColorAt(0, QColor(59, 130, 246, 100))
        gradient.setColorAt(1, QColor(59, 130, 246, 8))
        painter.fillPath(fill, gradient)
        painter.setPen(QPen(QColor('#60a5fa'), 2.2))
        painter.drawPath(path)
        painter.setPen(QColor('#a4bbd8'))
        for i in range(6):
            x = area.left()+i/5*area.width()
            painter.drawText(QRectF(x-32, area.bottom()+12, 64, 20), Qt.AlignCenter, f'{horizon*i/5/24:.0f} 天')


class MissionChart(QWidget):
    """Sampled demand and supplied vehicles; statistics use event integration."""
    def __init__(self):
        super().__init__()
        self.samples = []
        self.setMinimumHeight(200)

    def set_samples(self, samples):
        self.samples = samples
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.fillRect(self.rect(), QColor('#112139'))
        painter.setFont(QFont('Microsoft YaHei UI', 9))
        area = QRectF(55, 30, max(10, self.width()-80), max(10, self.height()-75))
        painter.setPen(QColor('#a4bbd8'))
        if not self.samples:
            painter.drawText(area, Qt.AlignCenter, '运行任务日历示例后显示供需曲线；旧实验无任务数据')
            return
        horizon = self.samples[-1]['time'] or 1
        maximum = max(1, max(s.get('demand', 0) for s in self.samples))
        for i in range(5):
            y = area.bottom()-area.height()*i/4
            painter.setPen(QPen(QColor('#29415f'), 1, Qt.DashLine))
            painter.drawLine(QPointF(area.left(), y), QPointF(area.right(), y))
            painter.setPen(QColor('#a4bbd8'))
            painter.drawText(QRectF(0, y-10, 45, 20), Qt.AlignRight | Qt.AlignVCenter, f'{maximum*i/4:g}')
        lines = [('demand', '#f3c77a', '目标设备', 55), ('supplied', '#60a5fa', '实际供给', 165)]
        if 'minimum' in self.samples[0]:
            lines.append(('minimum', '#67dfbd', '最低保障', 275))
        for key, color, caption, offset in lines:
            painter.setPen(QColor(color))
            painter.drawText(QRectF(offset, 0, 110, 25), Qt.AlignLeft, caption)
            points = [QPointF(area.left()+s['time']/horizon*area.width(), area.bottom()-s.get(key, 0)/maximum*area.height()) for s in self.samples]
            path = QPainterPath(points[0])
            for previous, point in zip(points, points[1:]):
                path.lineTo(QPointF(point.x(), previous.y()))
                path.lineTo(point)
            painter.setPen(QPen(QColor(color), 2, Qt.DashLine if key == 'demand' else Qt.SolidLine))
            painter.drawPath(path)
        painter.setPen(QColor('#a4bbd8'))
        for i in range(6):
            x = area.left()+i/5*area.width()
            painter.drawText(QRectF(x-34, area.bottom()+12, 68, 20), Qt.AlignCenter, f'{horizon*i/5/24:.1f} 天')
