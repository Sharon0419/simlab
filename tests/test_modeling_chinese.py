import copy
import csv
import re
import pytest
from PySide6.QtWidgets import QApplication, QStyleOptionViewItem
from simlab.compiler import SUPPORTED, compile_model
from simlab.project import save_project, load_project
from simlab.sample import demo_project
from simlab.schema import TABLES
from simlab.ui.modeling import ModelEditor


@pytest.fixture(scope='module')
def app():
    return QApplication.instance() or QApplication(['test', '-platform', 'offscreen'])


def test_browsing_chinese_fields_preserves_model(app):
    project = demo_project()
    before = copy.deepcopy(project)
    editor = ModelEditor()
    editor.set_project(project)
    assert set(editor.nodes) == set(SUPPORTED)
    for name, node in editor.nodes.items():
        assert not re.search('[A-Za-z]', node.text(0))
        editor.select_table(name)
        for column, field in enumerate(TABLES[name]):
            assert not re.search('[A-Za-z]', editor.grid.horizontalHeaderItem(column).text())
            editor.show_field(field)
            assert not re.search('[A-Za-z]', editor.info.toPlainText())
    editor.search.setText('每天首波')
    assert not editor.nodes['SimLabFlightRule'].isHidden()
    assert editor.nodes['Item'].isHidden()
    assert project == before


def test_chinese_option_edit_save_and_csv_keep_codes(app, tmp_path):
    project = demo_project()
    editor = ModelEditor()
    editor.set_project(project)
    editor.select_table('Control')
    column = next(i for i, f in enumerate(TABLES['Control']) if f['id'] == 'ENLOG')
    index = editor.grid.model().index(0, column)
    delegate = editor.grid.itemDelegate()
    widget = delegate.createEditor(editor.grid, QStyleOptionViewItem(), index)
    delegate.setEditorData(widget, index)
    widget.setCurrentText('是')
    delegate.setModelData(widget, editor.grid.model(), index)
    assert project['tables']['Control'][0]['ENLOG'] == 'Y'
    option = QStyleOptionViewItem()
    delegate.initStyleOption(option, index)
    assert option.text == '是'
    path = tmp_path/'project.sqlite'
    save_project(project, path)
    assert load_project(path)['tables']['Control'][0]['ENLOG'] == 'Y'
    editor.export_csv_path(tmp_path/'Control.csv')
    with (tmp_path/'Control.csv').open(encoding='utf-8-sig') as file:
        assert list(csv.DictReader(file))[0]['ENLOG'] == 'Y'
    editor.grid.setCurrentCell(0, column)
    editor.paste('否')
    assert project['tables']['Control'][0]['ENLOG'] == 'N'
    compile_model(project['tables'])
    # A user-defined identifier resembling an enum must remain an identifier.
    editor.select_table('Item')
    editor.grid.item(0, 0).setText('Y')
    option = QStyleOptionViewItem()
    delegate.initStyleOption(option, editor.grid.model().index(0, 0))
    assert option.text == 'Y'
