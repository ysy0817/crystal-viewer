"""录音（麦克风）封装。

依赖 ``pyaudio``，属于可选依赖：没装时只在需要语音功能时才报错。
"""

from __future__ import annotations

import logging
import wave
from pathlib import Path

__all__ = ["RecorderError", "record_audio"]

log = logging.getLogger(__name__)


class RecorderError(RuntimeError):
    """录音设备不可用，或缺少 pyaudio。"""


def _import_pyaudio():
    try:
        import pyaudio
    except ImportError as exc:
        raise RecorderError(
            "缺少 pyaudio，无法录音。请执行:  pip install pyaudio\n"
            "Windows 上如果安装失败，可改用:  pip install pipwin && pipwin install pyaudio"
        ) from exc
    return pyaudio


def record_audio(
    output_filename: str | Path,
    duration: float = 5,
    sample_rate: int = 16000,
    chunk_size: int = 1024,
    channels: int = 1,
) -> Path:
    """录制一段音频并写入 WAV 文件。

    Args:
        output_filename: 目标 WAV 路径（会自动创建所在目录）。
        duration: 录音时长，单位秒。
        sample_rate: 采样率，百度语音识别要求 16000。
        chunk_size: 每次读取的帧数。
        channels: 声道数，通常为 1。

    Returns:
        实际写入的文件路径。

    Raises:
        RecorderError: 没有 pyaudio、没有麦克风或设备打开失败。
    """
    pyaudio = _import_pyaudio()
    target = Path(output_filename)
    target.parent.mkdir(parents=True, exist_ok=True)

    audio = pyaudio.PyAudio()
    stream = None
    try:
        format_type = pyaudio.paInt16
        stream = audio.open(
            format=format_type,
            channels=int(channels),
            rate=int(sample_rate),
            input=True,
            frames_per_buffer=int(chunk_size),
        )
        log.info("开始录音 %s 秒…", duration)
        frames = [
            stream.read(int(chunk_size))
            for _ in range(int(sample_rate / chunk_size * duration))
        ]
    except OSError as exc:
        raise RecorderError(f"打开麦克风失败（检查录音设备与权限）: {exc}") from exc
    finally:
        if stream is not None:
            stream.stop_stream()
            stream.close()
        sample_width = audio.get_sample_size(pyaudio.paInt16)
        audio.terminate()

    with wave.open(str(target), "wb") as handle:
        handle.setnchannels(int(channels))
        handle.setsampwidth(sample_width)
        handle.setframerate(int(sample_rate))
        handle.writeframes(b"".join(frames))
    log.info("录音完成: %s", target)
    return target
