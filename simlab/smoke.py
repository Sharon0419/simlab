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
    window.close()
    app.processEvents()
    (directory/'smoke-result.json').write_text(json.dumps(output, indent=2), encoding='utf-8')
    return 0
