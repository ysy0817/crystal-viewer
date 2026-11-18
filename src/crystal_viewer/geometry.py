"""三维旋转与斜投影。

坐标约定：晶格点按行向量存放，形状 (N, 3)，变换统一写作 ``点 @ 矩阵``，
因此这里的矩阵与教科书里"左乘列向量"的写法互为转置。

每个视图各自维护一个累积旋转矩阵，每帧左乘一次自旋矩阵，再叠加斜投影矩阵，
把三维晶格压到屏幕的 x/y 平面上 —— 这就是原程序里"四个方向环绕"的画法。
"""

from __future__ import annotations

import numpy as np

from .config import Config

__all__ = ["AXES", "SpinStep", "ViewGeometry", "build_views", "rotation_matrix"]

AXES = ("x", "y", "z")


def rotation_matrix(axis: str, degrees: float) -> np.ndarray:
    """返回绕指定坐标轴旋转的 3x3 矩阵（行向量约定）。"""
    if axis not in AXES:
        raise ValueError(f"未知的旋转轴 {axis!r}，只能是 x / y / z")
    rad = np.deg2rad(float(degrees))
    cos, sin = np.cos(rad), np.sin(rad)
    if axis == "z":
        return np.array([[cos, -sin, 0.0], [sin, cos, 0.0], [0.0, 0.0, 1.0]])
    if axis == "y":
        return np.array([[cos, 0.0, -sin], [0.0, 1.0, 0.0], [sin, 0.0, cos]])
    return np.array([[1.0, 0.0, 0.0], [0.0, cos, -sin], [0.0, sin, cos]])


class SpinStep:
    """一次旋转的描述（轴 + 角度），对应配置里的 ``{axis: x, deg: 2}``。"""

    __slots__ = ("axis", "deg", "matrix")

    def __init__(self, axis: str, deg: float) -> None:
        self.axis = axis
        self.deg = float(deg)
        self.matrix = rotation_matrix(axis, deg)

    @classmethod
    def from_config(cls, node: object) -> "SpinStep":
        return cls(str(getattr(node, "axis")), float(getattr(node, "deg")))  # type: ignore[attr-defined]

    def __repr__(self) -> str:  # pragma: no cover - 仅调试
        return f"SpinStep({self.axis}, {self.deg}°)"


class ViewGeometry:
    """单个视图：负责晶格点在屏幕上的二维偏移。"""

    __slots__ = ("_base", "_spin", "_oblique", "_rotation", "_angle_deg", "_spin_deg")

    def __init__(
        self,
        points: np.ndarray,
        spin: SpinStep,
        oblique: SpinStep,
        initial: SpinStep | None = None,
    ) -> None:
        points = np.asarray(points, dtype=float)
        if points.ndim != 2 or points.shape[1] != 3:
            raise ValueError(f"晶格点形状应为 (N, 3)，实际 {points.shape}")
        self._base = points @ (initial.matrix if initial is not None else np.eye(3))
        self._spin = spin.matrix
        self._spin_deg = spin.deg
        self._oblique = oblique.matrix
        self._rotation = np.eye(3)
        self._angle_deg = 0.0

    # -- 状态变换 ---------------------------------------------------------- #
    def advance(self, steps: int = 1) -> None:
        """推进旋转；默认每帧调用一次。"""
        for _ in range(steps):
            self._rotation = self._rotation @ self._spin
            self._angle_deg += self._spin_deg

    def reset(self) -> None:
        """回到初始姿态。"""
        self._rotation = np.eye(3)
        self._angle_deg = 0.0

    # -- 结果 -------------------------------------------------------------- #
    def points_3d(self) -> np.ndarray:
        """当前姿态下（未投影）的三维坐标，主要用于测试。"""
        return self._base @ self._rotation

    def projected_xy(self) -> np.ndarray:
        """投影到屏幕平面后的 (N, 2) 偏移量，可直接叠加到视图中心。"""
        return (self._base @ self._rotation @ self._oblique)[:, :2]

    def __repr__(self) -> str:  # pragma: no cover - 仅调试
        return f"ViewGeometry(累计旋转 {self._angle_deg:.1f}°)"


def build_views(config: Config, points: np.ndarray) -> list[ViewGeometry]:
    """按配置里的 ``views`` 列表构造各视图的几何状态。"""
    views: list[ViewGeometry] = []
    for view in config.views:
        views.append(
            ViewGeometry(
                points,
                spin=SpinStep.from_config(view.spin),
                oblique=SpinStep.from_config(view.oblique),
                initial=SpinStep.from_config(view.initial_rotation),
            )
        )
    return views
