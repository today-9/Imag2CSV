"""アプリ全体のダークテーマ（Fusion + パレット + QSS）とアイコン。"""
from __future__ import annotations

import qtawesome as qta
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication

ACCENT = "#3b82f6"
ACCENT_DARK = "#2563eb"
DONE = "#34d399"
FG = "#e2e2e6"
FG_DIM = "#9aa0aa"
BG = "#212226"
BG_PANEL = "#26272c"
BG_INPUT = "#1b1c20"
BORDER = "#3a3b40"
BORDER_LIGHT = "#43444b"
ICON_COLOR = "#cfd2d8"

QSS = f"""
QWidget {{
    font-size: 9.5pt;
}}
QGroupBox {{
    border: 1px solid {BORDER};
    border-radius: 6px;
    margin-top: 12px;
    padding-top: 6px;
    background: {BG_PANEL};
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    left: 8px;
    padding: 0 4px;
    font-weight: bold;
    color: {FG_DIM};
}}
QGroupBox[done="true"]::title {{
    color: {DONE};
}}
QGroupBox[next="true"] {{
    border: 1px solid {ACCENT};
}}
QGroupBox[next="true"]::title {{
    color: {ACCENT};
}}
QPushButton {{
    background: #2f3037;
    border: 1px solid {BORDER_LIGHT};
    border-radius: 5px;
    padding: 5px 10px;
}}
QPushButton:hover {{
    background: #383a42;
    border-color: #5b5d66;
}}
QPushButton:pressed {{
    background: #2a2b31;
}}
QPushButton:disabled {{
    color: #6b6d75;
    background: #26272c;
}}
QPushButton[accent="true"] {{
    background: {ACCENT_DARK};
    border-color: {ACCENT_DARK};
    color: white;
    font-weight: bold;
}}
QPushButton[accent="true"]:hover {{
    background: {ACCENT};
}}
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox {{
    background: {BG_INPUT};
    border: 1px solid {BORDER_LIGHT};
    border-radius: 4px;
    padding: 3px 6px;
    selection-background-color: {ACCENT_DARK};
}}
QLineEdit:focus, QSpinBox:focus, QComboBox:focus {{
    border-color: {ACCENT};
}}
QComboBox QAbstractItemView {{
    background: {BG_INPUT};
    border: 1px solid {BORDER_LIGHT};
    selection-background-color: {ACCENT_DARK};
}}
QListWidget {{
    background: {BG_INPUT};
    border: 1px solid {BORDER_LIGHT};
    border-radius: 4px;
}}
QListWidget::item {{
    padding: 3px;
}}
QListWidget::item:selected {{
    background: {ACCENT_DARK};
    color: white;
    border-radius: 3px;
}}
QToolBar {{
    background: {BG_PANEL};
    border-bottom: 1px solid {BORDER};
    spacing: 2px;
    padding: 3px;
}}
QToolButton {{
    border-radius: 4px;
    padding: 4px 8px;
}}
QToolButton:hover {{
    background: #383a42;
}}
QToolButton:checked {{
    background: rgba(59, 130, 246, 0.25);
    border: 1px solid {ACCENT};
}}
QSlider::groove:horizontal {{
    height: 4px;
    background: {BORDER_LIGHT};
    border-radius: 2px;
}}
QSlider::handle:horizontal {{
    background: {ACCENT};
    width: 14px;
    height: 14px;
    margin: -5px 0;
    border-radius: 7px;
}}
QSlider::sub-page:horizontal {{
    background: {ACCENT_DARK};
    border-radius: 2px;
}}
QStatusBar {{
    background: {BG_PANEL};
    border-top: 1px solid {BORDER};
    color: {FG_DIM};
}}
QDockWidget {{
    titlebar-close-icon: none;
}}
QDockWidget::title {{
    background: {BG_PANEL};
    padding: 5px 8px;
    border-bottom: 1px solid {BORDER};
}}
QScrollArea {{
    border: none;
}}
QSplitter::handle {{
    background: {BORDER};
    width: 2px;
}}
QTableWidget {{
    background: {BG_INPUT};
    gridline-color: {BORDER};
}}
QHeaderView::section {{
    background: {BG_PANEL};
    border: none;
    border-right: 1px solid {BORDER};
    border-bottom: 1px solid {BORDER};
    padding: 4px;
}}
QToolTip {{
    background: #2f3037;
    color: {FG};
    border: 1px solid {BORDER_LIGHT};
    padding: 4px;
}}
"""


def apply_theme(app: QApplication) -> None:
    app.setStyle("Fusion")
    pal = QPalette()
    pal.setColor(QPalette.Window, QColor(BG))
    pal.setColor(QPalette.WindowText, QColor(FG))
    pal.setColor(QPalette.Base, QColor(BG_INPUT))
    pal.setColor(QPalette.AlternateBase, QColor(BG_PANEL))
    pal.setColor(QPalette.Text, QColor(FG))
    pal.setColor(QPalette.Button, QColor("#2f3037"))
    pal.setColor(QPalette.ButtonText, QColor(FG))
    pal.setColor(QPalette.Highlight, QColor(ACCENT_DARK))
    pal.setColor(QPalette.HighlightedText, QColor("white"))
    pal.setColor(QPalette.ToolTipBase, QColor("#2f3037"))
    pal.setColor(QPalette.ToolTipText, QColor(FG))
    pal.setColor(QPalette.PlaceholderText, QColor("#6b6d75"))
    pal.setColor(QPalette.Disabled, QPalette.Text, QColor("#6b6d75"))
    pal.setColor(QPalette.Disabled, QPalette.ButtonText, QColor("#6b6d75"))
    pal.setColor(QPalette.Disabled, QPalette.WindowText, QColor("#6b6d75"))
    app.setPalette(pal)
    app.setStyleSheet(QSS)


def icon(name: str, color: str = ICON_COLOR):
    """qtawesome アイコンを取得する（例: icon("fa5s.play")）。"""
    return qta.icon(name, color=color, color_active=FG)
