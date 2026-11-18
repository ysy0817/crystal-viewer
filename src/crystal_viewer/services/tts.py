"""百度语音合成（TTS）：把晶胞介绍文字读出来。

生成的 mp3 会先用 pygame.mixer 播放；因为 pygame 本就是本项目的必需依赖，
所以不再额外引入 playsound。
接口文档：https://ai.baidu.com/ai-doc/SPEECH/Gk38y8lzk
"""

from __future__ import annotations

import json
import logging
import tempfile
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

__all__ = ["BaiduTTS", "TTSError"]

log = logging.getLogger(__name__)

_TOKEN_URL = "https://aip.baidubce.com/oauth/2.0/token"
_TIMEOUT = 30.0


class TTSError(RuntimeError):
    """语音合成失败：缺少密钥、网络异常或音频设备不可用。"""


class BaiduTTS:
    """在线合成语音并播放。"""

    def __init__(
        self,
        api_key: str,
        secret_key: str,
        cuid: str,
        spd: int = 5,
        pit: int = 5,
        vol: int = 5,
        per: int = 5003,
        lan: str = "zh",
        ctp: int = 1,
        aue: int = 3,
        url: str = "https://tsn.baidu.com/text2audio",
    ) -> None:
        self._api_key = (api_key or "").strip()
        self._secret_key = (secret_key or "").strip()
        self._cuid = str(cuid or "0")
        self._spd = int(spd)
        self._pit = int(pit)
        self._vol = int(vol)
        self._per = int(per)
        self._lan = str(lan)
        self._ctp = int(ctp)
        self._aue = int(aue)
        self._url = url

    def check_ready(self) -> None:
        if not self._api_key or not self._secret_key:
            raise TTSError(
                "未配置百度语音合成密钥。请把 tts.api_key / tts.secret_key "
                "填到 config.local.yaml，或设置环境变量 "
                "BAIDU_TTS_API_KEY / BAIDU_TTS_SECRET_KEY"
            )

    # -- 合成 -------------------------------------------------------------- #
    def fetch_token(self) -> str:
        params = {
            "grant_type": "client_credentials",
            "client_id": self._api_key,
            "client_secret": self._secret_key,
        }
        data = urlencode(params).encode("utf-8")
        try:
            with urlopen(Request(_TOKEN_URL, data), timeout=_TIMEOUT) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except (URLError, HTTPError, json.JSONDecodeError) as exc:
            raise TTSError(f"获取百度 access_token 失败: {exc}") from exc
        token = payload.get("access_token")
        if not token:
            raise TTSError(f"百度返回里没有 access_token，请检查 TTS 密钥: {payload}")
        return str(token)

    def synthesize(self, text: str) -> bytes:
        """把文字合成为 mp3 二进制内容。"""
        self.check_ready()
        text = (text or "").strip()
        if not text:
            raise TTSError("要朗读的文字是空的")
        params = {
            "tex": text,
            "tok": self.fetch_token(),
            "cuid": self._cuid,
            "ctp": self._ctp,
            "lan": self._lan,
            "spd": self._spd,
            "pit": self._pit,
            "vol": self._vol,
            "per": self._per,
            "aue": self._aue,
        }
        body = urlencode(params).encode("utf-8")
        headers = {
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "*/*",
        }
        try:
            with urlopen(Request(self._url, body, headers), timeout=_TIMEOUT) as response:
                content = response.read()
                content_type = response.headers.get("Content-Type", "")
        except (URLError, HTTPError) as exc:
            raise TTSError(f"调用百度语音合成失败: {exc}") from exc

        if "json" in content_type.lower() or content[:1] in (b"{", b"["):
            try:
                payload = json.loads(content.decode("utf-8"))
            except (json.JSONDecodeError, UnicodeDecodeError):
                payload = {"raw": content[:200]}
            raise TTSError(
                f"百度语音合成返回错误: {payload.get('err_msg') or payload}"
            )
        return content

    # -- 播放 -------------------------------------------------------------- #
    def speak(self, text: str) -> None:
        """合成并播放；播放是阻塞的，建议放到线程里调用。"""
        audio = self.synthesize(text)
        try:
            import pygame
        except ImportError as exc:  # pragma: no cover - pygame 是必需依赖
            raise TTSError(f"播放音频需要 pygame: {exc}") from exc

        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as handle:
            handle.write(audio)
            temp_path = Path(handle.name)

        try:
            if not pygame.mixer.get_init():
                pygame.mixer.init()
            pygame.mixer.music.load(str(temp_path))
            pygame.mixer.music.play()
            clock = pygame.time.Clock()
            while pygame.mixer.music.get_busy():
                clock.tick(20)
        except pygame.error as exc:
            raise TTSError(f"播放语音失败（检查音频输出设备）: {exc}") from exc
        finally:
            try:
                pygame.mixer.music.unload()
            except (pygame.error, AttributeError):  # pragma: no cover
                pass
            temp_path.unlink(missing_ok=True)
        log.info("语音播放完成")
