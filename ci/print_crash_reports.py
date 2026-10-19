"""macOS 충돌 보고서(.ips)에서 죽은 스레드의 네이티브 스택을 출력한다 — CI의 Mac job이 실패했을 때 워크플로가 실행.

파이썬 스택(PYTHONFAULTHANDLER)만으로는 paddle·TensorFlow 같은 네이티브 라이브러리 안의 어느 함수에서 죽었는지 모름.
macOS(ReportCrash)가 남긴 보고서에서 예외 종류·신호와 죽은 스레드의 프레임(라이브러리 + 함수)을 보여 준다.
러너는 job마다 새 컴퓨터라 폴더의 보고서는 모두 이 job의 것 (시험이 일부러 죽인 파이썬의 보고서도 함께 나옴).

사용법: python3 ci/print_crash_reports.py [--frames N] [폴더 ...]   (기본: ~/Library/Logs/DiagnosticReports, /Library/Logs/DiagnosticReports)
"""

import argparse
import glob
import json
import os

DEFAULT_DIRS = [os.path.expanduser("~/Library/Logs/DiagnosticReports"), "/Library/Logs/DiagnosticReports"]


def describe(path, max_frames):
    """보고서 하나 → 출력할 줄들. 첫 줄은 머리(JSON), 나머지가 본문(JSON)인 macOS 12 이후 형식."""
    with open(path, encoding="utf-8") as fh:
        _header, body = fh.read().split("\n", 1)
    report = json.loads(body)
    exc = report.get("exception", {})
    lines = [f"===== {path}",
             f"프로세스: {report.get('procName')} ({report.get('procPath')}), {report.get('captureTime')}",
             f"예외: {exc.get('type')} {exc.get('signal')} {exc.get('subtype', '')}".rstrip(),
             f"끝난 이유: {report.get('termination', {}).get('indicator')}"]
    images = report["usedImages"]
    index = report["faultingThread"]
    thread = report["threads"][index]
    lines.append(f"죽은 스레드 {index} (이름 {thread.get('name')!r}, 큐 {thread.get('queue')!r}):")
    for number, frame in enumerate(thread["frames"][:max_frames]):
        image = images[frame["imageIndex"]].get("name", "?")
        where = f"{frame['symbol']} + {frame.get('symbolLocation', 0)}" if "symbol" in frame else f"+{frame['imageOffset']:#x}"
        lines.append(f"  {number:3d} {image:30s} {where}")
    if len(thread["frames"]) > max_frames:
        lines.append(f"  … 프레임 {len(thread['frames']) - max_frames}개 더")
    return lines


def main(argv=None):
    parser = argparse.ArgumentParser(description="macOS 충돌 보고서의 죽은 스레드 스택 출력")
    parser.add_argument("dirs", nargs="*", default=DEFAULT_DIRS, help="보고서 폴더")
    parser.add_argument("--frames", type=int, default=60, help="스레드마다 보여 줄 프레임 수")
    args = parser.parse_args(argv)
    paths = sorted((p for d in args.dirs for p in glob.glob(os.path.join(d, "*.ips"))), key=os.path.getmtime)
    if not paths:
        print(f"충돌 보고서 없음: {', '.join(args.dirs)}")
        return
    for path in paths:
        print("\n".join(describe(path, args.frames)))


if __name__ == "__main__":
    main()
