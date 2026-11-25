import sys

from PySide6.QtWidgets import QApplication

from .i18n import set_language
from .ui.main_window import MainWindow
from .ui.theme import DARK_QSS


def main() -> int:
    set_language("tr")
    app = QApplication(sys.argv)
    app.setStyleSheet(DARK_QSS)
    w = MainWindow(); w.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
