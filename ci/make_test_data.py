"""실행 시험 데이터: 공유 폴더에 공유 설정(.yesoncheck)과 한글이 든 작품 폴더·시험 영상을 만든다.

Windows CI: --share-root C:\\yc_share --unc \\\\localhost\\yc_test --mac-root /Volumes/yc_test --settings %APPDATA%\\YesonCheck\\settings.json
Mac(로컬 확인): --share-root /tmp/x --mac-root /tmp/x (변환표 없이 Mac 경로 그대로) 후 YESONCHECK_CONFIG_DIR=/tmp/x/.yesoncheck
자동 연결(--auto-connect): 공유 설정은 <share-root>\\test_jn\\.yesoncheck, 변환표는 '여기에_붙여넣기'가 남은 기본 파일
업데이트(--update-dir, ci/update_e2e.py): 공유 설정의 updates/에 새 버전 꾸러미(설치 파일·dmg)와 latest.json(NAS 배포 흉내)
  — --close-others면 다른 창이 켜진 채 업데이트 (실행 시험이 '다른 창도 닫고 업데이트' 확인 창에 답함)
"""

import argparse
import datetime
import hashlib
import json
import os
import shutil
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from yesoncheck import build_info, external_tools, updates  # noqa: E402

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


def sha256_of(path):
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def publish_update(config_dir, package_dir, version, platform_key):
    """NAS 배포 흉내: package_dir의 꾸러미 파일 하나를 <config_dir>/updates/로 복사하고 그 파일을 가리키는 latest.json을 씀
    (version·이 플랫폼 항목의 이름·크기·sha256 — 앱이 확인하는 형식, updates.parse_manifest로 다시 읽어 확인) → latest.json 경로."""
    names = sorted(os.listdir(package_dir))
    files = [name for name in names if os.path.isfile(os.path.join(package_dir, name))]
    if len(files) != 1 or len(names) != 1:
        raise SystemExit(f"--update-dir에는 꾸러미 파일이 정확히 하나만 있어야 합니다: {package_dir} ({names})")
    name = files[0]
    updates_dir = os.path.join(config_dir, updates.NAS_DIR_NAME)
    os.makedirs(updates_dir, exist_ok=True)
    package = os.path.join(updates_dir, name)
    shutil.copyfile(os.path.join(package_dir, name), package)
    manifest = {
        "version": version,
        "commit": "0" * 40,  # 시험용 꾸러미 (배포 커밋 아님)
        "released": datetime.datetime.now().astimezone().isoformat(timespec="seconds"),
        "notes": "업데이트 끝까지 시험용 꾸러미",
        "files": {platform_key: {"name": name, "size": os.path.getsize(package), "sha256": sha256_of(package)}},
    }
    manifest_path = os.path.join(updates_dir, updates.MANIFEST_NAME)
    write_json(manifest_path, manifest)
    with open(manifest_path, "rb") as fh:
        updates.parse_manifest(fh.read())  # 앱이 읽는 형식인지 (틀리면 ManifestError로 멈춤)
    return manifest_path


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
    parser.add_argument("--dead-share",
                        help="자동 연결 시험: 서버가 없는 기억된 네트워크 드라이브의 UNC (CI가 등록) — 실행 시험이 "
                             "실패하지 않고 공유 문제로 알렸는지 확인")
    parser.add_argument("--expect-version",
                        help="빌드된 앱의 버전 (기본 시나리오만) — 실행 시험이 앱이 읽은 build_info.json의 버전·창 제목을 확인")
    parser.add_argument("--update-dir",
                        help="업데이트 시험: 새 버전 꾸러미(설치 파일·dmg) 하나가 든 폴더 — 공유 설정의 updates/에 복사하고 "
                             "latest.json을 씀, 실행 시험은 'update' 시나리오 (빌드된 앱이 그 버전을 알리고 받아 도우미에 넘김)")
    parser.add_argument("--update-version", help="업데이트 시험: latest.json의 버전 = 앱이 알려야 할 새 버전")
    parser.add_argument("--close-others", action="store_true",
                        help="업데이트 시험: 같은 설치의 다른 창이 켜진 채 업데이트 — 실행 시험이 '다른 창도 닫고 업데이트' "
                             "확인 창에 [모두 닫고 업데이트]로 답함 (smoke_config의 close_others)")
    parser.add_argument("--update-platform", choices=build_info.PLATFORM_KEYS,
                        help="업데이트 시험: latest.json의 플랫폼 키 (기본: 이 컴퓨터)")
    args = parser.parse_args()
    if args.expect_version is not None and (not args.expect_version or args.auto_connect or args.update_dir):
        parser.error("--expect-version은 빈 값이 아닌 버전으로, 기본 시나리오(--auto-connect·--update-dir 없이)에만 씁니다")
    if args.update_dir:
        if args.auto_connect:
            parser.error("--update-dir과 --auto-connect는 함께 쓰지 않습니다 (실행 시험 시나리오가 다름)")
        if not args.update_version:
            parser.error("--update-dir에는 --update-version(알려야 할 새 버전)이 있어야 합니다")
        try:
            updates.Version.parse(args.update_version)
        except ValueError as exc:
            parser.error(f"--update-version: {exc}")
    elif args.update_version or args.update_platform or args.close_others:
        parser.error("--update-version·--update-platform·--close-others는 --update-dir과 함께만 씁니다")

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
        if args.dead_share:
            smoke_config["dead_share"] = args.dead_share
    if args.expect_version is not None:
        smoke_config["expect_version"] = args.expect_version
    if args.update_dir:
        manifest_path = publish_update(config_dir, args.update_dir, args.update_version,
                                       args.update_platform or build_info.platform_key())
        print("업데이트 꾸러미 배포 (NAS 흉내):", manifest_path)
        smoke_config.update({"scenario": "update", "expect_offer": args.update_version})
        if args.close_others:
            smoke_config["close_others"] = True
    write_json(os.path.join(args.workdir, "smoke_config.json"), smoke_config)
    if args.settings and args.auto_connect:
        if os.path.exists(args.settings):
            os.remove(args.settings)  # PC별 설정이 없어야 앱이 공유 설정 폴더를 스스로 찾음
    elif args.settings:
        write_json(args.settings, {"config_dir": args.unc + "\\.yesoncheck"})
    print("시험 데이터 완료:", config_dir)


if __name__ == "__main__":
    main()
