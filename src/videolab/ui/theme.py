DARK_QSS = """
* { font-family: 'Segoe UI', 'Inter', sans-serif; font-size: 13px; color: #d7dae0; }
QMainWindow, QWidget { background: #1b1d23; }
QMenuBar, QMenu, QToolBar { background: #22252c; border: none; }
QMenu::item:selected, QMenuBar::item:selected { background: #3a6df0; }
QToolButton { padding: 6px 10px; border-radius: 6px; background: transparent; }
QToolButton:hover { background: #2f333d; }
QDockWidget::title { background: #22252c; padding: 6px; font-weight: 600; }
QListWidget, QTreeWidget, QPlainTextEdit { background: #16181d; border: 1px solid #2a2d35; border-radius: 6px; }
QListWidget::item:selected { background: #3a6df0; }
QPushButton { background: #2f333d; border: 1px solid #3a3f4b; padding: 6px 12px; border-radius: 6px; }
QPushButton:hover { background: #3a3f4b; } QPushButton:default, QPushButton#primary { background: #3a6df0; border-color: #3a6df0; }
QSpinBox, QDoubleSpinBox, QComboBox, QLineEdit { background: #16181d; border: 1px solid #2a2d35; border-radius: 5px; padding: 3px 6px; }
QProgressBar { background: #16181d; border: 1px solid #2a2d35; border-radius: 5px; text-align: center; height: 16px; }
QProgressBar::chunk { background: #3a6df0; border-radius: 4px; }
QStatusBar { background: #22252c; }
"""
