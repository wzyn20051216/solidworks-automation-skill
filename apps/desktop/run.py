"""@brief CAD 自动化交付工作台桌面端入口。"""

from __future__ import annotations

import sys
from pathlib import Path


def main() -> int:
    """@brief 启动 PySide6 桌面应用。"""
    app_dir = Path(__file__).resolve().parent
    sys.path.insert(0, str(app_dir))

    try:
        from PySide6.QtWidgets import QApplication
    except ImportError:
        print("缺少 PySide6，请先执行: python -m pip install -r apps/desktop/requirements.txt")
        return 1

    from cad_workbench.app import MainWindow

    app = QApplication(sys.argv)
    app.setApplicationName("CAD 自动化交付工作台")
    app.setOrganizationName("solidworks-automation-skill")

    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
