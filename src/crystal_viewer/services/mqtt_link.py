"""MQTT 遥控（可选）。

用来让手机 APP / 物联网平台远程切换晶胞、触发语音识别。
依赖 ``paho-mqtt``（1.x 与 2.x 都兼容）。
"""

from __future__ import annotations

import logging
import random
from typing import Callable

__all__ = ["MqttError", "MqttLink"]

log = logging.getLogger(__name__)


class MqttError(RuntimeError):
    """MQTT 连接失败或缺少 paho-mqtt。"""


class MqttLink:
    """订阅一个 Topic，把收到的字符串映射成动作名并回调。

    回调在 MQTT 网络线程里执行，调用方应只做"塞进队列"这类轻量操作。
    """

    def __init__(self, config: object, on_action: Callable[[str], None]) -> None:
        self._config = config
        self._on_action = on_action
        self._client = None
        self._stopped = False

    # -- 生命周期 ---------------------------------------------------------- #
    def start(self) -> None:
        try:
            import paho.mqtt.client as mqtt
        except ImportError as exc:
            raise MqttError("缺少 paho-mqtt，无法使用远程遥控。请执行: pip install paho-mqtt") from exc

        cfg = self._config
        client_id = f"crystal-viewer-{random.randint(0, 9999)}"

        # paho-mqtt 2.x 要求显式声明回调版本；1.x 没有这个参数。
        try:
            from paho.mqtt.enums import CallbackAPIVersion

            client = mqtt.Client(
                callback_api_version=CallbackAPIVersion.VERSION2,
                client_id=client_id,
            )
        except ImportError:  # pragma: no cover - 仅 paho 1.x
            client = mqtt.Client(client_id=client_id)

        if cfg.username:
            client.username_pw_set(username=cfg.username, password=cfg.password or None)

        client.on_connect = self._on_connect
        client.on_disconnect = self._on_disconnect
        client.on_message = self._on_message
        client.connect_async(cfg.host, port=int(cfg.port), keepalive=int(cfg.keepalive))
        client.loop_start()
        self._client = client
        self._stopped = False
        log.info("MQTT 正在连接 %s:%s …", cfg.host, cfg.port)

    def stop(self) -> None:
        self._stopped = True
        client = self._client
        if client is None:
            return
        try:
            client.loop_stop()
            client.disconnect()
        except Exception:  # pragma: no cover - 退出阶段忽略
            pass
        finally:
            self._client = None

    # -- 回调 -------------------------------------------------------------- #
    def _on_connect(self, _client, _userdata, _flags, reason_code, *_args) -> None:
        ok = reason_code == 0 if isinstance(reason_code, int) else not getattr(
            reason_code, "is_failure", True
        )
        if not ok:
            log.error("MQTT 连接被拒绝: %s", reason_code)
            return
        topic = self._config.topic
        _client.subscribe(topic)
        log.info("MQTT 已连接，订阅 %s", topic)

    def _on_disconnect(self, _client, _userdata, *args) -> None:
        if not self._stopped:
            log.warning("MQTT 连接断开，将自动重连: %s", args[-1] if args else "")

    def _on_message(self, _client, _userdata, message) -> None:
        try:
            payload = message.payload.decode("utf-8", errors="replace").strip()
        except Exception:  # pragma: no cover - 解码极少失败
            return
        log.info("收到 MQTT 消息: %r", payload)
        commands = dict(self._config.commands)
        for action, expected in commands.items():
            if expected and payload == str(expected).strip():
                try:
                    self._on_action(action)
                except Exception:  # pragma: no cover - 防止线程崩溃
                    log.exception("处理 MQTT 动作 %r 时出错", action)
                return
        log.debug("未识别的 MQTT 命令: %r（可用: %s）", payload, commands)
