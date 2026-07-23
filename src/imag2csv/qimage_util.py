"""QImage と numpy 配列の相互変換ユーティリティ。"""
from __future__ import annotations

import numpy as np
from PySide6.QtGui import QImage


def qimage_to_rgb(qimg: QImage) -> np.ndarray:
    """QImage を (H, W, 3) uint8 RGB 配列に変換する。"""
    img = qimg.convertToFormat(QImage.Format_RGB888)
    h, w = img.height(), img.width()
    bpl = img.bytesPerLine()
    buf = np.frombuffer(img.constBits(), np.uint8, h * bpl).reshape(h, bpl)
    return buf[:, : w * 3].reshape(h, w, 3).copy()


def qimage_alpha(qimg: QImage) -> np.ndarray:
    """QImage のアルファチャンネルを (H, W) uint8 配列で返す。"""
    img = qimg.convertToFormat(QImage.Format_ARGB32)
    h, w = img.height(), img.width()
    bpl = img.bytesPerLine()
    buf = np.frombuffer(img.constBits(), np.uint8, h * bpl).reshape(h, bpl)
    # リトルエンディアンでは ARGB32 のメモリ配置は B,G,R,A
    return buf[:, : w * 4].reshape(h, w, 4)[:, :, 3].copy()


def rgba_to_qimage(arr: np.ndarray) -> QImage:
    """(H, W, 4) uint8 RGBA 配列を QImage に変換する（データはコピー）。"""
    arr = np.ascontiguousarray(arr)
    h, w = arr.shape[:2]
    return QImage(arr.data, w, h, w * 4, QImage.Format_RGBA8888).copy()
