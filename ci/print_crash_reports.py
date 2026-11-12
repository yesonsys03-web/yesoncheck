"""macOS 충돌 보고서(.ips)에서 죽은 스레드의 네이티브 스택을 출력한다 — CI의 Mac job이 실패했을 때 워크플로가 실행.

파이썬 스택(PYTHONFAULTHANDLER)만으로는 paddle·TensorFlow 같은 네이티브 라이브러리 안의 어느 함수에서 죽었는지 모름.
macOS(ReportCrash)가 남긴 보고서에서 예외 종류·신호와 죽은 스레드의 프레임(라이브러리 + 함수)을 보여 준다.
러너 이미지에는 이미지를 만들 때의 다른 프로그램 보고서도 들어 있으므로 --since(이 job을 시작한 시각)와 --process로 거른다.
시험(test_smoke.py)이 일부러 죽인 파이썬의 보고서도 python3.10이라 함께 나옴 (faulthandler_sigsegv·time.sleep 프레임).
보고서 하나를 읽지 못해도 멈추지 않고 그 오류를 출력한 뒤 다음 보고서로 넘어감 (진단용 — job은 이미 실패).

--wait 초: 보여 줄 보고서(이 job의 우리 프로세스 것, 읽을 수 있는 것)가 아직 없으면 그만큼까지 기다림. macOS는 프로세스가 죽은 뒤 보고서를
쓰는 데 몇 초~수십 초가 걸리는데, pytest가 세그폴트로 죽으면 이 단계가 1~2초 만에 돌아 "0개"만 찍었음(2026-11-12 — 같은 시험에서 되풀이된
세그폴트의 네이티브 스택을 한 번도 못 봄). 쓰는 중이라 아직 읽히지 않는 보고서는 기다리는 동안 '없음'으로 치고, 기한이 지나면 있는 대로 출력.

사용법: python3 ci/print_crash_reports.py [--since 유닉스시각] [--process 이름앞부분 ...] [--frames N] [--wait 초] [폴더 ...]
  (폴더 기본: ~/Library/Logs/DiagnosticReports, /Library/Logs/DiagnosticReports)
"""

import argparse
import glob
import json
import os
import time
import traceback

DEFAULT_DIRS = [os.path.expanduser("~/Library/Logs/DiagnosticReports"), "/Library/Logs/DiagnosticReports"]


def load(path):
    """(머리, 본문): 첫 줄이 머리(JSON), 나머지가 본문(JSON)인 macOS 12 이후 형식. 본문이 없으면 빈 dict."""
    with open(path, encoding="utf-8") as fh:
        header_line, _, body = fh.read().partition("\n")
    return json.loads(header_line), (json.loads(body) if body.strip() else {})


def process_name(header, report):
    return report.get("procName") or header.get("app_name") or header.get("name") or ""


def describe(path, header, report, max_frames):
    """보고서 하나 → 출력할 줄들. 없는 항목은 건너뛰고 있는 것만 보여 줌."""
    exc = report.get("exception") or {}
    lines = [f"===== {path}",
             f"프로세스: {process_name(header, report)} ({report.get('procPath')}), "
             f"{report.get('captureTime') or header.get('timestamp')}, 종류 {header.get('bug_type')}",
             f"예외: {exc.get('type')} {exc.get('signal')} {exc.get('subtype') or ''}".rstrip(),
             f"끝난 이유: {(report.get('termination') or {}).get('indicator')}"]
    threads = report.get("threads")
    index = report.get("faultingThread")
    if not isinstance(threads, list) or not isinstance(index, int) or not 0 <= index < len(threads):
        lines.append(f"죽은 스레드 정보 없음 (threads {type(threads).__name__}, faultingThread {index!r})")
        return lines
    images = report.get("usedImages") or []
    thread = threads[index]
    frames = thread.get("frames") or []
    lines.append(f"죽은 스레드 {index} (이름 {thread.get('name')!r}, 큐 {thread.get('queue')!r}):")
    for number, frame in enumerate(frames[:max_frames]):
        image_index = frame.get("imageIndex")
        image = images[image_index].get("name", "?") if isinstance(image_index, int) and 0 <= image_index < len(images) else "?"
        if "symbol" in frame:
            where = f"{frame['symbol']} + {frame.get('symbolLocation', 0)}"
        else:
            where = f"+{frame.get('imageOffset', '?')}"
        lines.append(f"  {number:3d} {image:30s} {where}")
    if len(frames) > max_frames:
        lines.append(f"  … 프레임 {len(frames) - max_frames}개 더")
    return lines


def scan(dirs, since, processes):
    """보고서 폴더를 한 번 훑음 → (보여 줄 것 [(경로, 머리, 본문) — 읽지 못했으면 (경로, None, 트레이스백 글)], --since 이전 것의 수,
    건너뛴 다른 프로세스 이름들). 고친 시각 순."""
    paths = sorted((p for d in dirs for p in glob.glob(os.path.join(d, "*.ips"))), key=os.path.getmtime)
    entries, older, other_processes = [], 0, []
    for path in paths:
        if since is not None and os.path.getmtime(path) < since:
            older += 1
            continue
        try:
            header, report = load(path)
        except Exception:
            entries.append((path, None, traceback.format_exc()))
            continue
        name = process_name(header, report)
        if processes and not name.startswith(tuple(processes)):
            other_processes.append(name or os.path.basename(path))
            continue
        entries.append((path, header, report))
    return entries, older, other_processes


def main(argv=None, sleep=time.sleep, clock=time.monotonic):
    parser = argparse.ArgumentParser(description="macOS 충돌 보고서의 죽은 스레드 스택 출력")
    parser.add_argument("dirs", nargs="*", default=DEFAULT_DIRS, help="보고서 폴더")
    parser.add_argument("--since", type=float, help="이 유닉스 시각(초) 이후에 생긴 보고서만 (job 시작 시각)")
    parser.add_argument("--process", action="append", default=[], help="이 이름으로 시작하는 프로세스만 (여러 번 가능)")
    parser.add_argument("--frames", type=int, default=60, help="스레드마다 보여 줄 프레임 수")
    parser.add_argument("--wait", type=float, default=0.0, help="보여 줄 보고서가 없으면 이 초만큼까지 기다림 (macOS가 보고서를 쓰는 동안)")
    parser.add_argument("--poll", type=float, default=2.0, help="기다리는 동안 다시 보는 간격(초)")
    args = parser.parse_args(argv)

    started = clock()
    deadline = started + args.wait
    while True:
        entries, older, other_processes = scan(args.dirs, args.since, args.process)
        readable = any(header is not None for _path, header, _report in entries)
        remaining = deadline - clock()
        if readable or remaining <= 0:
            break
        sleep(min(args.poll, remaining))
    for path, header, report in entries:
        if header is None:
            print(f"===== {path}\n이 보고서를 읽지 못함:\n{report}")
            continue
        try:
            print("\n".join(describe(path, header, report, args.frames)))
        except Exception:
            print(f"===== {path}\n이 보고서를 읽지 못함:\n{traceback.format_exc()}")
    waited = f", 기다림 {clock() - started:.0f}초(최대 {args.wait:.0f}초)" if args.wait > 0 else ""
    print(f"충돌 보고서 {len(entries)}개 출력 ({', '.join(args.dirs)}) — 건너뜀: --since 이전 {older}개, "
          f"다른 프로세스 {len(other_processes)}개{' ' + str(sorted(set(other_processes))) if other_processes else ''}{waited}")


if __name__ == "__main__":
    main()
