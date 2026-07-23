"""データモデル: 系列と軸キャリブレーション。"""
from __future__ import annotations

from dataclasses import dataclass, field

from PySide6.QtGui import QColor


@dataclass
class Series:
    """1本の曲線（データ系列）。抽出点は scene 上の PointItem が真のデータ。"""

    name: str
    color: QColor | None = None
    tolerance: int = 20


@dataclass
class LinearAxis:
    """1軸ぶんの線形キャリブレーション。p はピクセル座標、v はデータ値。"""

    p1: float | None = None
    v1: float | None = None
    p2: float | None = None
    v2: float | None = None

    def ready(self) -> bool:
        if None in (self.p1, self.v1, self.p2, self.v2):
            return False
        return self.p1 != self.p2 and self.v1 != self.v2

    def to_data(self, px: float) -> float:
        return self.v1 + (px - self.p1) * (self.v2 - self.v1) / (self.p2 - self.p1)

    def to_px(self, value: float) -> float:
        return self.p1 + (value - self.v1) * (self.p2 - self.p1) / (self.v2 - self.v1)


@dataclass
class Calibration:
    x: LinearAxis = field(default_factory=LinearAxis)
    y: LinearAxis = field(default_factory=LinearAxis)

    def ready(self) -> bool:
        return self.x.ready() and self.y.ready()

    def to_data(self, px: float, py: float) -> tuple[float, float]:
        return self.x.to_data(px), self.y.to_data(py)
