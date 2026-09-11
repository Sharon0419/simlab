"""End-to-end desktop verification, usable from source and the packaged exe."""
import json
from pathlib import Path
import time
from PySide6.QtCore import Qt
from PySide6.QtGui import QFontDatabase, QFont
from PySide6.QtWidgets import QApplication
from PySide6.QtTest import QTest
from .project import export_package, import_package, load_project
from .ui.window import MainWindow

def run(directory):
    directory = Path(directory).resolve()
    directory.mkdir(parents=True, exist_ok=True)
    app = QApplication.instance() or QApplication([])
    # The offscreen Windows platform does not enumerate installed fonts.
    for font_file in ['msyh.ttc', 'msyhbd.ttc', 'segoeui.ttf']:
        font_path = Path('C:/Windows/Fonts') / font_file
        if font_path.exists():
            QFontDatabase.addApplicationFont(str(font_path))
    app.setFont(QFont('Microsoft YaHei UI', 10))
    window = MainWindow(directory/'userdata', restore=False)
    failures = []
    window.warn = lambda title, message: failures.append(title+': '+message)
    window.show()
    QTest.qWait(150)
    # First snapshot: overview with the actual starter model.
    window.grab().save(str(directory/'01-overview.png'))
    window.nav.setCurrentRow(1)
    window.editor.select_table('Item')
    QTest.qWait(100)
    assert window.editor.grid.rowCount() == 3
    assert window.editor.grid.columnCount() == 18
    assert window.editor.grid.horizontalHeaderItem(2).text().startswith('FRT')
    window.editor.grid.item(0, 2).setText('1300')
    assert window.project['tables']['Item'][0]['FRT'] == '1300'
    window.save()
    assert load_project(window.project_path)['tables']['Item'][0]['FRT'] == '1300'
    window.grab().save(str(directory/'02-modeling.png'))
    window.editor.export_csv_path(directory/'Item.csv')
    # Start and cancel through the desktop controls.
    window.nav.setCurrentRow(2)
    window.repetitions.setValue(1000)
    window.horizon.setValue(8760)
    QTest.mouseClick(window.run_button, Qt.LeftButton)
    QTest.qWait(50)
    window.save()  # Exercise a save while the worker owns a frozen snapshot.
    QTest.mouseClick(window.cancel_button, Qt.LeftButton)
    deadline = time.monotonic()+20
    while window.process is not None and time.monotonic() < deadline:
        QTest.qWait(30)
    assert window.process is None, 'Cancelled worker did not exit'
    assert window.project['runs'][-1]['status'] == 'cancelled'
    # Run a real Monte Carlo experiment and check the durable result.
    window.repetitions.setValue(10)
    window.horizon.setValue(2160)
    QTest.mouseClick(window.run_button, Qt.LeftButton)
    deadline = time.monotonic()+60
    while window.process is not None and time.monotonic() < deadline:
        QTest.qWait(50)
    assert window.process is None, 'Worker did not finish'
    assert not failures, failures
    last = window.project['runs'][-1]
    assert last['status'] == 'completed', last
    assert 0 < last['result']['availability'] <= 1
    assert window.pages.currentIndex() == 3
    assert window.progress.value() == 100
    assert window.result_cards[0].number.text() != '—'
    assert load_project(window.project_path)['runs'][-1]['result'] == last['result']
    QTest.qWait(100)
    window.grab().save(str(directory/'03-results.png'))
    export_package(window.project, directory/'demo-complete.simproj')
    branch = import_package(directory/'demo-complete.simproj')
    assert branch['id'] != window.project['id']
    assert branch['tables'] == window.project['tables']
    assert branch['runs'][-1]['result'] == last['result']
    window.adopt_project(branch, directory/'imported.sqlite')
    assert window.complete_runs
    # v0.2: create through the actual UI, edit mission demand, run the worker,
    # verify durable results and the task-specific export and exchange path.
    window.nav.setCurrentRow(0)
    QTest.mouseClick(window.mission_demo_button, Qt.LeftButton)
    assert window.project['tables']['Operations']
    assert window.editor.current_table == 'MissionType'
    # Keep the runtime bounded but retain all 30 daily demand windows.
    window.editor.grid.item(0, 2).setText('22')
    window.editor.grid.item(0, 3).setText('22')
    window.save()
    window.grab().save(str(directory/'04-mission-model.png'))
    window.nav.setCurrentRow(2)
    window.repetitions.setValue(3)
    QTest.mouseClick(window.run_button, Qt.LeftButton)
    deadline = time.monotonic()+60
    while window.process is not None and time.monotonic() < deadline:
        QTest.qWait(50)
    assert window.process is None, 'Mission worker did not finish'
    assert not failures, failures
    mission_run = window.project['runs'][-1]
    assert mission_run['status'] == 'completed', mission_run
    mission = mission_run['result']['mission']
    assert 0 < mission['fulfillment'] < 1
    assert mission['gap_hours'] >= 2 * 8 * 30
    assert window.mission_table.rowCount() == 30
    assert window.mission_export_button.isEnabled()
    assert load_project(window.project_path)['runs'][-1]['result'] == mission_run['result']
    window.chart_tabs.setCurrentIndex(1)
    window.result_tabs.setCurrentIndex(5)
    QTest.qWait(100)
    window.grab().save(str(directory/'05-mission-results.png'))
    window.export_missions_path(directory/'mission-results.csv')
    assert len((directory/'mission-results.csv').read_text(encoding='utf-8-sig').splitlines()) == 31
    export_package(window.project, directory/'mission-complete.simproj')
    imported_mission = import_package(directory/'mission-complete.simproj')
    assert imported_mission['runs'][-1]['result']['mission'] == mission
    window.adopt_project(imported_mission, directory/'mission-imported.sqlite')
    assert window.mission_table.rowCount() == 30
    output = {'status': 'passed', 'checks': ['field editor', 'save/reopen', 'CSV export',
               'worker cancellation', 'worker run', 'result persistence', 'package export/import', 'branch provenance',
               'mission example button', 'mission field edit', 'mission worker run', 'mission persistence',
               'mission CSV export', 'mission package roundtrip'],
              'mission_fulfillment': mission['fulfillment'], 'mission_gap_hours': mission['gap_hours'],
              'availability': last['result']['availability'], 'replications': last['result']['replications']}
    window.nav.setCurrentRow(0)
    QTest.mouseClick(window.layered_demo_button, Qt.LeftButton)
    assert window.pages.currentIndex() == 5
    assert window.structure.tree.topLevelItem(0).child(0).child(0).text(0) == 'BOARD'
    QTest.qWait(100)
    window.grab().save(str(directory/'06-structure.png'))
    window.nav.setCurrentRow(1)
    window.editor.select_table('SimLabDepotProcess')
    window.editor.grid.item(0, 2).setText('2')
    window.save()
    assert load_project(window.project_path)['tables']['SimLabDepotProcess'][0]['DIAG_H'] == '2'
    window.grab().save(str(directory/'07-depot-process.png'))
    window.nav.setCurrentRow(2)
    window.repetitions.setValue(3)
    QTest.mouseClick(window.run_button, Qt.LeftButton)
    deadline = time.monotonic()+60
    while window.process is not None and time.monotonic() < deadline:
        QTest.qWait(50)
    if window.process is not None:
        window.process.kill()
        window.process.waitForFinished(3000)
        raise AssertionError('Layered worker timed out')
    assert not failures, failures
    layered_run = window.project['runs'][-1]
    assert layered_run['status'] == 'completed', layered_run
    m = layered_run['result']['maintenance']
    assert m['by_kind']['LRU']['completed'] > 0
    assert m['by_kind']['SRU']['completed'] > 0
    assert window.maintenance_table.rowCount() == 2
    assert window.component_table.rowCount() > 0
    window.result_tabs.setCurrentIndex(7)
    QTest.qWait(100)
    window.grab().save(str(directory/'08-maintenance-results.png'))
    window.export_maintenance_path(directory/'maintenance.csv')
    assert len((directory/'maintenance.csv').read_text(encoding='utf-8-sig').splitlines()) > 5
    export_package(window.project, directory/'layered-complete.simproj')
    imported = import_package(directory/'layered-complete.simproj')
    assert imported['runs'][-1]['result'] == layered_run['result']
    window.adopt_project(imported, directory/'layered-imported.sqlite')
    assert window.maintenance_table.rowCount() == 2
    output['checks'] += ['layered example', 'structure tree', 'depot extension edit', 'layered worker', 'maintenance CSV', 'layered package roundtrip']
    output['layered_availability'] = layered_run['result']['availability']
    output['layered_lru_tat'] = m['by_kind']['LRU']['mean_tat']
    window.nav.setCurrentRow(6)
    planner = window.duty_planner
    QTest.mouseClick(planner.example_button, Qt.LeftButton)
    assert window.project['tables']['SimLabDutyRule'][0]['MIN_QTY'] == '13'
    planner.minimum.setValue(14)
    planner.relief.setValue(.75)
    QTest.mouseClick(planner.save_button, Qt.LeftButton)
    assert window.project['tables']['SimLabDutyRule'][0]['MIN_QTY'] == '14'
    assert window.save()
    assert load_project(window.project_path)['tables']['SimLabDutyRule'][0]['RELIEF_H'] == '0.75'
    planner.name.setText('重点值守')
    planner.days.setValue(2)
    planner.start_hour.setValue(10)
    planner.end_hour.setValue(12)
    planner.target.setValue(2)
    planner.minimum.setValue(1)
    planner.priority.setValue(1)
    before_count = len(window.project['tables']['OperationProfile'])
    QTest.mouseClick(planner.preview_button, Qt.LeftButton)
    assert planner.apply_button.isEnabled(), planner.message.text()
    assert planner.grid.rowCount() == 2
    assert len(window.project['tables']['OperationProfile']) == before_count
    assert '2 对重叠' in planner.message.text()
    planner.days.setValue(3)
    assert not planner.apply_button.isEnabled()
    planner.days.setValue(2)
    QTest.mouseClick(planner.preview_button, Qt.LeftButton)
    QTest.mouseClick(planner.apply_button, Qt.LeftButton)
    assert len(window.project['tables']['OperationProfile']) == before_count + 2
    assert planner.grid.rowCount() == 32
    assert window.save()
    QTest.qWait(100)
    window.grab().save(str(directory/'09-duty-plan.png'))
    window.nav.setCurrentRow(2)
    window.repetitions.setValue(3)
    QTest.mouseClick(window.run_button, Qt.LeftButton)
    assert not planner.isEnabled()
    deadline = time.monotonic()+60
    while window.process is not None and time.monotonic() < deadline:
        QTest.qWait(50)
    if window.process is not None:
        window.process.kill()
        window.process.waitForFinished(3000)
        raise AssertionError('Duty worker timed out')
    assert not failures, failures
    duty_run = window.project['runs'][-1]
    assert duty_run['status'] == 'completed', duty_run
    duty = duty_run['result']['mission']
    assert 0 < duty['minimum_rate'] < 1
    assert 0 <= duty['qualified_rate'] <= 1
    assert duty['gap_reasons']['relief'] > 0
    assert window.duty_table.rowCount() == 32
    assert window.duty_intervals.rowCount() > 0
    assert planner.isEnabled()
    window.chart_tabs.setCurrentIndex(1)
    window.result_tabs.setCurrentIndex(9)
    QTest.qWait(100)
    window.grab().save(str(directory/'10-duty-results.png'))
    window.result_tabs.setCurrentIndex(10)
    QTest.qWait(100)
    window.grab().save(str(directory/'11-duty-intervals.png'))
    window.export_missions_path(directory/'duty.csv')
    assert 'qualified_rate' in (directory/'duty.csv').read_text(encoding='utf-8-sig').splitlines()[0]
    assert load_project(window.project_path)['runs'][-1]['result']['mission'] == duty
    export_package(window.project, directory/'duty-complete.simproj')
    imported_duty = import_package(directory/'duty-complete.simproj')
    assert imported_duty['runs'][-1]['result']['mission'] == duty
    window.adopt_project(imported_duty, directory/'duty-imported.sqlite')
    assert window.duty_table.rowCount() == 32
    output['checks'] += ['duty example', 'duty rule persistence', 'daily plan preview and conflict',
                         'preview invalidation', 'duty worker and metrics', 'duty CSV', 'duty exchange roundtrip']
    output['duty_minimum_rate'] = duty['minimum_rate']
    output['duty_qualified_rate'] = duty['qualified_rate']
    output['duty_relief_gap_hours'] = duty['gap_reasons']['relief']
    # v0.7: actual editor, isolated worker, success UI and both CSV paths.
    from .sample import mission_project
    from .flight_results import export_tasks
    from .compiler import compile_model
    import csv
    flight_project=mission_project()
    flight_project['name']='v0.7 飞行成功点桌面验收'
    tables=flight_project['tables']
    sid=tables['System'][0]['SID'];location=tables['SystemDeployment'][0]['USTID']
    tables['SystemDeployment']=[dict(SID=sid,USTID=location,QTYPS='12',UTIL='1')]
    for row in tables['Item']:row['FRT']='0'
    tables['MissionType']=[dict(MTID='FLIGHT',NOS='2',MNOS='2',DURN='3')]
    tables['MissionSystem']=[dict(MTID='FLIGHT',SID=sid)]
    tables['Operations']=[dict(USTID=location,PRID='P')]
    tables['OperationProfile']=[dict(PRID='P',SPRID='FLIGHT',STIM=str(d*24+h)) for d in range(3) for h in (9,12,15)]
    tables['SimLabFlightRule']=[dict(MTID='FLIGHT',PREP_H='.5')]
    tables['Control'][0].update(SIMPE='72',NREPS='3')
    window.adopt_project(flight_project,directory/'flight.sqlite')
    window.nav.setCurrentRow(1);window.editor.select_table('MissionType')
    helper=window.editor.flight_timing
    assert helper.isVisible()
    for spin,v in zip(helper.inputs,(180,30,30,150)):spin.setValue(v)
    assert '11:30:00' in helper.summary.text()
    helper.inputs[2].setValue(180)
    assert not helper.apply_button.isEnabled()
    helper.inputs[2].setValue(30)
    QTest.mouseClick(helper.apply_button,Qt.LeftButton)
    assert compile_model(window.project['tables'])['missions'][0]['success_fraction']==5/6
    assert window.save()
    QTest.qWait(100);window.grab().save(str(directory/'12-flight-timing.png'))
    window.nav.setCurrentRow(2)
    window.repetitions.setValue(3)
    QTest.mouseClick(window.run_button,Qt.LeftButton)
    deadline=time.monotonic()+60
    while window.process is not None and time.monotonic()<deadline:QTest.qWait(50)
    assert window.process is None, 'Flight worker timed out'
    assert not failures,failures
    flight_run=window.project['runs'][-1]
    assert flight_run['status']=='completed',flight_run
    assert flight_run['result']['mission']['flight']['successful']==9
    assert window.success_table.rowCount()==window.success_details.rowCount()==9
    window.chart_tabs.setCurrentIndex(1);window.result_tabs.setCurrentIndex(13)
    QTest.qWait(100);window.grab().save(str(directory/'13-flight-success.png'))
    window.result_tabs.setCurrentIndex(14)
    QTest.qWait(100);window.grab().save(str(directory/'14-flight-decisions.png'))
    window.export_missions_path(directory/'flight-summary.csv')
    export_tasks(flight_run,directory/'flight-details.csv',True)
    with (directory/'flight-details.csv').open(encoding='utf-8-sig',newline='') as file:
        detail=list(csv.DictReader(file))
    assert len(detail)==27 and all(row['successful']=='True' for row in detail)
    export_package(window.project,directory/'flight.simproj')
    loaded=import_package(directory/'flight.simproj')
    assert loaded['runs'][-1]['result']==flight_run['result']
    assert load_project(window.project_path)['extensions_version']==5
    output['checks']+=['flight minute input and preview','invalid phase input blocked','success worker and metrics',
        'success and decision views','all replication CSV','flight v5 exchange roundtrip']
    window.close()
    app.processEvents()
    (directory/'smoke-result.json').write_text(json.dumps(output, indent=2), encoding='utf-8')
    return 0
