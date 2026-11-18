"""配置加载相关测试。"""

from __future__ import annotations

import os
import textwrap
from pathlib import Path

import pytest

from crystal_viewer.config import ConfigError, apply_overrides, load

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """隔离外部环境变量，避免影响断言。"""
    for name in list(os.environ):
        if name.startswith("CRYSTAL_") or name.startswith("BAIDU_"):
            monkeypatch.delenv(name, raising=False)


def _write(tmp_path: Path, name: str, content: str) -> Path:
    path = tmp_path / name
    path.write_text(textwrap.dedent(content), encoding="utf-8")
    return path


def test_load_repository_config() -> None:
    config = load(ROOT / "config.yaml")
    assert config.window.width == 1920
    assert config.window.height == 1080
    assert config.render.scale == 100
    assert len(config.views) == 4
    assert config.root == ROOT


def test_env_override_is_coerced_to_int(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CRYSTAL_RENDER__LINE_WIDTH", "7")
    config = load(ROOT / "config.yaml")
    assert config.render.line_width == 7
    assert isinstance(config.render.line_width, int)


def test_env_override_bool(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CRYSTAL_GESTURE__ENABLED", "false")
    config = load(ROOT / "config.yaml")
    assert config.gesture.enabled is False


def test_keys_file_overrides_config(tmp_path: Path) -> None:
    """keys.yaml 用于放密钥，优先级高于 config.yaml。"""
    _write(tmp_path, "config.yaml", 'render:\n  line_width: 3\nasr:\n  api_key: ""\n')
    _write(tmp_path, "keys.yaml", 'render:\n  line_width: 9\nasr:\n  api_key: "abc"\n')
    config = load(tmp_path / "config.yaml")
    assert config.render.line_width == 9
    assert config.asr.api_key == "abc"


def test_placeholder_expansion(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _write(tmp_path, "config.yaml", 'asr:\n  api_key: "${TEST_KEY}"\n')
    monkeypatch.setenv("TEST_KEY", "hello")
    config = load(tmp_path / "config.yaml")
    assert config.asr.api_key == "hello"


def test_repository_config_file_has_no_secrets() -> None:
    """仓库里的 config.yaml 必须保持密钥为空（密钥放 keys.yaml）。"""
    import yaml

    data = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8-sig"))
    for section, fields in {
        "asr": ("api_key", "secret_key"),
        "tts": ("api_key", "secret_key"),
        "mqtt": ("topic", "username", "password"),
    }.items():
        for field in fields:
            assert data[section][field] == "", f"config.yaml 的 {section}.{field} 不能有值"


def test_missing_config_raises(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="找不到配置文件"):
        load(tmp_path / "nope.yaml")


def test_broken_yaml_raises(tmp_path: Path) -> None:
    _write(tmp_path, "config.yaml", "window:\n  width: 1920\n   bad_indent: 1\n")
    with pytest.raises(ConfigError, match="格式有误"):
        load(tmp_path / "config.yaml")


def test_invalid_color_rejected(tmp_path: Path) -> None:
    _write(tmp_path, "config.yaml", "render:\n  line_color: 16777216\n")
    with pytest.raises(ConfigError, match="line_color"):
        load(tmp_path / "config.yaml")


def test_apply_overrides(tmp_path: Path) -> None:
    config = load(ROOT / "config.yaml")
    apply_overrides(config, {"gesture.enabled": False, "window.width": 1280})
    assert config.gesture.enabled is False
    assert config.window.width == 1280


def test_apply_overrides_unknown_path(tmp_path: Path) -> None:
    config = load(ROOT / "config.yaml")
    with pytest.raises(ConfigError, match="未知的配置项"):
        apply_overrides(config, {"no_such_key": 1})


def test_path_resolution(tmp_path: Path) -> None:
    _write(tmp_path, "config.yaml", "data:\n  lattice: data/x.csv\n")
    config = load(tmp_path / "config.yaml")
    assert config.path(config.data.lattice) == tmp_path / "data" / "x.csv"
    absolute = tmp_path / "abs.csv"
    assert config.path(str(absolute)) == absolute
