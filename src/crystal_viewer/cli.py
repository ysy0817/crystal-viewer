"""命令行入口。

常用示例::

    python -m crystal_viewer                 # 正常演示
    python -m crystal_viewer --check         # 检查配置与数据是否可用
    python -m crystal_viewer --list-models   # 列出所有晶胞
    python -m crystal_viewer --no-camera     # 没有摄像头时
    python -m crystal_viewer --render-once preview.png   # 离屏出一张图
"""

from __future__ import annotations

import argparse
import importlib.util
import logging
import os
import sys
from pathlib import Path

from . import __version__
from .config import ConfigError, apply_overrides, load
from .models import load_lattice, load_models

__all__ = ["build_parser", "main"]

_EPILOG = """\
示例：
  python -m crystal_viewer                      正常启动演示
  python -m crystal_viewer --no-camera          没有摄像头时只保留键盘/语音
  python -m crystal_viewer --model caf2         直接从 CaF₂ 开始
  python -m crystal_viewer --windowed 1280x720  小窗口运行
  python -m crystal_viewer --check              检查配置/数据/依赖
  python -m crystal_viewer --render-once out.png 离屏渲染一张图

所有参数都可以在 config.yaml 中调整，配置文件顶部有逐项中文说明。
"""


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="crystal-viewer",
        description="晶体结构三维演示：四视图旋转展示常见晶胞。",
        epilog=_EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("-c", "--config", metavar="PATH", help="配置文件路径（默认当前目录 config.yaml）")
    parser.add_argument("--model", metavar="KEY或序号", help="启动时显示哪个晶胞")
    parser.add_argument("--windowed", metavar="宽x高", help="临时指定窗口大小，例如 1280x720")
    parser.add_argument("--no-camera", action="store_true", help="关闭摄像头手势识别")
    parser.add_argument("--no-voice", action="store_true", help="关闭语音识别与语音介绍")
    parser.add_argument("--no-mqtt", action="store_true", help="关闭 MQTT 远程遥控")
    parser.add_argument("--render-once", metavar="PNG", help="离屏渲染一帧保存后退出，无需显示器")
    parser.add_argument("--render-steps", type=int, default=6, metavar="N", help="离屏渲染前先旋转的帧数（默认 6）")
    parser.add_argument("--list-models", action="store_true", help="列出所有晶胞后退出")
    parser.add_argument("--check", action="store_true", help="检查配置、数据与依赖后退出")
    parser.add_argument("-v", "--verbose", action="count", default=0, help="输出更详细的日志（-vv 更详细）")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return parser


def _setup_logging(verbose: int) -> None:
    level = logging.WARNING
    if verbose == 1:
        level = logging.INFO
    elif verbose >= 2:
        level = logging.DEBUG
    logging.basicConfig(
        level=level,
        format="%(levelname)s %(message)s",
        stream=sys.stderr,
    )


def _parse_size(text: str) -> tuple[int, int]:
    try:
        width, height = (int(part) for part in text.lower().replace("*", "x").split("x", 1))
    except (ValueError, TypeError) as exc:
        raise ConfigError(f"--windowed 需要形如 1280x720 的写法，收到: {text!r}") from exc
    if width < 320 or height < 240:
        raise ConfigError(f"--windowed 尺寸太小: {width}x{height}")
    return width, height


def _resolve_model(models: list, spec: str) -> int:
    """把 --model 的取值解析成索引，支持 key、序号（从 1 开始）或名称。"""
    spec = str(spec).strip()
    for index, model in enumerate(models):
        if model.key == spec:
            return index
    if spec.isdigit():
        index = int(spec) - 1
        if 0 <= index < len(models):
            return index
        raise ConfigError(f"--model 序号超出范围：1~{len(models)}")
    for index, model in enumerate(models):
        if model.name == spec:
            return index
    available = "、".join(model.key for model in models)
    raise ConfigError(f"找不到晶胞 {spec!r}，可用的 key: {available}")


def _print_models(models: list) -> None:
    print(f"{'序号':<4}{'KEY':<14}{'名称':<20}{'棱线数':>6}  {'介绍'}")
    print("-" * 68)
    for index, model in enumerate(models, start=1):
        intro = "有" if model.intro else "无"
        print(f"{index:<6}{model.key:<14}{model.name:<20}{model.edge_count:>6}  {intro}")


def _print_check(config, lattice, models) -> None:
    def mark(ok: bool) -> str:
        return "OK" if ok else "--"

    optional = {
        "opencv-python（手势）": "cv2",
        "mediapipe（手势）": "mediapipe",
        "pyaudio（录音）": "pyaudio",
        "paho-mqtt（遥控）": "paho.mqtt",
    }
    print("配置检查")
    print(f"  配置文件   : {config.source}")
    print(f"  项目根目录 : {config.root}")
    print(f"  晶格点数量 : {len(lattice)}")
    print(f"  晶胞数量   : {len(models)}")
    print(f"  识别密钥   : {mark(bool(config.asr.api_key and config.asr.secret_key))}"
          f"  合成密钥: {mark(bool(config.tts.api_key and config.tts.secret_key))}"
          f"  MQTT: {mark(bool(config.mqtt.topic))}")
    print("可选依赖：")
    for label, module in optional.items():
        print(f"  {mark(importlib.util.find_spec(module) is not None)} {label}")
    print("检查通过，可以运行 python -m crystal_viewer")


def main(argv: list[str] | None = None) -> int:
    """命令行主函数，返回进程退出码。"""
    parser = build_parser()
    args = parser.parse_args(argv)
    _setup_logging(args.verbose)

    # 离屏渲染：必须在 pygame.init() 之前指定虚拟驱动，否则无显示器时会失败。
    if args.render_once:
        os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
        os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

    try:
        config = load(args.config)
        overrides: dict[str, object] = {}
        if args.no_camera:
            overrides["gesture.enabled"] = False
        if args.no_voice:
            overrides["voice.enabled"] = False
            overrides["tts.enabled"] = False
        if args.no_mqtt:
            overrides["mqtt.enabled"] = False
        if args.windowed:
            width, height = _parse_size(args.windowed)
            overrides["window.width"] = width
            overrides["window.height"] = height
        if overrides:
            apply_overrides(config, overrides)

        lattice = load_lattice(config)
        models = load_models(config, point_count=len(lattice))
    except ConfigError as exc:
        print(f"配置或数据有误：\n{exc}", file=sys.stderr)
        return 2

    if args.list_models:
        _print_models(models)
        return 0
    if args.check:
        _print_check(config, lattice, models)
        return 0

    from .app import CrystalApp  # 延迟导入，避免 --check 时加载 pygame

    try:
        app = CrystalApp(config)
    except ConfigError as exc:
        print(f"配置或数据有误：\n{exc}", file=sys.stderr)
        return 2

    if args.model:
        try:
            app.index = _resolve_model(models, args.model)
        except ConfigError as exc:
            print(f"参数有误：{exc}", file=sys.stderr)
            app.close()
            return 2

    if args.render_once:
        try:
            saved = app.render_still(Path(args.render_once), steps=args.render_steps)
        except RuntimeError as exc:
            print(f"渲染失败：{exc}", file=sys.stderr)
            return 1
        finally:
            app.close()
        print(f"已保存: {saved}")
        return 0

    try:
        app.run()
    except KeyboardInterrupt:
        app.close()
        print("\n已退出")
    return 0
