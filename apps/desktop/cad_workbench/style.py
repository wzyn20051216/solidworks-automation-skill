"""@brief 桌面端视觉样式。"""

APP_STYLE = """
QMainWindow {
  background: #edeeea;
}
QWidget {
  color: #182024;
  font-family: "Microsoft YaHei UI", "Microsoft YaHei", "Segoe UI";
  font-size: 13px;
}
QFrame#Sidebar {
  background: #141b1f;
  border: none;
}
QLabel#BrandTitle {
  color: #fafaf7;
  font-size: 20px;
  font-weight: 800;
}
QLabel#BrandSub {
  color: #aeb8b4;
  font-size: 12px;
}
QPushButton#NavButton {
  color: #dce2de;
  background: transparent;
  border: 1px solid transparent;
  border-radius: 6px;
  padding: 11px 13px;
  text-align: left;
}
QPushButton#NavButton:hover {
  background: #202a2f;
  border-color: #2d3a40;
  color: #fafaf7;
}
QPushButton#PrimaryButton {
  color: #fffaf2;
  background: #b87333;
  border: 1px solid #b87333;
  border-radius: 6px;
  padding: 10px 16px;
  font-weight: 700;
}
QPushButton#PrimaryButton:hover {
  background: #9f6128;
  border-color: #9f6128;
}
QPushButton#PrimaryButton:pressed {
  background: #865020;
}
QPushButton#QuietButton {
  color: #20282c;
  background: #fafaf7;
  border: 1px solid #cbd3cd;
  border-radius: 6px;
  padding: 9px 13px;
}
QPushButton#QuietButton:hover {
  border-color: #b87333;
  background: #fffdf8;
}
QLabel#PageTitle {
  font-size: 28px;
  font-weight: 800;
  color: #141b1f;
}
QLabel#SectionTitle {
  font-size: 16px;
  font-weight: 800;
  color: #182024;
}
QLabel#Muted {
  color: #56636b;
}
QFrame#Panel {
  background: #fafaf7;
  border: 1px solid #d8ddd7;
  border-radius: 8px;
}
QFrame#StatusPanel {
  background: #fafaf7;
  border: 1px solid #d8ddd7;
  border-radius: 8px;
}
QFrame#SummaryStrip {
  background: #fafaf7;
  border: 1px solid #d8ddd7;
  border-radius: 8px;
}
QFrame#SummaryItem {
  background: #f4f5f1;
  border: 1px solid #e0e3de;
  border-radius: 6px;
}
QLabel#SummaryLabel {
  color: #667179;
  font-size: 11px;
}
QLabel#SummaryValue {
  color: #182024;
  font-size: 15px;
  font-weight: 800;
}
QLabel#AccentLine {
  background: #b87333;
  min-height: 2px;
  max-height: 2px;
}
QLineEdit, QComboBox, QDoubleSpinBox, QSpinBox, QTextEdit, QTableWidget {
  background: #fffffd;
  border: 1px solid #cbd3cd;
  border-radius: 5px;
  padding: 6px;
  selection-background-color: #b87333;
}
QLineEdit:focus, QComboBox:focus, QDoubleSpinBox:focus, QSpinBox:focus, QTextEdit:focus {
  border-color: #b87333;
}
QCheckBox {
  spacing: 7px;
}
QCheckBox::indicator {
  width: 17px;
  height: 17px;
  border-radius: 4px;
  border: 1px solid #aeb8b4;
  background: #fffffd;
}
QCheckBox::indicator:checked {
  background: #b87333;
  border-color: #b87333;
}
QTabWidget::pane {
  border: none;
}
QTabBar::tab {
  color: #56636b;
  padding: 10px 18px;
  border-bottom: 2px solid transparent;
}
QTabBar::tab:selected {
  color: #182024;
  border-bottom: 2px solid #b87333;
  font-weight: 700;
}
QHeaderView::section {
  background: #ecefea;
  color: #2b353a;
  border: none;
  padding: 8px;
  font-weight: 700;
}
QTableWidget {
  gridline-color: #e1e5df;
  alternate-background-color: #f7f8f4;
}
QTableWidget::item {
  padding: 4px;
}
QTableWidget::item:selected {
  background: #ead6bf;
  color: #182024;
}
QTextEdit#LogBox {
  background: #12181b;
  color: #e0e7e1;
  border: 1px solid #2b353a;
  font-family: "Cascadia Mono", "Consolas";
}
QTextEdit#ReviewSummary {
  background: #fffffd;
  color: #182024;
  border: 1px solid #d8ddd7;
  border-radius: 6px;
}
QLabel#StatusGood {
  color: #2d6a4f;
  font-weight: 800;
}
QLabel#StatusWarn {
  color: #9f6128;
  font-weight: 800;
}
QLabel#StatusBad {
  color: #9a332d;
  font-weight: 800;
}
QScrollBar:vertical {
  background: transparent;
  width: 10px;
}
QScrollBar::handle:vertical {
  background: #c6cec8;
  border-radius: 5px;
  min-height: 28px;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
  height: 0px;
}
"""
