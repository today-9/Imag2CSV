"""ズーム・パン・点編集・ROIブラシ・ルーペを備えた QGraphicsView。"""
from __future__ import annotations

from PySide6.QtCore import QLineF, QPointF, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QImage, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QFrame,
    QGraphicsEllipseItem,
    QGraphicsItem,
    QGraphicsItemGroup,
    QGraphicsLineItem,
    QGraphicsPixmapItem,
    QGraphicsScene,
    QGraphicsSimpleTextItem,
    QGraphicsView,
)

from .qimage_util import qimage_alpha

# モード定数
MODE_PAN = "pan"
MODE_PICK = "pick"
MODE_CAL = "cal"
MODE_BRUSH = "brush"
MODE_ERASE = "erase"
MODE_EDIT = "edit"

ROI_COLOR = QColor(255, 70, 70, 110)
SELECT_COLOR = QColor(255, 220, 0)


def contrast_color(color: QColor | None) -> QColor:
    """系列色に対して視認しやすいマーカー色（補色ベース）を返す。"""
    if color is None:
        return QColor(60, 130, 255)
    h, s, v, _ = color.getHsv()
    if h < 0 or s < 30:  # グレー系は固定色
        return QColor(255, 80, 200)
    return QColor.fromHsv((h + 180) % 360, 255, 255)


class PointItem(QGraphicsEllipseItem):
    """データ点。scene 座標 = 画像ピクセル座標。表示サイズはズームに依らず一定。

    塗り色は系列色の補色（元の線の上でも見えるように）。
    """

    RADIUS = 4.5

    def __init__(self, series, x: float, y: float):
        r = self.RADIUS
        super().__init__(-r, -r, 2 * r, 2 * r)
        self.series = series
        self.setPos(x, y)
        self.refresh_color()
        self.setPen(QPen(QColor(255, 255, 255), 1.2))
        self.setFlag(QGraphicsItem.ItemIgnoresTransformations, True)
        self.setFlag(QGraphicsItem.ItemIsSelectable, True)
        self.setZValue(10)

    def refresh_color(self) -> None:
        self.setBrush(QBrush(contrast_color(self.series.color)))

    def paint(self, painter, option, widget=None):  # noqa: N802
        # デフォルトの点線選択枠を消し、選択時はリングを描く
        option.state &= ~option.state.__class__.State_Selected
        super().paint(painter, option, widget)
        if self.isSelected():
            painter.setPen(QPen(SELECT_COLOR, 2))
            painter.setBrush(Qt.NoBrush)
            r = self.RADIUS + 2.5
            painter.drawEllipse(QPointF(0, 0), r, r)


class CalMarkerItem(QGraphicsItemGroup):
    """キャリブレーション点マーカー。編集モードで移動でき、移動は較正に反映される。"""

    def __init__(self, view: "GraphView", key: str, x: float, y: float):
        super().__init__()
        self._view = view
        self.key = key
        self._color = QColor(255, 160, 0) if key.startswith("x") else QColor(0, 200, 120)
        self._lines: list[QGraphicsLineItem] = []
        pen = QPen(self._color, 1.5)
        for line in (QLineF(-9, 0, 9, 0), QLineF(0, -9, 0, 9)):
            li = QGraphicsLineItem(line, self)
            li.setPen(pen)
            self._lines.append(li)
        label = QGraphicsSimpleTextItem(key.upper(), self)
        label.setBrush(QBrush(self._color))
        label.setPos(7, -22)
        self.setFlag(QGraphicsItem.ItemIgnoresTransformations, True)
        self.setFlag(QGraphicsItem.ItemIsSelectable, True)
        self.setFlag(QGraphicsItem.ItemSendsScenePositionChanges, True)
        self.setZValue(5)
        self.setPos(x, y)

    def itemChange(self, change, value):  # noqa: N802
        if change == QGraphicsItem.ItemPositionHasChanged:
            self._view.calMarkerMoved.emit(self.key, self.pos().x(), self.pos().y())
        elif change == QGraphicsItem.ItemSelectedHasChanged:
            pen = QPen(SELECT_COLOR if value else self._color, 1.5)
            for li in self._lines:
                li.setPen(pen)
        return super().itemChange(change, value)


class LoupeView(QGraphicsView):
    """カーソル/選択点の周辺を拡大表示するルーペ（倍率可変・ドック配置用）。"""

    def __init__(self, scene: QGraphicsScene, parent=None):
        super().__init__(scene, parent)
        self.setMinimumSize(160, 160)
        # 常に正方形を保つ（縦長になるとレンズらしくない）
        policy = self.sizePolicy()
        policy.setHeightForWidth(True)
        self.setSizePolicy(policy)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setInteractive(False)
        self.setFrameShape(QFrame.Box)
        self.setStyleSheet("border: 1px solid #999; background: #222;")
        self.setRenderHint(QPainter.Antialiasing, False)
        self._zoom = 6.0
        self._center: QPointF | None = None
        self.scale(self._zoom, self._zoom)

    def hasHeightForWidth(self) -> bool:  # noqa: N802
        return True

    def heightForWidth(self, width: int) -> int:  # noqa: N802
        return width

    def center_on(self, pos: QPointF) -> None:
        self._center = pos
        self.centerOn(pos)

    def set_zoom(self, zoom: float) -> None:
        self._zoom = zoom
        self.resetTransform()
        self.scale(zoom, zoom)
        if self._center is not None:
            self.centerOn(self._center)

    def resizeEvent(self, event):  # noqa: N802
        super().resizeEvent(event)
        if self._center is not None:
            self.centerOn(self._center)

    def drawForeground(self, painter, rect):  # noqa: N802
        # ビューポート座標で中央十字線を描く
        painter.save()
        painter.resetTransform()
        w = self.viewport().width()
        h = self.viewport().height()
        painter.setPen(QPen(QColor(255, 220, 0, 170), 1))
        painter.drawLine(w // 2, 0, w // 2, h)
        painter.drawLine(0, h // 2, w, h // 2)
        painter.restore()


class GraphView(QGraphicsView):
    colorPicked = Signal(int, int)  # 画像ピクセル座標
    calClicked = Signal(float, float)
    calMarkerMoved = Signal(str, float, float)
    pointAddRequested = Signal(float, float)
    scenePosChanged = Signal(float, float)
    roiChanged = Signal()
    pointsChanged = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.AnchorViewCenter)
        self.setRenderHint(QPainter.Antialiasing)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setBackgroundBrush(QColor(45, 45, 48))

        self.mode = MODE_PAN
        self.brush_size = 20
        self._zoom = 1.0
        self._stroking = False
        self._last_stroke: QPointF | None = None
        self._panning = False
        self._pan_start = QPointF()

        self.pix_item: QGraphicsPixmapItem | None = None
        self.mask_item: QGraphicsPixmapItem | None = None
        self.roi_item: QGraphicsPixmapItem | None = None
        self.roi_img: QImage | None = None
        self._cal_markers: dict[str, CalMarkerItem] = {}

        self.loupe = LoupeView(self._scene)  # QDockWidget に載せる（main_window側）

        self._apply_mode()

    # ---------- 画像 ----------

    def set_image(self, qimg: QImage) -> None:
        self._scene.clear()
        self.pix_item = self._scene.addPixmap(QPixmap.fromImage(qimg))
        self.pix_item.setZValue(0)
        self.roi_img = QImage(qimg.size(), QImage.Format_ARGB32_Premultiplied)
        self.roi_img.fill(Qt.transparent)
        self.roi_item = self._scene.addPixmap(QPixmap.fromImage(self.roi_img))
        self.roi_item.setZValue(2)
        self.mask_item = None
        self._cal_markers = {}
        self._scene.setSceneRect(0, 0, qimg.width(), qimg.height())
        self.fit_view()

    def has_image(self) -> bool:
        return self.pix_item is not None

    def fit_view(self) -> None:
        if self.pix_item is not None:
            self.fitInView(self._scene.sceneRect(), Qt.KeepAspectRatio)
            self._zoom = self.transform().m11()

    # ---------- ルーペ ----------

    def set_loupe_zoom(self, zoom: float) -> None:
        self.loupe.set_zoom(zoom)

    def _loupe_follow(self, scene_pos: QPointF) -> None:
        if self.loupe.isVisible():
            self.loupe.center_on(scene_pos)

    # ---------- マスクプレビュー ----------

    def set_mask_overlay(self, qimg: QImage | None) -> None:
        if self.mask_item is not None:
            self._scene.removeItem(self.mask_item)
            self.mask_item = None
        if qimg is not None:
            self.mask_item = self._scene.addPixmap(QPixmap.fromImage(qimg))
            self.mask_item.setZValue(1)

    # ---------- ROI ----------

    def roi_mask(self):
        """塗られた領域の bool マスク。何も塗られていなければ None。"""
        if self.roi_img is None:
            return None
        alpha = qimage_alpha(self.roi_img)
        mask = alpha >= 40
        return mask if mask.any() else None

    def clear_roi(self) -> None:
        if self.roi_img is None:
            return
        self.roi_img.fill(Qt.transparent)
        self.roi_item.setPixmap(QPixmap.fromImage(self.roi_img))
        self.roiChanged.emit()

    def _stroke(self, scene_pos: QPointF) -> None:
        if self.roi_img is None:
            return
        p = QPainter(self.roi_img)
        if self.mode == MODE_ERASE:
            p.setCompositionMode(QPainter.CompositionMode_Clear)
        pen = QPen(ROI_COLOR, self.brush_size, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
        p.setPen(pen)
        if self._last_stroke is None:
            p.drawPoint(scene_pos)
        else:
            p.drawLine(self._last_stroke, scene_pos)
        p.end()
        self._last_stroke = scene_pos
        self.roi_item.setPixmap(QPixmap.fromImage(self.roi_img))

    # ---------- キャリブレーションマーカー ----------

    def set_cal_marker(self, key: str, x: float, y: float) -> None:
        old = self._cal_markers.pop(key, None)
        if old is not None:
            self._scene.removeItem(old)
        marker = CalMarkerItem(self, key, x, y)
        self._scene.addItem(marker)
        self._cal_markers[key] = marker
        self._gate_item(marker, self.mode == MODE_EDIT)

    def select_cal_marker(self, key: str) -> bool:
        """指定キーの較正マーカーだけを選択状態にする（重なりに依らず確実）。

        編集モードに切り替え、ルーペをマーカー位置へ移動し、
        矢印キーがすぐ効くようビューにフォーカスを移す。
        """
        marker = self._cal_markers.get(key)
        if marker is None:
            return False
        self.set_mode(MODE_EDIT)
        self._scene.clearSelection()
        marker.setSelected(True)
        self._loupe_follow(marker.pos())
        self.setFocus()
        return True

    # ---------- 点 ----------

    def add_point(self, series, x: float, y: float) -> PointItem:
        item = PointItem(series, x, y)
        self._scene.addItem(item)
        self._gate_item(item, self.mode == MODE_EDIT)
        return item

    def points(self, series=None) -> list[PointItem]:
        items = [i for i in self._scene.items() if isinstance(i, PointItem)]
        if series is not None:
            items = [i for i in items if i.series is series]
        return items

    def remove_points(self, series) -> None:
        for item in self.points(series):
            self._scene.removeItem(item)
        self.pointsChanged.emit()

    def _movable_items(self) -> list[QGraphicsItem]:
        return [
            i
            for i in self._scene.items()
            if isinstance(i, (PointItem, CalMarkerItem))
        ]

    @staticmethod
    def _gate_item(item: QGraphicsItem, editing: bool) -> None:
        item.setFlag(QGraphicsItem.ItemIsMovable, editing)
        item.setAcceptedMouseButtons(Qt.LeftButton if editing else Qt.NoButton)
        if not editing:
            item.setSelected(False)

    # ---------- モード ----------

    def set_mode(self, mode: str) -> None:
        self.mode = mode
        self._apply_mode()

    def _apply_mode(self) -> None:
        editing = self.mode == MODE_EDIT
        for item in self._movable_items():
            self._gate_item(item, editing)
        if self.mode == MODE_PAN:
            self.setDragMode(QGraphicsView.ScrollHandDrag)
        elif editing:
            self.setDragMode(QGraphicsView.RubberBandDrag)
        else:
            self.setDragMode(QGraphicsView.NoDrag)
        if self.mode in (MODE_PICK, MODE_CAL, MODE_BRUSH, MODE_ERASE):
            self.viewport().setCursor(Qt.CrossCursor)
        elif editing:
            self.viewport().setCursor(Qt.ArrowCursor)

    # ---------- イベント ----------

    def wheelEvent(self, event):  # noqa: N802
        if not self.has_image():
            return
        factor = 1.25 if event.angleDelta().y() > 0 else 0.8
        new_zoom = self._zoom * factor
        if not (0.02 <= new_zoom <= 80):
            return
        self._zoom = new_zoom
        self.scale(factor, factor)

    def mousePressEvent(self, event):  # noqa: N802
        pos = self.mapToScene(event.position().toPoint())
        # 中ボタンドラッグはどのモードでもパン
        if event.button() == Qt.MiddleButton and self.has_image():
            self._panning = True
            self._pan_start = event.position()
            self.viewport().setCursor(Qt.ClosedHandCursor)
            return
        if event.button() == Qt.LeftButton and self.has_image():
            if self.mode == MODE_PICK:
                self.colorPicked.emit(int(pos.x()), int(pos.y()))
                return
            if self.mode == MODE_CAL:
                self.calClicked.emit(pos.x(), pos.y())
                return
            if self.mode in (MODE_BRUSH, MODE_ERASE):
                self._stroking = True
                self._last_stroke = None
                self._stroke(pos)
                return
            if self.mode == MODE_EDIT and event.modifiers() & Qt.ControlModifier:
                self.pointAddRequested.emit(pos.x(), pos.y())
                return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):  # noqa: N802
        pos = self.mapToScene(event.position().toPoint())
        self.scenePosChanged.emit(pos.x(), pos.y())
        self._loupe_follow(pos)
        if self._panning:
            delta = event.position() - self._pan_start
            self._pan_start = event.position()
            self.horizontalScrollBar().setValue(
                self.horizontalScrollBar().value() - int(delta.x())
            )
            self.verticalScrollBar().setValue(
                self.verticalScrollBar().value() - int(delta.y())
            )
            return
        if self._stroking:
            self._stroke(pos)
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):  # noqa: N802
        if self._panning and event.button() == Qt.MiddleButton:
            self._panning = False
            self._apply_mode()  # カーソルを戻す
            return
        if self._stroking and event.button() == Qt.LeftButton:
            self._stroking = False
            self._last_stroke = None
            self.roiChanged.emit()
            return
        super().mouseReleaseEvent(event)
        if self.mode == MODE_EDIT:
            self.pointsChanged.emit()

    def keyPressEvent(self, event):  # noqa: N802
        if self.mode == MODE_EDIT:
            selected = [
                i
                for i in self._scene.selectedItems()
                if isinstance(i, (PointItem, CalMarkerItem))
            ]
            if selected:
                if event.modifiers() & Qt.ShiftModifier:
                    step = 5.0
                elif event.modifiers() & Qt.ControlModifier:
                    step = 0.1  # サブピクセル微調整
                else:
                    step = 1.0
                delta = {
                    Qt.Key_Left: QPointF(-step, 0),
                    Qt.Key_Right: QPointF(step, 0),
                    Qt.Key_Up: QPointF(0, -step),
                    Qt.Key_Down: QPointF(0, step),
                }.get(event.key())
                if delta is not None:
                    for item in selected:
                        item.setPos(item.pos() + delta)
                    self._loupe_follow(selected[0].pos())
                    self.pointsChanged.emit()
                    return
                if event.key() == Qt.Key_Delete:
                    removed = False
                    for item in selected:
                        if isinstance(item, PointItem):  # 較正点は削除しない
                            self._scene.removeItem(item)
                            removed = True
                    if removed:
                        self.pointsChanged.emit()
                    return
        if event.key() == Qt.Key_0 and event.modifiers() & Qt.ControlModifier:
            self.fit_view()
            return
        super().keyPressEvent(event)
