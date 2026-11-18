"""手势识别：用摄像头 + MediaPipe 追踪手腕横向移动来切换晶胞。

依赖 ``opencv-python`` 与 ``mediapipe``，属可选功能；缺失时程序仍可正常演示。
"""

from __future__ import annotations

import logging

__all__ = ["GestureError", "GestureTracker"]

log = logging.getLogger(__name__)


class GestureError(RuntimeError):
    """摄像头不可用或缺少 opencv / mediapipe。"""


class GestureTracker:
    """封装摄像头读取、姿态推理与"左右移动 → 切换"的判定。"""

    def __init__(self, config: object) -> None:
        self._cfg = config
        self._cv2 = None
        self._mp = None
        self._pose = None
        self._cap = None
        self._warmup = 0
        self._last_operation = 0.0
        self._skip_sample = False
        self._busy = False
        self._shown = False

    # -- 生命周期 ---------------------------------------------------------- #
    def open(self) -> None:
        try:
            import cv2
            import mediapipe as mp
        except ImportError as exc:
            raise GestureError(
                "手势识别需要 opencv-python 与 mediapipe，请执行:\n"
                "  pip install opencv-python mediapipe\n"
                "或者关闭手势功能: 把 config.yaml 里 gesture.enabled 改成 false"
            ) from exc

        self._cv2, self._mp = cv2, mp
        index = int(self._cfg.camera_index)
        capture = cv2.VideoCapture(index)
        if not capture.isOpened():
            capture.release()
            raise GestureError(
                f"无法打开摄像头 {index}。请检查是否被其他程序占用，"
                "或把 config.yaml 里的 gesture.camera_index 改成其他编号"
            )
        self._cap = capture
        self._pose = mp.solutions.pose.Pose()
        log.info("摄像头 %s 已就绪", index)

    def close(self) -> None:
        if self._cap is not None:
            self._cap.release()
            self._cap = None
        if self._pose is not None:
            self._pose.close()
            self._pose = None
        if self._shown and self._cv2 is not None:
            try:
                self._cv2.destroyAllWindows()
            except Exception:  # pragma: no cover - 退出阶段
                pass
            self._shown = False

    # -- 状态 -------------------------------------------------------------- #
    @property
    def busy(self) -> bool:
        """切换动画进行中时为 True，用来避免误触发。"""
        return self._busy

    @busy.setter
    def busy(self, value: bool) -> None:
        self._busy = bool(value)

    def notify_switched(self) -> None:
        """刚发生过切换：下一次采样只记录基准，不产生事件。"""
        self._skip_sample = True

    # -- 每帧处理 ---------------------------------------------------------- #
    def process(self) -> tuple[object | None, int]:
        """读取一帧并判断是否发生切换。

        Returns:
            ``(frame, event)``，event 为 ``+1``（下一个）、``-1``（上一个）或 ``0``。
            frame 为 None 表示取帧失败。
        """
        if self._cap is None or self._cv2 is None:
            return None, 0
        cv2 = self._cv2
        ok, frame = self._cap.read()
        if not ok or frame is None:
            return None, 0
        if self._cfg.mirror:
            frame = cv2.flip(frame, 1)

        results = self._pose.process(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
        event = 0
        if results.pose_landmarks:
            if self._cfg.show_window:
                self._mp.solutions.drawing_utils.draw_landmarks(
                    frame, results.pose_landmarks, self._mp.solutions.pose.POSE_CONNECTIONS
                )
            event = self._detect(results)

        if self._cfg.show_window:
            cv2.imshow("camera", frame)
            # 没有 waitKey 时窗口不会刷新，这里补上（按 q 也可退出）。
            if cv2.waitKey(1) & 0xFF == ord("q"):
                raise GestureError("用户关闭了摄像头窗口")
            self._shown = True
        return frame, event

    # -- 判定逻辑 ---------------------------------------------------------- #
    def _detect(self, results: object) -> int:
        if self._busy:
            return 0

        landmarks = results.pose_landmarks.landmark  # type: ignore[attr-defined]
        index = int(self._cfg.landmark)
        if index >= len(landmarks):
            return 0
        landmark = landmarks[index]
        if landmark.visibility <= float(self._cfg.min_visibility):
            return 0

        self._warmup += 1
        if self._warmup < int(self._cfg.warmup_frames):
            return 0

        current = landmark.x * float(self._cfg.move_scale)
        self._warmup = 0

        if self._skip_sample:
            self._last_operation = current
            self._skip_sample = False
            return 0

        delta = current - self._last_operation
        self._last_operation = current
        threshold = float(self._cfg.switch_threshold)
        if delta >= threshold:
            return 1
        if delta <= -threshold:
            return -1
        return 0
