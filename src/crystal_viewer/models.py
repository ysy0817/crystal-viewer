"""晶胞模型：读取晶格点、棱线、介绍文本。

数据全部来自纯文本 CSV / TXT，因此新增一种晶胞不需要改代码，见 README。
"""

from __future__ import annotations

import csv
import logging
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from .config import Config, ConfigError

__all__ = [
    "CrystalModel",
    "DataError",
    "load_edges",
    "load_lattice",
    "load_models",
]

log = logging.getLogger(__name__)


class DataError(ConfigError):
    """数据文件缺失或内容非法。继承 ConfigError，便于统一捕获。"""


@dataclass(frozen=True)
class CrystalModel:
    """一种晶体晶胞的显示数据。"""

    key: str
    name: str
    edges: np.ndarray
    intro: str
    edges_path: Path
    intro_path: Path | None

    @property
    def edge_count(self) -> int:
        return int(self.edges.shape[0])


def _read_csv(path: Path) -> list[list[str]]:
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            rows = [
                [cell.strip() for cell in row]
                for row in csv.reader(handle)
                if any(cell.strip() for cell in row)
            ]
    except FileNotFoundError as exc:
        raise DataError(f"找不到数据文件: {path}") from exc
    except OSError as exc:
        raise DataError(f"无法读取数据文件 {path}: {exc}") from exc
    if len(rows) < 2:
        raise DataError(f"数据文件至少需要一行表头和一行数据: {path}")
    return rows


def _to_float(rows: list[list[str]], path: Path, skip_header: int = 1) -> np.ndarray:
    try:
        data = [[float(cell) for cell in row] for row in rows[skip_header:]]
    except ValueError as exc:
        raise DataError(f"数据文件含非数字内容 {path}: {exc}") from exc
    array = np.asarray(data, dtype=float)
    if array.ndim != 2:
        raise DataError(f"数据文件格式不一致（各行列数需相同）: {path}")
    if not np.isfinite(array).all():
        raise DataError(f"数据文件含 NaN 或无穷大: {path}")
    return array


def load_lattice(config: Config) -> np.ndarray:
    """读取晶格点坐标，返回形状为 (N, 3) 的 float 数组。

    文件格式：首行表头 ``x,y,z``，其后每行一个点的三个坐标（无量纲）。
    """
    path = config.path(config.data.lattice)
    rows = _read_csv(path)
    array = _to_float(rows, path)
    if array.shape[1] != 3:
        raise DataError(f"晶格点文件需要 3 列 x,y,z，实际 {array.shape[1]} 列: {path}")
    return array


def load_edges(path: Path) -> np.ndarray:
    """读取棱线连接表，返回形状为 (M, 2) 的整数索引数组。

    文件格式：首行表头 ``s1,s2``，其后每行为一条棱线两端点的晶格点编号（从 0 开始）。
    """
    rows = _read_csv(path)
    array = _to_float(rows, path)
    if array.shape[1] != 2:
        raise DataError(f"棱线文件需要 2 列 s1,s2，实际 {array.shape[1]} 列: {path}")
    if not np.allclose(array, np.round(array)):
        raise DataError(f"棱线文件的编号必须是整数: {path}")
    return array.astype(int)


def _read_intro(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8-sig").strip()
    except FileNotFoundError:
        log.warning("介绍文本不存在，将跳过语音介绍: %s", path)
        return ""
    except OSError as exc:  # pragma: no cover - 取决于文件系统
        log.warning("读取介绍文本失败 %s: %s", path, exc)
        return ""


def load_models(config: Config, point_count: int) -> list[CrystalModel]:
    """按 ``models.yaml`` 的顺序加载全部晶胞。

    Args:
        config: 已加载的配置。
        point_count: 晶格点总数，用于校验棱线索引是否越界。

    Raises:
        DataError: 清单缺失、条目为空、索引越界等情况。
    """
    spec_path = config.path(config.models_file)
    try:
        import yaml
    except ImportError as exc:  # pragma: no cover - 安装依赖时已保证
        raise DataError("需要 PyYAML，请先执行 pip install -r requirements.txt") from exc

    try:
        raw = spec_path.read_text(encoding="utf-8-sig")
    except FileNotFoundError as exc:
        raise DataError(f"找不到晶胞清单: {spec_path}") from exc
    try:
        spec = yaml.safe_load(raw) or {}
    except yaml.YAMLError as exc:
        raise DataError(f"晶胞清单 {spec_path} 格式有误:\n{exc}") from exc

    entries = spec.get("models")
    if not isinstance(entries, list) or not entries:
        raise DataError(f"晶胞清单 {spec_path} 里需要一个非空的 models: 列表")

    edges_dir = config.path(config.data.edges_dir)
    intro_dir = config.path(config.data.intro_dir)
    models: list[CrystalModel] = []
    seen: set[str] = set()

    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            raise DataError(f"models[{index}] 必须是一组键值对")
        key = str(entry.get("key") or "").strip()
        if not key:
            raise DataError(f"models[{index}] 缺少 key")
        if key in seen:
            raise DataError(f"models 里的 key 重复: {key}")
        seen.add(key)

        name = str(entry.get("name") or key).strip()
        edges_path = config.path(entry.get("edges") or edges_dir / f"{key}.csv")
        intro_path = config.path(entry.get("intro") or intro_dir / f"{key}.txt")

        edges = load_edges(edges_path)
        if edges.size:
            highest = int(edges.max())
            if highest >= point_count:
                raise DataError(
                    f"{edges_path.name} 引用了第 {highest} 号晶格点，"
                    f"但晶格点文件只有 {point_count} 个（编号 0~{point_count - 1}）"
                )

        intro = _read_intro(intro_path) if intro_path.is_file() else ""
        models.append(
            CrystalModel(
                key=key,
                name=name,
                edges=edges,
                intro=intro,
                edges_path=edges_path,
                intro_path=intro_path if intro_path.is_file() else None,
            )
        )

    hotkeys = len(config.keyboard.model_keys)
    if len(models) > hotkeys:
        log.warning(
            "晶胞数量 %d 超过可用快捷键 %d 个，多出的晶胞只能用语音/MQTT 切换",
            len(models),
            hotkeys,
        )
    return models
