"""End-to-end desktop evidence for redundancy and workflow editing/results."""
import csv
import time
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from .project import export_package, import_package


def check_workflows(window, directory, failures):
    window.new_workflow_demo()
    assert not failures, failures
    window.editor.select_table('SimLabRedundancy')
    assert window.editor.grid.rowCount() == 2
    QTest.qWait(100)
    window.grab().save(str(directory/'30-redundancy-input.png'))
    window.editor.select_table('SimLabWorkflowStep')
    assert window.editor.grid.rowCount() > 10
    assert window.editor.successors_button.isVisible()
    assert window.editor.info.isHidden()
    QTest.qWait(100)
    window.grab().save(str(directory/'31-workflow-input.png'))
    assert window.save()
    window.nav.setCurrentRow(2)
    window.repetitions.setValue(3)
    QTest.mouseClick(window.run_button, Qt.LeftButton)
    deadline = time.monotonic()+120
    while window.process is not None and time.monotonic() < deadline:
        QTest.qWait(50)
    assert window.process is None and not failures, failures
    run = window.project['runs'][-1]
    assert run['status'] == 'completed', run
    result = run['result']
    assert len(result['replication_results']) == 3
    for rep in result['replication_results']:
        assert rep['parts']['initial'] == rep['parts']['final']
        assert rep['workflows']['steps']
        assert {a['activity'] for a in rep['workflows']['activities']} >= {'PREPARATION','CALENDAR','INSPECTION','MAINTENANCE'}
    window.nav.setCurrentRow(3)
    window.result_tabs.setCurrentWidget(window.workflow_page)
    window.workflow_page.selector.setCurrentIndex(window.workflow_page.selector.findData('steps'))
    assert window.workflow_page.table.rowCount() == len(result['workflows']['steps'])
    window.workflow_page.export_path(directory/'workflow-steps.csv')
    with (directory/'workflow-steps.csv').open(encoding='utf-8-sig', newline='') as handle:
        rows = list(csv.DictReader(handle))
    assert {r['replication'] for r in rows} == {'1','2','3'}
    assert len(rows) == sum(len(r['workflows']['steps']) for r in result['replication_results'])
    QTest.qWait(100)
    window.grab().save(str(directory/'32-workflow-results.png'))
    export_package(window.project, directory/'workflows.simproj')
    assert import_package(directory/'workflows.simproj')['runs'][-1]['result'] == result
    return ['two-level redundancy input', 'custom workflow input', 'dependency view available',
            'workflow worker', 'all support activity workflows', 'workflow physical conservation',
            'workflow result page', 'workflow all-rep CSV', 'format12 workflow roundtrip']
