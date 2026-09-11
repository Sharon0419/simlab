import sys
from pathlib import Path

def main():
    if len(sys.argv) == 4 and sys.argv[1] == '--worker':
        from simlab.worker import main as worker
        return worker(sys.argv[2], sys.argv[3])
    if len(sys.argv) == 3 and sys.argv[1] == '--smoke':
        from simlab.smoke import run
        return run(sys.argv[2])
    from PySide6.QtGui import QFont
    from PySide6.QtWidgets import QApplication, QMessageBox
    from simlab.ui.window import MainWindow
    app = QApplication(sys.argv)
    app.setApplicationName('SimLab')
    app.setOrganizationName('SimLab')
    app.setFont(QFont('Microsoft YaHei UI', 10))
    window = MainWindow()
    if len(sys.argv) == 3 and sys.argv[1] == '--project':
        try:
            window.open_path(sys.argv[2])
        except Exception as error:
            QMessageBox.warning(window, '打开项目失败', str(error))
    else:
        window.nav.setCurrentRow(7)
    window.show()
    return app.exec()

if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except Exception:
        import traceback
        import os
        directory = Path(os.getenv('LOCALAPPDATA', str(Path.home()))) / 'SimLab'
        directory.mkdir(parents=True, exist_ok=True)
        (directory/'crash.log').write_text(traceback.format_exc(), encoding='utf-8')
        raise
