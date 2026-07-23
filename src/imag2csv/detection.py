"""色検出とリサンプリング。"""
from __future__ import annotations

import math

import cv2
import numpy as np


def rgb_to_lab(rgb: np.ndarray) -> np.ndarray:
    """(H, W, 3) uint8 RGB → float32 Lab (L: 0-100, a/b: -127-127)。"""
    return cv2.cvtColor(rgb.astype(np.float32) / 255.0, cv2.COLOR_RGB2Lab)


def color_to_lab(rgb_color: tuple[int, int, int]) -> np.ndarray:
    pixel = np.array([[rgb_color]], dtype=np.float32) / 255.0
    return cv2.cvtColor(pixel, cv2.COLOR_RGB2Lab)[0, 0]


def color_mask(
    lab: np.ndarray, rgb_color: tuple[int, int, int], tolerance: float
) -> np.ndarray:
    """Lab 距離 (ΔE, CIE76) が tolerance 以下のピクセルを True とするマスク。"""
    target = color_to_lab(rgb_color)
    dist = np.linalg.norm(lab - target, axis=2)
    return dist <= tolerance


def color_similarity(
    lab: np.ndarray, rgb_color: tuple[int, int, int], tolerance: float
) -> np.ndarray:
    """連続的な色一致度マップ (0..1, float32)。ΔE=0 で 1、ΔE=tolerance で 0。

    アンチエイリアスされたマーカー縁も部分的な重みとして扱えるため、
    二値マスクよりテンプレート照合の位置精度が出る。
    """
    target = color_to_lab(rgb_color)
    dist = np.linalg.norm(lab - target, axis=2)
    return np.clip(1.0 - dist / float(tolerance), 0.0, 1.0).astype(np.float32)


_PATCH_MARGIN = 2  # ブロブ周辺のソフト縁を含める余白 (px)


def detect_blobs(
    mask: np.ndarray,
    min_size: int = 5,
    correct_partial: bool = True,
    sim: np.ndarray | None = None,
) -> list[tuple[float, float]]:
    """散布図向け: マスクの連結成分（マーカーの塊）ごとに中心を1点として返す。

    サンプル数の指定は不要で、適合した点をすべて検出する。
    min_size 未満の面積の成分はノイズとして無視する。

    correct_partial=True のとき、軸線・グリッド線などに一部を隠されたマーカー
    （面積が中央値より明らかに小さいブロブ）は、完全な形のマーカーを
    テンプレートとして最も一致する位置から真の中心を推定する。
    単純な重心だと隠れていない側へ偏るのを補正できる。
    マーカーが線で2つに分断された場合は補正後に近接点を統合する。

    sim に color_similarity() の連続一致度マップを渡すと、二値照合で求めた
    整数アライメントを、可視領域内の一致度モーメント差でサブピクセル精度に
    微調整する（アンチエイリアス縁の情報を利用。合成テストで誤差 0.5px → 0.02px）。

    戻り値は (px_x, px_y) のリスト（ピクセルインデックス座標）。
    """
    n, labels, stats, centroids = cv2.connectedComponentsWithStats(
        mask.astype(np.uint8), connectivity=8
    )
    idxs = [i for i in range(1, n) if stats[i, cv2.CC_STAT_AREA] >= min_size]
    if not idxs:
        return []
    areas = stats[idxs, cv2.CC_STAT_AREA].astype(float)
    med_area = float(np.median(areas))
    height, width = mask.shape
    # マーカー形状の統計を取るには数が要る
    do_correct = correct_partial and len(idxs) >= 3

    def blob_patch(i: int, soft: bool) -> tuple[np.ndarray, int, int]:
        """ブロブ i 周辺のパッチ（他ブロブの画素は除去）と原点を返す。"""
        x = int(stats[i, cv2.CC_STAT_LEFT])
        y = int(stats[i, cv2.CC_STAT_TOP])
        w = int(stats[i, cv2.CC_STAT_WIDTH])
        h = int(stats[i, cv2.CC_STAT_HEIGHT])
        x0 = max(0, x - _PATCH_MARGIN)
        y0 = max(0, y - _PATCH_MARGIN)
        x1 = min(width, x + w + _PATCH_MARGIN)
        y1 = min(height, y + h + _PATCH_MARGIN)
        lab_patch = labels[y0:y1, x0:x1]
        if soft and sim is not None:
            patch = sim[y0:y1, x0:x1].copy()
        else:
            patch = (lab_patch == i).astype(np.float32)
        patch[(lab_patch != 0) & (lab_patch != i)] = 0.0
        return patch, x0, y0

    if do_correct:
        # 面積が中央値に最も近いブロブを「完全な形」のテンプレートとする
        ref = idxs[int(np.argmin(np.abs(areas - med_area)))]
        tmpl_b, _tx0, _ty0 = blob_patch(ref, soft=False)  # 位置合わせ用（二値）
        tmpl_s, _, _ = blob_patch(ref, soft=True)  # 中心・微調整用（ソフト）
        th, tw = tmpl_b.shape
        ys_i, xs_i = np.indices(tmpl_b.shape)
        # テンプレート中心 = 一致度の重み付き重心
        mass = float(tmpl_s.sum())
        tcx = float((tmpl_s * xs_i).sum()) / mass
        tcy = float((tmpl_s * ys_i).sum()) / mass

    results: list[tuple[float, float, float]] = []  # (cx, cy, area)
    for i in idxs:
        area = float(stats[i, cv2.CC_STAT_AREA])
        cx, cy = float(centroids[i][0]), float(centroids[i][1])
        if do_correct and area < 0.85 * med_area:
            patch_b, x0, y0 = blob_patch(i, soft=False)
            ph, pw = patch_b.shape
            # パッチの周囲にテンプレート分の余白を確保したキャンバスで二値照合
            canvas = np.zeros((ph + 2 * th, pw + 2 * tw), np.float32)
            canvas[th : th + ph, tw : tw + pw] = patch_b
            res = cv2.matchTemplate(canvas, tmpl_b, cv2.TM_CCORR)
            _, maxv, _, _ = cv2.minMaxLoc(res)
            # 最大値近傍の平坦部は平均位置を取る（端に寄るバイアスを防ぐ）
            locs = np.argwhere(res >= maxv - 0.5)
            oyf, oxf = locs.mean(axis=0)
            cx = (x0 - tw) + float(oxf) + tcx
            cy = (y0 - th) + float(oyf) + tcy
            if sim is not None:
                # サブピクセル微調整: 整数アライメント位置で、可視領域の
                # 一致度重心とテンプレート側の対応重心の差を加える
                oy, ox = int(round(float(oyf))), int(round(float(oxf)))
                patch_s, _, _ = blob_patch(i, soft=True)
                canvas_s = np.zeros_like(canvas)
                canvas_s[th : th + ph, tw : tw + pw] = patch_s
                sub = canvas_s[oy : oy + th, ox : ox + tw]
                support = (sub > 0) & (tmpl_s > 0)
                if support.sum() > 4:
                    w_o = sub * support
                    w_t = tmpl_s * support
                    dx = float((w_o * xs_i).sum() / w_o.sum()
                               - (w_t * xs_i).sum() / w_t.sum())
                    dy = float((w_o * ys_i).sum() / w_o.sum()
                               - (w_t * ys_i).sum() / w_t.sum())
                    cx = (x0 - tw) + ox + tcx + dx
                    cy = (y0 - th) + oy + tcy + dy
        results.append((cx, cy, area))

    if do_correct:
        # 線で分断されたマーカーの断片同士を統合（面積の大きい断片を優先）
        r_med = (med_area / np.pi) ** 0.5
        results.sort(key=lambda t: -t[2])
        kept: list[tuple[float, float, float]] = []
        for cx, cy, area in results:
            if any(
                (cx - kx) ** 2 + (cy - ky) ** 2 < r_med**2 for kx, ky, _ in kept
            ):
                continue
            kept.append((cx, cy, area))
        results = kept

    return [(cx, cy) for cx, cy, _ in results]


def trace_points(
    mask: np.ndarray,
    n: int,
    axis: str = "x",
    anchor: float | None = None,
    anchor_step: float | None = None,
    gap: int = 3,
) -> list[tuple[float, float]]:
    """マスクの True ピクセルを axis 方向のグリッド位置でサンプリングして返す。

    グリッドは検出範囲の両端を含む等間隔 n 点（anchor 指定時は anchor が
    グリッド上に乗るよう整列し、範囲を等間隔で埋める。anchor_step を
    与えるとその間隔[px]を使い、n は無視される）。
    各サンプル位置では ±1px の狭い窓だけを見る（空なら段階的に拡大、
    最大±4px）ため、ビン平均で谷・山の頂点が「弦の内側」へ浮くバイアスがない。
    窓内のピクセルは直交方向のギャップ (> gap px) でクラスタに分け、
    直前のサンプルで選んだ枝に最も近いクラスタの重心を取る（連続性追跡）。

    戻り値は (px_x, px_y) のリスト。ピクセルが見つからない位置はスキップ。
    """
    ys, xs = np.nonzero(mask)
    if xs.size == 0:
        return []
    if axis == "x":
        coord, other = xs, ys
    else:
        coord, other = ys, xs
    lo, hi = float(coord.min()), float(coord.max())
    n = max(1, int(n))
    if anchor is not None and anchor_step is not None and anchor_step > 0:
        step = float(anchor_step)  # 間隔をデータ側から明示指定
    else:
        step = (hi - lo) / max(1, n - 1)
    if step <= 0:
        step = 1.0
    if anchor is not None:
        # 軸線が線の端を上書きして検出範囲が僅かに狭まっても、
        # 基準位置そのものがグリッドから漏れないよう範囲を少し外側まで許す
        margin = max(2.0, step / 2)
        kmin = math.ceil((lo - margin - anchor) / step - 1e-9)
        kmax = math.floor((hi + margin - anchor) / step + 1e-9)
        centers = [anchor + k * step for k in range(kmin, kmax + 1)]
    else:
        centers = list(np.linspace(lo, hi, n)) if n > 1 else [(lo + hi) / 2]

    max_half = max(1.0, step / 2)
    points: list[tuple[float, float]] = []
    prev: float | None = None
    for c in centers:
        # 狭い窓から始めて、空なら段階的に広げる（破線・かすれ・端の欠け対応）
        half = 1.0
        sel = None
        while half <= max(4.0, max_half * 2):
            sel = (coord >= c - half) & (coord <= c + half)
            if sel.any():
                break
            half *= 2
        if sel is None or not sel.any():
            continue
        o_sel = other[sel]
        c_sel = coord[sel]
        order = np.argsort(o_sel)
        o_sorted = o_sel[order]
        c_sorted = c_sel[order]
        # 直交方向のギャップでクラスタ分割
        breaks = np.nonzero(np.diff(o_sorted) > gap)[0]
        groups = np.split(np.arange(o_sorted.size), breaks + 1)
        if prev is None:
            g = max(groups, key=len)  # 初回は最大クラスタ
        else:
            g = min(groups, key=lambda gi: abs(float(o_sorted[gi].mean()) - prev))
        oc = float(o_sorted[g].mean())
        # 基準位置モードではグリッド位置をそのまま座標にする
        # （基準値・間隔・等間隔がデータ座標で正確に保たれる）
        cc = float(c) if anchor is not None else float(c_sorted[g].mean())
        prev = oc
        points.append((cc, oc) if axis == "x" else (oc, cc))
    return points
