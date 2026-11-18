"""MQTT 指令解析测试（不依赖 paho 与网络）。"""

from __future__ import annotations

from typing import Any

import pytest

from crystal_viewer.services.mqtt_link import MqttLink


class _Message:
    def __init__(self, payload: str) -> None:
        self.payload = payload.encode("utf-8")
        self.topic = "test/topic"


class _Config:
    """最小化的 mqtt 配置桩。"""

    def __init__(self, numeric_select: bool = True) -> None:
        self.commands = {
            "next": "+1",
            "previous": "-1",
            "listen": "turn",
            "introduce": "introduce",
            "spin_start": "start",
            "spin_stop": "stop",
        }
        self.numeric_select = numeric_select


def _make(numeric_select: bool = True) -> tuple[MqttLink, list[Any]]:
    actions: list[Any] = []
    return MqttLink(_Config(numeric_select), on_action=actions.append), actions


def _deliver(link: MqttLink, payload: str) -> None:
    link._on_message(None, None, _Message(payload))


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        ("+1", "next"),
        ("-1", "previous"),
        ("turn", "listen"),
        ("introduce", "introduce"),
        ("start", "spin_start"),
        ("stop", "spin_stop"),
    ],
)
def test_named_commands(payload: str, expected: str) -> None:
    link, actions = _make()
    _deliver(link, payload)
    assert actions == [expected]


@pytest.mark.parametrize(("payload", "index"), [("0", 0), ("3", 3), ("6", 6)])
def test_numeric_select_emits_index(payload: str, index: int) -> None:
    link, actions = _make()
    _deliver(link, payload)
    assert actions == [index]


def test_numeric_select_can_be_disabled() -> None:
    link, actions = _make(numeric_select=False)
    _deliver(link, "3")
    assert actions == []


@pytest.mark.parametrize("payload", ["", "abc", "\\000", "1.5", "-2"])
def test_unknown_payloads_ignored(payload: str) -> None:
    link, actions = _make()
    _deliver(link, payload)
    assert actions == []


def test_whitespace_is_trimmed() -> None:
    link, actions = _make()
    _deliver(link, "  start  ")
    assert actions == ["spin_start"]


def test_named_commands_take_priority_over_digits() -> None:
    """配置里把某个数字设成指令时，应优先按指令处理。"""
    config = _Config()
    config.commands["custom"] = "0"
    actions: list[Any] = []
    link = MqttLink(config, on_action=actions.append)
    _deliver(link, "0")
    assert actions == ["custom"]
