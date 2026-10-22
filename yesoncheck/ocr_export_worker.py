"""OCR 구간 내보내기 백그라운드 워커 (OCRExportWorker). 기존 경로 `yesoncheck.workers`에서도 불러올 수 있음."""

import re
import subprocess
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Lock

from PyQt5.QtCore import QThread, pyqtSignal

from yesoncheck import external_tools, file_names


class OCRExportWorker(QThread):
    """Export OCR-detected segments to individual video clips with parallel processing."""

    progress = pyqtSignal(int)
    status = pyqtSignal(str)
    error = pyqtSignal(str)
    completed = pyqtSignal(dict)  # {'segments': [...], 'cancelled': bool}

    def __init__(self, video_path, segments, output_dir, ffmpeg_path, include_audio=True, export_mode='balanced', bitrate=None, max_workers=4):
        super().__init__()
        self.video_path = video_path
        self.segments = segments or []
        self.output_dir = Path(output_dir)
        self.ffmpeg_path = ffmpeg_path
        self.include_audio = include_audio
        self.export_mode = export_mode  # 'fast' (VideoToolbox), 'quality' (libx264 slower), 'balanced' (libx264 faster)
        self.bitrate = bitrate or "8000k"  # 기본값: 8000k (fast 모드에서만 사용)
        self.max_workers = max_workers  # 동시 FFmpeg 프로세스 수 (기본값: 4)
        self._is_running = True
        self._was_cancelled = False
        self._progress_lock = Lock()  # 스레드 안전한 진행률 업데이트
        self._completed_count = 0
        self._executor = None  # ThreadPoolExecutor 참조 저장
        self._procs = set()  # 실행 중인 ffmpeg (취소 시 끝냄)
        self._procs_lock = Lock()

    def stop(self):
        self._is_running = False
        self._was_cancelled = True
        # ThreadPoolExecutor가 있으면 취소 시도
        if self._executor is not None:
            try:
                # 실행 중인 작업 취소 시도 (Python 3.9+)
                if hasattr(self._executor, 'shutdown'):
                    self._executor.shutdown(wait=False, cancel_futures=True)
            except Exception:
                pass  # 이미 종료되었거나 오류 발생 시 무시
        # 실행 중인 ffmpeg를 끝냄 (Windows에서는 남은 ffmpeg가 출력 파일을 잠금)
        with self._procs_lock:
            running = list(self._procs)
        for proc in running:
            proc.kill()

    def _export_single_segment(self, idx, segment, total_segments):
        """Export a single segment to video file. Returns (success, segment_with_path, error_msg)."""
        if not self._is_running:
            return (False, None, "취소됨")

        # duration이 segment에 직접 포함되어 있으면 사용 (정확한 프레임 계산)
        # 없으면 end_time - start_time으로 계산 (하위 호환성)
        if "duration" in segment:
            duration = segment["duration"]
        else:
            duration = max(0.0, segment["end_time"] - segment["start_time"])

        if duration <= 0.0:
            log_msg = f"[구간 {idx}/{total_segments}] duration이 0이므로 스킵"
            self.status.emit(log_msg)
            # print(f"[OCRExportWorker] {log_msg}")
            return (False, None, None)

        # edited_text가 있으면 우선 사용, 없으면 text(원본 OCR 결과) 사용
        safe_name = segment.get("edited_text") or segment.get("text") or "blank"
        safe_name = re.sub(r"[^0-9A-Za-z_-]+", "_", safe_name)[:80] or "segment"
        safe_name = file_names.avoid_reserved_name(safe_name)

        # 중복 파일명 처리: 같은 이름이 있으면 _1, _2, _3... 추가
        base_filename = f"{safe_name}.mp4"
        output_path = self.output_dir / base_filename
        counter = 1
        while output_path.exists():
            base_filename = f"{safe_name}_{counter}.mp4"
            output_path = self.output_dir / base_filename
            counter += 1

        filename = base_filename

        # 구간 정보 로그
        log_msg = f"[구간 {idx}/{total_segments}] '{filename}' 내보내기 시작..."
        self.status.emit(log_msg)
        # print(f"[OCRExportWorker] {log_msg}")

        # FFmpeg 정밀도 문제로 다음 프레임이 포함되는 것을 방지
        # end_time을 약간 일찍 끊어서 end_frame까지만 정확히 포함
        # 프레임의 마지막 시점 직전에 끊기
        start_frame = segment['start_frame']
        end_frame = segment['end_frame']
        start_time = segment['start_time']

        # fps 계산: duration과 프레임 수로 역산
        num_frames = end_frame - start_frame + 1
        if duration > 0:
            fps = num_frames / duration
        elif start_time > 0 and start_frame > 0:
            fps = start_frame / start_time
        else:
            fps = 24.0  # 기본값

        # end_frame의 끝 시점에서 약간 일찍 끊기 (다음 프레임 미포함)
        precise_end_time = (end_frame + 1 - 0.001) / fps

        # 구간 상세 정보 로그
        log_msg = f"[구간 {idx}/{total_segments}] 프레임: {start_frame}-{end_frame} ({num_frames}프레임), 시간: {start_time:.3f}s-{precise_end_time:.3f}s ({duration:.3f}s), FPS: {fps:.2f}"
        self.status.emit(log_msg)
        # print(f"[OCRExportWorker] {log_msg}")

        ffmpeg_cmd = [
            self.ffmpeg_path,
            "-y",
            "-i",
            str(self.video_path),
            "-ss",
            f"{segment['start_time']:.6f}",
            "-to",
            f"{precise_end_time:.6f}",
        ]

        # 내보내기 모드에 따라 인코딩 설정 (고속: Mac VideoToolbox, Windows libx264 veryfast + 비트레이트)
        ffmpeg_cmd.extend(external_tools.video_encoder_args(self.export_mode, self.bitrate))
        if self.include_audio:
            ffmpeg_cmd.extend(["-c:a", "aac", "-b:a", "192k"])
        else:
            ffmpeg_cmd.append("-an")
        mode_name = {"fast": external_tools.fast_mode_label(), "quality": "고품질 (libx264 slower, CRF 18)"}.get(
            self.export_mode, "균형 (libx264 faster, CRF 20)")
        bitrate_note = f", 비트레이트: {self.bitrate}" if self.export_mode == "fast" else ""
        log_msg = f"[구간 {idx}/{total_segments}] 인코딩 모드: {mode_name}{bitrate_note} (오디오: {'포함' if self.include_audio else '제외'})"

        self.status.emit(log_msg)
        # print(f"[OCRExportWorker] {log_msg}")

        ffmpeg_cmd.append(str(output_path))

        # FFmpeg 명령어 로그 (디버깅용)
        log_msg = f"[구간 {idx}/{total_segments}] FFmpeg 실행: {' '.join(ffmpeg_cmd[:10])}... (명령어 길이: {len(ffmpeg_cmd)}개 인자)"
        self.status.emit(log_msg)
        # print(f"[OCRExportWorker] {log_msg}")

        try:
            log_msg = f"[구간 {idx}/{total_segments}] FFmpeg 인코딩 시작..."
            self.status.emit(log_msg)
            # print(f"[OCRExportWorker] {log_msg}")

            proc = subprocess.Popen(ffmpeg_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                                    **external_tools.subprocess_kwargs())
        except OSError as exc:
            return (False, None, f"FFmpeg 실행 실패 ({filename}): {exc}")
        with self._procs_lock:
            self._procs.add(proc)
        if not self._is_running:  # stop()이 Popen과 등록 사이에 불린 경우
            proc.kill()
        try:
            _, stderr = proc.communicate()
        finally:
            with self._procs_lock:
                self._procs.discard(proc)
        if not self._is_running:
            output_path.unlink(missing_ok=True)  # 취소로 끊긴 미완성 파일
            return (False, None, "취소됨")
        if proc.returncode != 0:
            return (False, None, f"FFmpeg 오류 ({filename}): {external_tools.decode_output(stderr)}")

        log_msg = f"[구간 {idx}/{total_segments}] '{filename}' 내보내기 완료 → {output_path}"
        self.status.emit(log_msg)
        segment_with_path = dict(segment)
        segment_with_path["output_path"] = str(output_path)
        return (True, segment_with_path, None)

    def run(self):
        if not self.segments:
            log_msg = "내보낼 구간이 없습니다."
            self.progress.emit(100)
            self.status.emit(log_msg)
            # print(f"[OCRExportWorker] {log_msg}")
            self.completed.emit({"segments": [], "cancelled": False})
            return

        log_msg = f"FFmpeg로 구간을 내보내는 중… (총 {len(self.segments)}개 구간, 모드: {self.export_mode}, 병렬 처리: {self.max_workers}개)"
        self.status.emit(log_msg)
        # print(f"[OCRExportWorker] {log_msg}")

        try:
            self.output_dir.mkdir(parents=True, exist_ok=True)
            log_msg = f"출력 폴더 생성 완료: {self.output_dir}"
            self.status.emit(log_msg)
            # print(f"[OCRExportWorker] {log_msg}")
        except Exception as exc:
            error_msg = f"출력 폴더를 생성할 수 없습니다: {exc}"
            self.error.emit(error_msg)
            # print(f"[OCRExportWorker] {error_msg}")
            return

        total_segments = len(self.segments)
        exported_segments = []

        # ThreadPoolExecutor를 사용한 병렬 내보내기
        executor = ThreadPoolExecutor(max_workers=self.max_workers)
        self._executor = executor
        future_to_segment = {}  # finally 블록에서 사용하기 위해 미리 초기화
        
        try:
            # 모든 구간을 비동기로 제출
            future_to_segment = {
                executor.submit(self._export_single_segment, idx, segment, total_segments): (idx, segment)
                for idx, segment in enumerate(self.segments, start=1)
            }

            # 완료된 순서대로 처리 (실행 순서와 다를 수 있음)
            for future in as_completed(future_to_segment):
                if not self._is_running:
                    log_msg = "구간 내보내기가 취소되었습니다."
                    self.status.emit(log_msg)
                    # print(f"[OCRExportWorker] {log_msg}")
                    self.progress.emit(100)
                    self.completed.emit({"segments": exported_segments, "cancelled": True})
                    break  # 루프 종료, finally에서 executor 종료

                idx, segment = future_to_segment[future]

                try:
                    success, segment_with_path, error_msg = future.result()

                    if error_msg and error_msg != "취소됨":
                        # FFmpeg 오류 발생
                        self.error.emit(error_msg)
                        # print(f"[OCRExportWorker] {error_msg}")
                        self.progress.emit(100)
                        self.completed.emit({"segments": exported_segments, "cancelled": False})
                        break  # 루프 종료, finally에서 executor 종료

                    if success and segment_with_path:
                        exported_segments.append(segment_with_path)

                    # 스레드 안전한 진행률 업데이트
                    with self._progress_lock:
                        self._completed_count += 1
                        progress = int((self._completed_count / total_segments) * 100)
                        self.progress.emit(progress)
                        log_msg = f"진행률: {progress}% ({self._completed_count}/{total_segments} 구간 완료)"
                        self.status.emit(log_msg)

                except Exception as exc:
                    error_msg = f"예상치 못한 오류: {exc}"
                    self.error.emit(error_msg)
                    # print(f"[OCRExportWorker] {error_msg}")
                    self.progress.emit(100)
                    self.completed.emit({"segments": exported_segments, "cancelled": False})
                    break  # 루프 종료, finally에서 executor 종료
        finally:
            # ThreadPoolExecutor 안전하게 종료
            try:
                if self._is_running:
                    # 정상 종료: 모든 작업 완료 대기
                    executor.shutdown(wait=True)
                else:
                    # 취소된 경우: 실행 중인 작업 취소 시도 후 대기
                    try:
                        executor.shutdown(wait=False, cancel_futures=True)
                    except TypeError:
                        # Python 3.8 이하에서는 cancel_futures 지원 안 함
                        executor.shutdown(wait=False)
                    # 취소된 작업이 완료될 때까지 대기 (최대 10초)
                    import time
                    if future_to_segment:
                        start_time = time.time()
                        while time.time() - start_time < 10:
                            if all(future.done() for future in future_to_segment.keys()):
                                break
                            time.sleep(0.1)
            except Exception as exc:
                # print(f"[OCRExportWorker] Executor 종료 중 오류 (무시): {exc}")
                pass
            finally:
                self._executor = None

        self.progress.emit(100)
        log_msg = f"OCR 구간 내보내기가 완료되었습니다. (총 {len(exported_segments)}개 파일 생성, 출력 폴더: {self.output_dir})"
        self.status.emit(log_msg)
        # print(f"[OCRExportWorker] {log_msg}")
        self.completed.emit({"segments": exported_segments, "cancelled": self._was_cancelled})
