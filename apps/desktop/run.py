"""@brief CAD otomasyonu teslimat çalışma tezgâhı masaüstü girişi."""

from __future__ import annotations

import sys
from pathlib import Path


def main() -> int:
    """@brief PySide6 masaüstü uygulamasını başlatır."""
    app_dir = Path(__file__).resolve().parent
    sys.path.insert(0, str(app_dir))

    try:
        from PySide6.QtWidgets import QApplication
    except ImportError:
        print("PySide6 eksik; önce şunu çalıştırın: python -m pip install -r apps/desktop/requirements.txt")
        return 1

    from cad_workbench.app import MainWindow

    app = QApplication(sys.argv)
    app.setApplicationName("CAD Otomasyonu Teslimat Çalışma Tezgâhı")
    app.setOrganizationName("solidworks-automation-skill")

    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
