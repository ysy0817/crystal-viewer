"""百度语音识别（短语音识别标准版）。

只用标准库完成 HTTP 请求，因此不额外引入 requests 依赖。
接口文档：https://ai.baidu.com/ai-doc/SPEECH/Vk38lxily
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

__all__ = ["ASRError", "BaiduASR"]

log = logging.getLogger(__name__)

_TOKEN_URL = "https://aip.baidubce.com/oauth/2.0/token"
_TIMEOUT = 15.0


class ASRError(RuntimeError):
    """语音识别失败：缺少密钥、网络异常或服务端返回错误。"""


class BaiduASR:
    """把一段 WAV 转成中文文本。"""

    def __init__(
        self,
        api_key: str,
        secret_key: str,
        cuid: str,
        dev_pid: int = 1537,
        url: str = "http://vop.baidu.com/server_api",
        scope: str = "audio_voice_assistant_get",
        sample_rate: int = 16000,
    ) -> None:
        self._api_key = (api_key or "").strip()
        self._secret_key = (secret_key or "").strip()
        self._cuid = str(cuid or "0")
        self._dev_pid = int(dev_pid)
        self._url = url
        self._scope = scope
        self._sample_rate = int(sample_rate)

    # -- 密钥检查 ---------------------------------------------------------- #
    def check_ready(self) -> None:
        """在启动时提前检查密钥，避免用户录完音才发现没配置。"""
        if not self._api_key or not self._secret_key:
            raise ASRError(
                "未配置百度语音识别密钥。请把 asr.api_key / asr.secret_key "
                "填到 config.local.yaml，或设置环境变量 "
                "BAIDU_ASR_API_KEY / BAIDU_ASR_SECRET_KEY"
            )

    # -- token ------------------------------------------------------------- #
    def fetch_token(self) -> str:
        params = {
            "grant_type": "client_credentials",
            "client_id": self._api_key,
            "client_secret": self._secret_key,
        }
        data = urlencode(params).encode("utf-8")
        request = Request(_TOKEN_URL, data)
        try:
            with urlopen(request, timeout=_TIMEOUT) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except (URLError, HTTPError, json.JSONDecodeError) as exc:
            raise ASRError(f"获取百度 access_token 失败（检查网络或密钥）: {exc}") from exc

        token = payload.get("access_token")
        if not token:
            hint = payload.get("error_description") or payload.get("error") or payload
            raise ASRError(f"百度返回里没有 access_token，请检查 API Key: {hint}")

        scope = str(payload.get("scope") or "")
        if self._scope and self._scope not in scope.split(" "):
            log.warning(
                "百度账号缺少 %s 权限，语音识别可能不可用（请在控制台勾选该能力）",
                self._scope,
            )
        return str(token)

    # -- 识别 -------------------------------------------------------------- #
    def recognize(self, audio_file: str | Path) -> str:
        """识别 WAV 文件，返回识别出的文本（可能为空串）。"""
        self.check_ready()
        path = Path(audio_file)
        try:
            speech = path.read_bytes()
        except OSError as exc:
            raise ASRError(f"读取录音文件失败 {path}: {exc}") from exc
        if not speech:
            raise ASRError(f"录音文件是空的，没有录到声音: {path}")

        token = self.fetch_token()
        suffix = path.suffix.lower().lstrip(".") or "wav"
        if suffix not in {"pcm", "wav", "amr", "m4a"}:
            raise ASRError(f"百度识别不支持的音频格式: {suffix}（支持 pcm/wav/amr/m4a）")

        query = urlencode({"cuid": self._cuid, "token": token, "dev_pid": self._dev_pid})
        headers = {
            "Content-Type": f"audio/{suffix}; rate={self._sample_rate}",
            "Content-Length": str(len(speech)),
        }
        request = Request(f"{self._url}?{query}", speech, headers)
        try:
            with urlopen(request, timeout=_TIMEOUT) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except (URLError, HTTPError, json.JSONDecodeError) as exc:
            raise ASRError(f"调用百度语音识别失败: {exc}") from exc

        if payload.get("err_no") not in (0, None):
            raise ASRError(
                f"百度语音识别返回错误 {payload.get('err_no')}: {payload.get('err_msg')}"
            )
        results = payload.get("result") or []
        text = str(results[0]).strip() if results else ""
        log.info("识别结果: %r", text)
        return text
