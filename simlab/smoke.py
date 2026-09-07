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
    output = {'status': 'passed', 'checks': ['field editor', 'save/reopen', 'CSV export',
               'worker cancellation', 'worker run', 'result persistence', 'package export/import', 'branch provenance'],
              'availability': last['result']['availability'], 'replications': last['result']['replications']}
    window.close()
    app.processEvents()
    (directory/'smoke-result.json').write_text(json.dumps(output, indent=2), encoding='utf-8')
    return 0
