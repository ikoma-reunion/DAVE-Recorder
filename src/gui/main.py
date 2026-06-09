import sys
import logging
from PySide6.QtWidgets import QApplication
from core.settings import SettingsManager
from gui.main_window import MainWindow

def setup_logging():
    settings = SettingsManager.get_instance()
    level_str = str(settings.get("log_level", "INFO")).upper()
    numeric_level = getattr(logging, level_str, logging.INFO)
    logging.basicConfig(level=numeric_level, format='%(asctime)s [%(levelname)s] %(name)s: %(message)s')

def main():
    setup_logging()
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()