"""pygame 绘制封装：屏幕、线条、原子、旋转文字。

只做绘图，不包含任何业务逻辑，便于替换渲染后端。
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Sequence

import pygame

from .config import Config

__all__ = ["Renderer"]

log = logging.getLogger(__name__)


class Renderer:
    """封装 pygame 窗口与基础图元。"""

    def __init__(self, config: Config) -> None:
        self._config = config
        window = config.window
        flags = 0
        if window.fullscreen:
            flags |= pygame.FULLSCREEN
        elif window.resizable:
            flags |= pygame.RESIZABLE
        if not pygame.get_init():
            pygame.init()
        if not pygame.font.get_init():
            pygame.font.init()
        try:
            self._screen = pygame.display.set_mode(
                (int(window.width), int(window.height)), flags
            )
        except pygame.error as exc:  # pragma: no cover - 取决于显示环境
            raise RuntimeError(
                "无法创建窗口，请检查是否在无图形界面的环境中运行"
                f"（可以用 --render-once 做离屏渲染）：{exc}"
            ) from exc
        pygame.display.set_caption(str(window.title))
        self._background = self._parse_color(window.background, (0, 0, 0))
        self._font_name = str(config.render.font_name)
        self._fonts: dict[int, pygame.font.Font] = {}
        log.debug("窗口尺寸 %s", self._screen.get_size())

    # -- 基本属性 ---------------------------------------------------------- #
    @property
    def screen(self) -> pygame.Surface:
        return self._screen

    @property
    def size(self) -> tuple[int, int]:
        return self._screen.get_size()

    @property
    def center(self) -> tuple[int, int]:
        width, height = self.size
        return width // 2, height // 2

    # -- 图元 -------------------------------------------------------------- #
    def clear(self) -> None:
        """用背景色填满整个窗口。"""
        self._screen.fill(self._background)

    def line(self, color: int, start: Sequence[float], end: Sequence[float], width: int | None = None) -> None:
        """画一条晶胞棱线。"""
        if width is None:
            width = int(self._config.render.line_width)
        pygame.draw.line(
            self._screen,
            self._as_color(color),
            (int(round(start[0])), int(round(start[1]))),
            (int(round(end[0])), int(round(end[1]))),
            max(1, int(width)),
        )

    def point(self, color: int, position: Sequence[float], radius: int | None = None) -> None:
        """在晶格点位置画一个原子。"""
        if radius is None:
            radius = int(self._config.render.point_radius)
        pygame.draw.circle(
            self._screen,
            self._as_color(color),
            (int(round(position[0])), int(round(position[1]))),
            max(1, int(radius)),
        )

    def label(
        self,
        text: str,
        center: Sequence[float],
        color: int,
        rotation_deg: float = 0.0,
        font_size: int | None = None,
    ) -> None:
        """画模型名称；先上下翻转再旋转，与原程序观感一致。"""
        if not text:
            return
        size = int(font_size or self._config.render.font_size)
        font = self._get_font(size)
        surface = font.render(text, True, self._as_color(color))
        # 先做上下翻转再旋转 —— 镜像字形是原程序的设计效果，默认保持开启。
        if getattr(self._config.render, "label_flip_vertical", True):
            surface = pygame.transform.flip(surface, False, True)
        if rotation_deg:
            surface = pygame.transform.rotate(surface, rotation_deg)
        rect = surface.get_rect(
            center=(int(round(center[0])), int(round(center[1])))
        )
        self._screen.blit(surface, rect)

    def present(self) -> None:
        """把绘制结果显示到窗口。"""
        pygame.display.flip()

    def save(self, path: str | Path) -> Path:
        """把当前画面保存为图片（离屏渲染与截图用）。"""
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        pygame.image.save(self._screen, str(target))
        return target

    def close(self) -> None:
        try:
            pygame.quit()
        except pygame.error:  # pragma: no cover - 退出阶段
            pass

    # -- 内部工具 ---------------------------------------------------------- #
    def _get_font(self, size: int) -> pygame.font.Font:
        font = self._fonts.get(size)
        if font is None:
            try:
                font = pygame.font.SysFont(self._font_name, size)
            except Exception:  # pragma: no cover - 字体缺失时降级
                log.warning("找不到字体 %r，改用系统默认字体", self._font_name)
                font = pygame.font.SysFont(None, size)
            self._fonts[size] = font
        return font

    @staticmethod
    def _parse_color(value: object, fallback: tuple[int, int, int]) -> tuple[int, int, int]:
        if isinstance(value, (tuple, list)) and len(value) == 3:
            return tuple(int(v) for v in value)  # type: ignore[return-value]
        if isinstance(value, str):
            try:
                return pygame.Color(value)[:3]
            except ValueError:
                log.warning("无法识别的背景色 %r，使用黑色", value)
                return fallback
        return fallback

    @staticmethod
    def _as_color(value: int) -> tuple[int, int, int]:
        """把 0xRRGGBB 拆成 pygame 需要的 RGB 三元组。"""
        value = int(value) & 0xFFFFFF
        return (value >> 16) & 0xFF, (value >> 8) & 0xFF, value & 0xFF
