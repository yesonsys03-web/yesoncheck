"""열어 둔 파일이 디스크에서 다시 쓰였는지 — 연 때의 모습(크기·고친 때)을 적어 두고 나중에 견줌 (Qt 없음).

왜 (사용자 보고 2026-11-26): 검수 중인 영상을 누가 다시 렌더링하면, 열어 둔 캡처는 예전 파일의 자리(프레임마다 파일 안의 위치)를
기억한 채라 더 읽지 못함 — 그때 뜨던 오류 창은 "VideoToolbox로 영상을 읽다가 도중에 실패 … 파일이 probe보다 짧거나 잘림" 같은
기술적인 글뿐이라 사용자는 무슨 일인지 몰랐음. 영상 캡처(mac_native_source·movie_pipe_source)가 열 때 `stamp`를 적어 두고, 도중에
실패하면 `rewritten_note`로 파일이 바뀌었는지 보아 바뀌었으면 긴 오류 창 대신 쉬운 말의 알림 창을 띄움 (error_window.show_notice —
기술적인 원인은 그 창의 '자세히'와 기록에 그대로; 띄우는 일은 movie_pipe_source._report_rewritten).
캡처는 이 둘을 직접 부르지 않고 `stamp_at_open`(생성자)·`note_at_failure`(도중 실패 — read 안이라 예외를 내지 않음)를 부름.

이 Mac에서 재현 (ProRes 23장을 열어 끝까지 읽은 뒤 파일을 바꾸고 5번으로 이동): 빈 파일(다시 쓰기 시작한 직후) → 리더가 0장을 주고
끝남(보고된 글과 같음 — 40번 중 38번, 2번은 Invalid sample cursor), 다른 내용으로 덮어씀·앞 절반만 있음 → Cannot Decode, 더 짧은 파일로
덮어씀 → Invalid sample cursor. 기술적인 원인 글은 이렇게 갈리지만 '파일이 바뀌었는지'는 늘 같음 — 그래서 원인 글이 아니라 파일을 봄.
"""

import os
import time
import traceback
from dataclasses import dataclass

REWRITTEN_HEADLINE = "이 영상은 연 뒤에 파일이 다시 쓰였습니다 — 다시 렌더링되는 중이거나 방금 끝난 것으로 보입니다."
REWRITTEN_ADVICE = ("열어 둔 영상은 예전 파일을 가리켜 더 읽을 수 없습니다. 렌더가 끝난 뒤 목록에서 이 영상을 다시 눌러 열어 주세요 "
                    "(파일이 깨진 것이 아닙니다).")
TECHNICAL_HEADER = "아래는 기술 정보입니다:"  # 기록에서 쉬운 말 다음에 오는 원래 오류 글의 머리
UNCHECKED_HEADLINE = "파일이 다시 쓰였는지 확인하지 못했습니다"  # 견주지 못했을 때 기술 글 끝에 덧붙이는 줄의 머리 (사유가 뒤따름)


@dataclass(frozen=True)
class FileStamp:
    """연 때의 파일 모습."""

    size: int
    mtime_ns: int


def stamp(path):
    """지금의 파일 모습 (연 때 적어 둠). 읽지 못하면 그 OSError 그대로."""
    status = os.stat(path)
    return FileStamp(size=status.st_size, mtime_ns=status.st_mtime_ns)


def change_since(opened, path):
    """opened(연 때의 FileStamp) 뒤로 path가 바뀌었으면 무엇이 바뀌었는지의 글, 그대로면 None.

    파일이 없어졌으면 그것도 바뀐 것(지웠다 다시 만드는 렌더가 있음). 지금 확인하지 못하는 것(NAS 연결 끊김·권한 — FileNotFoundError가
    아닌 OSError)은 '다시 쓰였다'가 아니므로 그대로 올림.
    """
    try:
        now = stamp(path)
    except FileNotFoundError:
        return "지금은 파일이 없습니다 (지워졌거나 다시 만드는 중)"
    changes = []
    if now.size != opened.size:
        changes.append(f"크기 {size_text(opened.size)} → {size_text(now.size)}")
    if now.mtime_ns != opened.mtime_ns:
        changes.append(f"고친 때 {_time_text(opened.mtime_ns)} → {_time_text(now.mtime_ns)}")
    return " · ".join(changes) or None


def rewritten_note(opened, path):
    """연 뒤 파일이 다시 쓰였으면 오류 창·기록의 첫머리에 둘 쉬운 말(머리말 · 할 일 · 파일 · 바뀐 것), 아니면 None."""
    change = change_since(opened, path)
    if change is None:
        return None
    return f"{REWRITTEN_HEADLINE}\n{REWRITTEN_ADVICE}\n\n파일: {path}\n바뀐 것: {change}"


def stamp_at_open(path):
    """(영상 캡처의 생성자) → (연 때의 FileStamp, None) 또는 적어 두지 못했으면 (None, 사유 글). 예외를 내지 않음.

    적어 두지 못해도 여는 일은 막지 않음: 파일을 못 여는 까닭은 여는 쪽(ffmpeg·AVFoundation)이 자기 오류로 알리고, 이 사유는 그
    캡처가 도중에 실패할 때 note_at_failure가 함께 알림 (그때까지는 쓸 일이 없는 값).
    """
    try:
        return stamp(path), None
    except (OSError, ValueError) as exc:  # ValueError: 경로에 NUL
        return None, f"열 때 파일 모습(크기·고친 때)을 적어 두지 못함 — {type(exc).__name__}: {exc}"


def note_at_failure(opened, problem, path):
    """영상 캡처가 도중 실패를 알릴 때 → (쉬운 말 또는 None, 덧붙일 글). 예외를 내지 않음 (캡처의 read 안에서 불림).

    opened·problem: stamp_at_open이 준 둘.
    - 연 뒤 다시 쓰인 파일: (rewritten_note의 글, "") — 캡처가 그 글을 알림 창의 본문으로, 기술적인 글은 자세히·기록에.
    - 그대로인 파일: (None, "") — 캡처는 예전 오류 창 그대로.
    - 견주지 못함(열 때 적어 두지 못함 · 지금 확인 못 함 — NAS 연결 끊김·권한 · 예상 못 한 예외): 다시 쓰였다고 하지 않음 —
      (None, "\n\n" + UNCHECKED_HEADLINE + 사유(예외면 트레이스백째)) — 캡처가 예전 오류 창의 자세한 글 끝에 붙임.
    """
    if opened is None:
        return None, f"\n\n{UNCHECKED_HEADLINE} — {problem}"
    try:
        return rewritten_note(opened, path), ""
    except Exception:  # 원래 실패는 그대로 알려야 함 — 견주다 난 예외는 올리지 않고 글로
        return None, f"\n\n{UNCHECKED_HEADLINE} — {traceback.format_exc().rstrip()}"


def size_text(size):
    """바이트 수를 읽기 쉽게 (십진 — 1000바이트 미만·딱 1000은 바이트로, 그 위는 KB·MB·GB)."""
    if size <= 1000:
        return f"{size}바이트"
    if size < 1_000_000:
        return f"{size / 1000:.0f}KB"
    if size < 1_000_000_000:
        return f"{size / 1_000_000:.1f}MB"
    return f"{size / 1_000_000_000:.1f}GB"


def _time_text(mtime_ns):
    return time.strftime("%m-%d %H:%M:%S", time.localtime(mtime_ns / 1e9))
