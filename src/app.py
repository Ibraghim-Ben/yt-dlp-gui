import sys
import os
import traceback
import ctypes
import pathlib
from PyQt6.QtWidgets import QApplication, QMessageBox
from PyQt6.QtGui import QFont, QIcon

from .utils.config import Config
from .utils.theme import load_theme
from .core.queue_manager import QueueManager
from .core.ffmpeg_utils import find_ffmpeg, setup_bundled_binaries
from .ui.main_window import MainWindow


def global_exception_handler(exctype, value, tb):
    if issubclass(exctype, KeyboardInterrupt):
        sys.__excepthook__(exctype, value, tb)
        return
    tb_str = "".join(traceback.format_exception(exctype, value, tb))
    msg_box = QMessageBox()
    msg_box.setIcon(QMessageBox.Icon.Critical)
    msg_box.setWindowTitle("Critical Error")
    msg_box.setText(f"An unexpected critical error occurred:\n{value}")
    msg_box.setDetailedText(tb_str)
    msg_box.exec()
    sys.__excepthook__(exctype, value, tb)


def _get_icon_path() -> str:
    base_dirs = [
        pathlib.Path(__file__).parent / "resources",
        pathlib.Path(getattr(sys, "_MEIPASS", ".")) / "src" / "resources",
        pathlib.Path(getattr(sys, "_MEIPASS", ".")) / "resources",
    ]
    for b in base_dirs:
        ico = b / "app_icon.ico"
        if ico.exists():
            return str(ico)
        png = b / "app_icon.png"
        if png.exists():
            return str(png)
    return ""

def run() -> int:
    sys.excepthook = global_exception_handler
    setup_bundled_binaries()
    
    if os.name == "nt":
        try:
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("scorionix.ytdlpgui.app.1")
        except Exception:
            pass

    app = QApplication(sys.argv)
    app.setApplicationName("yt-dlp GUI")
    app.setApplicationVersion("0.1.0")
    app.setStyle("Fusion")

    icon_path = _get_icon_path()
    if icon_path:
        app.setWindowIcon(QIcon(icon_path))

    font = QFont()
    font.setFamilies(["Segoe UI", "SF Pro Text", "Helvetica Neue", "Ubuntu", "sans-serif"])
    font.setPointSize(10)
    font.setHintingPreference(QFont.HintingPreference.PreferDefaultHinting)
    app.setFont(font)

    config = Config.load()
    if config.corrupted_backup_path:
        QMessageBox.warning(
            None,
            "Configuration Corrupted",
            f"The configuration file was corrupted and has been reset to defaults.\n\n"
            f"A backup of the corrupted file was saved to:\n{config.corrupted_backup_path}"
        )

    if not config.ffmpeg_path or not os.path.isfile(config.ffmpeg_path):
        found = find_ffmpeg()
        if found:
            config.ffmpeg_path = found

    load_theme(app, config.theme)

    queue = QueueManager(config)
    window = MainWindow(config, queue)
    window.show()

    return app.exec()