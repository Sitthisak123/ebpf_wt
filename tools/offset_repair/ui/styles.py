"""
Modern Dark Theme QSS Stylesheet for Offset Repair Tool
"""

DARK_THEME_QSS = """
QMainWindow, QWidget {
    background-color: #121316;
    color: #E1E3E6;
    font-family: 'Segoe UI', 'Ubuntu', 'Sans-Serif';
    font-size: 13px;
}

QTabBar::tab {
    background: #1C1E24;
    color: #9BA1A6;
    padding: 10px 18px;
    margin-right: 2px;
    border-top-left-radius: 6px;
    border-top-right-radius: 6px;
    font-weight: bold;
}

QTabBar::tab:selected {
    background: #252830;
    color: #4CAF50;
    border-bottom: 2px solid #4CAF50;
}

QTabBar::tab:hover {
    background: #23262E;
    color: #FFFFFF;
}

QPushButton {
    background-color: #2A2E39;
    color: #E1E3E6;
    border: 1px solid #3E4452;
    border-radius: 5px;
    padding: 8px 16px;
    font-weight: bold;
}

QPushButton:hover {
    background-color: #353B49;
    border-color: #5C6370;
}

QPushButton:pressed {
    background-color: #20242D;
}

QPushButton:disabled {
    background-color: #1E2026;
    color: #555A64;
    border-color: #2A2E38;
}

QPushButton#btn_next {
    background-color: #2E7D32;
    color: #FFFFFF;
    border: 1px solid #4CAF50;
}

QPushButton#btn_next:hover {
    background-color: #388E3C;
}

QPushButton#btn_next:disabled {
    background-color: #1B381D;
    color: #6C826E;
    border-color: #234725;
}

QPushButton#btn_scan {
    background-color: #1565C0;
    color: #FFFFFF;
    border: 1px solid #1E88E5;
}

QPushButton#btn_scan:hover {
    background-color: #1976D2;
}

QPushButton#btn_scan:disabled {
    background-color: #132D4E;
    color: #576F8E;
    border-color: #1E3F66;
}

QComboBox {
    background-color: #1E2129;
    color: #E1E3E6;
    border: 1px solid #3E4452;
    border-radius: 4px;
    padding: 6px 12px;
}

QComboBox::drop-down {
    subcontrol-origin: padding;
    subcontrol-position: top right;
    width: 25px;
    border-left: 1px solid #3E4452;
}

QComboBox QAbstractItemView {
    background-color: #1E2129;
    color: #E1E3E6;
    selection-background-color: #2E7D32;
    selection-color: #FFFFFF;
    border: 1px solid #3E4452;
}

QTableWidget {
    background-color: #181A20;
    gridline-color: #2D313B;
    border: 1px solid #2D313B;
    border-radius: 4px;
    selection-background-color: #2A3B4C;
}

QHeaderView::section {
    background-color: #20232B;
    color: #A0A6B2;
    padding: 6px;
    border: 1px solid #2D313B;
    font-weight: bold;
}

QGroupBox {
    border: 1px solid #2D313B;
    border-radius: 6px;
    margin-top: 14px;
    padding-top: 14px;
    font-weight: bold;
    color: #61AFEF;
}

QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 12px;
    padding: 0 4px;
}

QLabel#header_title {
    font-size: 16px;
    font-weight: bold;
    color: #FFFFFF;
}

QLabel#status_banner {
    padding: 8px 12px;
    border-radius: 4px;
    font-weight: bold;
}

QStatusBar {
    background-color: #16181D;
    color: #8C92A0;
    border-top: 1px solid #242730;
}
"""
