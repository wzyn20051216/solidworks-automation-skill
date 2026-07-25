"""@brief 桌面端视觉样式。"""

APP_STYLE = """
QMainWindow {
  background: #f4f6f3;
}
QWidget {
  color: #1f2a2e;
  font-family: "Microsoft YaHei UI", "Microsoft YaHei", "Segoe UI";
  font-size: 13px;
}
QFrame#Sidebar {
  background: #172125;
  border: none;
}
QLabel#BrandTitle {
  color: #f4f1e8;
  font-size: 18px;
  font-weight: 700;
}
QLabel#BrandSub {
  color: #aab8b2;
  font-size: 11px;
}
QPushButton#NavButton {
  color: #c8d2ce;
  background: transparent;
  border: 1px solid transparent;
  border-radius: 6px;
  padding: 10px 12px;
  text-align: left;
}
QPushButton#NavButton:hover {
  background: #223136;
  color: #ffffff;
}
QPushButton#PrimaryButton {
  color: #ffffff;
  background: #315f72;
  border: 1px solid #315f72;
  border-radius: 6px;
  padding: 9px 14px;
  font-weight: 700;
}
QPushButton#PrimaryButton:hover {
  background: #274f60;
}
QPushButton#QuietButton {
  color: #243239;
  background: #ffffff;
  border: 1px solid #cbd5d1;
  border-radius: 6px;
  padding: 8px 12px;
}
QPushButton#QuietButton:hover {
  border-color: #6f8f9b;
  background: #f7faf8;
}
QLabel#PageTitle {
  font-size: 24px;
  font-weight: 800;
  color: #172125;
}
QLabel#SectionTitle {
  font-size: 15px;
  font-weight: 800;
  color: #172125;
}
QLabel#Muted {
  color: #607079;
}
QFrame#Panel {
  background: #ffffff;
  border: 1px solid #d9e0dc;
  border-radius: 8px;
}
QFrame#StatusPanel {
  background: #fbfcfa;
  border: 1px solid #d9e0dc;
  border-radius: 8px;
}
QLineEdit, QComboBox, QDoubleSpinBox, QSpinBox, QTextEdit, QTableWidget {
  background: #ffffff;
  border: 1px solid #cfd8d4;
  border-radius: 5px;
  padding: 5px;
  selection-background-color: #315f72;
}
QLineEdit:focus, QComboBox:focus, QDoubleSpinBox:focus, QSpinBox:focus, QTextEdit:focus {
  border-color: #315f72;
}
QTabWidget::pane {
  border: none;
}
QTabBar::tab {
  color: #607079;
  padding: 9px 16px;
  border-bottom: 2px solid transparent;
}
QTabBar::tab:selected {
  color: #172125;
  border-bottom: 2px solid #b88746;
  font-weight: 700;
}
QHeaderView::section {
  background: #edf1ee;
  color: #314047;
  border: none;
  padding: 7px;
  font-weight: 700;
}
QTableWidget {
  gridline-color: #e2e8e4;
}
QTextEdit#LogBox {
  background: #11181b;
  color: #d7e2dd;
  border: 1px solid #253237;
  font-family: "Cascadia Mono", "Consolas";
}
QLabel#StatusGood {
  color: #1d6b4f;
  font-weight: 800;
}
QLabel#StatusWarn {
  color: #94652d;
  font-weight: 800;
}
QLabel#StatusBad {
  color: #9b3131;
  font-weight: 800;
}
"""
