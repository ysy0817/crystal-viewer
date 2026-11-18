"""应用主循环：窗口渲染、输入事件、晶胞切换。

输入统一折算成"动作"放进队列，由主线程消费，避免多线程直接改渲染状态：

    键盘 ─┐
    手势 ─┼─▶ _queue ─▶ _handle_action ─▶ request_switch
    MQTT ─┤
    语音 ─┘
"""

from __future__ import annotations

import logging
import queue
import threading
from pathlib import Path
from typing import Any

import numpy as np
import pygame

from .config import Config
from .effects import ColorFader, FadePhase
from .geometry import ViewGeometry, build_views
from .models import CrystalModel, load_lattice, load_models
from .renderer import Renderer
from .services import gestures, recorder
from .services.asr import ASRError, BaiduASR
from .services.gestures import GestureError, GestureTracker
from .services.mqtt_link import MqttError, MqttLink
from .services.tts import BaiduTTS, TTSError

__all__ = ["CrystalApp"]

log = logging.getLogger(__name__)

#: 归一化语音文本时要去掉的标点与空白。
_PUNCTUATION = str.maketrans("", "", "。，,.!！?？、;；:： \t\r\n\"'“”‘’")


class CrystalApp:
    """晶体结构演示程序。"""

    def __init__(self, config: Config) -> None:
        self.config = config
        self.lattice = load_lattice(config) * float(config.render.scale)
        self.models = load_models(config, point_count=len(self.lattice))
        if not self.models:
            raise RuntimeError("没有可显示的晶胞，请检查 models.yaml")

        self._views: list[ViewGeometry] = build_views(config, self.lattice)
        self._faders: dict[str, ColorFader] = {
            "line": ColorFader(config.render.line_color, config.render.line_fade_step),
            "point": ColorFader(config.render.point_color, config.render.point_fade_step),
            "text": ColorFader(config.render.text_color, config.render.text_fade_step),
        }

        self.index = 0
        self._auto_spin = bool(config.rotation.auto)
        self._phase = "idle"  # idle → out（变暗）→ in（变亮）
        self._pending_index = 0
        self._queue: "queue.Queue[Any]" = queue.Queue()
        self._running = False

        self._renderer: Renderer | None = None
        self._gestures: GestureTracker | None = None
        self._mqtt: MqttLink | None = None
        self._asr: BaiduASR | None = None
        self._tts: BaiduTTS | None = None
        self._workers: list[threading.Thread] = []

    # -- 生命周期 ---------------------------------------------------------- #
    def _ensure_renderer(self) -> Renderer:
        if self._renderer is None:
            self._renderer = Renderer(self.config)
        return self._renderer

    def run(self) -> None:
        """进入主循环，直到用户关闭窗口或按退出键。"""
        renderer = self._ensure_renderer()
        self._start_services()
        clock = pygame.time.Clock()
        fps = int(self.config.window.fps)
        self._running = True
        log.info(
            "开始演示：%d 个晶胞，按 ESC 退出，按 F1~F%d 切换",
            len(self.models),
            min(len(self.models), len(self.config.keyboard.model_keys)),
        )
        try:
            while self._running:
                self._pump_pygame_events()
                self._drain_actions()
                self._poll_gestures()
                self._tick_transition()
                self._draw_frame()
                renderer.present()
                clock.tick(fps)
        except GestureError as exc:  # 摄像头窗口被关闭等情况
            log.info("退出演示：%s", exc)
        finally:
            self.close()

    def render_still(self, path: str | Path, steps: int = 0) -> Path:
        """渲染一帧并保存为图片（离屏预览 / 生成文档配图用）。"""
        self._ensure_renderer()
        for _ in range(max(0, int(steps))):
            for view in self._views:
                view.advance()
        self._draw_frame()
        saved = self._renderer.save(path)  # type: ignore[union-attr]
        log.info("已保存预览图: %s", saved)
        return saved

    def close(self) -> None:
        self._running = False
        if self._mqtt is not None:
            self._mqtt.stop()
            self._mqtt = None
        if self._gestures is not None:
            self._gestures.close()
            self._gestures = None
        for worker in self._workers:
            worker.join(timeout=2.0)
        self._workers.clear()
        if self._renderer is not None:
            self._renderer.close()
            self._renderer = None

    # -- 服务初始化 -------------------------------------------------------- #
    def _start_services(self) -> None:
        config = self.config

        if config.gesture.enabled:
            tracker = GestureTracker(config.gesture)
            try:
                tracker.open()
            except GestureError as exc:
                log.warning("手势功能未启用：%s", exc)
            else:
                self._gestures = tracker

        self._asr = self._make_asr()
        self._tts = self._make_tts()

        if config.mqtt.enabled:
            link = MqttLink(config.mqtt, on_action=self._queue.put)
            try:
                link.start()
            except (MqttError, OSError, ValueError) as exc:
                log.warning("MQTT 未启用：%s", exc)
            else:
                self._mqtt = link

    def _make_asr(self) -> BaiduASR | None:
        asr_cfg = self.config.asr
        voice_cfg = self.config.voice
        client = BaiduASR(
            api_key=asr_cfg.api_key,
            secret_key=asr_cfg.secret_key,
            cuid=asr_cfg.cuid,
            dev_pid=asr_cfg.dev_pid,
            url=asr_cfg.url,
            scope=asr_cfg.scope,
            sample_rate=voice_cfg.sample_rate,
        )
        if not voice_cfg.enabled:
            return client
        try:
            client.check_ready()
        except ASRError as exc:
            log.warning("语音识别未启用：%s", exc)
            return None
        return client

    def _make_tts(self) -> BaiduTTS | None:
        tts_cfg = self.config.tts
        client = BaiduTTS(
            api_key=tts_cfg.api_key,
            secret_key=tts_cfg.secret_key,
            cuid=tts_cfg.cuid,
            spd=tts_cfg.spd,
            pit=tts_cfg.pit,
            vol=tts_cfg.vol,
            per=tts_cfg.per,
            lan=tts_cfg.lan,
            ctp=1,
            aue=tts_cfg.aue,
            url=tts_cfg.url,
        )
        if not tts_cfg.enabled:
            return client
        try:
            client.check_ready()
        except TTSError as exc:
            log.warning("语音介绍未启用：%s", exc)
            return None
        return client

    # -- 事件 -------------------------------------------------------------- #
    @property
    def busy(self) -> bool:
        """切换过渡进行中。"""
        return self._phase != "idle"

    def _pump_pygame_events(self) -> None:
        keyboard = self.config.keyboard
        quit_key = str(keyboard.quit_key or "escape").lower()
        model_keys = [str(key).lower() for key in keyboard.model_keys]
        voice_key = str(keyboard.voice_key).lower() if keyboard.voice_key else None

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                self._running = False
                continue
            if event.type != pygame.KEYDOWN or not keyboard.enabled:
                continue

            name = pygame.key.name(event.key)
            if name == quit_key:
                self._running = False
            elif name in model_keys:
                target = model_keys.index(name)
                if target < len(self.models):
                    self.request_switch(index=target)
                else:
                    log.info("快捷键 %s 没有对应的晶胞（只有 %d 个）", name.upper(), len(self.models))
            elif voice_key is not None and name == voice_key:
                self._queue.put("listen")

    def _poll_gestures(self) -> None:
        if self._gestures is None:
            return
        self._gestures.busy = self.busy
        try:
            _frame, event = self._gestures.process()
        except GestureError as exc:
            log.warning("手势识别已停止：%s", exc)
            self._gestures.close()
            self._gestures = None
            return
        if event:
            self.request_switch(event)

    def _drain_actions(self) -> None:
        while True:
            try:
                action = self._queue.get_nowait()
            except queue.Empty:
                return
            self._handle_action(action)

    def _handle_action(self, action: Any) -> None:
        if action in ("next", "previous"):
            self.request_switch(1 if action == "next" else -1)
        elif action == "spin_start":
            self._set_auto_spin(True)
        elif action == "spin_stop":
            self._set_auto_spin(False)
        elif action == "listen":
            self._start_listening()
        elif action == "introduce":
            self._start_introduce()
        elif isinstance(action, int):
            self.jump_to(action)
        else:
            log.debug("忽略未知动作: %r", action)

    def _set_auto_spin(self, enabled: bool) -> None:
        """开始 / 停止自动旋转，对应 MQTT 的 start / stop 指令。"""
        if self._auto_spin == enabled:
            return
        self._auto_spin = enabled
        log.info("自动旋转: %s", "开始" if enabled else "停止")

    def jump_to(self, index: int) -> None:
        """直接跳到指定序号的晶胞（从 0 开始）；超出范围则忽略。"""
        if not 0 <= index < len(self.models):
            log.warning("晶胞序号 %d 超出范围（可用 0~%d）", index, len(self.models) - 1)
            return
        self.request_switch(index=index)

    # -- 切换 -------------------------------------------------------------- #
    def request_switch(self, delta: int = 0, index: int | None = None) -> None:
        """请求切换晶胞；过渡动画进行中时忽略新请求。"""
        if self.busy:
            log.debug("切换动画进行中，忽略本次请求")
            return
        total = len(self.models)
        if index is not None:
            if not 0 <= int(index) < total:
                log.warning("晶胞序号 %d 超出范围（可用 0~%d）", int(index), total - 1)
                return
            target = int(index)
        else:
            target = (self.index + delta) % total
        if target == self.index:
            return
        self._pending_index = target
        self._phase = "out"
        for fader in self._faders.values():
            fader.fade_out()

    def _tick_transition(self) -> None:
        for fader in self._faders.values():
            fader.update()

        if self._phase == "out" and all(f.at_bottom for f in self._faders.values()):
            self.index = self._pending_index
            for fader in self._faders.values():
                fader.fade_in()
            self._phase = "in"
            if self._gestures is not None:
                self._gestures.notify_switched()
            log.info("当前晶胞: %s", self.models[self.index].name)
        elif self._phase == "in" and all(
            f.phase == FadePhase.IDLE for f in self._faders.values()
        ):
            self._phase = "idle"

    # -- 绘制 -------------------------------------------------------------- #
    def _draw_frame(self) -> None:
        renderer = self._ensure_renderer()
        renderer.clear()
        model = self.models[self.index]
        center_x, center_y = renderer.center

        line_color = self._faders["line"].value
        point_color = self._faders["point"].value
        text_color = self._faders["text"].value
        used_points = np.unique(model.edges) if model.edges.size else np.array([], dtype=int)

        for view_index, view in enumerate(self._views):
            view_config = self.config.views[view_index]
            offset_x, offset_y = view_config.offset
            origin_x = center_x + offset_x
            origin_y = center_y + offset_y

            if self._auto_spin:
                view.advance()
            projected = view.projected_xy()

            for start, end in model.edges:
                renderer.line(
                    line_color,
                    (origin_x + projected[start, 0], origin_y + projected[start, 1]),
                    (origin_x + projected[end, 0], origin_y + projected[end, 1]),
                )
            for point in used_points:
                renderer.point(
                    point_color,
                    (origin_x + projected[point, 0], origin_y + projected[point, 1]),
                )

            label_x, label_y = view_config.label_offset
            renderer.label(
                model.name,
                (origin_x + label_x, origin_y + label_y),
                text_color,
                float(view_config.label_rotation),
            )

    # -- 语音 -------------------------------------------------------------- #
    def _start_listening(self) -> None:
        if self._asr is None or not self.config.voice.enabled:
            log.warning("语音识别不可用（未配置密钥或已关闭该功能）")
            return
        if self._worker_alive("voice"):
            return
        worker = threading.Thread(target=self._listen_worker, name="voice", daemon=True)
        self._workers.append(worker)
        worker.start()

    def _listen_worker(self) -> None:
        voice_cfg = self.config.voice
        audio_path = self.config.path(voice_cfg.audio_file)
        try:
            recorder.record_audio(
                audio_path,
                duration=voice_cfg.duration,
                sample_rate=voice_cfg.sample_rate,
                chunk_size=voice_cfg.chunk_size,
                channels=voice_cfg.channels,
            )
            text = self._asr.recognize(audio_path) if self._asr else ""
        except Exception as exc:  # 录音或识别失败都不应终止程序
            log.error("语音识别失败：%s", exc)
            return

        action = self._match_phrase(text)
        if action is None:
            log.info("没有匹配到切换指令（听到：%r）", text)
            return
        log.info("语音指令匹配：%r → %s", text, action)
        self._queue.put(action)

    def _match_phrase(self, text: str) -> str | None:
        normalized = (text or "").translate(_PUNCTUATION)
        if not normalized:
            return None
        voice_cfg = self.config.voice
        for phrase in voice_cfg.next_phrases:
            if str(phrase).translate(_PUNCTUATION) in normalized:
                return "next"
        for phrase in voice_cfg.prev_phrases:
            if str(phrase).translate(_PUNCTUATION) in normalized:
                return "previous"
        return None

    def _start_introduce(self) -> None:
        if self._tts is None or not self.config.tts.enabled:
            log.warning("语音介绍不可用（未配置密钥或已关闭该功能）")
            return
        if self._worker_alive("introduce"):
            return
        worker = threading.Thread(target=self._introduce_worker, name="introduce", daemon=True)
        self._workers.append(worker)
        worker.start()

    def _introduce_worker(self) -> None:
        model = self.models[self.index]
        if not model.intro:
            log.warning("晶胞 %s 没有介绍文本", model.name)
            return
        try:
            self._tts.speak(model.intro)  # type: ignore[union-attr]
        except TTSError as exc:
            log.error("语音介绍失败：%s", exc)

    def _worker_alive(self, name: str) -> bool:
        self._workers = [worker for worker in self._workers if worker.is_alive()]
        return any(worker.name == name for worker in self._workers)
