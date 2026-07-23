"""抽出データのプレビュー: 実データの数値テーブル + 簡易グラフ。"""
from __future__ import annotations

import math

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

# 系列データ: (表示名, 色, [(x, y), ...])
SeriesData = tuple[str, QColor, list[tuple[float, float]]]


def _nice_step(span: float) -> float:
    """およそ5分割になるキリのいい目盛り間隔を返す。"""
    if span <= 0:
        return 1.0
    raw = span / 5
    mag = 10 ** math.floor(math.log10(raw))
    for m in (1, 2, 5, 10):
        if raw <= m * mag:
            return m * mag
    return 10 * mag


class PlotWidget(QWidget):
    """抽出点をデータ座標で描く簡易プロット。"""

    MARGIN_L, MARGIN_R, MARGIN_T, MARGIN_B = 60, 15, 15, 35

    def __init__(self, parent=None):
        super().__init__(parent)
        self.series: list[SeriesData] = []
        self.setMinimumSize(300, 250)

    def set_data(self, series: list[SeriesData]) -> None:
        self.series = series
        self.update()

    def paintEvent(self, event):  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.fillRect(self.rect(), QColor(255, 255, 255))
        rect = self.rect().adjusted(
            self.MARGIN_L, self.MARGIN_T, -self.MARGIN_R, -self.MARGIN_B
        )
        all_pts = [pt for _, _, pts in self.series for pt in pts]
        if not all_pts or rect.width() < 20 or rect.height() < 20:
            p.setPen(QColor(120, 120, 120))
            p.drawText(self.rect(), Qt.AlignCenter, "データなし")
            p.end()
            return
        xs = [pt[0] for pt in all_pts]
        ys = [pt[1] for pt in all_pts]
        x0, x1 = min(xs), max(xs)
        y0, y1 = min(ys), max(ys)
        # 余白を付けたレンジ（ゼロ幅は適当に広げる）
        dx = (x1 - x0) or abs(x0) or 1.0
        dy = (y1 - y0) or abs(y0) or 1.0
        x0 -= dx * 0.05
        x1 += dx * 0.05
        y0 -= dy * 0.05
        y1 += dy * 0.05

        def to_px(x: float, y: float) -> tuple[float, float]:
            px = rect.left() + (x - x0) / (x1 - x0) * rect.width()
            py = rect.bottom() - (y - y0) / (y1 - y0) * rect.height()
            return px, py

        # グリッドと目盛り
        p.setPen(QColor(60, 60, 60))
        font = p.font()
        font.setPointSize(8)
        p.setFont(font)
        step = _nice_step(x1 - x0)
        t = math.ceil(x0 / step) * step
        while t <= x1:
            px, _ = to_px(t, y0)
            p.setPen(QColor(225, 225, 225))
            p.drawLine(int(px), rect.top(), int(px), rect.bottom())
            p.setPen(QColor(60, 60, 60))
            p.drawText(
                int(px) - 40, rect.bottom() + 4, 80, 16, Qt.AlignHCenter, f"{t:.6g}"
            )
            t += step
        step = _nice_step(y1 - y0)
        t = math.ceil(y0 / step) * step
        while t <= y1:
            _, py = to_px(x0, t)
            p.setPen(QColor(225, 225, 225))
            p.drawLine(rect.left(), int(py), rect.right(), int(py))
            p.setPen(QColor(60, 60, 60))
            p.drawText(
                0, int(py) - 8, self.MARGIN_L - 6, 16, Qt.AlignRight, f"{t:.6g}"
            )
            t += step
        p.setPen(QPen(QColor(60, 60, 60), 1))
        p.drawRect(rect)

        # 系列: x順の折れ線 + マーカー
        for name, color, pts in self.series:
            if not pts:
                continue
            spts = sorted(pts)
            line = QPen(QColor(color), 1)
            line.setStyle(Qt.SolidLine)
            p.setPen(line)
            last = None
            for x, y in spts:
                cur = to_px(x, y)
                if last is not None:
                    p.drawLine(int(last[0]), int(last[1]), int(cur[0]), int(cur[1]))
                last = cur
            p.setBrush(QColor(color))
            p.setPen(QPen(QColor(255, 255, 255), 1))
            for x, y in spts:
                px, py = to_px(x, y)
                p.drawEllipse(int(px) - 3, int(py) - 3, 6, 6)
        p.end()


class PreviewDialog(QDialog):
    """実データの数値テーブルと簡易グラフを表示するモードレスダイアログ。"""

    def __init__(self, parent, refresh_cb):
        super().__init__(parent)
        self.setWindowTitle("データプレビュー")
        self.resize(860, 480)
        self._refresh_cb = refresh_cb

        layout = QVBoxLayout(self)
        self.info = QLabel("")
        self.info.setStyleSheet("color: gray;")
        layout.addWidget(self.info)

        splitter = QSplitter(Qt.Horizontal, self)
        self.table = QTableWidget()
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        splitter.addWidget(self.table)
        self.plot = PlotWidget()
        splitter.addWidget(self.plot)
        splitter.setSizes([430, 430])
        layout.addWidget(splitter, 1)

        row = QHBoxLayout()
        btn_refresh = QPushButton("更新")
        btn_refresh.clicked.connect(self.refresh)
        row.addWidget(btn_refresh)
        row.addStretch(1)
        btn_close = QPushButton("閉じる")
        btn_close.clicked.connect(self.close)
        row.addWidget(btn_close)
        layout.addLayout(row)

    def refresh(self) -> None:
        series, calibrated = self._refresh_cb()
        self.info.setText(
            "座標系: データ座標（キャリブレーション適用済み）"
            if calibrated
            else "座標系: ピクセル座標（キャリブレーション未完了）"
        )
        # テーブル: CSV と同じ並び（系列ごとに x, y 列）
        headers: list[str] = []
        columns: list[list[float]] = []
        for name, _color, pts in series:
            spts = sorted(pts)
            headers += [f"{name}_x", f"{name}_y"]
            columns.append([pt[0] for pt in spts])
            columns.append([pt[1] for pt in spts])
        nrows = max((len(c) for c in columns), default=0)
        self.table.clear()
        self.table.setColumnCount(len(headers))
        self.table.setRowCount(nrows)
        self.table.setHorizontalHeaderLabels(headers)
        for col, values in enumerate(columns):
            for r, v in enumerate(values):
                item = QTableWidgetItem(f"{v:.6g}")
                item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                self.table.setItem(r, col, item)
        for c in range(len(headers)):
            self.table.setColumnWidth(c, 90)
        self.plot.set_data(series)
