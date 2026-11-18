"""颜色渐变等轻量视觉效果（不依赖 pygame，可单独测试）。"""

from __future__ import annotations

__all__ = ["ColorFader", "FadePhase"]


class FadePhase(str):
    """渐变所处阶段。用字符串常量便于日志输出。"""

    IDLE = "idle"      # 停在目标色上
    OUT = "out"        # 正在变暗
    BOTTOM = "bottom"  # 刚好暗到 0，等待切换数据
    IN = "in"          # 正在变亮


class ColorFader:
    """在 0 与目标色之间做线性渐变。

    切换晶胞时的完整过程是"变暗 → 换成新晶胞 → 变亮"：调用方先 ``fade_out()``，
    收到 ``BOTTOM`` 阶段后切换数据并 ``fade_in()``，最后回到 ``IDLE``。
    """

    __slots__ = ("_target", "_step", "_value", "_phase")

    def __init__(self, target_color: int, step: int) -> None:
        self._target = int(target_color)
        self._step = max(1, int(step))
        self._value = self._target
        self._phase = FadePhase.IDLE

    # -- 只读属性 ---------------------------------------------------------- #
    @property
    def value(self) -> int:
        """当前颜色值（0xRRGGBB）。"""
        return self._value

    @property
    def phase(self) -> str:
        return self._phase

    @property
    def at_bottom(self) -> bool:
        return self._phase == FadePhase.BOTTOM

    # -- 控制 -------------------------------------------------------------- #
    def fade_out(self) -> None:
        """开始变暗；已在变暗或已在底部时不重复触发。"""
        if self._phase in (FadePhase.IDLE, FadePhase.IN):
            self._phase = FadePhase.OUT

    def fade_in(self) -> None:
        """开始变亮，回到目标色。"""
        if self._phase in (FadePhase.BOTTOM, FadePhase.OUT):
            self._phase = FadePhase.IN

    def update(self) -> str:
        """推进一步，返回推进后的阶段。每帧调用一次。"""
        if self._phase == FadePhase.OUT:
            self._value -= self._step
            if self._value <= 0:
                self._value = 0
                self._phase = FadePhase.BOTTOM
        elif self._phase == FadePhase.IN:
            self._value += self._step
            if self._value >= self._target:
                self._value = self._target
                self._phase = FadePhase.IDLE
        return self._phase

    def snap(self) -> None:
        """立即回到目标色（用于初始化）。"""
        self._value = self._target
        self._phase = FadePhase.IDLE

    def __repr__(self) -> str:  # pragma: no cover - 仅调试
        return f"ColorFader(0x{self._value:06X}, {self._phase})"
