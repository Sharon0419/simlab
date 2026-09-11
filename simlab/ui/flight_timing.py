"""Minute-based helper for original MissionType fields; edits require Apply."""
import math
from PySide6.QtCore import Signal
from PySide6.QtWidgets import QWidget, QGridLayout, QVBoxLayout, QDoubleSpinBox
from ..schema import value
from .widgets import label, button


def clock(hours):
    total=round(hours*3600)
    day,seconds=divmod(total,86400)
    h,seconds=divmod(seconds,3600)
    minute,second=divmod(seconds,60)
    return f'第{day+1}天 {h:02}:{minute:02}:{second:02}'


class FlightTiming(QWidget):
    applied=Signal()

    def __init__(self):
        super().__init__()
        self.row=None
        self.project=None
        outer=QVBoxLayout(self)
        outer.setContentsMargins(0,0,0,0)
        outer.addWidget(label('飞行阶段与成功点 · 分钟辅助输入', 'Muted'))
        line=QGridLayout()
        self.inputs=[]
        for i,title in enumerate(('总时长','出航','返航','起飞至成功点')):
            line.addWidget(label(title),i//2,(i%2)*2)
            spin=QDoubleSpinBox()
            spin.setRange(0,1440)
            spin.setDecimals(6)
            spin.setSuffix(' 分')
            spin.valueChanged.connect(self.preview)
            line.addWidget(spin,i//2,(i%2)*2+1)
            self.inputs.append(spin)
        self.apply_button=button('应用到此任务类型',self.apply)
        line.addWidget(self.apply_button,0,4,2,1)
        outer.addLayout(line)
        self.summary=label('', 'Muted', True)
        self.summary.setMinimumHeight(86)
        outer.addWidget(self.summary)

    def bind(self,project,row):
        self.project,self.row=project,row
        try:
            duration=float(value('MissionType',row,'DURN'))*60
            vals=[duration]+[duration*float(value('MissionType',row,k)) for k in ('TFOUT','TFRET','MSUCPT')]
            if not all(math.isfinite(x) and 0<=x<=1440 for x in vals):
                raise ValueError()
            for spin,v in zip(self.inputs,vals):
                spin.blockSignals(True);spin.setValue(v);spin.blockSignals(False)
            self.preview()
        except (ValueError,TypeError):
            self.row=None
            self.apply_button.setEnabled(False)
            self.summary.setText('原字段数值无效或超出单日范围，请先在表格修正。')

    def preview(self):
        if self.row is None:return
        duration,out,back,success=[s.value() for s in self.inputs]
        valid=duration>0 and out+back<=duration and success<=duration
        self.apply_button.setEnabled(valid)
        if not valid:
            self.summary.setText('要求总时长>0，出航+返航≤总时长，成功点≤总时长。')
            return
        tid=self.row.get('MTID')
        starts=[float(r['STIM']) for r in self.project['tables'].get('OperationProfile',[])
                if r.get('SPRID')==tid and _numeric(r.get('STIM'))]
        start=min(starts) if starts else 0
        prefix='首次计划：' if starts else '相对起飞时刻：'
        self.summary.setText(prefix+f'{clock(start)} 起飞 → {clock(start+out/60)} 进入任务区 → '
            f'{clock(start+(duration-back)/60)} 返航 → {clock(start+duration/60)} 落地\n'
            f'任务区 {duration-out-back:g} 分；成功点 {clock(start+success/60)}（{success/duration:.2%}）。'
            '成功后仍可能中止；同刻故障算已达成功点。点击应用后保存原字段 DURN/TFOUT/TFRET/MSUCPT；需配置飞行规则。')

    def apply(self):
        if self.row is None or not self.apply_button.isEnabled():return
        duration,out,back,success=[s.value() for s in self.inputs]
        self.row.update(DURN=str(duration/60),TFOUT=str(out/duration),TFRET=str(back/duration),MSUCPT=str(success/duration))
        self.applied.emit()


def _numeric(v):
    try:return math.isfinite(float(v))
    except (ValueError,TypeError):return False
