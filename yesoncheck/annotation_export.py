"""Export video with frame annotations burned in."""

import os
import subprocess
import sys

import cv2
from PyQt5.QtCore import QThread, pyqtSignal

from yesoncheck.annotation_burn import burn_annotations_on_frame


class AnnotationExportWorker(QThread):
    """Re-encode a video with per-frame annotations burned into pixels."""

    progress = pyqtSignal(int)
    status = pyqtSignal(str)
    error = pyqtSignal(str)
    completed = pyqtSignal(str)

    def __init__(
        self,
        video_path,
        annotations_by_frame,
        output_path,
        ffmpeg_path,
        include_audio=True,
        export_mode="balanced",
        bitrate="8000k",
    ):
        super().__init__()
        self.video_path = video_path
        self.annotations_by_frame = annotations_by_frame or {}
        self.output_path = output_path
        self.ffmpeg_path = ffmpeg_path
        self.include_audio = include_audio
        self.export_mode = export_mode
        self.bitrate = bitrate
        self._is_running = True

    def stop(self):
        self._is_running = False

    def _build_ffmpeg_cmd(self, width, height, fps):
        cmd = [
            self.ffmpeg_path,
            "-y",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "bgr24",
            "-s",
            f"{width}x{height}",
            "-r",
            f"{fps:.6f}",
            "-i",
            "pipe:0",
            "-i",
            self.video_path,
            "-map",
            "0:v:0",
        ]
        if self.include_audio:
            cmd.extend(["-map", "1:a:0?"])
        else:
            cmd.append("-an")

        if self.export_mode == "fast" and sys.platform == "darwin":
            cmd.extend(
                [
                    "-c:v",
                    "h264_videotoolbox",
                    "-b:v",
                    self.bitrate,
                    "-allow_sw",
                    "1",
                ]
            )
        elif self.export_mode == "quality":
            cmd.extend(["-c:v", "libx264", "-preset", "slower", "-crf", "18"])
        else:
            cmd.extend(["-c:v", "libx264", "-preset", "faster", "-crf", "20"])

        if self.include_audio:
            cmd.extend(["-c:a", "aac", "-b:a", "192k"])
        cmd.append(self.output_path)
        return cmd

    def run(self):
        cap = None
        proc = None
        try:
            cap = cv2.VideoCapture(self.video_path)
            if not cap.isOpened():
                self.error.emit(f"비디오를 열 수 없습니다: {self.video_path}")
                return

            width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            fps = float(cap.get(cv2.CAP_PROP_FPS) or 0.0)
            if fps <= 0:
                fps = 24.0
            total_frames = max(1, int(cap.get(cv2.CAP_PROP_FRAME_COUNT)))

            output_dir = os.path.dirname(self.output_path)
            if output_dir:
                os.makedirs(output_dir, exist_ok=True)

            cmd = self._build_ffmpeg_cmd(width, height, fps)
            self.status.emit("주석 포함 영상 인코딩 시작…")
            proc = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            frame_idx = 0
            annotated_frames = 0
            while self._is_running:
                ret, frame_bgr = cap.read()
                if not ret:
                    break

                items = self.annotations_by_frame.get(frame_idx, [])
                if items:
                    frame_rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
                    frame_rgb = burn_annotations_on_frame(frame_rgb, items)
                    frame_bgr = cv2.cvtColor(frame_rgb, cv2.COLOR_RGB2BGR)
                    annotated_frames += 1

                proc.stdin.write(frame_bgr.tobytes())
                frame_idx += 1
                if frame_idx % 5 == 0 or frame_idx == total_frames:
                    self.progress.emit(min(99, int(frame_idx / total_frames * 100)))

            if not self._is_running:
                proc.stdin.close()
                proc.terminate()
                self.error.emit("보내기가 취소되었습니다.")
                return

            proc.stdin.close()
            stderr = proc.stderr.read().decode("utf-8", errors="ignore")
            return_code = proc.wait()
            if return_code != 0:
                self.error.emit(f"FFmpeg 오류:\n{stderr[-4000:]}")
                return

            self.progress.emit(100)
            self.status.emit(
                f"완료: {frame_idx}프레임 처리, {annotated_frames}프레임에 주석 적용"
            )
            self.completed.emit(self.output_path)
        except Exception as exc:
            self.error.emit(str(exc))
        finally:
            if cap is not None:
                cap.release()
            if proc is not None and proc.poll() is None:
                proc.terminate()
