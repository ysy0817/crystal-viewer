"""颜色渐变的阶段机测试。"""

from __future__ import annotations

from crystal_viewer.effects import ColorFader, FadePhase


def test_starts_on_target_color() -> None:
    fader = ColorFader(0xFFFFFF, 0x111111)
    assert fader.value == 0xFFFFFF
    assert fader.phase == FadePhase.IDLE


def test_fade_out_reaches_bottom() -> None:
    fader = ColorFader(0xFFFFFF, 0x111111)
    fader.fade_out()
    for _ in range(100):
        fader.update()
    assert fader.value == 0
    assert fader.phase == FadePhase.BOTTOM
    assert fader.at_bottom


def test_fade_in_returns_to_target() -> None:
    fader = ColorFader(0xFFFFFF, 0x111111)
    fader.fade_out()
    for _ in range(100):
        fader.update()
    fader.fade_in()
    for _ in range(100):
        fader.update()
    assert fader.value == 0xFFFFFF
    assert fader.phase == FadePhase.IDLE


def test_step_is_at_least_one() -> None:
    fader = ColorFader(0x0000FF, 0)
    fader.fade_out()
    fader.update()
    assert fader.value < 0x0000FF


def test_snap_restores_target() -> None:
    fader = ColorFader(0x00FF00, 0x010101)
    fader.fade_out()
    fader.update()
    fader.snap()
    assert fader.value == 0x00FF00
    assert fader.phase == FadePhase.IDLE
