"""应用层逻辑测试：数字跳转与自动旋转开关。

需要 pygame；未安装时整个模块跳过，不影响其余测试。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from crystal_viewer.config import load

pytest.importorskip("pygame")

from crystal_viewer.app import CrystalApp  # noqa: E402  (需先确认 pygame 可用)

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture()
def app() -> CrystalApp:
    instance = CrystalApp(load(ROOT / "config.yaml"))
    yield instance
    instance.close()


def test_auto_spin_defaults_to_config(app: CrystalApp) -> None:
    assert app._auto_spin is True


def test_auto_spin_can_be_toggled(app: CrystalApp) -> None:
    app._set_auto_spin(False)
    assert app._auto_spin is False
    app._set_auto_spin(True)
    assert app._auto_spin is True


def test_jump_to_valid_index_starts_transition(app: CrystalApp) -> None:
    app.jump_to(3)
    assert app.busy is True
    assert app._pending_index == 3


def test_jump_to_out_of_range_is_ignored(app: CrystalApp) -> None:
    app.jump_to(2)
    app.jump_to(99)
    assert app._pending_index == 2  # 未被越界调用改写
    app.jump_to(-1)
    assert app._pending_index == 2


def test_request_switch_rejects_out_of_range_index(app: CrystalApp) -> None:
    app.request_switch(index=len(app.models) + 5)
    assert app.busy is False
