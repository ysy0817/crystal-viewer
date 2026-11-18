"""晶胞数据加载测试。"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from crystal_viewer.config import load
from crystal_viewer.models import DataError, load_edges, load_lattice, load_models

ROOT = Path(__file__).resolve().parents[1]

EXPECTED_KEYS = [
    "simple_cubic",
    "cscl_bcc",
    "zns_fcc",
    "nacl_fcc",
    "hcp_ab",
    "cu_fcc",
    "caf2",
]


def _make_project(tmp_path: Path, edge_line: str = "0,1", intro: bool = True) -> Path:
    (tmp_path / "data" / "edges").mkdir(parents=True)
    (tmp_path / "data" / "intro").mkdir(parents=True)
    (tmp_path / "data" / "lattice.csv").write_text("x,y,z\n0,0,0\n1,0,0\n", encoding="utf-8")
    (tmp_path / "data" / "edges" / "demo.csv").write_text(
        f"s1,s2\n{edge_line}\n", encoding="utf-8"
    )
    if intro:
        (tmp_path / "data" / "intro" / "demo.txt").write_text("介绍文字", encoding="utf-8")
    (tmp_path / "models.yaml").write_text(
        "models:\n  - key: demo\n    name: 演示晶胞\n", encoding="utf-8"
    )
    config_path = tmp_path / "config.yaml"
    config_path.write_text("data:\n  lattice: data/lattice.csv\n", encoding="utf-8")
    return config_path


def test_lattice_shape_and_range() -> None:
    config = load(ROOT / "config.yaml")
    points = load_lattice(config)
    assert points.ndim == 2
    assert points.shape[1] == 3
    assert points.shape[0] >= 8
    assert np.all(np.abs(points) <= 1.0 + 1e-9)


def test_models_follow_manifest_order() -> None:
    config = load(ROOT / "config.yaml")
    points = load_lattice(config)
    models = load_models(config, point_count=len(points))
    assert [model.key for model in models] == EXPECTED_KEYS
    for model in models:
        assert model.name
        assert model.edge_count > 0
        assert int(model.edges.max()) < len(points)
        assert model.intro, f"{model.key} 缺少介绍文本"


def test_edges_are_integer_pairs() -> None:
    edges = load_edges(ROOT / "data" / "edges" / "simple_cubic.csv")
    assert edges.dtype.kind == "i"
    assert edges.shape[1] == 2
    assert edges.shape[0] == 12  # 立方体 12 条棱


def test_out_of_range_edge_index_raises(tmp_path: Path) -> None:
    config_path = _make_project(tmp_path, edge_line="0,5")
    config = load(config_path)
    points = load_lattice(config)
    with pytest.raises(DataError, match="引用了第 5 号晶格点"):
        load_models(config, point_count=len(points))


def test_missing_intro_only_warns(tmp_path: Path) -> None:
    config_path = _make_project(tmp_path, intro=False)
    config = load(config_path)
    models = load_models(config, point_count=2)
    assert models[0].intro == ""
    assert models[0].intro_path is None


def test_missing_edges_file_raises(tmp_path: Path) -> None:
    config_path = _make_project(tmp_path)
    (tmp_path / "data" / "edges" / "demo.csv").unlink()
    config = load(config_path)
    with pytest.raises(DataError, match="找不到数据文件"):
        load_models(config, point_count=2)


def test_duplicate_key_raises(tmp_path: Path) -> None:
    config_path = _make_project(tmp_path)
    (tmp_path / "models.yaml").write_text(
        "models:\n  - key: demo\n  - key: demo\n", encoding="utf-8"
    )
    config = load(config_path)
    with pytest.raises(DataError, match="重复"):
        load_models(config, point_count=2)
