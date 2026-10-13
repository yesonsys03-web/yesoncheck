"""실행 시험 데이터: 공유 폴더에 공유 설정(.yesoncheck)과 한글이 든 작품 폴더·시험 영상을 만든다.

Windows CI: --share-root C:\\yc_share --unc \\\\localhost\\yc_test --mac-root /Volumes/yc_test --settings %APPDATA%\\YesonCheck\\settings.json
Mac(로컬 확인): --share-root /tmp/x --mac-root /tmp/x (변환표 없이 Mac 경로 그대로) 후 YESONCHECK_CONFIG_DIR=/tmp/x/.yesoncheck
자동 연결(--auto-connect): 공유 설정은 <share-root>\\test_jn\\.yesoncheck, 변환표는 '여기에_붙여넣기'가 남은 기본 파일
"""

import argparse
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from yesoncheck import external_tools  # noqa: E402

WORK = "SMOKE"
WORK_FOLDER = "작품_시험"
SEASON = "시즌1"
JOB = "job_01"
VIDEO_NAMES = ["SMOKE_101_컷_001.mov", "SMOKE_101_컷_002.mov"]
TEMPLATE_PLACEHOLDER = "여기에_붙여넣기"


def write_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)


def make_video(ffmpeg, path, seconds=2):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    subprocess.run(
        [ffmpeg, "-y", "-v", "error",
         "-f", "lavfi", "-i", f"testsrc=duration={seconds}:size=320x240:rate=24",
         "-f", "lavfi", "-i", f"sine=duration={seconds}",
         "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", path],
        check=True, **external_tools.subprocess_kwargs(),
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--share-root", required=True, help="공유 폴더의 이 PC 경로 (C:\\yc_share)")
    parser.add_argument("--mac-root", required=True, help="같은 폴더를 공유 설정에 적을 Mac 경로")
    parser.add_argument("--unc", help="같은 폴더의 UNC (Windows만, 변환표에 씀)")
    parser.add_argument("--workdir", required=True, help="실행 시험 작업 폴더")
    parser.add_argument("--settings", help="PC별 설정 파일 경로 (Windows만)")
    parser.add_argument("--auto-connect", action="store_true",
                        help="자동 연결 시험: 공유 설정을 <share-root>\\test_jn\\.yesoncheck에 두고 PC별 설정 없이, "
                             "변환표는 '여기에_붙여넣기'가 남은 기본 파일로 (앱이 백업 후 새로 만들어야 함)")
    args = parser.parse_args()

    ffmpeg = external_tools.ffmpeg_path()
    if args.auto_connect:
        # Mac 공유 설정 경로 /USA_DB/test_jn/.yesoncheck의 뒷부분과 같은 모양 → 앱이 연결된 드라이브에서 찾아야 함
        config_dir = os.path.join(args.share_root, "test_jn", ".yesoncheck")
    else:
        config_dir = os.path.join(args.share_root, ".yesoncheck")
    write_json(os.path.join(config_dir, "work_paths.json"), {WORK: f"{args.mac_root}/{WORK_FOLDER}"})
    if args.auto_connect:
        # 배포 때 놓아 두는 기본 파일 → 앱이 SMB 공유 위의 기존 파일을 백업하고 바꿔치기하는지 시험
        write_json(os.path.join(config_dir, "path_map.json"),
                   {"version": 1, "shares": [{"mac": args.mac_root, "windows": [TEMPLATE_PLACEHOLDER]}]})
    elif args.unc:
        write_json(os.path.join(config_dir, "path_map.json"),
                   {"version": 1, "shares": [{"mac": args.mac_root, "windows": [args.unc]}]})
    frames = os.path.join(args.share_root, WORK_FOLDER, SEASON, JOB, "scene-001", "frames")
    for name in VIDEO_NAMES:
        make_video(ffmpeg, os.path.join(frames, name))
    smoke_config = {"work": WORK, "season": SEASON, "job": JOB, "expected_files": len(VIDEO_NAMES)}
    if args.auto_connect:
        smoke_config.update({"scenario": "auto_connect", "mac_prefix": args.mac_root})
    write_json(os.path.join(args.workdir, "smoke_config.json"), smoke_config)
    if args.settings and args.auto_connect:
        if os.path.exists(args.settings):
            os.remove(args.settings)  # PC별 설정이 없어야 앱이 공유 설정 폴더를 스스로 찾음
    elif args.settings:
        write_json(args.settings, {"config_dir": args.unc + "\\.yesoncheck"})
    print("시험 데이터 완료:", config_dir)


if __name__ == "__main__":
    main()
