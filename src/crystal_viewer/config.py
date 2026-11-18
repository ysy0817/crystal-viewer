"""配置加载。

优先级（后者覆盖前者）::

    代码内置默认值  <  config.yaml  <  keys.yaml  <  环境变量

``config.yaml`` 是公开的主配置，里面的密钥字段一律留空；
``keys.yaml`` 专门存放 API Key、账号密码，已被 .gitignore 忽略。

环境变量写法为 ``CRYSTAL_<SECTION>__<KEY>``，双下划线分隔层级，例如::

    CRYSTAL_RENDER__LINE_WIDTH=4
    CRYSTAL_ASR__API_KEY=xxxx

此外，配置值里形如 ``${VAR}`` 的字符串会被替换为同名环境变量的值，
方便在 CI / 服务器上注入密钥。
"""

from __future__ import annotations

import copy
import os
import re
from collections.abc import Iterator, Mapping
from pathlib import Path
from typing import Any

import yaml

__all__ = ["Config", "ConfigError", "apply_overrides", "load", "load_config"]


class ConfigError(RuntimeError):
    """配置文件缺失、格式错误或参数取值非法。"""


#: 内置默认值。缺少 config.yaml 时也能运行，同时让配置项有明确的类型。
DEFAULTS: dict[str, Any] = {
    "window": {
        "width": 1920,
        "height": 1080,
        "title": "晶体结构演示",
        "resizable": True,
        "fullscreen": False,
        "background": "black",
        "fps": 60,
    },
    "render": {
        "scale": 100,
        "line_width": 2,
        "point_radius": 5,
        "font_name": "simhei",
        "font_size": 24,
        "label_flip_vertical": True,
        "line_color": 0xFFFFFF,
        "point_color": 0xFF0000,
        "text_color": 0xFFFFFF,
        "line_fade_step": 0x111111,
        "point_fade_step": 0x110000,
        "text_fade_step": 0x111111,
    },
    "views": [
        {
            "offset": [300, 0],
            "label_offset": [350, 0],
            "label_rotation": 90,
            "initial_rotation": {"axis": "z", "deg": 0},
            "spin": {"axis": "x", "deg": 2},
            "oblique": {"axis": "y", "deg": 30},
        },
        {
            "offset": [-300, 0],
            "label_offset": [-350, 0],
            "label_rotation": 270,
            "initial_rotation": {"axis": "z", "deg": 180},
            "spin": {"axis": "x", "deg": 2},
            "oblique": {"axis": "y", "deg": -30},
        },
        {
            "offset": [0, 300],
            "label_offset": [0, 185],
            "label_rotation": 0,
            "initial_rotation": {"axis": "z", "deg": 270},
            "spin": {"axis": "y", "deg": 2},
            "oblique": {"axis": "x", "deg": 30},
        },
        {
            "offset": [0, -300],
            "label_offset": [0, -185],
            "label_rotation": 0,
            "initial_rotation": {"axis": "z", "deg": 90},
            "spin": {"axis": "y", "deg": 2},
            "oblique": {"axis": "x", "deg": -30},
        },
    ],
    "keyboard": {
        "enabled": True,
        "quit_key": "escape",
        "model_keys": [
            "f1", "f2", "f3", "f4", "f5", "f6",
            "f7", "f8", "f9", "f10", "f11",
        ],
        "voice_key": None,
    },
    "gesture": {
        "enabled": True,
        "camera_index": 0,
        "mirror": False,
        "landmark": 15,
        "min_visibility": 0.8,
        "warmup_frames": 10,
        "move_scale": 10,
        "switch_threshold": 2.0,
        "show_window": True,
    },
    "voice": {
        "enabled": True,
        "duration": 5,
        "sample_rate": 16000,
        "channels": 1,
        "chunk_size": 1024,
        "audio_file": "output.wav",
        "next_phrases": ["下一个", "下一个。"],
        "prev_phrases": ["上一个", "上一个。"],
    },
    "asr": {
        "dev_pid": 1537,
        "url": "http://vop.baidu.com/server_api",
        "scope": "audio_voice_assistant_get",
        "api_key": "",
        "secret_key": "",
        "cuid": "117158949",
    },
    "tts": {
        "enabled": True,
        "spd": 5,
        "pit": 5,
        "vol": 5,
        "per": 5003,
        "lan": "zh",
        "aue": 3,
        "url": "https://tsn.baidu.com/text2audio",
        "api_key": "",
        "secret_key": "",
        "cuid": "Vlw1AHr92vqnaLUH8iqwedfUM3ITilDV",
    },
    "mqtt": {
        "enabled": True,
        "host": "iot.dfrobot.com.cn",
        "port": 1883,
        "topic": "",
        "username": "",
        "password": "",
        "keepalive": 60,
        "commands": {
            "next": "+1",
            "previous": "-1",
            "listen": "turn",
            "introduce": "introduce",
        },
    },
    "models_file": "models.yaml",
    "data": {
        "lattice": "data/lattice/unit_cell_points.csv",
        "edges_dir": "data/edges",
        "intro_dir": "data/intro",
    },
}

_ENV_PREFIX = "CRYSTAL_"
_ENV_SEP = "__"
_PLACEHOLDER = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")

#: 存放密钥的私有配置文件名（与 config.yaml 同目录，已在 .gitignore 中忽略）
_KEYS_FILENAME = "keys.yaml"

_TRUE = {"1", "true", "yes", "on", "y"}
_FALSE = {"0", "false", "no", "off", "n", ""}


# --------------------------------------------------------------------------- #
# 工具函数
# --------------------------------------------------------------------------- #
def _deep_merge(base: dict[str, Any], override: Mapping[str, Any]) -> dict[str, Any]:
    """递归合并字典；override 中的列表整体替换 base 中的列表。"""
    result = copy.deepcopy(base)
    for key, value in override.items():
        if isinstance(value, Mapping) and isinstance(result.get(key), Mapping):
            result[key] = _deep_merge(dict(result[key]), value)
        else:
            result[key] = copy.deepcopy(value)
    return result


def _coerce(raw: str, template: Any) -> Any:
    """按默认值的类型把环境变量字符串转成对应类型。"""
    if isinstance(template, bool):
        lowered = raw.strip().lower()
        if lowered in _TRUE:
            return True
        if lowered in _FALSE:
            return False
        raise ConfigError(f"环境变量取值无法识别为布尔值: {raw!r}")
    if isinstance(template, int):
        try:
            return int(raw)
        except ValueError as exc:
            raise ConfigError(f"环境变量取值无法识别为整数: {raw!r}") from exc
    if isinstance(template, float):
        try:
            return float(raw)
        except ValueError as exc:
            raise ConfigError(f"环境变量取值无法识别为数字: {raw!r}") from exc
    if isinstance(template, (list, tuple)) and "," in raw:
        return [item.strip() for item in raw.split(",")]
    return raw


def _set_by_path(tree: dict[str, Any], path: list[str], value: Any) -> None:
    node = tree
    for part in path[:-1]:
        child = node.get(part)
        if not isinstance(child, dict):
            return  # 路径在默认值里不存在，忽略该环境变量
        node = child
    if path[-1] in node:
        node[path[-1]] = _coerce(value, node[path[-1]])


def _expand_env(value: Any) -> Any:
    """把字符串里的 ${VAR} 替换为环境变量值（未设置则替换为空串）。"""
    if isinstance(value, str):
        return _PLACEHOLDER.sub(lambda m: os.environ.get(m.group(1), ""), value)
    if isinstance(value, Mapping):
        return {k: _expand_env(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_expand_env(item) for item in value]
    return value


def _read_yaml(path: Path) -> dict[str, Any]:
    try:
        text = path.read_text(encoding="utf-8-sig")
    except OSError as exc:
        raise ConfigError(f"无法读取配置文件 {path}: {exc}") from exc
    try:
        loaded = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise ConfigError(f"配置文件 {path} 格式有误（注意冒号后要有空格）:\n{exc}") from exc
    if loaded is None:
        return {}
    if not isinstance(loaded, dict):
        raise ConfigError(f"配置文件 {path} 的顶层必须是键值对")
    return loaded


# --------------------------------------------------------------------------- #
# 配置对象
# --------------------------------------------------------------------------- #
class _NodeList(list):
    """列表节点：把列表里的字典也包装成 ``_Node``，保证 ``views[0].offset`` 可用。"""

    __slots__ = ()

    def __init__(self, values: Any) -> None:
        super().__init__(_wrap(value) for value in values)

    def __getitem__(self, index: Any) -> Any:
        return _wrap(list.__getitem__(self, index))


def _wrap(value: Any) -> Any:
    """把 dict / list 递归包装成支持点号访问的节点。"""
    if isinstance(value, Mapping):
        return _Node(value)
    if isinstance(value, list):
        return _NodeList(value)
    return value


class _Node(Mapping[str, Any]):
    """支持 ``node.key`` 与 ``node["key"]`` 两种访问方式的只读节点。"""

    __slots__ = ("_data",)

    def __init__(self, data: Mapping[str, Any]) -> None:
        object.__setattr__(self, "_data", data)

    def __getattr__(self, name: str) -> Any:
        if name.startswith("_"):
            raise AttributeError(name)
        try:
            value = self._data[name]
        except KeyError:
            raise AttributeError(
                f"配置项不存在: {name}（可用项: {', '.join(self._data)}）"
            ) from None
        return _wrap(value)

    def __getitem__(self, key: Any) -> Any:
        if isinstance(key, int):
            raise TypeError("_Node 是映射，请用键名访问；列表请用索引访问 _NodeList")
        return _wrap(self._data[key])

    def __iter__(self) -> Iterator[str]:
        return iter(self._data)

    def __len__(self) -> int:
        return len(self._data)

    def __contains__(self, key: object) -> bool:
        return key in self._data

    def as_dict(self) -> dict[str, Any]:
        return copy.deepcopy(dict(self._data))

    def __repr__(self) -> str:  # pragma: no cover - 仅用于调试
        return f"配置({dict(self._data)!r})"


class Config(_Node):
    """加载完成的配置，并记录项目根目录与来源文件。"""

    __slots__ = ("_root", "_source")

    def __init__(self, data: Mapping[str, Any], root: Path, source: Path) -> None:
        super().__init__(data)
        object.__setattr__(self, "_root", root.resolve())
        object.__setattr__(self, "_source", source)

    @property
    def root(self) -> Path:
        """项目根目录（配置文件所在目录），所有相对路径都相对它解析。"""
        return self._root

    @property
    def source(self) -> Path:
        """主配置文件的路径。"""
        return self._source

    def path(self, value: str | os.PathLike[str]) -> Path:
        """把配置里的相对路径解析为绝对路径（相对项目根目录）。"""
        candidate = Path(value).expanduser()
        return candidate if candidate.is_absolute() else (self._root / candidate)

    def section(self, name: str) -> _Node:
        return self[name]


# --------------------------------------------------------------------------- #
# 校验
# --------------------------------------------------------------------------- #
def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ConfigError(message)


def _is_color(value: Any) -> bool:
    return isinstance(value, int) and 0 <= value <= 0xFFFFFF


def validate(config: Config) -> None:
    """对关键参数做范围检查，尽早给出可读的错误提示。"""
    width = config.window.width
    height = config.window.height
    _require(isinstance(width, int) and width >= 320, f"window.width 至少为 320，当前 {width!r}")
    _require(isinstance(height, int) and height >= 240, f"window.height 至少为 240，当前 {height!r}")
    _require(isinstance(config.window.fps, int) and config.window.fps > 0, "window.fps 必须为正整数")

    render = config.render
    _require(isinstance(render.scale, (int, float)) and render.scale > 0, "render.scale 必须大于 0")
    for name in ("line_color", "point_color", "text_color"):
        _require(_is_color(getattr(render, name)), f"render.{name} 必须是 0x000000~0xFFFFFF 的整数")
    for name in ("line_width", "point_radius", "font_size"):
        value = getattr(render, name)
        _require(isinstance(value, int) and value > 0, f"render.{name} 必须为正整数")

    views = config.views
    _require(len(views) > 0, "views 至少要配置一个视图")
    for index, view in enumerate(views):
        _require(
            isinstance(view.offset, (list, tuple)) and len(view.offset) == 2,
            f"views[{index}].offset 必须是 [x, y] 两个数字",
        )
        axis = view.spin.axis
        _require(axis in {"x", "y", "z"}, f"views[{index}].spin.axis 只能是 x / y / z，当前 {axis!r}")
        axis = view.oblique.axis
        _require(axis in {"x", "y", "z"}, f"views[{index}].oblique.axis 只能是 x / y / z，当前 {axis!r}")

    _require(len(config.keyboard.model_keys) > 0, "keyboard.model_keys 不能为空")
    _require(
        isinstance(config.gesture.switch_threshold, (int, float))
        and config.gesture.switch_threshold > 0,
        "gesture.switch_threshold 必须大于 0",
    )
    _require(
        isinstance(config.voice.sample_rate, int) and config.voice.sample_rate > 0,
        "voice.sample_rate 必须为正整数",
    )
    _require(
        isinstance(config.voice.duration, (int, float)) and config.voice.duration > 0,
        "voice.duration 必须大于 0",
    )


# --------------------------------------------------------------------------- #
# 加载入口
# --------------------------------------------------------------------------- #
def _default_candidates() -> list[Path]:
    """未显式指定配置文件时的搜索顺序。"""
    candidates: list[Path] = []
    env_path = os.environ.get(_ENV_PREFIX + "CONFIG")
    if env_path:
        candidates.append(Path(env_path))
    candidates.append(Path.cwd() / "config.yaml")
    # src 布局下：<root>/src/crystal_viewer/config.py -> <root>
    candidates.append(Path(__file__).resolve().parents[2] / "config.yaml")
    return candidates


def load(config_path: str | os.PathLike[str] | None = None) -> Config:
    """加载配置。

    Args:
        config_path: 主配置文件路径。省略时依次查找
            ``$CRYSTAL_CONFIG``、当前目录 ``config.yaml``、项目根目录 ``config.yaml``。

    Raises:
        ConfigError: 配置缺失、YAML 语法错误或参数取值非法。
    """
    explicit = config_path is not None
    if explicit:
        source = Path(config_path).expanduser()
        if not source.is_file():
            raise ConfigError(f"找不到配置文件: {source}")
        source = source.resolve()
    else:
        source = None
        for candidate in _default_candidates():
            if candidate.is_file():
                source = candidate.resolve()
                break
        if source is None:
            searched = "\n  ".join(str(item) for item in _default_candidates())
            raise ConfigError(f"找不到 config.yaml，已查找:\n  {searched}")

    root = source.parent
    merged = _deep_merge(DEFAULTS, _read_yaml(source))

    # 私有密钥文件：只在本地存在，不会提交到仓库
    keys_path = root / _KEYS_FILENAME
    if keys_path.is_file():
        merged = _deep_merge(merged, _read_yaml(keys_path))

    for name, raw in os.environ.items():
        if not name.startswith(_ENV_PREFIX) or name == _ENV_PREFIX + "CONFIG":
            continue
        parts = name[len(_ENV_PREFIX):].split(_ENV_SEP)
        if len(parts) < 2:
            continue
        _set_by_path(merged, [part.lower() for part in parts], raw)

    merged = _expand_env(merged)
    config = Config(merged, root, source)
    validate(config)
    return config


#: ``load_config`` 是 ``load`` 的别名，便于调用方使用更明确的名称。
load_config = load


def apply_overrides(config: Config, overrides: Mapping[str, Any]) -> None:
    """用命令行开关覆盖配置（只允许覆盖已存在的配置项）。

    Args:
        config: ``load()`` 返回的配置对象，会被就地修改。
        overrides: ``{"gesture.enabled": False}`` 这样的点号路径映射。

    Raises:
        ConfigError: 路径不存在，或覆盖后取值非法。
    """
    data: dict[str, Any] = config._data  # type: ignore[attr-defined]
    for dotted, value in overrides.items():
        parts = dotted.split(".")
        node: dict[str, Any] = data
        for part in parts[:-1]:
            child = node.get(part)
            if not isinstance(child, dict):
                raise ConfigError(f"未知的配置项: {dotted}")
            node = child
        if parts[-1] not in node:
            raise ConfigError(f"未知的配置项: {dotted}")
        node[parts[-1]] = value
    validate(config)
