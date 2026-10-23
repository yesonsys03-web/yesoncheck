"""이미지 시퀀스 -> mov 일괄 내보내기 백그라운드 워커 (SequenceExportWorker)와 출력 폴더 검사(validate_out_dir).

`AnnotationExportWorker`의 파이프 패턴을 본뜬다: ImageSequenceCapture가 주는 BGR 프레임을 ffmpeg stdin(rawvideo bgr24)으로 흘리고,
ffmpeg의 stderr는 리더 스레드로 계속 비운다 (안 읽으면 파이프가 차서 ffmpeg도, 프레임을 쓰는 이쪽도 멈춤).
캡처가 빠진 번호를 직전 프레임으로 메우므로 모든 read()를 그대로 흘리면 길이가 보존되고, 진행률은 프레임 단위다.

항목은 하나씩 차례로 처리한다. 항목 하나의 실패(시퀀스를 못 엶·디코드 오류·ffmpeg 오류·프레임 수 불일치·덮어쓸 파일이 잠김)는
그 항목의 부분 출력을 지우고 기록만 한 뒤 다음 항목으로 넘어가며, 모두 끝난 뒤 실패가 하나라도 있으면 error(요약) 하나로 알린다.
취소(stop)와 오류는 모두 만들던 항목의 부분 출력을 지운다. 출력은 `<base>.mov.part`로 만들다가 검증이 끝나면 `<base>.mov`로 바꾼다
(os.replace) — 만드는 중인 파일이 `.mov`로 보이지 않고, 실패·취소가 이미 있던 `<base>.mov`를 건드리지 않는다.
"""

import os
import subprocess
import threading
import traceback
from fractions import Fraction

import cv2
from PyQt5.QtCore import QThread, pyqtSignal

from yesoncheck import external_tools
from yesoncheck.sequence_source import ImageSequenceCapture

EXPORT_MODE = "balanced"  # 주석 굽기 내보내기의 기본 모드와 같은 video_encoder_args (libx264 faster, crf 20)
EXPORT_BITRATE = "8000k"  # 고속 모드에서만 쓰이는 값 — 주석 굽기 내보내기의 기본값과 같게
PARTIAL_SUFFIX = ".mov.part"  # 만드는 중인 출력의 이름 (<base>.mov.part)
MAX_RATE_DENOMINATOR = 1001  # fps 분수의 분모 한도 (23.976 -> 24000/1001) — 병합의 pick_frame_rate와 같은 기준
ERROR_TAIL_CHARS = 4000  # 오류 글에 붙이는 ffmpeg stderr의 끝부분


class SequenceExportError(RuntimeError):
    """예상한 실패 — 메시지가 곧 설명이라 스택 트레이스 없이 보여 준다 (그 밖의 예외는 스택 트레이스째)."""


class _Cancelled(Exception):
    """stop()으로 항목을 중간에 멈춤 (내부 신호 — 오류가 아님)."""


def _normalized(path):
    return os.path.normcase(os.path.realpath(os.path.abspath(path)))


def _same_folder(first, second):
    """같은 폴더인지: 정규화한 경로가 같거나, 둘 다 있으면 같은 파일 시스템 항목 (링크·대소문자 무시 파일 시스템·마운트 별칭)."""
    if _normalized(first) == _normalized(second):
        return True
    try:
        return os.path.samefile(first, second)
    except (FileNotFoundError, NotADirectoryError):
        return False  # 하나가 아직 없는 폴더면 같은 폴더일 수 없음


def validate_out_dir(items, out_dir):
    """out_dir이 어떤 항목의 원본 폴더(dir)와 같으면 거부 사유 문자열, 아니면 None (원본 폴더에는 mov를 만들지 않는다)."""
    for item in items:
        if _same_folder(item.dir, out_dir):
            return f"원본 폴더에는 MOV를 만들 수 없습니다 — 다른 폴더를 고르세요.\n원본 폴더: {item.dir}"
    return None


def _frames_of(seq):
    """스캔에서 본 시퀀스의 길이 (빠진 번호도 한 프레임으로 셈 — 빠진 프레임은 직전 프레임으로 메워 내보내므로)."""
    return seq.last - seq.first + 1


def _count_packets(path):
    """ffprobe로 센 mov의 영상 패킷 수 (컨테이너에 실제로 든 프레임 수)."""
    result = subprocess.run(
        [external_tools.ffprobe_path(), "-v", "error", "-count_packets", "-select_streams", "v:0",
         "-show_entries", "stream=nb_read_packets", "-of", "csv=p=0", path],
        capture_output=True, **external_tools.subprocess_kwargs())
    text = external_tools.decode_output(result.stdout).strip()
    if result.returncode != 0 or not text.isdigit():
        raise SequenceExportError(f"만든 mov의 프레임 수를 알 수 없습니다 (ffprobe 종료 코드 {result.returncode}, "
                                  f"출력 {text!r})\n{external_tools.decode_output(result.stderr)[-ERROR_TAIL_CHARS:]}")
    return int(text)


class SequenceExportWorker(QThread):
    """시퀀스 여러 개를 mov로 — `<out_dir>/<base>.mov`, fps는 짝 mov의 것(없으면 24).

    item_started(index, base): 항목을 시작할 때. progress(완료 프레임, 전체 프레임): 프레임마다, 전체는 항목 합산.
    finished(): 모두 성공. error(글): 실패가 있으면 끝난 뒤 요약 하나 (실패한 항목마다 이유), 또는 시작할 수 없을 때 이유.
    취소(stop)는 finished도 error도 내지 않는다 (cancelled가 True).
    """

    item_started = pyqtSignal(int, str)
    progress = pyqtSignal(int, int)
    finished = pyqtSignal()  # QThread.finished를 가림 — FFmpegWorker와 같은 모양 (스레드가 끝난 것은 wait()로)
    error = pyqtSignal(str)

    def __init__(self, items, out_dir, ffmpeg):
        super().__init__()
        self.items = list(items)
        self.out_dir = out_dir
        self.ffmpeg = ffmpeg
        self._stopped = threading.Event()
        self._proc = None
        self._proc_lock = threading.Lock()
        # 아래 셋은 run()을 도는 스레드만 만짐
        self._total = sum(_frames_of(seq) for seq in self.items)
        self._done = 0
        self._item_frames = 0  # 지금 항목의 프레임 수 (캡처를 열면 실제 값으로 바뀜)

    @property
    def cancelled(self):
        return self._stopped.is_set()

    def stop(self):
        """멈춤: 도는 ffmpeg를 끝내고 run()이 만들던 항목의 부분 출력을 지운다 (지우기는 ffmpeg가 완전히 끝난 뒤 run() 안에서 —
        Windows는 ffmpeg가 파일을 잡고 있는 동안 못 지움). 부분 출력이 사라진 것은 스레드가 끝난 뒤(wait())에 확실하다."""
        with self._proc_lock:
            self._stopped.set()
            proc = self._proc
        if proc is not None and proc.poll() is None:
            proc.kill()

    def _register(self, proc):
        with self._proc_lock:
            self._proc = proc
            stopped = self._stopped.is_set()
        if stopped:  # stop()이 ffmpeg를 띄우는 사이에 불린 경우
            proc.kill()

    def run(self):
        reason = validate_out_dir(self.items, self.out_dir)
        if reason is not None:
            self.error.emit(reason)
            return
        try:
            os.makedirs(self.out_dir, exist_ok=True)
        except OSError as exc:
            self.error.emit(f"출력 폴더를 만들 수 없습니다: {self.out_dir}\n{exc!r}\n\n{traceback.format_exc()}")
            return
        self.progress.emit(0, self._total)
        failures = []  # [(base, 이유)]
        made = set()  # 이 작업에서 이미 만든 출력 이름 (대소문자 무시) — 같은 이름을 말없이 덮어쓰지 않으려고
        for index, seq in enumerate(self.items):
            if self._stopped.is_set():
                break
            self.item_started.emit(index, seq.base)
            try:
                self._export_item(seq, made)
            except _Cancelled:
                break
            except (SequenceExportError, external_tools.ToolNotFoundError) as exc:
                failures.append((seq.base, str(exc)))
            except Exception as exc:  # 예상 못 한 실패: 이 항목만 실패로 — 무엇인지 + 스택 트레이스째 알림
                failures.append((seq.base, f"{exc!r}\n\n{traceback.format_exc()}"))
            else:
                continue
            self.progress.emit(self._done, self._total)  # 실패한 항목의 몫을 건너뛰어 전체 진행이 끝까지 가게
        if failures:
            self.error.emit(self._summary(failures))
        elif not self._stopped.is_set():
            self.finished.emit()

    def _summary(self, failures):
        header = f"{len(self.items)}개 중 {len(failures)}개 실패" + (" (취소됨)" if self.cancelled else "")
        return header + "\n" + "\n\n".join(f"[{base}] {reason}" for base, reason in failures)

    def _export_item(self, seq, made):
        """항목 하나를 만든다. 실패·취소면 부분 출력을 지우고 예외를 그대로 올림."""
        planned = _frames_of(seq)
        self._item_frames = planned
        base_done = self._done
        final = os.path.join(self.out_dir, seq.base + ".mov")
        partial = os.path.join(self.out_dir, seq.base + PARTIAL_SUFFIX)
        try:
            if seq.base.casefold() in made:
                raise SequenceExportError(f"같은 이름({seq.base}.mov)의 출력이 이 작업에서 이미 만들어졌습니다 — "
                                          f"덮어쓰지 않고 건너뜁니다: {seq.identity}")
            self._encode(seq, base_done, planned, partial)
            try:
                os.replace(partial, final)
            except PermissionError as exc:  # Windows: 덮어쓸 mov를 다른 프로그램이 열고 있음
                raise SequenceExportError(f"이미 있는 파일을 덮어쓸 수 없습니다 — 다른 프로그램이 열고 있는지 확인하세요: "
                                          f"{final}\n{exc!r}") from exc
            made.add(seq.base.casefold())
        except BaseException:
            self._remove_partial(partial)
            raise
        finally:
            self._done = base_done + self._item_frames

    @staticmethod
    def _remove_partial(path):
        try:
            os.remove(path)
        except FileNotFoundError:
            pass  # 만들기 전에 실패했거나 이미 없음

    def _command(self, width, height, fps, output):
        rate = Fraction(fps).limit_denominator(MAX_RATE_DENOMINATOR)  # 23.976024 -> 24000/1001 (소수로 주면 엉뚱한 분수가 됨)
        cmd = [self.ffmpeg, "-y", "-hide_banner", "-nostats", "-loglevel", "error",
               "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{width}x{height}",
               "-r", f"{rate.numerator}/{rate.denominator}", "-i", "pipe:0", "-an"]
        even_width, even_height = width + width % 2, height + height % 2
        if (even_width, even_height) != (width, height):  # yuv420p는 짝수 크기만 — 홀수면 검은 한 줄을 덧붙임
            cmd += ["-vf", f"pad={even_width}:{even_height}:0:0"]
        cmd += external_tools.video_encoder_args(EXPORT_MODE, EXPORT_BITRATE)
        cmd += ["-pix_fmt", "yuv420p", "-f", "mov", output]  # 확장자가 .part라 형식을 직접 정함
        return cmd

    def _encode(self, seq, base_done, planned, partial):
        """시퀀스를 읽어 ffmpeg에 흘리고, 끝나면 partial의 프레임 수를 확인한다 (틀리면 SequenceExportError)."""
        cap = ImageSequenceCapture(seq.identity)  # 폴더를 읽지 못하면 OSError가 그대로 올라옴
        proc = reader = None
        stderr_chunks = []
        try:
            if not cap.isOpened():
                raise SequenceExportError(f"시퀀스를 열 수 없습니다 (프레임이 없어졌거나 2장 미만): {seq.identity}")
            width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
            fps = float(cap.get(cv2.CAP_PROP_FPS))
            self._total += count - planned  # 스캔 뒤 폴더가 바뀌었으면 실제 길이로 (진행이 전체를 넘지 않게)
            self._item_frames = count

            proc = subprocess.Popen(self._command(width, height, fps, partial), stdin=subprocess.PIPE,
                                    stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, **external_tools.subprocess_kwargs())
            self._register(proc)
            reader = threading.Thread(target=lambda: stderr_chunks.append(proc.stderr.read()), daemon=True)
            reader.start()

            written = 0
            pipe_error = None  # ffmpeg가 다 읽기 전에 끝나서 stdin에 쓰지 못함
            while written < count:
                if self._stopped.is_set():
                    raise _Cancelled()
                ok, frame = cap.read()
                if not ok:
                    break
                try:
                    proc.stdin.write(frame.tobytes())
                except OSError as exc:
                    pipe_error = exc
                    break
                written += 1
                self.progress.emit(base_done + written, self._total)
            if pipe_error is None:
                try:
                    proc.stdin.close()
                except OSError as exc:
                    pipe_error = exc
            code = proc.wait()
            reader.join()
            if self._stopped.is_set():
                raise _Cancelled()
            stderr = external_tools.decode_output(b"".join(stderr_chunks))[-ERROR_TAIL_CHARS:]
            if code != 0 or pipe_error is not None:
                raise SequenceExportError(f"FFmpeg 오류 (종료 코드 {code}, {written}/{count}프레임 보냄"
                                          f"{'' if pipe_error is None else f', {pipe_error!r}'})\n{stderr}")
            if written != count:
                raise SequenceExportError(f"프레임을 {count}장 중 {written}장만 읽었습니다: {seq.identity}")
            if not os.path.exists(partial):
                raise SequenceExportError(f"FFmpeg가 출력 파일을 만들지 않았습니다: {partial}\n{stderr}")
            packets = _count_packets(partial)
            if packets != written:
                raise SequenceExportError(f"만든 mov의 프레임 수({packets})가 시퀀스의 프레임 수({written})와 다릅니다: {seq.identity}")
        finally:
            cap.release()
            self._reap(proc, reader)

    @staticmethod
    def _reap(proc, reader):
        """ffmpeg가 남지 않게 정리 (정상 종료한 뒤에는 아무 일도 하지 않음). 부분 출력을 지우기 전에 불려야 함 — Windows는 열린 파일을 못 지움."""
        if proc is None:
            return
        if proc.poll() is None:
            proc.kill()
        if not proc.stdin.closed:
            try:
                proc.stdin.close()
            except OSError:
                pass  # 방금 끝낸(또는 스스로 끝난) ffmpeg로 남은 버퍼를 보낼 수 없는 것은 정리 중에는 당연함
        proc.wait()
        if reader is not None:
            reader.join()
        proc.stderr.close()
