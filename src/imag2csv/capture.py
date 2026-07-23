"""画面キャプチャ: モニタごとに凍結オーバーレイを表示し、ドラッグで矩形を切り出す。

マルチモニタ環境（モニタごとに DPI スケールが異なる場合を含む）では、
1枚のウィンドウを仮想デスクトップ全体に広げる方式は正しく動作しないため、
QScreen ごとに独立したフルスクリーンオーバーレイを表示する。
範囲選択は 1 モニタ内で完結する。
"""
from __future__ import annotations

from PySide6.QtCore import QObject, QPoint, QRect, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QGuiApplication, QImage, QPainter, QPen
from PySide6.QtWidgets import QWidget


class ScreenOverlay(QWidget):
    """1つのモニタを覆う凍結スクリーンショットのオーバーレイ。"""

    regionSelected = Signal(QImage)
    canceled = Signal()

    def __init__(self, screen):
        super().__init__()
        self._dpr = screen.devicePixelRatio()
        shot = screen.grabWindow(0)
        shot.setDevicePixelRatio(self._dpr)
        self._shot = shot
        self._origin: QPoint | None = None
        self._current: QPoint | None = None
        self.setWindowFlags(
            Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool
        )
        self.setScreen(screen)
        self.setGeometry(screen.geometry())
        self.setCursor(Qt.CrossCursor)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setMouseTracking(True)

    def _sel_rect(self) -> QRect | None:
        if self._origin is None or self._current is None:
            return None
        return QRect(self._origin, self._current).normalized()

    def paintEvent(self, event):  # noqa: N802
        p = QPainter(self)
        p.drawPixmap(0, 0, self._shot)
        p.fillRect(self.rect(), QColor(0, 0, 0, 110))
        sel = self._sel_rect()
        if sel is not None and not sel.isEmpty():
            # 選択範囲だけ明るく（元のスクリーンショットを再描画）
            src = QRectF(
                sel.x() * self._dpr,
                sel.y() * self._dpr,
                sel.width() * self._dpr,
                sel.height() * self._dpr,
            )
            p.drawPixmap(QRectF(sel), self._shot, src)
            p.setPen(QPen(QColor(80, 180, 255), 1.5))
            p.drawRect(sel)
            p.setPen(QColor(255, 255, 255))
            p.drawText(
                sel.bottomRight() + QPoint(-80, 18),
                f"{sel.width()} x {sel.height()}",
            )
        else:
            p.setPen(QColor(230, 230, 230))
            p.drawText(
                self.rect().adjusted(0, 24, 0, 0),
                Qt.AlignHCenter | Qt.AlignTop,
                "ドラッグで範囲選択 / Esc・右クリックでキャンセル",
            )
        p.end()

    def mousePressEvent(self, event):  # noqa: N802
        if event.button() == Qt.LeftButton:
            self._origin = event.position().toPoint()
            self._current = self._origin
            self.update()
        elif event.button() == Qt.RightButton:
            self.canceled.emit()

    def mouseMoveEvent(self, event):  # noqa: N802
        if self._origin is not None:
            self._current = event.position().toPoint()
            self.update()

    def mouseReleaseEvent(self, event):  # noqa: N802
        if event.button() != Qt.LeftButton:
            return
        sel = self._sel_rect()
        self._origin = self._current = None
        if sel is None or sel.width() < 5 or sel.height() < 5:
            self.update()
            return
        dev = QRect(
            int(sel.x() * self._dpr),
            int(sel.y() * self._dpr),
            int(sel.width() * self._dpr),
            int(sel.height() * self._dpr),
        )
        cropped = self._shot.copy(dev)
        cropped.setDevicePixelRatio(1.0)  # フル解像度をそのまま画像ピクセルとして扱う
        self.regionSelected.emit(cropped.toImage())

    def keyPressEvent(self, event):  # noqa: N802
        if event.key() == Qt.Key_Escape:
            self.canceled.emit()
        else:
            super().keyPressEvent(event)


class CaptureController(QObject):
    """全モニタにオーバーレイを表示し、最初に確定した選択を返す。"""

    captured = Signal(QImage)
    canceled = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._overlays: list[ScreenOverlay] = []
        self._done = False

    def start(self) -> None:
        self._done = False
        self._overlays = []
        for screen in QGuiApplication.screens():
            overlay = ScreenOverlay(screen)
            overlay.regionSelected.connect(self._on_selected)
            overlay.canceled.connect(self._on_canceled)
            self._overlays.append(overlay)
        for overlay in self._overlays:
            overlay.show()
            overlay.raise_()
        if self._overlays:
            self._overlays[0].activateWindow()

    def _close_all(self) -> None:
        for overlay in self._overlays:
            overlay.close()
            overlay.deleteLater()
        self._overlays = []

    def _on_selected(self, img: QImage) -> None:
        if self._done:
            return
        self._done = True
        self._close_all()
        self.captured.emit(img)

    def _on_canceled(self) -> None:
        if self._done:
            return
        self._done = True
        self._close_all()
        self.canceled.emit()
