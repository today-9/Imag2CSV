"""メインウィンドウ: UIパネルと各機能の配線。"""
from __future__ import annotations

import csv
from itertools import zip_longest

import numpy as np
from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import (
    QAction,
    QActionGroup,
    QColor,
    QGuiApplication,
    QIcon,
    QImage,
    QKeySequence,
    QPixmap,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDockWidget,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSlider,
    QSpinBox,
    QSplitter,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from . import detection
from .capture import CaptureController
from .model import Calibration, Series
from .preview import PreviewDialog
from .qimage_util import qimage_to_rgb, rgba_to_qimage
from .view import (
    MODE_BRUSH,
    MODE_CAL,
    MODE_EDIT,
    MODE_ERASE,
    MODE_PAN,
    MODE_PICK,
    GraphView,
)

CAL_KEYS = ("x1", "x2", "y1", "y2")


def _swatch_icon(color: QColor | None) -> QIcon:
    pix = QPixmap(16, 16)
    pix.fill(color if color is not None else QColor(200, 200, 200))
    return QIcon(pix)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Imag2CSV — グラフ画像 → CSV")
        self.resize(1280, 820)

        self.rgb: np.ndarray | None = None
        self._lab: np.ndarray | None = None
        self.cal = Calibration()
        self._cal_target: str | None = None
        self._cal_queue: list[str] = []
        self._capture: CaptureController | None = None
        self._preview_dialog: PreviewDialog | None = None

        self.view = GraphView(self)
        self._preview_timer = QTimer(self)
        self._preview_timer.setSingleShot(True)
        self._preview_timer.setInterval(200)
        self._preview_timer.timeout.connect(self._update_preview)

        splitter = QSplitter(Qt.Horizontal, self)
        splitter.addWidget(self._build_panel())
        splitter.addWidget(self.view)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([340, 940])
        self.setCentralWidget(splitter)

        # ルーペは右側のドック（グラフに重ならない。切り離し・リサイズ可）
        self.loupe_dock = QDockWidget("ルーペ", self)
        self.loupe_dock.setObjectName("loupe_dock")
        panel = QWidget()
        pv = QVBoxLayout(panel)
        pv.setContentsMargins(6, 6, 6, 6)
        pv.addWidget(self.view.loupe)  # heightForWidth で常に正方形
        zoom_row = QHBoxLayout()
        zoom_row.addWidget(QLabel("倍率:"))
        self.loupe_zoom_combo = QComboBox()
        self.loupe_zoom_combo.addItems(
            ["2×", "4×", "6×", "8×", "12×", "16×", "24×", "32×"]
        )
        self.loupe_zoom_combo.setCurrentText("6×")
        self.loupe_zoom_combo.currentTextChanged.connect(
            lambda t: self.view.set_loupe_zoom(float(t.rstrip("×")))
        )
        zoom_row.addWidget(self.loupe_zoom_combo, 1)
        pv.addLayout(zoom_row)
        pv.addStretch(1)
        self.loupe_dock.setWidget(panel)
        self.addDockWidget(Qt.RightDockWidgetArea, self.loupe_dock)

        self._build_toolbar()

        self.statusBar().showMessage("画像を開くか、画面をキャプチャしてください")

        # 配線
        self.view.colorPicked.connect(self._on_color_picked)
        self.view.calClicked.connect(self._on_cal_clicked)
        self.view.calMarkerMoved.connect(self._on_cal_marker_moved)
        self.view.pointAddRequested.connect(self._on_point_add)
        self.view.scenePosChanged.connect(self._on_scene_pos)
        self.view.roiChanged.connect(self._schedule_preview)

        self._add_series()  # 最初の系列を用意

    # ================= ツールバー =================

    def _build_toolbar(self) -> None:
        tb = QToolBar("メイン", self)
        tb.setMovable(False)
        tb.setToolButtonStyle(Qt.ToolButtonTextOnly)
        self.addToolBar(Qt.TopToolBarArea, tb)

        def act(text, slot, shortcut=None, checkable=False, tip=None):
            a = QAction(text, self)
            if shortcut:
                a.setShortcut(QKeySequence(shortcut))
            a.setCheckable(checkable)
            if checkable:
                a.toggled.connect(slot)
            else:
                a.triggered.connect(slot)
            if tip or shortcut:
                a.setToolTip(f"{tip or text} ({shortcut})" if shortcut else tip)
            tb.addAction(a)
            return a

        act("開く", self._open_image, "Ctrl+O")
        act("貼り付け", self._paste_clipboard, "Ctrl+V")
        act("キャプチャ", self._start_capture, "F9")
        tb.addSeparator()

        self._mode_actions: dict[str, QAction] = {}
        group = QActionGroup(self)
        group.setExclusive(True)
        for i, (mode, text) in enumerate(
            [
                (MODE_PAN, "パン"),
                (MODE_BRUSH, "ブラシ"),
                (MODE_ERASE, "消しゴム"),
                (MODE_EDIT, "点編集"),
            ],
            start=1,
        ):
            a = QAction(text, self)
            a.setCheckable(True)
            a.setShortcut(QKeySequence(str(i)))
            a.setToolTip(f"{text}モード (キー: {i})")
            a.triggered.connect(lambda _=False, m=mode: self._set_mode(m))
            group.addAction(a)
            tb.addAction(a)
            self._mode_actions[mode] = a
        self._mode_actions[MODE_PAN].setChecked(True)
        tb.addSeparator()

        act("検出実行", self._detect, "F5")
        act("プレビュー", self._show_preview, "Ctrl+P", tip="抽出データの数値とグラフを確認")
        act("CSV出力", self._export_csv, "Ctrl+E")
        tb.addSeparator()
        act("全体表示", self.view.fit_view, "Ctrl+0")
        loupe = act(
            "ルーペ", self.loupe_dock.setVisible, "L", checkable=True,
            tip="ルーペパネルの表示切替",
        )
        loupe.setChecked(True)
        # ドックの×で閉じたときもボタン状態を同期
        self.loupe_dock.visibilityChanged.connect(loupe.setChecked)

    # ================= パネル構築 =================

    def _build_panel(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setSpacing(8)

        # --- キャリブレーション ---
        box = QGroupBox("軸キャリブレーション（直線軸）")
        grid = QGridLayout(box)
        btn_seq = QPushButton("連続指定（X1→X2→Y1→Y2）")
        btn_seq.setStyleSheet("font-weight: bold;")
        btn_seq.setToolTip(
            "4点を続けてクリックで指定します。\n"
            "指定後にマーカー調整で微調整 → 最後に値を入力してください。"
        )
        btn_seq.clicked.connect(self._arm_cal_sequence)
        grid.addWidget(btn_seq, 0, 0, 1, 2)
        self._cal_buttons: dict[str, QPushButton] = {}
        self._cal_edits: dict[str, QLineEdit] = {}
        for row, key in enumerate(CAL_KEYS, start=1):
            btn = QPushButton(key.upper() + " をクリック")
            btn.clicked.connect(lambda _=False, k=key: self._arm_cal(k))
            edit = QLineEdit()
            edit.setPlaceholderText("実際の値")
            edit.editingFinished.connect(self._read_cal_values)
            grid.addWidget(btn, row, 0)
            grid.addWidget(edit, row, 1)
            self._cal_buttons[key] = btn
            self._cal_edits[key] = edit
        # 重なったマーカーでも確実に選択できる調整ボタン
        adjust_row = QHBoxLayout()
        adjust_row.addWidget(QLabel("マーカー調整:"))
        for key in CAL_KEYS:
            b = QPushButton(key.upper())
            b.setFixedWidth(40)
            b.setToolTip(
                f"{key.upper()} マーカーを選択します。\n"
                "矢印キーで移動（Shift: 5px / Ctrl: 0.1px）。\n"
                "重なった点でも選択できます。"
            )
            b.clicked.connect(lambda _=False, k=key: self._select_cal_marker(k))
            adjust_row.addWidget(b)
        adjust_row.addStretch(1)
        grid.addLayout(adjust_row, len(CAL_KEYS) + 1, 0, 1, 2)
        self.cal_status = QLabel("未設定")
        self.cal_status.setStyleSheet("color: gray;")
        grid.addWidget(self.cal_status, len(CAL_KEYS) + 2, 0, 1, 2)
        layout.addWidget(box)

        # --- 系列 ---
        box = QGroupBox("系列")
        v = QVBoxLayout(box)
        self.series_list = QListWidget()
        self.series_list.setSelectionMode(QAbstractItemView.SingleSelection)
        self.series_list.currentItemChanged.connect(self._on_series_changed)
        self.series_list.itemChanged.connect(lambda _: None)  # リネームはそのまま反映
        v.addWidget(self.series_list)
        h = QHBoxLayout()
        btn_add = QPushButton("追加")
        btn_add.clicked.connect(self._add_series)
        btn_del = QPushButton("削除")
        btn_del.clicked.connect(self._remove_series)
        h.addWidget(btn_add)
        h.addWidget(btn_del)
        v.addLayout(h)
        layout.addWidget(box)

        # --- 色検出 ---
        box = QGroupBox("色検出")
        form = QFormLayout(box)
        btn_pick = QPushButton("画像から色を取得 (C)")
        btn_pick.setShortcut("C")
        btn_pick.setToolTip(
            "画像上の抽出したい線・点をクリックして、選択中の系列の色にします"
        )
        btn_pick.clicked.connect(self._arm_pick)
        form.addRow(btn_pick)
        self.swatch = QLabel()
        self.swatch.setFixedSize(48, 20)
        self.swatch.setStyleSheet("background: #ccc; border: 1px solid #888;")
        form.addRow("選択色:", self.swatch)
        h = QHBoxLayout()
        self.tol_slider = QSlider(Qt.Horizontal)
        self.tol_slider.setRange(1, 100)
        self.tol_slider.setValue(20)
        self.tol_spin = QSpinBox()
        self.tol_spin.setRange(1, 100)
        self.tol_spin.setValue(20)
        self.tol_slider.valueChanged.connect(self.tol_spin.setValue)
        self.tol_spin.valueChanged.connect(self.tol_slider.setValue)
        self.tol_slider.valueChanged.connect(self._on_tolerance_changed)
        h.addWidget(self.tol_slider)
        h.addWidget(self.tol_spin)
        form.addRow("許容度:", h)
        self.preview_btn = QPushButton("マスク表示")
        self.preview_btn.setCheckable(True)
        self.preview_btn.toggled.connect(lambda _: self._update_preview())
        form.addRow(self.preview_btn)
        layout.addWidget(box)

        # --- ROI ---
        box = QGroupBox("ROIブラシ（検出範囲の限定）")
        form = QFormLayout(box)
        self.brush_spin = QSpinBox()
        self.brush_spin.setRange(2, 200)
        self.brush_spin.setValue(20)
        self.brush_spin.valueChanged.connect(
            lambda v: setattr(self.view, "brush_size", v)
        )
        form.addRow("ブラシサイズ:", self.brush_spin)
        btn_clear = QPushButton("ROIをクリア")
        btn_clear.clicked.connect(self.view.clear_roi)
        form.addRow(btn_clear)
        layout.addWidget(box)

        # --- 抽出設定 ---
        box = QGroupBox("抽出設定")
        form = QFormLayout(box)
        self.extract_combo = QComboBox()
        self.extract_combo.addItems(["線（リサンプリング）", "点（散布図・全検出）"])
        self.extract_combo.currentIndexChanged.connect(self._on_extract_type_changed)
        form.addRow("抽出タイプ:", self.extract_combo)
        self.axis_combo = QComboBox()
        self.axis_combo.addItems(["X方向", "Y方向"])
        form.addRow("分割方向:", self.axis_combo)
        self.npoints_spin = QSpinBox()
        self.npoints_spin.setRange(1, 10000)
        self.npoints_spin.setValue(50)
        form.addRow("データ点数:", self.npoints_spin)
        self.min_blob_spin = QSpinBox()
        self.min_blob_spin.setRange(1, 10000)
        self.min_blob_spin.setValue(5)
        self.min_blob_spin.setToolTip(
            "この面積(px)未満の塊はノイズとして無視します"
        )
        self.min_blob_spin.setEnabled(False)
        form.addRow("最小サイズ:", self.min_blob_spin)
        self.partial_check = QCheckBox("欠けたマーカーを補正")
        self.partial_check.setChecked(True)
        self.partial_check.setToolTip(
            "軸線などに一部を隠されたマーカーの中心を、\n"
            "完全な形のマーカーとの照合で推定します"
        )
        self.partial_check.setEnabled(False)
        form.addRow(self.partial_check)
        self.anchor_check = QCheckBox("基準位置を通す")
        self.anchor_check.setToolTip(
            "指定した位置（分割方向のデータ座標、例: x=0）を必ずサンプリングし、\n"
            "そこを基準に等間隔でグリッドを張ります。\n"
            "使用にはキャリブレーションが必要です。線抽出のみ。"
        )
        form.addRow(self.anchor_check)
        anchor_row = QHBoxLayout()
        self.anchor_edit = QLineEdit()
        self.anchor_edit.setPlaceholderText("基準値 (例: 0)")
        self.anchor_step_edit = QLineEdit()
        self.anchor_step_edit.setPlaceholderText("間隔 (例: 0.2)")
        self.anchor_step_edit.setToolTip(
            "サンプリング間隔をデータ座標で指定します。\n"
            "空欄の場合は「データ点数」から自動で決まります\n"
            "（その場合、間隔は中途半端な値になります）。"
        )
        anchor_row.addWidget(self.anchor_edit)
        anchor_row.addWidget(self.anchor_step_edit)
        form.addRow("基準値/間隔:", anchor_row)
        self.auto_detect_check = QCheckBox("自動再検出（チューニングモード）")
        self.auto_detect_check.setToolTip(
            "点数・間隔・基準値などを変えると即座に再検出します。\n"
            "選択中の系列の点は置き換えられるので、手動調整は最後に行ってください。"
        )
        form.addRow(self.auto_detect_check)
        btn_detect = QPushButton("検出実行")
        btn_detect.setStyleSheet("font-weight: bold;")
        btn_detect.clicked.connect(self._detect)
        form.addRow(btn_detect)
        layout.addWidget(box)

        # チューニングモード: 抽出設定の変更で自動再検出（デバウンス付き）
        self._detect_timer = QTimer(self)
        self._detect_timer.setSingleShot(True)
        self._detect_timer.setInterval(300)
        self._detect_timer.timeout.connect(lambda: self._detect(auto=True))
        self.npoints_spin.valueChanged.connect(self._schedule_detect)
        self.axis_combo.currentIndexChanged.connect(self._schedule_detect)
        self.extract_combo.currentIndexChanged.connect(self._schedule_detect)
        self.anchor_check.toggled.connect(self._schedule_detect)
        self.anchor_edit.textChanged.connect(self._schedule_detect)
        self.anchor_step_edit.textChanged.connect(self._schedule_detect)
        self.min_blob_spin.valueChanged.connect(self._schedule_detect)
        self.partial_check.toggled.connect(self._schedule_detect)
        self.tol_slider.valueChanged.connect(self._schedule_detect)

        # --- 編集ヒント / 出力 ---
        hint = QLabel(
            "モード切替: 1〜4 キー / 色取得: C\n"
            "点編集モード: クリック選択 / ドラッグ移動\n"
            "矢印キー: 1px 移動（Shift: 5px / Ctrl: 0.1px）\n"
            "Ctrl+クリック: 追加 / Del: 削除\n"
            "較正マーカー(X1〜Y2)も編集モードで移動可\n"
            "ホイール: ズーム / 中ドラッグ: パン\n"
            "L: ルーペ表示切替 / Ctrl+0: 全体表示"
        )
        hint.setStyleSheet("color: gray;")
        layout.addWidget(hint)

        btn_export = QPushButton("CSVエクスポート")
        btn_export.setStyleSheet("font-weight: bold;")
        btn_export.clicked.connect(self._export_csv)
        layout.addWidget(btn_export)

        layout.addStretch(1)

        scroll = QScrollArea()
        scroll.setWidget(panel)
        scroll.setWidgetResizable(True)
        scroll.setMinimumWidth(320)
        return scroll

    # ================= 画像入力 =================

    def _open_image(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "グラフ画像を開く",
            "",
            "画像ファイル (*.png *.jpg *.jpeg *.bmp *.gif *.tif *.tiff *.webp)",
        )
        if not path:
            return
        img = QImage(path)
        if img.isNull():
            QMessageBox.warning(self, "エラー", "画像を読み込めませんでした。")
            return
        self._set_image(img)

    def _paste_clipboard(self) -> None:
        img = QGuiApplication.clipboard().image()
        if img.isNull():
            self.statusBar().showMessage("クリップボードに画像がありません", 3000)
            return
        self._set_image(img)

    def _start_capture(self) -> None:
        self.hide()
        QTimer.singleShot(250, self._do_capture)

    def _do_capture(self) -> None:
        controller = CaptureController(self)
        controller.captured.connect(self._on_captured)
        controller.canceled.connect(self._on_capture_canceled)
        self._capture = controller  # GC 防止
        controller.start()

    def _on_captured(self, img: QImage) -> None:
        self._capture = None
        self.show()
        self.activateWindow()
        self._set_image(img)

    def _on_capture_canceled(self) -> None:
        self._capture = None
        self.show()
        self.activateWindow()

    def _set_image(self, qimg: QImage) -> None:
        qimg = qimg.convertToFormat(QImage.Format_RGB32)
        self.rgb = qimage_to_rgb(qimg)
        self._lab = None
        self.view.set_image(qimg)
        # 画像が変わると較正・点は無効
        self.cal = Calibration()
        self._cal_target = None
        for key in CAL_KEYS:
            self._cal_edits[key].clear()
        self._update_cal_status()
        self.statusBar().showMessage(
            f"画像を読み込みました ({qimg.width()} x {qimg.height()} px)。"
            "軸キャリブレーションを設定してください",
            6000,
        )

    # ================= モード =================

    def _set_mode(self, mode: str) -> None:
        self._cal_target = None
        self._cal_queue = []
        self.view.set_mode(mode)

    def _check_mode_button(self, mode: str) -> None:
        action = self._mode_actions.get(mode)
        if action is not None:
            action.setChecked(True)

    # ================= キャリブレーション =================

    def _arm_cal(self, key: str) -> None:
        if not self.view.has_image():
            self.statusBar().showMessage("先に画像を読み込んでください", 3000)
            return
        self._cal_target = key
        self._cal_queue = []
        self.view.set_mode(MODE_CAL)
        self.statusBar().showMessage(
            f"{key.upper()} の位置を画像上でクリックしてください"
        )

    def _arm_cal_sequence(self) -> None:
        """4点を連続してマウス指定するモード。"""
        if not self.view.has_image():
            self.statusBar().showMessage("先に画像を読み込んでください", 3000)
            return
        self._cal_target = None
        self._cal_queue = list(CAL_KEYS)
        self.view.set_mode(MODE_CAL)
        self.statusBar().showMessage(
            "連続指定 (1/4): X1 の位置をクリックしてください（モード切替でキャンセル）"
        )

    def _store_cal_point(self, key: str, x: float, y: float) -> None:
        axis = self.cal.x if key.startswith("x") else self.cal.y
        px = x if key.startswith("x") else y
        if key.endswith("1"):
            axis.p1 = px
        else:
            axis.p2 = px
        self.view.set_cal_marker(key, x, y)
        self._update_cal_status()

    def _on_cal_clicked(self, x: float, y: float) -> None:
        # 連続指定モード: キューを順に消化する
        if self._cal_queue:
            key = self._cal_queue.pop(0)
            self._store_cal_point(key, x, y)
            if self._cal_queue:
                nxt = self._cal_queue[0]
                done = len(CAL_KEYS) - len(self._cal_queue)
                self.statusBar().showMessage(
                    f"連続指定 ({done + 1}/4): {nxt.upper()} の位置をクリックしてください"
                )
            else:
                self.view.set_mode(MODE_PAN)
                self._check_mode_button(MODE_PAN)
                self.statusBar().showMessage(
                    "4点を設定しました。必要ならマーカー調整で微調整し、値を入力してください",
                    8000,
                )
            return
        # 単発指定モード
        key = self._cal_target
        if key is None:
            return
        self._store_cal_point(key, x, y)
        self._cal_target = None
        self.view.set_mode(MODE_PAN)
        self._check_mode_button(MODE_PAN)
        self._cal_edits[key].setFocus()
        self._cal_edits[key].selectAll()
        self.statusBar().showMessage(
            f"{key.upper()} を設定しました。実際の値を入力してください", 4000
        )

    def _on_cal_marker_moved(self, key: str, x: float, y: float) -> None:
        """編集モードで較正マーカーが動かされたら、較正のピクセル位置を追従させる。"""
        axis = self.cal.x if key.startswith("x") else self.cal.y
        px = x if key.startswith("x") else y
        if key.endswith("1"):
            axis.p1 = px
        else:
            axis.p2 = px
        self._update_cal_status()

    def _select_cal_marker(self, key: str) -> None:
        """パネルから較正マーカーを直接選択する（重なっていても確実に選べる）。"""
        if not self.view.select_cal_marker(key):
            self.statusBar().showMessage(
                f"{key.upper()} はまだ設定されていません。上のボタンで位置をクリックしてください",
                4000,
            )
            return
        self._check_mode_button(MODE_EDIT)
        self.statusBar().showMessage(
            f"{key.upper()} を選択しました。矢印キーで移動（Shift: 5px / Ctrl: 0.1px）",
            5000,
        )

    def _read_cal_values(self) -> None:
        for key in CAL_KEYS:
            text = self._cal_edits[key].text().strip()
            try:
                value = float(text) if text else None
            except ValueError:
                value = None
            axis = self.cal.x if key.startswith("x") else self.cal.y
            if key.endswith("1"):
                axis.v1 = value
            else:
                axis.v2 = value
        self._update_cal_status()

    def _update_cal_status(self) -> None:
        if self.cal.ready():
            self.cal_status.setText("キャリブレーション完了 ✓")
            self.cal_status.setStyleSheet("color: #2a2;")
        else:
            self.cal_status.setText("未設定（4点の位置と値が必要）")
            self.cal_status.setStyleSheet("color: gray;")

    # ================= 系列 =================

    def _current_series(self) -> Series | None:
        item = self.series_list.currentItem()
        if item is None:
            return None
        return item.data(Qt.UserRole)

    def _add_series(self) -> None:
        n = self.series_list.count() + 1
        series = Series(name=f"系列{n}")
        item = QListWidgetItem(series.name)
        item.setData(Qt.UserRole, series)
        item.setFlags(item.flags() | Qt.ItemIsEditable)
        item.setIcon(_swatch_icon(series.color))
        self.series_list.addItem(item)
        self.series_list.setCurrentItem(item)

    def _remove_series(self) -> None:
        row = self.series_list.currentRow()
        if row < 0:
            return
        item = self.series_list.takeItem(row)
        series = item.data(Qt.UserRole)
        self.view.remove_points(series)
        self._update_preview()

    def _on_series_changed(self, current, _previous) -> None:
        series = self._current_series()
        if series is None:
            return
        self.tol_slider.blockSignals(True)
        self.tol_spin.blockSignals(True)
        self.tol_slider.setValue(series.tolerance)
        self.tol_spin.setValue(series.tolerance)
        self.tol_slider.blockSignals(False)
        self.tol_spin.blockSignals(False)
        self._update_swatch(series)
        self._schedule_preview()

    def _update_swatch(self, series: Series) -> None:
        if series.color is not None:
            self.swatch.setStyleSheet(
                f"background: {series.color.name()}; border: 1px solid #888;"
            )
        else:
            self.swatch.setStyleSheet("background: #ccc; border: 1px solid #888;")
        item = self.series_list.currentItem()
        if item is not None and item.data(Qt.UserRole) is series:
            item.setIcon(_swatch_icon(series.color))

    # ================= 色検出 =================

    def _arm_pick(self) -> None:
        """色取得モードに入る（取得後は自動でパンモードへ戻る）。"""
        if not self.view.has_image():
            self.statusBar().showMessage("先に画像を読み込んでください", 3000)
            return
        if self._current_series() is None:
            self.statusBar().showMessage("系列を選択してください", 3000)
            return
        self._set_mode(MODE_PICK)
        self.statusBar().showMessage(
            "抽出したい線・点の色を画像上でクリックしてください"
        )

    def _lab_image(self) -> np.ndarray | None:
        if self.rgb is None:
            return None
        if self._lab is None:
            self._lab = detection.rgb_to_lab(self.rgb)
        return self._lab

    def _on_color_picked(self, x: int, y: int) -> None:
        series = self._current_series()
        if series is None or self.rgb is None:
            return
        h, w = self.rgb.shape[:2]
        if not (0 <= x < w and 0 <= y < h):
            return
        r, g, b = (int(v) for v in self.rgb[y, x])
        series.color = QColor(r, g, b)
        self._update_swatch(series)
        # 点の色も更新（系列色の補色マーカー）
        for item in self.view.points(series):
            item.refresh_color()
        if not self.preview_btn.isChecked():
            self.preview_btn.setChecked(True)  # フィードバックとして自動でマスク表示
        else:
            self._update_preview()
        # 取得したらパンモードへ戻る
        self._set_mode(MODE_PAN)
        self._check_mode_button(MODE_PAN)
        self.statusBar().showMessage(
            f"色を取得: RGB({r}, {g}, {b})", 4000
        )

    def _on_tolerance_changed(self, value: int) -> None:
        series = self._current_series()
        if series is not None:
            series.tolerance = value
        self._schedule_preview()

    def _compute_mask(self, series: Series) -> np.ndarray | None:
        lab = self._lab_image()
        if lab is None or series.color is None:
            return None
        mask = detection.color_mask(
            lab,
            (series.color.red(), series.color.green(), series.color.blue()),
            float(series.tolerance),
        )
        roi = self.view.roi_mask()
        if roi is not None:
            mask &= roi
        return mask

    def _schedule_preview(self) -> None:
        if self.preview_btn.isChecked():
            self._preview_timer.start()

    def _update_preview(self) -> None:
        if not self.preview_btn.isChecked():
            self.view.set_mask_overlay(None)
            return
        series = self._current_series()
        mask = self._compute_mask(series) if series is not None else None
        if mask is None:
            self.view.set_mask_overlay(None)
            return
        h, w = mask.shape
        overlay = np.zeros((h, w, 4), np.uint8)
        c = series.color
        overlay[mask] = (c.red(), c.green(), c.blue(), 140)
        self.view.set_mask_overlay(rgba_to_qimage(overlay))

    # ================= 検出 =================

    def _schedule_detect(self, *_args) -> None:
        """チューニングモード時、抽出設定の変更で再検出を予約する。"""
        if self.auto_detect_check.isChecked():
            self._detect_timer.start()

    def _detect_error(self, auto: bool, title: str, msg: str) -> None:
        if auto:
            self.statusBar().showMessage(msg.replace("\n", " "), 3000)
        else:
            QMessageBox.information(self, title, msg)

    def _detect(self, auto: bool = False) -> None:
        series = self._current_series()
        if series is None:
            return
        if not self.view.has_image():
            self.statusBar().showMessage("先に画像を読み込んでください", 3000)
            return
        if series.color is None:
            self._detect_error(
                auto, "色未選択", "「色を取得」で対象の色をクリックしてください。"
            )
            return
        mask = self._compute_mask(series)
        if mask is None or not mask.any():
            self._detect_error(
                auto,
                "検出なし",
                "マッチするピクセルがありません。許容度を上げるか色を選び直してください。",
            )
            return
        if self.extract_combo.currentIndex() == 0:
            # 線: 指定した点数にリサンプリング
            axis = "x" if self.axis_combo.currentIndex() == 0 else "y"
            # 基準位置（分割方向のデータ座標 → ピクセルインデックス座標）
            anchor_along = None
            if self.anchor_check.isChecked():
                try:
                    av = float(self.anchor_edit.text())
                except ValueError:
                    self._detect_error(
                        auto, "基準位置", "基準値を数値で入力してください。"
                    )
                    return
                if not self.cal.ready():
                    self._detect_error(
                        auto,
                        "基準位置",
                        "基準位置はデータ座標で指定するため、"
                        "先に軸キャリブレーションを完了してください。",
                    )
                    return
                axis_cal = self.cal.x if axis == "x" else self.cal.y
                anchor_along = axis_cal.to_px(av) - 0.5
            # 間隔（データ座標）→ ピクセル間隔
            anchor_step_px = None
            if anchor_along is not None and self.anchor_step_edit.text().strip():
                try:
                    step_data = float(self.anchor_step_edit.text())
                except ValueError:
                    self._detect_error(
                        auto, "基準位置", "間隔を数値で入力してください。"
                    )
                    return
                if step_data <= 0:
                    self._detect_error(
                        auto, "基準位置", "間隔は正の値で入力してください。"
                    )
                    return
                axis_cal = self.cal.x if axis == "x" else self.cal.y
                anchor_step_px = abs(
                    step_data * (axis_cal.p2 - axis_cal.p1) / (axis_cal.v2 - axis_cal.v1)
                )
            points = detection.trace_points(
                mask,
                self.npoints_spin.value(),
                axis,
                anchor=anchor_along,
                anchor_step=anchor_step_px,
            )
        else:
            # 点(散布図): 連結成分ごとに1点、全検出
            sim = None
            if self.partial_check.isChecked():
                # 連続一致度マップでソフト照合（アンチエイリアス縁に頑健）
                c = series.color
                sim = detection.color_similarity(
                    self._lab_image(),
                    (c.red(), c.green(), c.blue()),
                    float(series.tolerance),
                )
                roi = self.view.roi_mask()
                if roi is not None:
                    sim = sim * roi
            points = detection.detect_blobs(
                mask,
                self.min_blob_spin.value(),
                correct_partial=self.partial_check.isChecked(),
                sim=sim,
            )
        self.view.remove_points(series)
        for px, py in points:
            # 検出はピクセルインデックス座標 → 表示はピクセル中心 (+0.5)
            self.view.add_point(series, px + 0.5, py + 0.5)
        self.statusBar().showMessage(
            f"「{self._series_name(series)}」: {len(points)} 点を検出しました", 5000
        )

    def _on_extract_type_changed(self, index: int) -> None:
        is_line = index == 0
        self.axis_combo.setEnabled(is_line)
        self.npoints_spin.setEnabled(is_line)
        self.anchor_check.setEnabled(is_line)
        self.anchor_edit.setEnabled(is_line)
        self.anchor_step_edit.setEnabled(is_line)
        self.min_blob_spin.setEnabled(not is_line)
        self.partial_check.setEnabled(not is_line)

    def _series_name(self, series: Series) -> str:
        for i in range(self.series_list.count()):
            item = self.series_list.item(i)
            if item.data(Qt.UserRole) is series:
                return item.text()
        return series.name

    # ================= 手動編集 =================

    def _on_point_add(self, x: float, y: float) -> None:
        series = self._current_series()
        if series is None:
            self.statusBar().showMessage("系列を選択してください", 3000)
            return
        item = self.view.add_point(series, x, y)
        item.setSelected(True)

    def _on_scene_pos(self, x: float, y: float) -> None:
        msg = f"px: ({x:.1f}, {y:.1f})"
        if self.cal.ready():
            dx, dy = self.cal.to_data(x, y)
            msg += f"   data: ({dx:.6g}, {dy:.6g})"
        self.statusBar().showMessage(msg)

    # ================= プレビュー / エクスポート =================

    def _collect_series_data(self, use_cal: bool):
        """全系列の点を (表示名, 色, [(x, y), ...]) のリストで返す。"""
        out = []
        for i in range(self.series_list.count()):
            item = self.series_list.item(i)
            series = item.data(Qt.UserRole)
            pts = [(p.pos().x(), p.pos().y()) for p in self.view.points(series)]
            if not pts:
                continue
            if use_cal:
                data = [self.cal.to_data(px, py) for px, py in pts]
            else:
                data = pts
            color = series.color if series.color is not None else QColor(60, 130, 255)
            out.append((item.text(), color, data))
        return out

    def _show_preview(self) -> None:
        if self._preview_dialog is None:
            self._preview_dialog = PreviewDialog(
                self,
                lambda: (
                    self._collect_series_data(self.cal.ready()),
                    self.cal.ready(),
                ),
            )
        self._preview_dialog.refresh()
        self._preview_dialog.show()
        self._preview_dialog.raise_()
        self._preview_dialog.activateWindow()

    def _export_csv(self) -> None:
        use_cal = self.cal.ready()
        if not use_cal:
            reply = QMessageBox.question(
                self,
                "キャリブレーション未完了",
                "軸キャリブレーションが完了していません。\n"
                "ピクセル座標のまま出力しますか？",
                QMessageBox.Yes | QMessageBox.No,
            )
            if reply != QMessageBox.Yes:
                return

        columns: list[tuple[str, list[float]]] = []
        for name, _color, data in self._collect_series_data(use_cal):
            data = sorted(data, key=lambda t: t[0])
            columns.append((f"{name}_x", [d[0] for d in data]))
            columns.append((f"{name}_y", [d[1] for d in data]))

        if not columns:
            QMessageBox.information(self, "データなし", "出力する点がありません。")
            return

        path, _ = QFileDialog.getSaveFileName(
            self, "CSVを保存", "graph_data.csv", "CSVファイル (*.csv)"
        )
        if not path:
            return
        with open(path, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.writer(f)
            writer.writerow([name for name, _ in columns])
            for row in zip_longest(*(vals for _, vals in columns), fillvalue=""):
                writer.writerow(
                    [f"{v:.6g}" if isinstance(v, float) else v for v in row]
                )
        self.statusBar().showMessage(f"CSVを保存しました: {path}", 6000)
