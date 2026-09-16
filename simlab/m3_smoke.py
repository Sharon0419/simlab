"""M3 desktop checks shared by source and packaged application."""
import csv
import time

from PySide6.QtCore import Qt, QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialogButtonBox, QTextBrowser

from .project import export_package, import_package


def check_m3(window, directory, failures):
    from .sample import demo_project
    legacy_path = directory/'migration-source.sqlite'
    window.adopt_project(demo_project(), legacy_path)
    before = legacy_path.read_bytes()
    source_id = window.project['id']
    preview_seen = []
    def finish_preview(accept):
        dialog = QApplication.activeModalWidget()
        preview_seen.append(dialog.findChild(QTextBrowser).toPlainText())
        if accept:
            dialog.grab().save(str(directory/'24-m3-migration-preview.png'))
        buttons = dialog.findChild(QDialogButtonBox)
        QTest.mouseClick(buttons.button(QDialogButtonBox.Ok if accept else QDialogButtonBox.Cancel), Qt.LeftButton)
    QTimer.singleShot(150, lambda: finish_preview(False))
    window.migrate_m3()
    assert window.project['id'] == source_id and legacy_path.read_bytes() == before
    QTimer.singleShot(150, lambda: finish_preview(True))
    window.migrate_m3()
    assert window.project['id'] != source_id and legacy_path.read_bytes() == before
    assert len(preview_seen) == 2 and all('SURPT' in text and 'TARGET_QTY' in text for text in preview_seen)
    assert not window.project['runs']
    window.new_m3_demo()
    assert not failures, failures
    assert window.project['tables']['SimLabExecution'] == [{'MODE': 'M3'}]
    window.editor.select_table('SimLabSupplyPolicy')
    assert window.editor.grid.rowCount() == 2
    assert window.save()
    window.grab().save(str(directory/'21-m3-input.png'))
    window.nav.setCurrentRow(2)
    window.repetitions.setValue(3)
    QTest.mouseClick(window.run_button, Qt.LeftButton)
    deadline = time.monotonic() + 120
    while window.process is not None and time.monotonic() < deadline:
        QTest.qWait(50)
    assert window.process is None and not failures, failures
    run = window.project['runs'][-1]
    assert run['status'] == 'completed', run
    result = run['result']
    assert len(result['replication_results']) == 3
    for rep in result['replication_results']:
        assert rep['parts']['initial'] == rep['parts']['final']
        assert rep['supply']['orders'] and rep['supply']['shipments']
        assert any(job['kind'] == 'PREVENTIVE' for job in rep['service']['jobs'])
    window.nav.setCurrentRow(3)
    window.result_tabs.setCurrentWidget(window.m3_supply_page)
    assert window.m3_supply_page.table.rowCount() > 0
    window.m3_supply_page.export_path(directory/'m3-orders.csv')
    with (directory/'m3-orders.csv').open(encoding='utf-8-sig', newline='') as handle:
        rows = list(csv.DictReader(handle))
    assert {row['replication'] for row in rows} == {'1', '2', '3'}
    QTest.qWait(100)
    window.grab().save(str(directory/'22-m3-supply.png'))
    window.result_tabs.setCurrentWidget(window.m3_service_page)
    assert window.m3_service_page.table.rowCount() > 0
    window.m3_service_page.export_path(directory/'m3-jobs.csv')
    QTest.qWait(100)
    window.grab().save(str(directory/'23-m3-service.png'))
    export_package(window.project, directory/'m3.simproj')
    restored = import_package(directory/'m3.simproj')
    assert restored['runs'][-1]['result'] == result
    return ['M3 input and example', 'M3 worker', 'M3 supply and service results',
            'M3 all-replication CSV', 'M3 physical conservation', 'format10 M3 roundtrip',
            'M3 migration preview cancel', 'M3 migration independent copy']
