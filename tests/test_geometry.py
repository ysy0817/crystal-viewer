"""旋转矩阵与投影的数学测试。"""

from __future__ import annotations

import numpy as np
import pytest

from crystal_viewer.config import load
from crystal_viewer.geometry import (
    AXES,
    SpinStep,
    ViewGeometry,
    build_views,
    rotation_matrix,
)
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_z90_maps_x_to_negative_y() -> None:
    # 行向量约定下，v @ R 与左乘写法方向相反，这里锁定实际行为。
    result = np.array([1.0, 0.0, 0.0]) @ rotation_matrix("z", 90)
    assert np.allclose(result, [0.0, -1.0, 0.0], atol=1e-9)


def test_rotation_preserves_length() -> None:
    point = np.array([1.0, 2.0, 3.0])
    for axis in AXES:
        for degree in (-37.5, 0.0, 2.0, 90.0, 123.0):
            moved = point @ rotation_matrix(axis, degree)
            assert np.isclose(np.linalg.norm(moved), np.linalg.norm(point), atol=1e-9)


def test_full_turn_returns_identity() -> None:
    matrix = np.eye(3)
    for _ in range(360):
        matrix = matrix @ rotation_matrix("x", 1.0)
    assert np.allclose(matrix, np.eye(3), atol=1e-6)


def test_unknown_axis_raises() -> None:
    with pytest.raises(ValueError, match="未知的旋转轴"):
        rotation_matrix("w", 10)


def test_advance_accumulates_spin() -> None:
    points = np.array([[1.0, 0.0, 0.0]])
    view = ViewGeometry(points, SpinStep("z", 90), SpinStep("z", 0))
    view.advance(2)
    assert np.allclose(view.points_3d(), [[-1.0, 0.0, 0.0]], atol=1e-9)


def test_initial_rotation_applied_at_construction() -> None:
    points = np.array([[1.0, 0.0, 0.0]])
    view = ViewGeometry(points, SpinStep("x", 0), SpinStep("x", 0), initial=SpinStep("z", 180))
    assert np.allclose(view.points_3d(), [[-1.0, 0.0, 0.0]], atol=1e-9)


def test_projection_drops_z_when_oblique_is_identity() -> None:
    points = np.array([[1.0, 2.0, 3.0], [-1.0, -2.0, -3.0]])
    view = ViewGeometry(points, SpinStep("x", 0), SpinStep("x", 0))
    projected = view.projected_xy()
    assert projected.shape == (2, 2)
    assert np.allclose(projected, view.points_3d()[:, :2])


def test_oblique_projection_shortens_vertical_offset() -> None:
    """斜投影应当把 z 分量折算到平面内，而不是简单丢弃。"""
    points = np.array([[0.0, 0.0, 10.0]])
    view = ViewGeometry(points, SpinStep("x", 0), SpinStep("x", 30))
    projected = view.projected_xy()
    assert not np.allclose(projected[0], [0.0, 0.0], atol=1e-9)


def test_build_views_from_config() -> None:
    config = load(ROOT / "config.yaml")
    points = np.array([[1.0, 1.0, 1.0]])
    views = build_views(config, points)
    assert len(views) == 4
    for view in views:
        assert view.projected_xy().shape == (1, 2)


def test_wrong_point_shape_raises() -> None:
    with pytest.raises(ValueError, match="晶格点形状"):
        ViewGeometry(np.zeros((4, 2)), SpinStep("x", 1), SpinStep("x", 1))
