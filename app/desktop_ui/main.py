from __future__ import annotations

from pathlib import Path

from app.desktop_ui.qt import PYSIDE_IMPORT_ERROR, QApplication, QIcon
from app.desktop_ui.window import VoiceDesktopWindow


def run() -> None:
    if PYSIDE_IMPORT_ERROR is not None:
        raise SystemExit(
            "PySide6 is not installed in the current environment. "
            "Install project dependencies first: `pip install -e .`."
        ) from PYSIDE_IMPORT_ERROR

    app = QApplication.instance() or QApplication([])
    app.setApplicationName("iVoice")
    app.setApplicationDisplayName("iVoice")
    app.setDesktopFileName("ivoice")
    app.setOrganizationName("iVoice")
    icon_path = Path(__file__).resolve().parents[2] / "assets" / "icons" / "logo.ico"
    if icon_path.exists():
        app.setWindowIcon(QIcon(str(icon_path)))
    window = VoiceDesktopWindow()
    if icon_path.exists():
        window.setWindowIcon(QIcon(str(icon_path)))
    window.show()
    app.exec()


if __name__ == "__main__":
    run()
