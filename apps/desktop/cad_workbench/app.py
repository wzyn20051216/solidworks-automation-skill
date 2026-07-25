"""@brief CAD 自动化交付工作台主界面。"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from .core import create_project, default_output_root, ensure_project_tree, read_json, write_json
from .mock_runner import run_mock
from .style import APP_STYLE


class MainWindow(QMainWindow):
    """@brief 桌面软件主窗口。"""

    def __init__(self) -> None:
        super().__init__()
        self.project_dir: Path | None = None
        self.setWindowTitle("CAD 自动化交付工作台")
        self.resize(1320, 820)
        self.setMinimumSize(1120, 720)
        self.setStyleSheet(APP_STYLE)
        self._build_ui()
        self._load_default_values()

    def _build_ui(self) -> None:
        root = QWidget()
        root_layout = QHBoxLayout(root)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        root_layout.addWidget(self._build_sidebar())

        body = QWidget()
        body_layout = QHBoxLayout(body)
        body_layout.setContentsMargins(24, 22, 24, 22)
        body_layout.setSpacing(18)

        main_column = QWidget()
        main_layout = QVBoxLayout(main_column)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(14)

        title_row = QHBoxLayout()
        title_box = QVBoxLayout()
        self.title = QLabel("3D 打印外壳自动交付")
        self.title.setObjectName("PageTitle")
        self.subtitle = QLabel("先把项目、参数、复核和交付目录跑顺，真实 CAD 引擎后续接入。")
        self.subtitle.setObjectName("Muted")
        title_box.addWidget(self.title)
        title_box.addWidget(self.subtitle)
        title_row.addLayout(title_box)
        title_row.addStretch()

        self.save_button = QPushButton("保存参数")
        self.save_button.setObjectName("QuietButton")
        self.save_button.clicked.connect(self.save_project)
        self.run_button = QPushButton("Mock 执行")
        self.run_button.setObjectName("PrimaryButton")
        self.run_button.clicked.connect(self.run_mock_pipeline)
        title_row.addWidget(self.save_button)
        title_row.addWidget(self.run_button)

        main_layout.addLayout(title_row)
        main_layout.addWidget(self._build_tabs(), 1)

        body_layout.addWidget(main_column, 1)
        body_layout.addWidget(self._build_status_panel())
        root_layout.addWidget(body, 1)

        self.setCentralWidget(root)

    def _build_sidebar(self) -> QWidget:
        sidebar = QFrame()
        sidebar.setObjectName("Sidebar")
        sidebar.setFixedWidth(228)
        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(18, 22, 18, 18)
        layout.setSpacing(10)

        brand = QLabel("CAD 工作台")
        brand.setObjectName("BrandTitle")
        sub = QLabel("SolidWorks / AutoCAD Skill")
        sub.setObjectName("BrandSub")
        layout.addWidget(brand)
        layout.addWidget(sub)
        layout.addSpacing(18)

        for text in ["项目", "外壳参数", "孔槽与螺丝柱", "执行与复核", "输出交付", "Skills 管理"]:
            button = QPushButton(text)
            button.setObjectName("NavButton")
            button.setCursor(Qt.PointingHandCursor)
            layout.addWidget(button)

        layout.addStretch()
        foot = QLabel("本地运行 · 数据不出电脑")
        foot.setObjectName("BrandSub")
        layout.addWidget(foot)
        return sidebar

    def _panel(self, title: str) -> tuple[QFrame, QVBoxLayout]:
        panel = QFrame()
        panel.setObjectName("Panel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(18, 16, 18, 18)
        layout.setSpacing(12)
        label = QLabel(title)
        label.setObjectName("SectionTitle")
        layout.addWidget(label)
        return panel, layout

    def _build_tabs(self) -> QTabWidget:
        tabs = QTabWidget()
        tabs.addTab(self._build_project_tab(), "项目")
        tabs.addTab(self._build_shell_tab(), "外壳")
        tabs.addTab(self._build_feature_tab(), "孔槽")
        tabs.addTab(self._build_execution_tab(), "执行")
        return tabs

    def _build_project_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)

        panel, form_host = self._panel("项目设置")
        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignRight)
        form.setFormAlignment(Qt.AlignTop)
        form.setHorizontalSpacing(16)
        form.setVerticalSpacing(12)

        self.project_name = QLineEdit()
        self.project_name.setPlaceholderText("例如: ai_cpu_cooling_shell")
        self.output_root = QLineEdit()
        browse = QPushButton("选择目录")
        browse.setObjectName("QuietButton")
        browse.clicked.connect(self.pick_output_root)
        output_row = QHBoxLayout()
        output_row.addWidget(self.output_root, 1)
        output_row.addWidget(browse)

        self.need_dwg = QCheckBox("DWG")
        self.need_dwg.setChecked(True)
        self.need_dxf = QCheckBox("DXF")
        self.need_dxf.setChecked(True)
        self.need_pdf = QCheckBox("PDF")
        self.need_pdf.setChecked(True)
        self.need_stl = QCheckBox("STL")
        self.need_stl.setChecked(True)
        self.need_step = QCheckBox("STEP")
        self.need_step.setChecked(True)
        exports = QHBoxLayout()
        for box in [self.need_dwg, self.need_dxf, self.need_pdf, self.need_stl, self.need_step]:
            exports.addWidget(box)
        exports.addStretch()

        self.standard = QComboBox()
        self.standard.addItems(["GB/T 风格", "企业模板优先"])
        self.material = QLineEdit("PLA/PETG")

        form.addRow("项目名称", self.project_name)
        form.addRow("输出根目录", output_row)
        form.addRow("图纸风格", self.standard)
        form.addRow("材料/工艺假设", self.material)
        form.addRow("交付格式", exports)
        form_host.addLayout(form)
        layout.addWidget(panel)

        note_panel, note_layout = self._panel("设计原则")
        note = QLabel("所有孔、槽、接口和螺丝柱都必须同时填写规格、数量和定位尺寸；图纸阶段不允许用长引线代替关键尺寸链。")
        note.setWordWrap(True)
        note.setObjectName("Muted")
        note_layout.addWidget(note)
        layout.addWidget(note_panel)
        layout.addStretch()
        return page

    def _spin(self, value: float, minimum: float = 0.0, maximum: float = 10000.0, suffix: str = " mm") -> QDoubleSpinBox:
        spin = QDoubleSpinBox()
        spin.setDecimals(2)
        spin.setRange(minimum, maximum)
        spin.setValue(value)
        spin.setSuffix(suffix)
        spin.setSingleStep(0.1)
        return spin

    def _build_shell_tab(self) -> QWidget:
        page = QWidget()
        layout = QGridLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)

        shell_panel, shell_layout = self._panel("外形尺寸")
        shell_form = QFormLayout()
        shell_form.setHorizontalSpacing(16)
        shell_form.setVerticalSpacing(10)
        self.outer_length = self._spin(120)
        self.outer_width = self._spin(80)
        self.outer_height = self._spin(35)
        self.wall_thickness = self._spin(1.6, 0.1)
        self.bottom_thickness = self._spin(2.0, 0.1)
        self.corner_radius = self._spin(4.0)
        self.edge_chamfer = self._spin(0.5)
        self.open_direction = QComboBox()
        self.open_direction.addItems(["top", "bottom", "side"])
        for label, widget in [
            ("长度", self.outer_length),
            ("宽度", self.outer_width),
            ("高度", self.outer_height),
            ("壁厚", self.wall_thickness),
            ("底厚", self.bottom_thickness),
            ("圆角", self.corner_radius),
            ("倒角", self.edge_chamfer),
            ("开口方向", self.open_direction),
        ]:
            shell_form.addRow(label, widget)
        shell_layout.addLayout(shell_form)

        print_panel, print_layout = self._panel("3D 打印参数")
        print_form = QFormLayout()
        print_form.setHorizontalSpacing(16)
        print_form.setVerticalSpacing(10)
        self.print_process = QComboBox()
        self.print_process.addItems(["FDM", "SLA", "SLS"])
        self.nozzle_diameter = self._spin(0.4, 0.1, 2.0)
        self.hole_compensation = self._spin(0.2, 0, 2)
        self.fit_clearance = self._spin(0.3, 0, 3)
        self.min_wall_warning = self._spin(1.2, 0.1, 5)
        for label, widget in [
            ("打印工艺", self.print_process),
            ("喷嘴直径", self.nozzle_diameter),
            ("孔径放量", self.hole_compensation),
            ("装配间隙", self.fit_clearance),
            ("壁厚警戒", self.min_wall_warning),
        ]:
            print_form.addRow(label, widget)
        print_layout.addLayout(print_form)

        layout.addWidget(shell_panel, 0, 0)
        layout.addWidget(print_panel, 0, 1)
        layout.setColumnStretch(0, 1)
        layout.setColumnStretch(1, 1)
        return page

    def _table(self, columns: list[str]) -> QTableWidget:
        table = QTableWidget(0, len(columns))
        table.setHorizontalHeaderLabels(columns)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        table.verticalHeader().setVisible(False)
        table.setSelectionBehavior(QAbstractItemView.SelectRows)
        table.setAlternatingRowColors(True)
        table.setMinimumHeight(150)
        return table

    def _build_feature_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)

        holes_panel, holes_layout = self._panel("孔")
        self.holes_table = self._table(["id", "名称", "类型", "面", "直径", "数量", "X基准", "Y基准", "X定位", "Y定位", "X节距", "Y节距", "通孔"])
        holes_layout.addWidget(self.holes_table)
        holes_layout.addLayout(self._table_buttons(self.holes_table, "hole"))

        cutouts_panel, cutouts_layout = self._panel("接口开孔")
        self.cutouts_table = self._table(["id", "类型", "面", "宽", "高", "直径", "圆角", "X定位", "Y定位", "数量", "间隙"])
        cutouts_layout.addWidget(self.cutouts_table)
        cutouts_layout.addLayout(self._table_buttons(self.cutouts_table, "cutout"))

        bosses_panel, bosses_layout = self._panel("螺丝柱")
        self.bosses_table = self._table(["id", "螺丝", "外径", "孔径", "高度", "面", "X定位", "Y定位", "数量", "加强筋"])
        bosses_layout.addWidget(self.bosses_table)
        bosses_layout.addLayout(self._table_buttons(self.bosses_table, "boss"))

        layout.addWidget(holes_panel)
        layout.addWidget(cutouts_panel)
        layout.addWidget(bosses_panel)
        return page

    def _table_buttons(self, table: QTableWidget, kind: str) -> QHBoxLayout:
        row = QHBoxLayout()
        add = QPushButton("添加")
        add.setObjectName("QuietButton")
        add.clicked.connect(lambda: self.add_default_row(table, kind))
        remove = QPushButton("删除选中")
        remove.setObjectName("QuietButton")
        remove.clicked.connect(lambda: self.remove_selected_rows(table))
        row.addWidget(add)
        row.addWidget(remove)
        row.addStretch()
        return row

    def _build_execution_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)
        panel, panel_layout = self._panel("执行日志")
        self.log_box = QTextEdit()
        self.log_box.setObjectName("LogBox")
        self.log_box.setReadOnly(True)
        panel_layout.addWidget(self.log_box, 1)
        layout.addWidget(panel, 1)
        return page

    def _build_status_panel(self) -> QWidget:
        panel = QFrame()
        panel.setObjectName("StatusPanel")
        panel.setFixedWidth(330)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(14)

        title = QLabel("复核状态")
        title.setObjectName("SectionTitle")
        layout.addWidget(title)
        self.overall_status = QLabel("尚未执行")
        self.overall_status.setObjectName("StatusWarn")
        layout.addWidget(self.overall_status)

        self.status_labels: dict[str, QLabel] = {}
        for key, label in [("model", "模型"), ("drawing", "图纸"), ("printing", "打印"), ("package", "交付")]:
            item = QLabel(f"{label}: 等待")
            item.setObjectName("Muted")
            self.status_labels[key] = item
            layout.addWidget(item)

        layout.addSpacing(8)
        output_title = QLabel("输出")
        output_title.setObjectName("SectionTitle")
        layout.addWidget(output_title)
        self.project_path_label = QLabel("未创建项目")
        self.project_path_label.setObjectName("Muted")
        self.project_path_label.setWordWrap(True)
        layout.addWidget(self.project_path_label)

        open_dir = QPushButton("打开输出目录")
        open_dir.setObjectName("QuietButton")
        open_dir.clicked.connect(self.open_project_dir)
        layout.addWidget(open_dir)
        open_review = QPushButton("打开 final_review.json")
        open_review.setObjectName("QuietButton")
        open_review.clicked.connect(self.open_final_review)
        layout.addWidget(open_review)
        layout.addStretch()
        return panel

    def _load_default_values(self) -> None:
        self.project_name.setText("ai_cpu_cooling_shell")
        self.output_root.setText(str(default_output_root()))
        self.add_default_row(self.holes_table, "hole")
        self.add_default_row(self.cutouts_table, "cutout")
        self.add_default_row(self.bosses_table, "boss")
        self.append_log("原型已就绪。先保存参数，再执行 mock 流水线。")

    def pick_output_root(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "选择输出根目录", self.output_root.text())
        if folder:
            self.output_root.setText(folder)

    def append_log(self, message: str) -> None:
        self.log_box.append(message)
        self.log_box.verticalScrollBar().setValue(self.log_box.verticalScrollBar().maximum())
        QApplication.processEvents()

    def _set_table_row(self, table: QTableWidget, values: list[Any]) -> None:
        row = table.rowCount()
        table.insertRow(row)
        for column, value in enumerate(values):
            table.setItem(row, column, QTableWidgetItem(str(value)))

    def add_default_row(self, table: QTableWidget, kind: str) -> None:
        if kind == "hole":
            self._set_table_row(table, ["H1", "安装孔", "round", "bottom", "3.4", "4", "left", "bottom", "10", "10", "100", "60", "true"])
        elif kind == "cutout":
            self._set_table_row(table, ["I1", "USB-C", "front", "10", "4", "0", "1", "60", "15", "1", "0.3"])
        else:
            self._set_table_row(table, ["B1", "M3", "7", "2.8", "8", "bottom", "10", "10", "4", "true"])

    def remove_selected_rows(self, table: QTableWidget) -> None:
        rows = sorted({index.row() for index in table.selectedIndexes()}, reverse=True)
        for row in rows:
            table.removeRow(row)

    def _cell(self, table: QTableWidget, row: int, column: int) -> str:
        item = table.item(row, column)
        return item.text().strip() if item else ""

    def _float_cell(self, table: QTableWidget, row: int, column: int) -> float:
        text = self._cell(table, row, column)
        return float(text) if text else 0.0

    def _int_cell(self, table: QTableWidget, row: int, column: int) -> int:
        text = self._cell(table, row, column)
        return int(float(text)) if text else 0

    def _bool_cell(self, table: QTableWidget, row: int, column: int) -> bool:
        return self._cell(table, row, column).lower() in {"true", "1", "yes", "是"}

    def collect_parameters(self) -> dict[str, Any]:
        holes = []
        for row in range(self.holes_table.rowCount()):
            holes.append(
                {
                    "id": self._cell(self.holes_table, row, 0),
                    "name": self._cell(self.holes_table, row, 1),
                    "hole_type": self._cell(self.holes_table, row, 2),
                    "face": self._cell(self.holes_table, row, 3),
                    "diameter": self._float_cell(self.holes_table, row, 4),
                    "quantity": self._int_cell(self.holes_table, row, 5),
                    "datum_x": self._cell(self.holes_table, row, 6),
                    "datum_y": self._cell(self.holes_table, row, 7),
                    "center_x": self._float_cell(self.holes_table, row, 8),
                    "center_y": self._float_cell(self.holes_table, row, 9),
                    "pitch_x": self._float_cell(self.holes_table, row, 10),
                    "pitch_y": self._float_cell(self.holes_table, row, 11),
                    "through": self._bool_cell(self.holes_table, row, 12),
                    "note": "",
                }
            )

        cutouts = []
        for row in range(self.cutouts_table.rowCount()):
            cutouts.append(
                {
                    "id": self._cell(self.cutouts_table, row, 0),
                    "interface_type": self._cell(self.cutouts_table, row, 1),
                    "face": self._cell(self.cutouts_table, row, 2),
                    "cutout_width": self._float_cell(self.cutouts_table, row, 3),
                    "cutout_height": self._float_cell(self.cutouts_table, row, 4),
                    "cutout_diameter": self._float_cell(self.cutouts_table, row, 5),
                    "corner_radius": self._float_cell(self.cutouts_table, row, 6),
                    "center_x": self._float_cell(self.cutouts_table, row, 7),
                    "center_y": self._float_cell(self.cutouts_table, row, 8),
                    "quantity": self._int_cell(self.cutouts_table, row, 9),
                    "clearance": self._float_cell(self.cutouts_table, row, 10),
                }
            )

        bosses = []
        for row in range(self.bosses_table.rowCount()):
            bosses.append(
                {
                    "id": self._cell(self.bosses_table, row, 0),
                    "screw_size": self._cell(self.bosses_table, row, 1),
                    "boss_outer_diameter": self._float_cell(self.bosses_table, row, 2),
                    "hole_diameter": self._float_cell(self.bosses_table, row, 3),
                    "boss_height": self._float_cell(self.bosses_table, row, 4),
                    "face": self._cell(self.bosses_table, row, 5),
                    "center_x": self._float_cell(self.bosses_table, row, 6),
                    "center_y": self._float_cell(self.bosses_table, row, 7),
                    "quantity": self._int_cell(self.bosses_table, row, 8),
                    "rib_enabled": self._bool_cell(self.bosses_table, row, 9),
                }
            )

        exports = []
        if self.need_dwg.isChecked():
            exports.append("dwg")
        if self.need_dxf.isChecked():
            exports.append("dxf")
        if self.need_pdf.isChecked():
            exports.append("pdf")
        if self.need_stl.isChecked():
            exports.append("stl")
        if self.need_step.isChecked():
            exports.append("step")

        return {
            "schema_version": "0.1",
            "units": "mm",
            "shell": {
                "outer_length": self.outer_length.value(),
                "outer_width": self.outer_width.value(),
                "outer_height": self.outer_height.value(),
                "wall_thickness": self.wall_thickness.value(),
                "bottom_thickness": self.bottom_thickness.value(),
                "corner_radius": self.corner_radius.value(),
                "edge_chamfer": self.edge_chamfer.value(),
                "open_direction": self.open_direction.currentText(),
            },
            "printing": {
                "process": self.print_process.currentText(),
                "nozzle_diameter": self.nozzle_diameter.value(),
                "hole_compensation": self.hole_compensation.value(),
                "fit_clearance": self.fit_clearance.value(),
                "min_wall_warning": self.min_wall_warning.value(),
            },
            "features": {"holes": holes, "cutouts": cutouts, "bosses": bosses, "vents": []},
            "drawing": {
                "paper_size": "A3",
                "scale": "1:1",
                "title": "3D打印外壳",
                "material": self.material.text().strip() or "PLA/PETG",
                "projection": "first_angle",
                "required_exports": exports,
            },
        }

    def save_project(self) -> None:
        try:
            name = self.project_name.text().strip()
            if not name:
                raise ValueError("项目名称不能为空")
            output_root = Path(self.output_root.text().strip()).expanduser()
            if self.project_dir is None:
                self.project_dir, _, _ = create_project(name, output_root)
            else:
                ensure_project_tree(self.project_dir)
            parameters = self.collect_parameters()
            write_json(self.project_dir / "parameters.json", parameters)
            project = read_json(self.project_dir / "project.json")
            project["project_name"] = name
            project["status"] = "ready"
            project["drawing_standard"] = "GB_T_style" if self.standard.currentIndex() == 0 else "enterprise_template_first"
            write_json(self.project_dir / "project.json", project)
            self.project_path_label.setText(str(self.project_dir))
            self.append_log(f"已保存参数: {self.project_dir / 'parameters.json'}")
        except Exception as exc:
            QMessageBox.critical(self, "保存失败", str(exc))

    def run_mock_pipeline(self) -> None:
        if self.project_dir is None:
            self.save_project()
        if self.project_dir is None:
            return
        try:
            self.save_project()
            review = run_mock(self.project_dir, self.append_log)
            self.update_status(review)
            self.append_log(f"最终复核: {review['overall_status']}")
        except Exception as exc:
            QMessageBox.critical(self, "执行失败", str(exc))

    def update_status(self, review: dict[str, Any]) -> None:
        status = review.get("overall_status", "unknown")
        if status == "fail":
            self.overall_status.setText("不可交付")
            self.overall_status.setObjectName("StatusBad")
        elif status == "warning":
            self.overall_status.setText("需人工确认")
            self.overall_status.setObjectName("StatusWarn")
        else:
            self.overall_status.setText("可交付")
            self.overall_status.setObjectName("StatusGood")
        self.overall_status.style().unpolish(self.overall_status)
        self.overall_status.style().polish(self.overall_status)

        checks = review.get("checks", [])
        targets = {"model": "通过", "drawing": "通过", "printing": "通过", "package": "通过"}
        for check in checks:
            if check.get("status") == "fail":
                targets[check.get("target", "package")] = "失败"
            elif check.get("status") == "warning" and targets.get(check.get("target")) != "失败":
                targets[check.get("target", "package")] = "提醒"
        labels = {"model": "模型", "drawing": "图纸", "printing": "打印", "package": "交付"}
        for key, label in labels.items():
            self.status_labels[key].setText(f"{label}: {targets.get(key, '等待')}")

    def open_project_dir(self) -> None:
        if not self.project_dir:
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.project_dir)))

    def open_final_review(self) -> None:
        if not self.project_dir:
            return
        review = self.project_dir / "reviews" / "final_review.json"
        if not review.exists():
            QMessageBox.information(self, "还没有复核报告", "请先执行 mock 流水线。")
            return
        if os.name == "nt":
            subprocess.Popen(["notepad.exe", str(review)])
        else:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(review)))
